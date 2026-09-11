import io
import json

import pytest
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from eda_proto.logstore import (
    HEADER_KEY,
    HEADER_SIZE,
    LogStore,
    frame_record,
    load_design,
    open_store,
    read_record,
    save_design,
)
from eda_proto.model import Design
from eda_proto.ops import add_instance, connect, create_net, delete_instance, ipin
from eda_proto.serialize import designs_equal
from tests.helpers import build_hierarchical_divider, scaffold, wired_divider


# ==========================================================================
# Slice 1 tests: Record framing-how a record is laid out on a disk
# ==========================================================================
def test_single_record_round_trips() -> None:
    raw = frame_record(7, b'{"id":7}')
    result = read_record(io.BytesIO(raw))
    assert result is not None
    key, payload, deleted = result
    assert key == 7
    assert payload == b'{"id":7}'
    assert deleted is False


def test_tombstone_round_trips() -> None:
    raw = frame_record(3, b"", deleted=True)
    result = read_record(io.BytesIO(raw))
    assert result is not None
    key, payload, deleted = result
    assert key == 3
    assert payload == b""
    assert deleted is True


def test_three_records_read_in_order() -> None:
    buf = frame_record(1, b"aaa") + frame_record(4, b"bbbb") + frame_record(1, b"", deleted=True)
    f = io.BytesIO(buf)
    assert read_record(f) == (1, b"aaa", False)
    assert read_record(f) == (4, b"bbbb", False)
    assert read_record(f) == (1, b"", True)
    assert read_record(f) is None  # clean EOF


def test_empty_buffer_is_clean_eof() -> None:
    assert read_record(io.BytesIO(b"")) is None


def test_empty_payload_nondeleted_round_trips() -> None:
    # a live record with a zero-length payload is still a valid frame
    raw = frame_record(9, b"")
    assert read_record(io.BytesIO(raw)) == (9, b"", False)


def test_binary_safe_payload() -> None:
    # payload may contain any bytes, including what looks like a header
    nasty = bytes(range(256))
    result = read_record(io.BytesIO(frame_record(2, nasty)))
    assert result is not None
    _, payload, _ = result
    assert payload == nasty


def test_truncated_header_raises() -> None:
    raw = frame_record(1, b"hello")
    with pytest.raises(ValueError):
        read_record(io.BytesIO(raw[: HEADER_SIZE - 1]))  # header cut short


def test_truncated_payload_raises() -> None:
    raw = frame_record(1, b"hello")
    with pytest.raises(ValueError):
        read_record(io.BytesIO(raw[:-1]))  # payload one byte short


def test_length_field_delimits_adjacent_records() -> None:
    # second record's bytes must NOT bleed into the first read
    buf = frame_record(1, b"first") + frame_record(2, b"second")
    f = io.BytesIO(buf)
    assert read_record(f) == (1, b"first", False)  # stops exactly at 'first'
    assert read_record(f) == (2, b"second", False)


# ==========================================================================
# Slice 2 tests: In-memory index + put/get/delete
# ==========================================================================
def new_store() -> LogStore:
    return LogStore(io.BytesIO())


# ----------
# put/get
# ----------
def test_get_after_put_returns_payload() -> None:
    s = new_store()
    s.put(1, b"resistor")
    assert s.get(1) == b"resistor"


def test_get_missing_key_is_none() -> None:
    s = new_store()
    assert s.get(99) is None


def test_multiple_keys_are_independent() -> None:
    s = new_store()
    s.put(1, b"aaa")
    s.put(4, b"bbbb")
    assert s.get(1) == b"aaa"
    assert s.get(4) == b"bbbb"


def test_empty_payload_round_trips() -> None:
    s = new_store()
    s.put(5, b"")
    assert s.get(5) == b""  # empty payload is real but not missing


# ----------
# update, latest takes it
# ----------
def test_update_returns_latest_value() -> None:
    s = new_store()
    s.put(1, b"v1")
    s.put(1, b"v2")
    assert s.get(1) == b"v2"


def test_update_appends_not_overwrites() -> None:
    s = new_store()
    s.put(1, b"old")
    size_after_first = s.f.seek(0, 2)
    s.put(1, b"new")
    size_after_second = s.f.seek(0, 2)
    assert size_after_second > size_after_first
    assert s.get(1) == b"new"


# ----------
# delete
# ----------
def test_get_after_delete_is_none() -> None:
    s = new_store()
    s.put(1, b"x")
    s.delete(1)
    assert s.get(1) is None


def test_delete_missing_key_is_noop() -> None:
    s = new_store()
    s.delete(123)
    assert s.get(123) is None


def test_delete_then_put_revives_key() -> None:
    s = new_store()
    s.put(1, b"x")
    s.delete(1)
    s.put(1, b"y")
    assert s.get(1) == b"y"


def test_delete_appends_tombstone_to_file() -> None:
    s = new_store()
    s.put(1, b"x")
    size_before = s.f.seek(0, 2)
    s.delete(1)
    size_after = s.f.seek(0, 2)
    assert size_after > size_before


# ----------
# Differential Rule : store must behave exactly like a dict
# ----------
class StoreVsDict(RuleBasedStateMachine):
    KEYS = [1, 2, 3, 4, 5]

    def __init__(self) -> None:
        super().__init__()
        self.store = new_store()
        self.ref: dict[int, bytes] = {}

    @rule(k=st.sampled_from(KEYS), v=st.binary(max_size=12))
    def put(self, k: int, v: bytes) -> None:
        self.store.put(k, v)
        self.ref[k] = v

    @precondition(lambda self: bool(self.ref))
    @rule(k=st.sampled_from(KEYS))
    def delete(self, k: int) -> None:
        self.store.delete(k)
        self.ref.pop(k, None)

    @invariant()
    def store_matches_dict(self) -> None:
        for k in self.KEYS:
            assert self.store.get(k) == self.ref.get(k)


TestStoreVsDict = StoreVsDict.TestCase


# ==========================================================================
# Slice 3 tests: Recovery on open
# ==========================================================================
# ----------
# put->close->reopen->get returns real file
# ----------
def test_reopen_returns_records(tmp_path) -> None:
    path = str(tmp_path / "d.log")
    s = open_store(path)
    s.put(1, b"resistor")
    s.put(7, b"divider")
    s.close()

    s2 = open_store(path)
    assert s2.get(1) == b"resistor"
    assert s2.get(7) == b"divider"
    s2.close()


def test_reopen_reflects_update(tmp_path) -> None:
    path = str(tmp_path / "d.log")
    s = open_store(path)
    s.put(1, b"v1")
    s.put(1, b"v2")
    s.close()
    s2 = open_store(path)
    assert s2.get(1) == b"v2"
    s2.close()


def test_reopen_reflects_delete(tmp_path) -> None:
    path = str(tmp_path / "d.log")
    s = open_store(path)
    s.put(1, b"x")
    s.delete(1)
    s.close()
    s2 = open_store(path)
    assert s2.get(1) is None
    s2.close()


def test_reopen_reflects_revive(tmp_path) -> None:
    path = str(tmp_path / "d.log")
    s = open_store(path)
    s.put(1, b"x")
    s.delete(1)
    s.put(1, b"revived")
    s.close()
    s2 = open_store(path)
    assert s2.get(1) == b"revived"
    s2.close()


def test_fresh_file_recovers_empty(tmp_path) -> None:
    # opening a never-written store yields an empty index (recovery over empty file)
    path = str(tmp_path / "new.log")
    s = open_store(path)
    assert s.get(1) is None
    assert s.index == {}
    s.close()


def test_reopen_is_idempotent(tmp_path) -> None:
    # open -> close -> open -> close -> open doesn't change
    path = str(tmp_path / "d.log")
    s = open_store(path)
    s.put(1, b"a")
    s.put(2, b"b")
    s.close()
    for _ in range(3):
        s = open_store(path)
        assert s.get(1) == b"a"
        assert s.get(2) == b"b"
        s.close()


# ----------
# Property: reopening MID-STREAM must preserve the dict-equivalence
# ----------
class RecoveryVsDict(RuleBasedStateMachine):
    KEYS = [1, 2, 3, 4, 5]

    def __init__(self) -> None:
        super().__init__()
        self.store = LogStore(io.BytesIO())
        self.ref: dict[int, bytes] = {}

    def _reopen(self) -> None:
        # simulate a restart
        buf = self.store.f.getvalue()
        self.store = LogStore(io.BytesIO(buf))

    @rule(k=st.sampled_from(KEYS), v=st.binary(max_size=12))
    def put(self, k: int, v: bytes) -> None:
        self.store.put(k, v)
        self.ref[k] = v

    @precondition(lambda self: bool(self.ref))
    @rule(k=st.sampled_from(KEYS))
    def delete(self, k: int) -> None:
        self.store.delete(k)
        self.ref.pop(k, None)

    @rule()
    def reopen(self) -> None:
        self._reopen()  # restart at random point

    @invariant()
    def store_matches_dict(self) -> None:
        for k in self.KEYS:
            assert self.store.get(k) == self.ref.get(k)


TestRecoveryVsDict = RecoveryVsDict.TestCase


# ==========================================================================
# Slice 4 tests: A design recorded and read back
# ==========================================================================
def _roundtrip_via_bytes(d: Design) -> Design:
    s = LogStore(io.BytesIO())
    save_design(d, s)
    buf = s.f.getvalue()
    return load_design(LogStore(io.BytesIO(buf)))  # simulated restart


# ----------
# Consinstency through restart
# ----------
def test_divider_survives_restart(tmp_path) -> None:
    d, _, _ = wired_divider()
    path = str(tmp_path / "d.log")
    s = open_store(path)
    save_design(d, s)
    s.close()
    s2 = open_store(path)
    back = load_design(s2)
    s2.close()
    assert designs_equal(back, d)


def test_hierarchical_survives_restart(tmp_path) -> None:
    d, _ = build_hierarchical_divider()
    path = str(tmp_path / "d.log")
    s = open_store(path)
    save_design(d, s)
    s.close()
    s2 = open_store(path)
    back = load_design(s2)
    s2.close()
    assert designs_equal(back, d)


def test_empty_design_survives_restart(tmp_path) -> None:
    d = Design()
    path = str(tmp_path / "d.log")
    s = open_store(path)
    save_design(d, s)
    s.close()
    s2 = open_store(path)
    back = load_design(s2)
    s2.close()
    assert designs_equal(back, d)


# ==========================================================================
# Append-only behaviour
# ==========================================================================
def test_double_save_still_loads_correctly() -> None:
    d, _, _ = wired_divider()
    s = LogStore(io.BytesIO())
    save_design(d, s)
    save_design(d, s)  # append a second full copy
    assert designs_equal(load_design(s), d)


def test_resave_after_edit_loads_latest() -> None:
    # save, edit design, save again in same store -> load sees the edit
    d, sch, h = wired_divider()
    s = LogStore(io.BytesIO())
    save_design(d, s)
    delete_instance(d, sch, h.R1)  # mutate
    save_design(d, s)
    assert designs_equal(load_design(s), d)


# ----------
# Need to refuse
# ----------
def test_load_refuses_store_with_no_header() -> None:
    s = LogStore(io.BytesIO())  # no design saved
    with pytest.raises(ValueError):
        load_design(s)


def test_load_refuses_bad_header_version() -> None:
    d, _, _ = wired_divider()
    s = LogStore(io.BytesIO())
    save_design(d, s)
    # overwrite header with a future version
    s.put(HEADER_KEY, json.dumps({"version": 99, "top": d.top, "next_id": d._next_id}).encode())
    with pytest.raises(ValueError):
        load_design(s)


# ----------
# Make sure any built design round-trips through a restart
# ----------
class DesignSurvivesRestart(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.d, self.sch, self.ids = scaffold()
        self._n = 0

    @rule()
    def add_resistor(self) -> None:
        add_instance(self.d, self.sch, self.ids.res, f"R{self._n}")
        self._n += 1

    @rule()
    def wire_a_free_pin(self) -> None:
        # find any (instance, pin-name) not already on a net, wire it to a fresh net
        for iid in self.sch.instances:
            for pname in ("a", "b"):
                p = ipin(self.d, self.sch, iid, pname)
                if p not in self.sch.pin_to_net:
                    n = create_net(self.d, self.sch)
                    connect(self.d, self.sch, p, n)
                    return

    @invariant()
    def round_trips_through_restart(self) -> None:
        assert designs_equal(_roundtrip_via_bytes(self.d), self.d)


TestDesignSurvivesRestart = DesignSurvivesRestart.TestCase

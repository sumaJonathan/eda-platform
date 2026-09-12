import io
import os

from hypothesis import given
from hypothesis import strategies as st

from eda_proto.logstore import LogStore, _sync, frame_record, open_store, read_record, save_design
from tests.helpers import wired_divider


def new_store() -> LogStore:
    return LogStore(io.BytesIO())


def _store_from(buf: bytes) -> LogStore:
    return LogStore(io.BytesIO(buf))


def _live_dict(s: LogStore, keys) -> dict:
    return {k: s.get(k) for k in keys if s.get(k) is not None}


def _expected(buf: bytes, keys) -> dict:
    # the correct recovered state = all COMPLETE records
    d: dict[int, bytes] = {}
    f = io.BytesIO(buf)
    while True:
        try:
            rec = read_record(f)
        except ValueError:
            break  # crash before end
        if rec is None:
            break
        k, v, deleted = rec
        if deleted:
            d.pop(k, None)
        else:
            d[k] = v
    return {k: d[k] for k in keys if k in d}


_RECS = [(1, b"resistor"), (4, b"vsource"), (1, b"resistor-v2"), (7, b"divider")]
_KEYS = [1, 4, 7]


def _full_log() -> bytes:
    return b"".join(frame_record(k, v) for k, v in _RECS)


# ==========================================================================
# Phase 1.5.1: Torn tail recovery of design saving
# ==========================================================================
# ----------------
# Crash mid-append must recover to the last complete record
# ----------------
def test_clean_log_recovers_fully() -> None:
    buf = _full_log()
    s = _store_from(buf)
    assert _live_dict(s, _KEYS) == {1: b"resistor-v2", 4: b"vsource", 7: b"divider"}


def test_chop_mid_last_record_drops_only_that_record() -> None:
    buf = _full_log()
    s = _store_from(buf[:-3])  # last record cut short
    assert s.get(7) is None
    assert s.get(1) == b"resistor-v2"
    assert s.get(4) == b"vsource"


def test_recovery_truncates_file_to_clean_boundary() -> None:
    buf = _full_log()
    s = _store_from(buf[:-3])  # torn tail
    reopened = _store_from(s.f.getvalue())
    assert _live_dict(reopened, _KEYS) == _live_dict(s, _KEYS)


def test_can_write_after_recovering_torn_tail() -> None:
    buf = _full_log()
    s = _store_from(buf[:-3])
    s.put(9, b"after-crash")  # append must work post-recovery
    reopened = _store_from(s.f.getvalue())
    assert reopened.get(9) == b"after-crash"
    assert reopened.get(1) == b"resistor-v2"  # old data still there


def test_partial_header_recovers() -> None:
    # crash early only a few header bytes landed
    buf = _full_log()
    s = _store_from(buf[:2])  # 2 bytes of first header
    assert _live_dict(s, _KEYS) == {}  # nothing complete, no crash


def test_empty_log_recovers_empty() -> None:
    s = _store_from(b"")
    assert _live_dict(s, _KEYS) == {}


# ----------------
# Chop at ANY byte length, recovery == last complete state
# ----------------
@given(st.integers(min_value=0, max_value=len(_full_log())))
def test_recovery_at_any_truncation_point(n: int) -> None:
    buf = _full_log()
    s = _store_from(buf[:n])
    assert _live_dict(s, _KEYS) == _expected(buf[:n], _KEYS)
    reopened = _store_from(s.f.getvalue())
    assert _live_dict(reopened, _KEYS) == _live_dict(s, _KEYS)


# ==========================================================================
# Phase 1.5.2: Durable commit (unguaranteed testing)
# ==========================================================================
# ----------------
# Guarding sync() shouldn't choke on an in-memory (BytesIO) store
# ----------------
def test_sync_on_bytesio_does_not_raise() -> None:
    s = new_store()
    s.put(1, b"x")
    s.sync()


def test_bytesio_sync_skips_fsync(monkeypatch) -> None:
    # os.fsync should not be called on an in-memory store,
    called: list = []
    monkeypatch.setattr(os, "fsync", lambda fd: called.append(fd))
    s = new_store()
    s.put(1, b"x")
    s.sync()
    assert called == []


# ----------------
# sync() actually invokes fsync
# ----------------
def test_sync_calls_fsync_on_real_file(tmp_path, monkeypatch) -> None:
    calls = []
    real_fsync = os.fsync

    def spy(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    path = str(tmp_path / "d.log")
    s = open_store(path)
    s.put(1, b"resistor")
    s.sync()
    assert len(calls) == 1  # ensure fsync invoked only once
    s.close()


def test_save_design_commits_once(tmp_path, monkeypatch) -> None:
    # save_design must sync exactly once, regardless of how many cells it writes
    calls = []
    real_fsync = os.fsync

    def spy(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    d, _, _ = wired_divider()  # several cells
    path = str(tmp_path / "d.log")
    s = open_store(path)
    save_design(d, s)
    assert len(calls) == 1  # one commit for the whole save
    s.close()


def test_sync_helper_flushes_bytesio() -> None:
    # _sync flushes and tolerates a fileno-less object
    b = io.BytesIO()
    b.write(b"hello")
    _sync(b)  # shouldn't raise on a BytesIO
    assert b.getvalue() == b"hello"


def test_synced_data_survives_reopen(tmp_path) -> None:
    # path does not corrupt,
    path = str(tmp_path / "d.log")
    s = open_store(path)
    s.put(1, b"durable")
    s.sync()
    s.close()
    s2 = open_store(path)
    assert s2.get(1) == b"durable"
    s2.close()

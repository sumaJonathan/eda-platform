import copy

from eda_proto.commands import (
    AddInstanceCmd,
    ConnectCmd,
    DeleteInstanceCmd,
    DisconnectCmd,
    MergeNetsCmd,
    SplitNetCmd,
    designs_equivalent,
)
from eda_proto.logcommands import CommandLog, top_schematic
from eda_proto.ops import add_instance, connect, create_net, ipin
from eda_proto.serialize import designs_equal
from tests.helpers import scaffold


def _base_with_setup():
    # one instance already wired to a net, exists before editing
    base, sch, ids = scaffold()
    r0 = add_instance(base, sch, ids.res, "R0")
    shared = create_net(base, sch, "shared")
    connect(base, sch, ipin(base, sch, r0, "a"), shared)
    return base, sch, ids, r0, shared


# ==========================================================================
# Phase 1.6.3:Command Log and Design Replay/Reload
# ==========================================================================
def test_top_schematic_finds_view_in_copy() -> None:
    base, sch, ids, r0, shared = _base_with_setup()
    copy_design = copy.deepcopy(base)
    v = top_schematic(copy_design)
    assert v is not sch  # the COPY's view, not the original
    assert r0 in v.instances


def test_record_applies_and_logs() -> None:
    base, sch, ids, r0, shared = _base_with_setup()
    log = CommandLog()
    cmd = AddInstanceCmd(ids.res, "R1")
    log.record(cmd, base, sch)
    assert cmd.created_id in sch.instances
    assert log.commands == [cmd]


def test_replay_reproduces_live_design() -> None:
    # THE sequence oracle: live edits == replay-from-base, exactly
    base, sch, ids, r0, shared = _base_with_setup()
    snapshot = copy.deepcopy(base)
    log = CommandLog()
    r1 = AddInstanceCmd(ids.res, "R1")
    log.record(r1, base, sch)
    assert r1.created_id is not None
    log.record(ConnectCmd(ipin(base, sch, r1.created_id, "a"), shared), base, sch)
    log.record(ConnectCmd(ipin(base, sch, r1.created_id, "b"), shared), base, sch)
    log.record(DisconnectCmd(ipin(base, sch, r0, "a")), base, sch)
    log.record(DeleteInstanceCmd(r1.created_id), base, sch)
    rebuilt = log.replay(snapshot, top_schematic)
    assert designs_equal(rebuilt, base)


def test_replay_does_not_mutate_base() -> None:
    base, sch, ids, r0, shared = _base_with_setup()
    snapshot = copy.deepcopy(base)
    snapshot_untouched = copy.deepcopy(snapshot)
    log = CommandLog()
    log.record(AddInstanceCmd(ids.res, "R1"), base, sch)
    log.replay(snapshot, top_schematic)
    assert designs_equal(snapshot, snapshot_untouched)


def test_replay_empty_log_returns_base_copy() -> None:
    base, sch, ids, r0, shared = _base_with_setup()
    snapshot = copy.deepcopy(base)
    rebuilt = CommandLog().replay(snapshot, top_schematic)
    assert designs_equal(rebuilt, base)


def test_replay_with_split_and_merge() -> None:
    base, sch, ids, r0, shared = _base_with_setup()
    r1 = add_instance(base, sch, ids.res, "R1")
    connect(base, sch, ipin(base, sch, r1, "a"), shared)
    snapshot = copy.deepcopy(base)
    log = CommandLog()
    sp = SplitNetCmd(shared, {ipin(base, sch, r1, "a")})
    log.record(sp, base, sch)
    assert sp.new_net_id is not None
    log.record(MergeNetsCmd(keep=shared, drop=sp.new_net_id), base, sch)
    rebuilt = log.replay(snapshot, top_schematic)
    assert designs_equal(rebuilt, base)


# ==========================================================================
# Phase 1.6.4: Undo/Redo using a history pointer
# ==========================================================================
def _setup():
    # `live`= design we edit; `base`= untouched snapshot to replay from
    live, sch, ids = scaffold()
    base = copy.deepcopy(live)
    return live, sch, ids, base, CommandLog()


def _oracle(log, live, base) -> bool:
    rebuilt = log.replay(base, top_schematic, upto=log.cursor)
    return designs_equivalent(live, rebuilt)


def test_undo_reverses_last_edit() -> None:
    live, sch, ids, base, log = _setup()
    r1 = AddInstanceCmd(ids.res, "R1")
    log.record(r1, live, sch)
    assert r1.created_id in sch.instances
    log.undo(live, sch)
    assert r1.created_id not in sch.instances
    assert _oracle(log, live, base)


def test_redo_reapplies_undone_edit() -> None:
    live, sch, ids, base, log = _setup()
    r1 = AddInstanceCmd(ids.res, "R1")
    log.record(r1, live, sch)
    log.undo(live, sch)
    log.redo(live, sch)
    assert r1.created_id in sch.instances
    assert _oracle(log, live, base)


def test_redo_restores_same_id() -> None:
    live, sch, ids, base, log = _setup()
    r1 = AddInstanceCmd(ids.res, "R1")
    log.record(r1, live, sch)
    original = r1.created_id
    log.undo(live, sch)
    log.redo(live, sch)
    assert original in sch.instances


def test_undo_past_start_is_noop() -> None:
    live, sch, ids, base, log = _setup()
    before = copy.deepcopy(live)
    log.undo(live, sch)
    assert designs_equivalent(live, before)


def test_redo_past_end_is_noop() -> None:
    live, sch, ids, base, log = _setup()
    log.record(AddInstanceCmd(ids.res, "R1"), live, sch)
    after = copy.deepcopy(live)
    log.redo(live, sch)
    assert designs_equivalent(live, after)


def test_new_edit_after_undo_truncates_redo_branch() -> None:
    live, sch, ids, base, log = _setup()
    log.record(AddInstanceCmd(ids.res, "R1"), live, sch)
    log.record(AddInstanceCmd(ids.res, "R2"), live, sch)
    log.undo(live, sch)
    log.record(AddInstanceCmd(ids.res, "R3"), live, sch)
    assert len(log.commands) == 2
    assert log.cursor == 2
    log.redo(live, sch)
    assert _oracle(log, live, base)


def test_undo_redo_sequence_matches_replay() -> None:
    live, sch, ids, base, log = _setup()
    for name in ("R1", "R2", "R3"):
        log.record(AddInstanceCmd(ids.res, name), live, sch)
        assert _oracle(log, live, base)
    log.undo(live, sch)
    assert _oracle(log, live, base)
    log.undo(live, sch)
    assert _oracle(log, live, base)
    log.redo(live, sch)
    assert _oracle(log, live, base)
    while log.cursor:
        log.undo(live, sch)
        assert _oracle(log, live, base)

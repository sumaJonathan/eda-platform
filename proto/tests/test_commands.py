import copy
import json

import pytest

from eda_proto.commands import (
    AddInstanceCmd,
    ConnectCmd,
    DeleteInstanceCmd,
    DisconnectCmd,
    MergeNetsCmd,
    RestoreSplitCmd,
    SplitNetCmd,
    designs_equivalent,
)
from eda_proto.ids import InstanceId, InstancePin, NetId, PinId
from eda_proto.model import SchematicView
from eda_proto.ops import add_instance, connect, create_net, ipin, pins_on_net
from eda_proto.serialize import designs_equal
from tests.helpers import build_hierarchical_divider, scaffold


# ==========================================================================
# Phase 1.6.1: Create the command frame
# ==========================================================================
# apply: a command mutates the design via ops, and captures what it created
def test_add_instance_apply_creates_and_captures_id() -> None:
    d, sch, ids = scaffold()
    cmd = AddInstanceCmd(ids.res, "R1")
    iid = cmd.apply(d, sch)
    assert iid in sch.instances
    assert cmd.created_id == iid  # get it at apply


def test_connect_apply_wires_pin() -> None:
    d, sch, ids = scaffold()
    r = AddInstanceCmd(ids.res, "R1").apply(d, sch)
    n = create_net(d, sch, "n")
    ConnectCmd(ipin(d, sch, r, "a"), n).apply(d, sch)
    assert ipin(d, sch, r, "a") in sch.pin_to_net


# invert: produces the CORRECT inverse COMMAND (inverse's apply arrives in Slice 2)
def test_add_instance_inverts_to_delete_of_created_id() -> None:
    d, sch, ids = scaffold()
    cmd = AddInstanceCmd(ids.res, "R1")
    iid = cmd.apply(d, sch)
    assert cmd.invert() == DeleteInstanceCmd(iid)


def test_connect_inverts_to_disconnect_of_same_args() -> None:
    d, sch, ids = scaffold()
    r = AddInstanceCmd(ids.res, "R1").apply(d, sch)
    n = create_net(d, sch, "n")
    p = ipin(d, sch, r, "a")
    cmd = ConnectCmd(p, n)
    cmd.apply(d, sch)
    assert cmd.invert() == DisconnectCmd(p, n)


# invert contract: inverting AddInstance before apply is a bug (id unknown)
def test_invert_before_apply_raises() -> None:
    cmd = AddInstanceCmd.from_dict(
        {"op": "add_instance", "cell_id": 1, "name": "R", "created_id": None}
    )
    with pytest.raises(AssertionError):
        cmd.invert()


# serialize: a command round-trips to plain values and back
def test_add_instance_round_trips_after_apply() -> None:
    d, sch, ids = scaffold()
    cmd = AddInstanceCmd(ids.res, "R1")
    cmd.apply(d, sch)
    back = AddInstanceCmd.from_dict(json.loads(json.dumps(cmd.to_dict())))
    assert back == cmd


def test_connect_round_trips() -> None:
    cmd = ConnectCmd(InstancePin(InstanceId(5), PinId(2)), NetId(6))
    back = ConnectCmd.from_dict(json.loads(json.dumps(cmd.to_dict())))
    assert back == cmd


def test_captured_id_survives_serialization_for_inverse() -> None:
    d, sch, ids = scaffold()
    cmd = AddInstanceCmd(ids.res, "R1")
    cmd.apply(d, sch)
    assert cmd.created_id is not None
    reloaded = AddInstanceCmd.from_dict(json.loads(json.dumps(cmd.to_dict())))
    assert reloaded.invert() == DeleteInstanceCmd(cmd.created_id)


# command apply calls the underlying op directly
def test_apply_matches_direct_op() -> None:
    from eda_proto.ops import add_instance

    d1, sch1, ids1 = scaffold()
    d2, sch2, ids2 = scaffold()
    AddInstanceCmd(ids1.res, "R1").apply(d1, sch1)
    add_instance(d2, sch2, ids2.res, "R1")
    assert designs_equal(d1, d2)


def test_addinstance_fresh_mints_and_captures() -> None:
    d, sch, ids = scaffold()
    cmd = AddInstanceCmd(ids.res, "R1")
    assert cmd.created_id is None
    iid = cmd.apply(d, sch)
    assert cmd.created_id == iid
    assert iid in sch.instances


def test_addinstance_replay_reuses_captured_id() -> None:
    d1, sch1, ids1 = scaffold()
    cmd = AddInstanceCmd(ids1.res, "R1")
    id_fresh = cmd.apply(d1, sch1)
    d2, sch2, ids2 = scaffold()
    id_replay = cmd.apply(d2, sch2)
    assert id_replay == id_fresh
    assert id_fresh in sch2.instances
    assert sch2.instances[id_fresh].name == "R1"


def test_addinstance_replay_keeps_counter_monotonic() -> None:
    d1, sch1, ids1 = scaffold()
    cmd = AddInstanceCmd(ids1.res, "R1")
    id_fresh = cmd.apply(d1, sch1)
    d2, sch2, ids2 = scaffold()
    cmd.apply(d2, sch2)
    assert d2._next_id >= id_fresh


# ==========================================================================
# Phase 1.6.2: Harder inverses
# ==========================================================================
# ----------------
# SplitNet tests
# ----------------
def _two_pin_net():
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    r2 = add_instance(d, sch, ids.res, "R2")
    n = create_net(d, sch, "n")
    connect(d, sch, ipin(d, sch, r1, "a"), n)
    connect(d, sch, ipin(d, sch, r2, "a"), n)
    return d, sch, ids, r1, r2, n


def test_splitnet_apply_captures_new_id() -> None:
    d, sch, _, _, r2, n = _two_pin_net()
    cmd = SplitNetCmd(n, {ipin(d, sch, r2, "a")})
    new = cmd.apply(d, sch)
    assert cmd.new_net_id == new
    assert new in sch.nets
    assert ipin(d, sch, r2, "a") in sch.nets[new].pins


def test_splitnet_inverts_to_mergenets() -> None:
    d, sch, _, _, r2, n = _two_pin_net()
    cmd = SplitNetCmd(n, {ipin(d, sch, r2, "a")})
    cmd.apply(d, sch)
    assert cmd.new_net_id is not None
    assert cmd.invert() == MergeNetsCmd(keep=n, drop=cmd.new_net_id)


def test_splitnet_apply_then_invert_returns_to_start() -> None:
    # split then merge-back is structurally identity (counter aside)
    d, sch, _, _, r2, n = _two_pin_net()
    before = copy.deepcopy(d)
    cmd = SplitNetCmd(n, {ipin(d, sch, r2, "a")})
    cmd.apply(d, sch)
    cmd.invert().apply(d, sch)
    assert designs_equivalent(d, before)


def test_splitnet_keeps_counter_monotonic() -> None:
    # Position B: undo must NOT rewind _next_id
    d, sch, _, _, r2, n = _two_pin_net()
    before_counter = d._next_id
    cmd = SplitNetCmd(n, {ipin(d, sch, r2, "a")})
    cmd.apply(d, sch)
    cmd.invert().apply(d, sch)
    assert d._next_id >= before_counter


def test_splitnet_invert_before_apply_raises() -> None:
    cmd = SplitNetCmd(NetId(5), set())
    with pytest.raises(AssertionError):
        cmd.invert()  # new_net_id is None


def test_splitnet_fresh_mints_and_captures() -> None:
    d, sch, ids, r1, r2, n = _two_pin_net()
    cmd = SplitNetCmd(n, {ipin(d, sch, r2, "a")})
    assert cmd.new_net_id is None
    nid = cmd.apply(d, sch)
    assert cmd.new_net_id == nid
    assert nid in sch.nets


def test_splitnet_replay_reuses_captured_id() -> None:
    d1, sch1, ids1, r1a, r2a, n1 = _two_pin_net()
    cmd = SplitNetCmd(n1, {ipin(d1, sch1, r2a, "a")})
    nid_fresh = cmd.apply(d1, sch1)
    d2, sch2, ids2, r1b, r2b, n2 = _two_pin_net()
    cmd.pins_to_move = {ipin(d2, sch2, r2b, "a")}
    nid_replay = cmd.apply(d2, sch2)
    assert nid_replay == nid_fresh
    assert nid_replay in sch2.nets
    assert ipin(d2, sch2, r2b, "a") in sch2.nets[nid_replay].pins


def test_splitnet_replayed_net_is_anonymous() -> None:
    d1, sch1, ids1, r1a, r2a, n1 = _two_pin_net()
    cmd = SplitNetCmd(n1, {ipin(d1, sch1, r2a, "a")})
    cmd.apply(d1, sch1)
    d2, sch2, ids2, r1b, r2b, n2 = _two_pin_net()
    cmd.pins_to_move = {ipin(d2, sch2, r2b, "a")}
    nid = cmd.apply(d2, sch2)
    assert sch2.nets[nid].name is None


# ----------------
# MergeNets tests
# ----------------
def _two_nets():
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    r2 = add_instance(d, sch, ids.res, "R2")
    a = create_net(d, sch, "A")
    b = create_net(d, sch, "B")
    connect(d, sch, ipin(d, sch, r1, "a"), a)
    connect(d, sch, ipin(d, sch, r2, "a"), b)
    return d, sch, ids, r1, r2, a, b


def test_merge_apply_captures_drop_state() -> None:
    d, sch, _, _, r2, a, b = _two_nets()
    cmd = MergeNetsCmd(keep=a, drop=b)
    cmd.apply(d, sch)
    assert b not in sch.nets
    assert len(pins_on_net(sch, a)) == 2
    assert cmd.drop_name == "B"
    assert cmd.drop_pins is not None
    assert ipin(d, sch, r2, "a") in cmd.drop_pins


def test_merge_inverts_to_restoresplit_with_keep() -> None:
    d, sch, _, _, _, a, b = _two_nets()
    cmd = MergeNetsCmd(keep=a, drop=b)
    cmd.apply(d, sch)
    inv = cmd.invert()
    assert isinstance(inv, RestoreSplitCmd)
    assert inv.keep == a and inv.net_id == b


def test_merge_apply_then_invert_returns_to_start() -> None:
    d, sch, _, _, _, a, b = _two_nets()
    before = copy.deepcopy(d)
    cmd = MergeNetsCmd(keep=a, drop=b)
    cmd.apply(d, sch)
    cmd.invert().apply(d, sch)
    assert designs_equivalent(d, before)
    assert sch.nets[b].name == "B"


def test_merge_undo_redo_undo_cycle() -> None:
    d, sch, _, _, _, a, b = _two_nets()
    before = copy.deepcopy(d)
    cmd = MergeNetsCmd(keep=a, drop=b)
    cmd.apply(d, sch)
    undo = cmd.invert()
    undo.apply(d, sch)
    assert designs_equivalent(d, before)
    redo = undo.invert()
    redo.apply(d, sch)
    assert b not in sch.nets
    undo2 = redo.invert()
    undo2.apply(d, sch)
    assert designs_equivalent(d, before)


def test_merge_keeps_counter_monotonic() -> None:
    d, sch, _, _, _, a, b = _two_nets()
    before_counter = d._next_id
    cmd = MergeNetsCmd(keep=a, drop=b)
    cmd.apply(d, sch)
    cmd.invert().apply(d, sch)
    assert d._next_id >= before_counter


def test_restoresplit_reuses_original_net_id() -> None:
    d, sch, _, _, _, a, b = _two_nets()
    cmd = MergeNetsCmd(keep=a, drop=b)
    cmd.apply(d, sch)
    cmd.invert().apply(d, sch)
    assert b in sch.nets


# ----------------
#  Disconnect & Reconnect tests
# ----------------
def _shared_net():
    # two pins on one net -> disconnecting one leaves the net alive
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    r2 = add_instance(d, sch, ids.res, "R2")
    n = create_net(d, sch, "n")
    connect(d, sch, ipin(d, sch, r1, "a"), n)
    connect(d, sch, ipin(d, sch, r2, "a"), n)
    return d, sch, ids, r1, r2, n


def _solo_net():
    # one pin on one net -> disconnecting it empties and deletes the net
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    n = create_net(d, sch, "solo")
    connect(d, sch, ipin(d, sch, r1, "a"), n)
    return d, sch, ids, r1, n


# ---- branch 1: net survives ------------------------------------------------
def test_disconnect_net_survives_captures_flag_false() -> None:
    d, sch, _, r1, _, n = _shared_net()
    c = DisconnectCmd(ipin(d, sch, r1, "a"))
    c.apply(d, sch)
    assert n in sch.nets
    assert c.net_deleted is False
    assert c.net_id == n


def test_disconnect_net_survives_round_trip() -> None:
    d, sch, _, r1, _, _ = _shared_net()
    before = copy.deepcopy(d)
    c = DisconnectCmd(ipin(d, sch, r1, "a"))
    c.apply(d, sch)
    c.invert().apply(d, sch)
    assert designs_equivalent(d, before)


# ---- branch 2: net emptied & deleted ---------------------------------------
def test_disconnect_deletes_net_captures_flag_true() -> None:
    d, sch, _, r1, n = _solo_net()
    c = DisconnectCmd(ipin(d, sch, r1, "a"))
    c.apply(d, sch)
    assert n not in sch.nets
    assert c.net_deleted is True
    assert c.net_name == "solo"


def test_disconnect_deleted_net_round_trip_restores_net() -> None:
    d, sch, _, r1, n = _solo_net()
    before = copy.deepcopy(d)
    c = DisconnectCmd(ipin(d, sch, r1, "a"))
    c.apply(d, sch)
    c.invert().apply(d, sch)
    assert designs_equivalent(d, before)
    assert n in sch.nets and sch.nets[n].name == "solo"  # same id, same name


# ---- redo cycle on the harder (net-deleted) branch -------------------------
def test_disconnect_undo_redo_undo_deleted_branch() -> None:
    d, sch, _, r1, n = _solo_net()
    before = copy.deepcopy(d)
    c = DisconnectCmd(ipin(d, sch, r1, "a"))
    c.apply(d, sch)
    undo = c.invert()
    undo.apply(d, sch)
    assert designs_equivalent(d, before)  # net restored
    redo = undo.invert()
    redo.apply(d, sch)
    assert n not in sch.nets  # disconnected again
    undo2 = redo.invert()
    undo2.apply(d, sch)
    assert designs_equivalent(d, before)


# ---- no-op: disconnecting an unwired pin -----------------------------------
def test_disconnect_unwired_pin_is_noop() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    before = copy.deepcopy(d)
    c = DisconnectCmd(ipin(d, sch, r1, "a"))  # never connected
    c.apply(d, sch)
    assert c.net_id is None
    c.invert().apply(d, sch)  # undo of nothing = nothing
    assert designs_equivalent(d, before)


def test_disconnect_keeps_counter_monotonic() -> None:
    d, sch, _, r1, _ = _solo_net()
    before_counter = d._next_id
    c = DisconnectCmd(ipin(d, sch, r1, "a"))
    c.apply(d, sch)
    c.invert().apply(d, sch)
    assert d._next_id >= before_counter


# ----------------
#  Deleting and Restoring instances
# ----------------
def _r1_on_solo_and_shared():
    # R1 has one pin alone on 'solo' and one pin shared with R2 on 'shared'
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    r2 = add_instance(d, sch, ids.res, "R2")
    solo = create_net(d, sch, "solo")
    shared = create_net(d, sch, "shared")
    connect(d, sch, ipin(d, sch, r1, "a"), solo)
    connect(d, sch, ipin(d, sch, r1, "b"), shared)
    connect(d, sch, ipin(d, sch, r2, "a"), shared)
    return d, sch, ids, r1, r2, solo, shared


def test_delete_captures_only_solely_owned_nets() -> None:
    d, sch, ids, r1, r2, solo, shared = _r1_on_solo_and_shared()
    c = DeleteInstanceCmd(r1)
    c.apply(d, sch)
    assert r1 not in sch.instances
    assert solo not in sch.nets  # emptied and deleted
    assert shared in sch.nets  # R2 keeps it alive
    assert c.emptied_nets is not None
    emptied_ids = {nid for nid, _ in c.emptied_nets}
    assert emptied_ids == {solo}  # ONLY solo captured, not shared


def test_delete_captures_name_and_params() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    sch.instances[r1].params["resistance"] = 1000.0
    c = DeleteInstanceCmd(r1)
    c.apply(d, sch)
    assert c.name == "R1"
    assert c.params == {"resistance": 1000.0}


def test_delete_round_trip_multi_net() -> None:
    d, sch, ids, r1, r2, solo, shared = _r1_on_solo_and_shared()
    before = copy.deepcopy(d)
    c = DeleteInstanceCmd(r1)
    c.apply(d, sch)
    c.invert().apply(d, sch)
    assert designs_equivalent(d, before)
    assert sch.instances[r1].name == "R1"
    assert solo in sch.nets and sch.nets[solo].name == "solo"  # recreated, orig id+name
    assert len(pins_on_net(sch, shared)) == 2  # R1's pin re-attached


def test_delete_undo_redo_undo() -> None:
    d, sch, ids, r1, r2, solo, shared = _r1_on_solo_and_shared()
    before = copy.deepcopy(d)
    c = DeleteInstanceCmd(r1)
    c.apply(d, sch)
    undo = c.invert()
    undo.apply(d, sch)
    assert designs_equivalent(d, before)
    redo = undo.invert()
    redo.apply(d, sch)
    assert r1 not in sch.instances
    undo2 = redo.invert()
    undo2.apply(d, sch)
    assert designs_equivalent(d, before)


def _find_ported_view(design) -> SchematicView:
    """Return a schematic view that has both instances and a non-empty port_map."""
    for cell in design.library.values():
        v = cell.views.get("schematic")
        if isinstance(v, SchematicView) and v.instances and v.port_map:
            return v
    raise AssertionError("no ported schematic view in this design")


def test_delete_restores_port_map() -> None:
    # deleting a ported instance must capture and restore the pruned port_map entries
    d, _ = build_hierarchical_divider()
    view = _find_ported_view(d)
    iid = next(iter(view.instances))
    before = copy.deepcopy(d)
    c = DeleteInstanceCmd(iid)
    c.apply(d, view)
    c.invert().apply(d, view)
    assert designs_equivalent(d, before)


def test_delete_keeps_counter_monotonic() -> None:
    d, sch, ids, r1, r2, solo, shared = _r1_on_solo_and_shared()
    before_counter = d._next_id
    c = DeleteInstanceCmd(r1)
    c.apply(d, sch)
    c.invert().apply(d, sch)
    assert d._next_id >= before_counter

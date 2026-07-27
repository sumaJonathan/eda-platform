"""Tests for eda_proto.ops.

Pattern: perform an operation, assert the specific result, then call
check_invariants(d) and trust it -- the invariant layer (already tested) is the
oracle that catches any corruption an operation might cause.

Note on empty nets: create_net makes a net with no pins, which invariant 6
forbids AT REST. So tests that call create_net without connecting a pin must NOT
call check_invariants until the net is either filled or removed.
"""

from types import SimpleNamespace

import pytest

from eda_proto.ids import CellId, InstanceId, InstancePin, NetId, PinId
from eda_proto.invariants import check_invariants
from eda_proto.model import Design, Direction, Pin, SchematicView
from eda_proto.ops import (
    add_cell,
    add_instance,
    connect,
    create_net,
    delete_instance,
    disconnect,
    ipin,
    nets_on_instance,
    pins_on_net,
)


def scaffold() -> tuple[Design, SchematicView, SimpleNamespace]:
    """A library (resistor, vsource) plus an empty 'divider' schematic view."""
    d = Design()
    res = add_cell(d, "resistor", [("a", Direction.PASSIVE), ("b", Direction.PASSIVE)])
    vsrc = add_cell(d, "vsource", [("p", Direction.PASSIVE), ("n", Direction.PASSIVE)])
    top = add_cell(d, "divider", [])
    d.top = top
    sch = SchematicView(owner=top, instances={}, nets={}, pin_to_net={}, port_map={})
    d.library[top].views["schematic"] = sch
    return d, sch, SimpleNamespace(res=res, vsrc=vsrc, top=top)


def wired_divider() -> tuple[Design, SchematicView, SimpleNamespace]:
    """The fully wired voltage divider, built entirely through ops."""
    d, sch, ids = scaffold()
    v1 = add_instance(d, sch, ids.vsrc, "V1")
    r1 = add_instance(d, sch, ids.res, "R1")
    r2 = add_instance(d, sch, ids.res, "R2")
    vin = create_net(d, sch, "vin")
    out = create_net(d, sch, "out")
    gnd = create_net(d, sch, "gnd")
    connect(d, sch, ipin(d, sch, v1, "p"), vin)
    connect(d, sch, ipin(d, sch, r1, "a"), vin)
    connect(d, sch, ipin(d, sch, r1, "b"), out)
    connect(d, sch, ipin(d, sch, r2, "a"), out)
    connect(d, sch, ipin(d, sch, r2, "b"), gnd)
    connect(d, sch, ipin(d, sch, v1, "n"), gnd)
    h = SimpleNamespace(
        res=ids.res,
        vsrc=ids.vsrc,
        top=ids.top,
        V1=v1,
        R1=r1,
        R2=r2,
        vin=vin,
        out=out,
        gnd=gnd,
    )
    return d, sch, h


# ==========================================================================
# ipin
# ==========================================================================
def test_ipin_resolves_pin_by_name() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    p = ipin(d, sch, r1, "a")
    assert p.instance == r1
    a_id = next(pid for pid, pin in d.library[ids.res].pins.items() if pin.name == "a")
    assert p.pin == a_id


def test_ipin_rejects_unknown_instance() -> None:
    d, sch, _ = scaffold()
    with pytest.raises(ValueError):
        ipin(d, sch, InstanceId(99999), "a")


def test_ipin_rejects_unknown_pin_name() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    with pytest.raises(ValueError):
        ipin(d, sch, r1, "z")


# ==========================================================================
# add_cell
# ==========================================================================
def test_add_cell_creates_cell_with_pins() -> None:
    d = Design()
    cid = add_cell(d, "resistor", [("a", Direction.PASSIVE), ("b", Direction.PASSIVE)])
    cell = d.library[cid]
    assert cell.name == "resistor"
    assert {p.name for p in cell.pins.values()} == {"a", "b"}
    assert cell.views == {}
    check_invariants(d)


def test_add_cell_empty_pins_is_valid() -> None:
    d = Design()
    cid = add_cell(d, "divider", [])
    assert d.library[cid].pins == {}
    check_invariants(d)


def test_add_cell_rejects_duplicate_cell_name() -> None:
    d = Design()
    add_cell(d, "resistor", [])
    with pytest.raises(ValueError):
        add_cell(d, "resistor", [])


def test_add_cell_rejects_duplicate_pin_name() -> None:
    d = Design()
    with pytest.raises(ValueError):
        add_cell(d, "resistor", [("a", Direction.PASSIVE), ("a", Direction.PASSIVE)])


def test_add_cell_ids_are_distinct() -> None:
    d = Design()
    c1 = add_cell(d, "a", [])
    c2 = add_cell(d, "b", [])
    assert c1 != c2


# ==========================================================================
# add_instance
# ==========================================================================
def test_add_instance_references_cell_without_copying() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    r2 = add_instance(d, sch, ids.res, "R2")
    assert sch.instances[r1].cell == ids.res
    assert sch.instances[r2].cell == ids.res
    assert d.library[sch.instances[r1].cell] is d.library[sch.instances[r2].cell]
    check_invariants(d)


def test_add_instance_rejects_unknown_cell() -> None:
    d, sch, _ = scaffold()
    with pytest.raises(ValueError):
        add_instance(d, sch, CellId(99999), "X")


def test_add_instance_rejects_duplicate_name() -> None:
    d, sch, ids = scaffold()
    add_instance(d, sch, ids.res, "R1")
    with pytest.raises(ValueError):
        add_instance(d, sch, ids.res, "R1")


def test_add_instance_rejects_direct_self_cycle() -> None:
    d, sch, ids = scaffold()
    # sch belongs to 'divider'; placing divider inside itself is a direct cycle
    with pytest.raises(ValueError):
        add_instance(d, sch, ids.top, "self")


def test_add_instance_rejects_transitive_cycle() -> None:
    d = Design()
    a = add_cell(d, "A", [])
    b = add_cell(d, "B", [])
    a_view = SchematicView(owner=a, instances={}, nets={}, pin_to_net={}, port_map={})
    d.library[a].views["schematic"] = a_view
    add_instance(d, a_view, b, "b0")  # A now contains B
    b_view = SchematicView(owner=b, instances={}, nets={}, pin_to_net={}, port_map={})
    d.library[b].views["schematic"] = b_view
    with pytest.raises(ValueError):
        add_instance(d, b_view, a, "a0")  # placing A in B closes A->B->A


# ==========================================================================
# create_net
# ==========================================================================
def test_create_net_named() -> None:
    d, sch, _ = scaffold()
    n = create_net(d, sch, "vin")
    assert sch.nets[n].name == "vin"


def test_create_net_anonymous() -> None:
    d, sch, _ = scaffold()
    n = create_net(d, sch)
    assert sch.nets[n].name is None


def test_create_net_rejects_duplicate_name() -> None:
    d, sch, _ = scaffold()
    create_net(d, sch, "vin")
    with pytest.raises(ValueError):
        create_net(d, sch, "vin")


def test_create_net_allows_multiple_anonymous() -> None:
    d, sch, _ = scaffold()
    a = create_net(d, sch)
    b = create_net(d, sch)
    assert a != b


# ==========================================================================
# connect
# ==========================================================================
def test_connect_places_pin_on_net() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    n = create_net(d, sch, "n")
    p = ipin(d, sch, r1, "a")
    connect(d, sch, p, n)
    assert pins_on_net(sch, n) == {p}
    check_invariants(d)


def test_connect_same_pin_same_net_is_idempotent() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    n = create_net(d, sch, "n")
    p = ipin(d, sch, r1, "a")
    connect(d, sch, p, n)
    connect(d, sch, p, n)  # again -- must not raise or duplicate
    assert pins_on_net(sch, n) == {p}
    check_invariants(d)


def test_connect_rejects_rewire_to_different_net() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    n1 = create_net(d, sch, "n1")
    n2 = create_net(d, sch, "n2")
    p = ipin(d, sch, r1, "a")
    connect(d, sch, p, n1)
    with pytest.raises(ValueError):
        connect(d, sch, p, n2)


def test_connect_rejects_pin_from_wrong_cell() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    n = create_net(d, sch, "n")
    # a vsource pin id, placed on a resistor instance -- not a declared pin
    vpin_id = next(iter(d.library[ids.vsrc].pins))
    bad = InstancePin(r1, vpin_id)
    with pytest.raises(ValueError):
        connect(d, sch, bad, n)


def test_connect_rejects_unknown_instance() -> None:
    d, sch, _ = scaffold()
    n = create_net(d, sch, "n")
    bad = InstancePin(InstanceId(99999), PinId(1))  # instance not in view
    with pytest.raises(ValueError):
        connect(d, sch, bad, n)


def test_connect_rejects_unknown_net() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    with pytest.raises(ValueError):
        connect(d, sch, ipin(d, sch, r1, "a"), NetId(99999))


# ==========================================================================
# disconnect
# ==========================================================================
def test_disconnect_removes_pin_from_net() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    r2 = add_instance(d, sch, ids.res, "R2")
    n = create_net(d, sch, "n")
    pa = ipin(d, sch, r1, "a")
    pb = ipin(d, sch, r2, "a")
    connect(d, sch, pa, n)
    connect(d, sch, pb, n)
    disconnect(d, sch, pa)
    assert pins_on_net(sch, n) == {pb}
    check_invariants(d)


def test_disconnect_unconnected_pin_is_noop() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    disconnect(d, sch, ipin(d, sch, r1, "a"))  # never connected
    check_invariants(d)


def test_disconnect_last_pin_removes_net() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    n = create_net(d, sch, "n")
    p = ipin(d, sch, r1, "a")
    connect(d, sch, p, n)
    disconnect(d, sch, p)
    assert n not in sch.nets  # empty net collected
    check_invariants(d)


# ==========================================================================
# pins_on_net
# ==========================================================================
def test_pins_on_net_returns_immutable_copy() -> None:
    d, sch, h = wired_divider()
    result = pins_on_net(sch, h.out)
    assert isinstance(result, frozenset)
    assert result == {ipin(d, sch, h.R1, "b"), ipin(d, sch, h.R2, "a")}


def test_pins_on_net_empty_for_fresh_net() -> None:
    d, sch, _ = scaffold()
    n = create_net(d, sch, "n")
    assert pins_on_net(sch, n) == frozenset()


# ==========================================================================
# nets_on_instance
# ==========================================================================
def test_nets_on_instance_reports_wired_and_unwired() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    n = create_net(d, sch, "n")
    connect(d, sch, ipin(d, sch, r1, "a"), n)
    result = nets_on_instance(d, sch, r1)
    a_pid = ipin(d, sch, r1, "a").pin
    b_pid = ipin(d, sch, r1, "b").pin
    assert result[a_pid] == n
    assert result[b_pid] is None
    assert len(result) == 2


# ==========================================================================
# delete_instance
# ==========================================================================
def test_delete_instance_removes_instance() -> None:
    d, sch, h = wired_divider()
    delete_instance(d, sch, h.R1)
    assert h.R1 not in sch.instances
    check_invariants(d)


def test_delete_instance_detaches_all_pins() -> None:
    d, sch, h = wired_divider()
    delete_instance(d, sch, h.R1)
    # no net or index entry may still reference R1
    for net in sch.nets.values():
        assert all(p.instance != h.R1 for p in net.pins)
    assert all(p.instance != h.R1 for p in sch.pin_to_net)
    check_invariants(d)


def test_delete_instance_keeps_shared_net() -> None:
    d, sch, h = wired_divider()
    # 'out' holds R1.b and R2.a; deleting R1 must leave R2.a on out
    delete_instance(d, sch, h.R1)
    assert pins_on_net(sch, h.out) == {ipin(d, sch, h.R2, "a")}
    check_invariants(d)


def test_delete_instance_collects_emptied_net_and_port_map() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    solo = create_net(d, sch, "solo")
    connect(d, sch, ipin(d, sch, r1, "a"), solo)  # only R1.a on this net
    # expose 'solo' as a port of the top cell
    port = Pin(id=d.new_pin_id(), name="p_out", direction=Direction.INOUT)
    d.library[ids.top].pins[port.id] = port
    sch.port_map[port.id] = solo
    delete_instance(d, sch, r1)
    assert solo not in sch.nets  # emptied net gone
    assert port.id not in sch.port_map  # dangling port_map entry removed
    check_invariants(d)


def test_delete_instance_rejects_unknown() -> None:
    d, sch, _ = scaffold()
    with pytest.raises(ValueError):
        delete_instance(d, sch, InstanceId(99999))


# ==========================================================================
# integration
# ==========================================================================
def test_full_divider_done_when() -> None:
    d, sch, h = wired_divider()
    assert pins_on_net(sch, h.out) == {
        ipin(d, sch, h.R1, "b"),
        ipin(d, sch, h.R2, "a"),
    }
    check_invariants(d)


def test_disconnect_then_reconnect_round_trips() -> None:
    d, sch, h = wired_divider()
    p = ipin(d, sch, h.R1, "a")
    disconnect(d, sch, p)
    # vin still exists (V1.p keeps it alive), R1.a now unwired
    assert nets_on_instance(d, sch, h.R1)[p.pin] is None
    connect(d, sch, p, h.vin)
    assert nets_on_instance(d, sch, h.R1)[p.pin] == h.vin
    check_invariants(d)

"""Tests for eda_proto.invariants.

Strategy: build one valid voltage divider, confirm every check is silent on it,
then for each invariant make a fresh copy, corrupt exactly the thing that
invariant guards, and assert the matching _check_* reports it.

Because there is no ops.py yet, divider is assembled manually and each test
reaches directly into the dicts to break it, simulating the corruption a
buggy operation will later cause.
"""

from types import SimpleNamespace

import pytest

from eda_proto.ids import CellId, InstancePin, NetId, PinId
from eda_proto.invariants import (
    _check_cells_resolve,
    _check_counter_covers_ids,
    _check_index_is_inverse,
    _check_instances_resolve,
    _check_names_unique,
    _check_no_cycles,
    _check_no_empty_nets,
    _check_pin_in_at_most_one_net,
    _check_pins_belong_to_cell,
    _check_port_map,
    check_invariants,
)
from eda_proto.model import (
    Cell,
    Design,
    Direction,
    Instance,
    Net,
    Pin,
    SchematicView,
)


def make_divider() -> tuple[Design, SimpleNamespace]:
    """A valid voltage divider. Returns (design, handles) for corruption.

    Library: resistor (pins a,b), vsource (pins p,n).
    Top cell 'divider' has a schematic view with V1, R1, R2 and nets vin/out/gnd,
    fully wired. `handles` exposes every object and id by name.
    """
    d = Design()

    ra = Pin(id=d.new_pin_id(), name="a", direction=Direction.PASSIVE)
    rb = Pin(id=d.new_pin_id(), name="b", direction=Direction.PASSIVE)
    resistor = Cell(id=d.new_cell_id(), name="resistor", pins={ra.id: ra, rb.id: rb}, views={})
    d.library[resistor.id] = resistor

    vp = Pin(id=d.new_pin_id(), name="p", direction=Direction.PASSIVE)
    vn = Pin(id=d.new_pin_id(), name="n", direction=Direction.PASSIVE)
    vsource = Cell(id=d.new_cell_id(), name="vsource", pins={vp.id: vp, vn.id: vn}, views={})
    d.library[vsource.id] = vsource

    divider = Cell(id=d.new_cell_id(), name="divider", pins={}, views={})
    d.library[divider.id] = divider
    d.top = divider.id

    v1 = Instance(id=d.new_instance_id(), name="V1", cell=vsource.id, params={})
    r1 = Instance(id=d.new_instance_id(), name="R1", cell=resistor.id, params={})
    r2 = Instance(id=d.new_instance_id(), name="R2", cell=resistor.id, params={})

    vin = Net(id=d.new_net_id(), name="vin", pins=set())
    out = Net(id=d.new_net_id(), name="out", pins=set())
    gnd = Net(id=d.new_net_id(), name="gnd", pins=set())

    view = SchematicView(
        owner=divider.id,
        instances={v1.id: v1, r1.id: r1, r2.id: r2},
        nets={vin.id: vin, out.id: out, gnd.id: gnd},
        pin_to_net={},
        port_map={},
    )
    divider.views["schematic"] = view

    def attach(ipin: InstancePin, net: Net) -> None:
        net.pins.add(ipin)
        view.pin_to_net[ipin] = net.id

    attach(InstancePin(v1.id, vp.id), vin)
    attach(InstancePin(r1.id, ra.id), vin)
    attach(InstancePin(r1.id, rb.id), out)
    attach(InstancePin(r2.id, ra.id), out)
    attach(InstancePin(r2.id, rb.id), gnd)
    attach(InstancePin(v1.id, vn.id), gnd)

    h = SimpleNamespace(
        resistor=resistor,
        vsource=vsource,
        divider=divider,
        view=view,
        V1=v1,
        R1=r1,
        R2=r2,
        vin=vin,
        out=out,
        gnd=gnd,
        ra=ra,
        rb=rb,
        vp=vp,
        vn=vn,
    )
    return d, h


# --------------------------------------------------------------------------
# The clean divider must satisfy everything.
# --------------------------------------------------------------------------
def test_clean_divider_passes_every_check() -> None:
    d, _ = make_divider()
    for check in (
        _check_cells_resolve,
        _check_instances_resolve,
        _check_pins_belong_to_cell,
        _check_index_is_inverse,
        _check_pin_in_at_most_one_net,
        _check_no_empty_nets,
        _check_port_map,
        _check_no_cycles,
        _check_names_unique,
    ):
        assert check(d) == [], f"{check.__name__} fired on a clean divider"


def test_clean_divider_check_invariants_silent() -> None:
    d, _ = make_divider()
    check_invariants(d)  # must not raise


def test_empty_design_is_silent() -> None:
    check_invariants(Design())


# --------------------------------------------------------------------------
# INV 1 -- instance ids resolve
# --------------------------------------------------------------------------
def test_inv1_key_disagrees_with_instance_id() -> None:
    d, h = make_divider()
    # R1 is still referenced everywhere by its dict key; only its own .id is wrong,
    # so exactly the key/id-agreement sub-check fires and nothing else.
    h.R1.id = _bump(h.R1.id)
    assert len(_check_instances_resolve(d)) == 1


def test_inv1_net_references_deleted_instance() -> None:
    d, h = make_divider()
    view = h.view
    view.instances.pop(h.R1.id)  # R1 gone, but nets + index still name it
    # R1 has 2 pins wired (a->vin, b->out): 2 net refs + 2 index refs
    assert len(_check_instances_resolve(d)) == 4


# --------------------------------------------------------------------------
# INV 2 -- cells resolve
# --------------------------------------------------------------------------
def test_inv2_instance_references_missing_cell() -> None:
    d, h = make_divider()
    h.R1.cell = CellId(99999)
    assert len(_check_cells_resolve(d)) == 1


def test_inv2_library_key_disagrees_with_cell_id() -> None:
    d, h = make_divider()
    h.resistor.id = _bump(h.resistor.id)  # key unchanged, object .id now wrong
    assert len(_check_cells_resolve(d)) == 1


def test_inv2_top_points_at_missing_cell() -> None:
    d, _ = make_divider()
    d.top = CellId(99999)
    assert len(_check_cells_resolve(d)) == 1


# --------------------------------------------------------------------------
# INV 3 -- pins belong to the instance's cell
# --------------------------------------------------------------------------
def test_inv3_pin_from_wrong_cell() -> None:
    d, h = make_divider()
    # R1 is a resistor; vp is vsource's pin "p" -- not declared on resistor
    h.out.pins.add(InstancePin(h.R1.id, h.vp.id))
    assert len(_check_pins_belong_to_cell(d)) == 1


# --------------------------------------------------------------------------
# INV 4 -- pin_to_net and net.pins are exact inverses
# --------------------------------------------------------------------------
def test_inv4_index_points_to_missing_net() -> None:
    d, h = make_divider()
    # a fresh index entry for a pin in no net, pointing at a nonexistent net
    h.view.pin_to_net[InstancePin(h.R1.id, PinId(12345))] = NetId(99999)
    assert len(_check_index_is_inverse(d)) == 1


def test_inv4_net_pin_missing_from_index() -> None:
    d, h = make_divider()
    # add a pin to a net but not to the index
    h.gnd.pins.add(InstancePin(h.R2.id, PinId(54321)))
    assert len(_check_index_is_inverse(d)) == 1


def test_inv4_index_and_net_disagree() -> None:
    d, h = make_divider()
    # R1.a is in vin; point the index at gnd instead -> forward + backward both fire
    h.view.pin_to_net[InstancePin(h.R1.id, h.ra.id)] = h.gnd.id
    assert len(_check_index_is_inverse(d)) == 2


# --------------------------------------------------------------------------
# INV 5 -- a pin is in at most one net
# --------------------------------------------------------------------------
def test_inv5_pin_in_two_nets() -> None:
    d, h = make_divider()
    h.gnd.pins.add(InstancePin(h.R1.id, h.ra.id))  # R1.a already in vin
    assert len(_check_pin_in_at_most_one_net(d)) == 1


# --------------------------------------------------------------------------
# INV 6 -- no empty nets
# --------------------------------------------------------------------------
def test_inv6_empty_net() -> None:
    d, h = make_divider()
    floating = Net(id=d.new_net_id(), name="floating", pins=set())
    h.view.nets[floating.id] = floating
    assert len(_check_no_empty_nets(d)) == 1


def test_inv6_one_pin_net_is_legal() -> None:
    d, h = make_divider()
    # a stub (exactly one pin) is fine -- 1.2's split produces these
    stub = Net(id=d.new_net_id(), name="stub", pins=set())
    ipin = InstancePin(h.R2.id, PinId(4242))
    stub.pins.add(ipin)
    h.view.nets[stub.id] = stub
    assert _check_no_empty_nets(d) == []


# --------------------------------------------------------------------------
# INV 7 -- port map
# --------------------------------------------------------------------------
def test_inv7_view_owner_mismatch() -> None:
    d, h = make_divider()
    h.view.owner = CellId(99999)
    assert len(_check_port_map(d)) == 1


def test_inv7_port_map_key_not_declared() -> None:
    d, h = make_divider()
    # divider declares no pins; any key is undeclared. value is a real net.
    h.view.port_map[PinId(99999)] = h.vin.id
    assert len(_check_port_map(d)) == 1


def test_inv7_port_map_value_not_a_net() -> None:
    d, h = make_divider()
    # give divider a real pin, then map it to a nonexistent net
    port = Pin(id=d.new_pin_id(), name="vin_port", direction=Direction.INOUT)
    h.divider.pins[port.id] = port
    h.view.port_map[port.id] = NetId(99999)
    assert len(_check_port_map(d)) == 1


# --------------------------------------------------------------------------
# INV 8 -- no hierarchy cycles
# --------------------------------------------------------------------------
def test_inv8_direct_self_cycle() -> None:
    d, h = make_divider()
    me = Instance(id=d.new_instance_id(), name="SELF", cell=h.divider.id, params={})
    h.view.instances[me.id] = me
    assert len(_check_no_cycles(d)) == 1


def test_inv8_mutual_cycle() -> None:
    d = Design()
    a = Cell(id=d.new_cell_id(), name="A", pins={}, views={})
    b = Cell(id=d.new_cell_id(), name="B", pins={}, views={})
    d.library[a.id] = a
    d.library[b.id] = b
    b_in_a = Instance(id=d.new_instance_id(), name="b0", cell=b.id, params={})
    a.views["schematic"] = SchematicView(
        owner=a.id, instances={b_in_a.id: b_in_a}, nets={}, pin_to_net={}, port_map={}
    )
    a_in_b = Instance(id=d.new_instance_id(), name="a0", cell=a.id, params={})
    b.views["schematic"] = SchematicView(
        owner=b.id, instances={a_in_b.id: a_in_b}, nets={}, pin_to_net={}, port_map={}
    )
    assert len(_check_no_cycles(d)) == 1


# --------------------------------------------------------------------------
# INV 9 -- names unique within scope
# --------------------------------------------------------------------------
def test_inv9_duplicate_cell_name() -> None:
    d, _ = make_divider()
    dup = Cell(id=d.new_cell_id(), name="resistor", pins={}, views={})
    d.library[dup.id] = dup
    assert len(_check_names_unique(d)) == 1


def test_inv9_duplicate_pin_name_in_cell() -> None:
    d, h = make_divider()
    extra = Pin(id=d.new_pin_id(), name="a", direction=Direction.PASSIVE)
    h.resistor.pins[extra.id] = extra
    assert len(_check_names_unique(d)) == 1


def test_inv9_duplicate_instance_name_in_view() -> None:
    d, h = make_divider()
    dup = Instance(id=d.new_instance_id(), name="R1", cell=h.resistor.id, params={})
    h.view.instances[dup.id] = dup
    assert len(_check_names_unique(d)) == 1


def test_inv9_duplicate_net_name_in_view() -> None:
    d, h = make_divider()
    dup = Net(id=d.new_net_id(), name="out", pins=set())
    h.view.nets[dup.id] = dup
    assert len(_check_names_unique(d)) == 1


def test_inv9_anonymous_nets_are_not_duplicates() -> None:
    d, h = make_divider()
    for _ in range(3):
        anon = Net(id=d.new_net_id(), name=None, pins=set())
        h.view.nets[anon.id] = anon
    assert _check_names_unique(d) == []


# --------------------------------------------------------------------------
# INV 10 --
# --------------------------------------------------------------------------
def test_inv10_counter_below_max_id() -> None:
    d, h = make_divider()
    d._next_id = 2  # far below the ids actually in use
    assert len(_check_counter_covers_ids(d)) == 1


# --------------------------------------------------------------------------
# check_invariants aggregation
# --------------------------------------------------------------------------
def test_check_invariants_raises_and_reports_multiple() -> None:
    d, h = make_divider()
    dup = Cell(id=d.new_cell_id(), name="resistor", pins={}, views={})
    d.library[dup.id] = dup  # duplicate cell name (INV9)
    h.R1.cell = CellId(99999)  # missing cell reference (INV2)
    with pytest.raises(AssertionError) as excinfo:
        check_invariants(d)
    msg = str(excinfo.value)
    assert "resistor" in msg
    assert "99999" in msg


def _bump(x: int) -> int:
    """Return an int distinct from x (for corrupting an id in place)."""
    return x + 100000

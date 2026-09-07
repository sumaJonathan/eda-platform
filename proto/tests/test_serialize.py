import copy

from eda_proto.model import Design, Direction, Pin, SchematicView, View
from eda_proto.ops import add_cell, add_instance
from eda_proto.serialize import designs_equal
from tests.helpers import build_hierarchical_divider, wired_divider


# HELPER
def _schem(d: Design) -> SchematicView:
    assert d.top is not None
    v = d.library[d.top].views["schematic"]
    assert isinstance(v, SchematicView)
    return v


# ==========================================================================
# Equal designs compare equal
# ==========================================================================
def test_deepcopy_of_divider_is_equal() -> None:
    d, _, _ = wired_divider()
    assert designs_equal(d, copy.deepcopy(d))


def test_deepcopy_of_hierarchical_is_equal() -> None:
    d, _ = build_hierarchical_divider()
    assert designs_equal(d, copy.deepcopy(d))


def test_two_empty_designs_are_equal() -> None:
    assert designs_equal(Design(), Design())


def test_two_independent_identical_builds_are_equal() -> None:
    # built separately, never copied — must still be equal
    a, _, _ = wired_divider()
    b, _, _ = wired_divider()
    assert designs_equal(a, b)


def test_equality_is_symmetric_on_a_difference() -> None:
    d1, _, _ = wired_divider()
    d2 = copy.deepcopy(d1)
    d2._next_id += 1
    assert designs_equal(d1, d2) == designs_equal(d2, d1)
    assert not designs_equal(d1, d2)


# ==========================================================================
# Design-level fields
# ==========================================================================
def test_next_id_off_by_one_not_equal() -> None:
    d1, _, _ = wired_divider()
    d2 = copy.deepcopy(d1)
    d2._next_id += 1
    assert not designs_equal(d1, d2)


def test_top_differs_not_equal() -> None:
    d1, _, _ = wired_divider()
    d2 = copy.deepcopy(d1)
    d2.top = None
    assert not designs_equal(d1, d2)


# ==========================================================================
# Population differences (subset / superset)
# ==========================================================================
def test_extra_cell_not_equal() -> None:
    # d1 has one more cell than d2; resync the counter so it isn't
    # the counter check doing the catching
    d1, _, _ = wired_divider()
    d2 = copy.deepcopy(d1)
    add_cell(d1, "extra_cell", [])
    d2._next_id = d1._next_id
    assert not designs_equal(d1, d2)


def test_extra_instance_in_view_not_equal() -> None:
    # same cells, but d1's view has an extra instance; counter resynced
    d1, sch, h = wired_divider()
    d2 = copy.deepcopy(d1)
    add_instance(d1, sch, h.res, "R_extra")
    d2._next_id = d1._next_id
    assert not designs_equal(d1, d2)


# ==========================================================================
# Cell / pin differences
# ==========================================================================
def test_pin_direction_differs_not_equal() -> None:
    d1, _, _ = wired_divider()
    d2 = copy.deepcopy(d1)
    cell = next(c for c in d2.library.values() if c.name == "resistor")
    pin = next(iter(cell.pins.values()))
    pin.direction = Direction.IN
    assert not designs_equal(d1, d2)


# ==========================================================================
# View-level differences
# ==========================================================================
def test_instance_renamed_not_equal() -> None:
    d1, _, _ = wired_divider()
    d2 = copy.deepcopy(d1)
    sch2 = _schem(d2)  # make sure it's a schematic view
    inst = next(iter(sch2.instances.values()))
    inst.name = inst.name + "_X"
    assert not designs_equal(d1, d2)


def test_instance_param_differs_not_equal() -> None:
    d1, _, _ = wired_divider()
    d2 = copy.deepcopy(d1)
    sch2 = _schem(d2)  # make sure it's a schematic view
    inst = next(iter(sch2.instances.values()))
    inst.params["resistance"] = 1000
    assert not designs_equal(d1, d2)


def test_net_renamed_not_equal() -> None:
    d1, _, _ = wired_divider()
    d2 = copy.deepcopy(d1)
    sch2 = _schem(d2)  # make sure it's a schematic view
    net = next(iter(sch2.nets.values()))
    net.name = "ZZZ"
    assert not designs_equal(d1, d2)


def test_net_membership_swapped_not_equal() -> None:
    # move a pin from 'out' to 'gnd' by editing net.pins directly.
    d1, _, _ = wired_divider()
    d2 = copy.deepcopy(d1)
    sch2 = _schem(d2)  # make sure it's a schematic view
    out = next(n for n in sch2.nets.values() if n.name == "out")
    gnd = next(n for n in sch2.nets.values() if n.name == "gnd")
    pin = next(iter(out.pins))
    out.pins.discard(pin)
    gnd.pins.add(pin)
    assert not designs_equal(d1, d2)


def test_port_map_differs_not_equal() -> None:
    d1, _, _ = wired_divider()
    d2 = copy.deepcopy(d1)
    assert d2.top is not None
    top = d2.library[d2.top]
    sch2 = _schem(d2)
    p = Pin(id=d2.new_pin_id(), name="px", direction=Direction.INOUT)
    top.pins[p.id] = p
    sch2.port_map[p.id] = next(iter(sch2.nets))
    assert not designs_equal(d1, d2)


def test_bare_view_vs_schematic_view_not_equal() -> None:
    # same "schematic" key, one with bare View-must be rejected by type check
    d1, _, _ = wired_divider()
    d2 = copy.deepcopy(d1)
    assert d2.top is not None
    d2.library[d2.top].views["schematic"] = View()
    assert not designs_equal(d1, d2)

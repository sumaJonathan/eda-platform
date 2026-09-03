from eda_proto.flatten import FlatNetlist, FlatPin, flatten
from eda_proto.ids import CellId, PinId
from eda_proto.model import Design
from tests.helpers import build_hierarchical_divider


# ----------------------------------------------------------------
# Oracle for flattening Netlist
# ----------------------------------------------------------------
def net_partition(flat: FlatNetlist) -> set[frozenset[FlatPin]]:
    """The structural map, which pins share a net, ignoring net ids or names"""
    return {frozenset(pins) for pins in flat.nets.values() if pins}


def cell_by_name(design: Design, name: str) -> CellId:
    """Helper to get a dict of cell names to ids for a design"""
    return next(cid for cid, c in design.library.items() if c.name == name)


def pin_id(design: Design, cell_name: str, pin_name: str) -> PinId:
    """Helper to get a dict of pin names to ids for a design"""
    cid = cell_by_name(design, cell_name)
    cell = design.library[cid]
    return next(pid for pid, p in cell.pins.items() if p.name == pin_name)


def test_flatten_2level_divider() -> None:
    d, top = build_hierarchical_divider()  # the rpair-in-divider setup
    flat = flatten(d, top)
    # three leaf instances
    assert set(flat.instances) == {"V", "X/R1", "X/R2"}
    # resolve pin ids by name, then assert the 3 groups
    V_p = pin_id(d, "vsource", "p")
    V_n = pin_id(d, "vsource", "n")
    R_a = pin_id(d, "resistor", "a")
    R_b = pin_id(d, "resistor", "b")
    assert net_partition(flat) == {
        frozenset({("V", V_p), ("X/R1", R_a)}),
        frozenset({("X/R1", R_b), ("X/R2", R_a)}),
        frozenset({("V", V_n), ("X/R2", R_b)}),
    }

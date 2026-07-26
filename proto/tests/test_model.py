from eda_proto.ids import CellId, InstanceId
from eda_proto.model import Cell, Design, Direction, Instance, Pin


def test_new_id_is_unique() -> None:
    d = Design()
    ids = [d.new_id() for _ in range(100)]
    assert len(set(ids)) == 100


def test_new_id_is_monotonic() -> None:
    d = Design()
    a, b, c = d.new_id(), d.new_id(), d.new_id()
    assert a < b < c
    assert a > 0  # 0 is falsy; never hand it out


def test_designs_do_not_share_state() -> None:
    d1, d2 = Design(), Design()
    pin_a = Pin(id=d1.new_pin_id(), name="a", direction=Direction.PASSIVE)
    c1 = Cell(id=d1.new_cell_id(), name="C1", pins={pin_a.id: pin_a}, views={})
    d1.library[c1.id] = c1
    assert d1.library != {}
    assert d2.library == {}


def test_instance_params_are_independent() -> None:
    r1 = Instance(id=InstanceId(1), name="R1", cell=CellId(9), params={})
    r2 = Instance(id=InstanceId(2), name="R2", cell=CellId(9), params={})
    r1.params["resistance"] = 1000
    assert r2.params == {}
    assert r1.cell == r2.cell  # same cell — one blueprint, two uses

from types import SimpleNamespace

from eda_proto.model import Design, Direction, SchematicView
from eda_proto.ops import add_cell, add_instance, connect, create_net, ipin


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

from types import SimpleNamespace

from eda_proto.ids import CellId
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


def build_hierarchical_divider() -> tuple[Design, CellId]:
    """A 2-level hierarchy that flattens to the voltage divider.
    Lib: R(a,b), Vsource(p,n)
    Mid cell 'rpair': R1,R2 in series with 3 ports
    Top cell 'divide_top': one rpair inst X + one Vsource V

    Return (design, top_cell_id). Flattening top_cell_id yields leaf
    insts V, X/R1, X/R2 grouped into the divider's 3 nets.
    """
    d = Design()
    res = add_cell(d, "resistor", [("a", Direction.PASSIVE), ("b", Direction.PASSIVE)])
    vsrc = add_cell(d, "vsource", [("p", Direction.PASSIVE), ("n", Direction.PASSIVE)])

    # Mid cell: rpair
    rpair = add_cell(
        d,
        "rpair",
        [("top", Direction.PASSIVE), ("mid", Direction.PASSIVE), ("bot", Direction.PASSIVE)],
    )

    rp = SchematicView(owner=rpair, instances={}, nets={}, pin_to_net={}, port_map={})
    d.library[rpair].views["schematic"] = rp
    r1 = add_instance(d, rp, res, "R1")
    r2 = add_instance(d, rp, res, "R2")
    ntop = create_net(d, rp, "ntop")
    nmid = create_net(d, rp, "nmid")
    nbot = create_net(d, rp, "nbot")
    connect(d, rp, ipin(d, rp, r1, "a"), ntop)
    connect(d, rp, ipin(d, rp, r1, "b"), nmid)
    connect(d, rp, ipin(d, rp, r2, "a"), nmid)
    connect(d, rp, ipin(d, rp, r2, "b"), nbot)

    # make the 3 internal nets as ports
    net_for_port = {"top": ntop, "mid": nmid, "bot": nbot}
    for pid, pin in d.library[rpair].pins.items():
        rp.port_map[pid] = net_for_port[pin.name]

    # top cell
    top = add_cell(d, "divider_top", [])
    d.top = top
    tv = SchematicView(owner=top, instances={}, nets={}, pin_to_net={}, port_map={})
    d.library[top].views["schematic"] = tv
    x = add_instance(d, tv, rpair, "X")
    v = add_instance(d, tv, vsrc, "V")
    vin = create_net(d, tv, "vin")
    vmid = create_net(d, tv, "vmid")
    gnd = create_net(d, tv, "gnd")
    connect(d, tv, ipin(d, tv, x, "top"), vin)
    connect(d, tv, ipin(d, tv, x, "mid"), vmid)
    connect(d, tv, ipin(d, tv, x, "bot"), gnd)
    connect(d, tv, ipin(d, tv, v, "p"), vin)
    connect(d, tv, ipin(d, tv, v, "n"), gnd)
    return d, top


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

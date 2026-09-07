import json

from eda_proto.ids import CellId, InstanceId, InstancePin, NetId, PinId
from eda_proto.invariants import check_invariants
from eda_proto.model import Cell, Design, Direction, Instance, Net, Pin, SchematicView, View
from eda_proto.oracle import recompute_index


# ===============================================================
# HELPERS: equality checks for model objects
# ===============================================================
def cell_equal(c1: Cell, c2: Cell) -> bool:
    """Check if two cells are equal.
    Args:
        c1: First cell.
        c2: Second cell.
    Returns:
        bool: True if the cells are equal, False otherwise.
    """
    if c1.id != c2.id:
        return False
    if c1.name != c2.name:
        return False

    # pins: same ids and each pin equal
    if set(c1.pins) != set(c2.pins):
        return False
    for pid in c1.pins:
        if not pins_equal(c1.pins[pid], c2.pins[pid]):
            return False

    # views: same types like ("schematic", "layout") and each view equal
    if set(c1.views) != set(c2.views):
        return False
    for kind in c1.views:
        if not views_equal(c1.views[kind], c2.views[kind]):
            return False

    return True


def pins_equal(p1: Pin, p2: Pin) -> bool:
    return p1.id == p2.id and p1.name == p2.name and p1.direction == p2.direction


def views_equal(v1: View, v2: View) -> bool:
    """Check if two views are equal.
    Args:
        v1: First view.
        v2: Second view.
    Returns:
        bool: True if the views are equal, False otherwise.
    """
    if type(v1) is not type(v2):
        return False
    if not isinstance(v1, SchematicView) or not isinstance(v2, SchematicView):
        return True  # bare view, nothing to compare
    # compare schematic view attributes
    if v1.owner != v2.owner:
        return False
    # same ids and instances equal
    if set(v1.instances) != set(v2.instances):
        return False
    for iid in v1.instances:
        if not instances_equal(v1.instances[iid], v2.instances[iid]):
            return False
    # same ids and nets equal
    if set(v1.nets) != set(v2.nets):
        return False
    for nid in v1.nets:
        if not nets_equal(v1.nets[nid], v2.nets[nid]):
            return False
    # port_map
    if v1.port_map != v2.port_map:
        return False

    return True


def instances_equal(i1: Instance, i2: Instance) -> bool:
    return i1.id == i2.id and i1.name == i2.name and i1.cell == i2.cell and i1.params == i2.params


def nets_equal(n1: Net, n2: Net) -> bool:
    return n1.id == n2.id and n1.name == n2.name and n1.pins == n2.pins


# ===============================================================
# MAIN ENTRY POINT: compare two designs for equality
# ===============================================================
def designs_equal(d1: Design, d2: Design) -> bool:
    """Check if two designs are equal.
    Args:
        d1: First design.
        d2: Second design.
    Returns:
    bool: True if the designs are equal, False otherwise.
    """
    if d1._next_id != d2._next_id:
        return False
    if d1.top != d2.top:
        return False
    if set(d1.library) != set(d2.library):
        return False  # same cell ids
    # each cell matches its twin
    for cid in d1.library:
        if not cell_equal(d1.library[cid], d2.library[cid]):
            return False

    return True


# ====================================================================
# SAVING DESIGN TO FILE
# ====================================================================
def design_to_dict(design: Design) -> dict:
    """Convert a Design object to a dictionary representation.
    Args:
        design: The Design object to convert.
    Returns:
        dict: A dictionary representation of the Design object.
    """
    return {
        "version": 1,
        "next_id": design._next_id,  # counter included
        "top": design.top,
        "library": [
            cell_to_dict(cell) for cell in sorted(design.library.values(), key=lambda c: c.id)
        ],
    }


def cell_to_dict(cell: Cell) -> dict:
    """Convert a Cell object to a dictionary representation.
    Args:
        cell: The Cell object to convert.
    Returns:
        dict: A dictionary representation of the Cell object.
    """
    return {
        "id": cell.id,
        "name": cell.name,
        "pins": [
            {"id": p.id, "name": p.name, "direction": p.direction.value}
            for p in sorted(cell.pins.values(), key=lambda p: p.id)
        ],
        "views": [
            [kind, view_to_dict(cell.views[kind])]
            for kind in sorted(cell.views)  # key is a string, sorts ok
        ],
    }


def view_to_dict(view: View) -> dict:
    """Convert a View object to a dictionary representation.
    Args:
        view: The View object to convert.
    Returns:
        dict: A dictionary representation of the View object.
    """
    if not isinstance(view, SchematicView):
        raise ValueError(f"cannot serialize view of type {type(view).__name__}")
    return {
        "owner": view.owner,
        "instances": [
            {"id": inst.id, "name": inst.name, "cell": inst.cell, "params": inst.params}
            for inst in sorted(view.instances.values(), key=lambda inst: inst.id)
        ],
        "nets": [net_to_dict(n) for n in sorted(view.nets.values(), key=lambda n: n.id)],
        "port_map": [
            [pid, view.port_map[pid]]
            for pid in sorted(view.port_map)  # pid is int
        ],
    }


def net_to_dict(net: Net) -> dict:
    return {
        "id": net.id,
        "name": net.name,
        "pins": [
            [ip.instance, ip.pin] for ip in sorted(net.pins, key=lambda ip: (ip.instance, ip.pin))
        ],
    }


def save(design: Design, path: str) -> None:
    text = json.dumps(design_to_dict(design), sort_keys=True, indent=2)
    with open(path, "w") as f:
        f.write(text + "\n")


# ====================================================================
# LOADING DESIGN FROM FILE
# ====================================================================
def design_from_dict(data: dict) -> Design:
    # if data["version"] != 1:
    #     raise ValueError(f"unknown format version {data['version']}")
    data = _migrate_to_current(data)
    design = Design()
    design._next_id = data["next_id"]  # restore counter
    design.top = CellId(data["top"]) if data["top"] is not None else None
    for cell_data in data["library"]:
        cell = cell_from_dict(cell_data)
        if cell.id in design.library:
            raise ValueError(f"duplicate cell {cell.id}")
        design.library[cell.id] = cell
    check_invariants(design)
    return design


def cell_from_dict(cell_data: dict) -> Cell:
    pins: dict = {}
    for p in cell_data["pins"]:
        pin = Pin(id=PinId(p["id"]), name=p["name"], direction=Direction(p["direction"]))
        if pin.id in pins:
            raise ValueError(f"duplicate pin id {pin.id}")
        pins[pin.id] = pin
    views: dict = {}
    for kind, view_data in cell_data["views"]:
        views[kind] = view_from_dict(view_data)  # only Schematic view for now
    return Cell(id=CellId(cell_data["id"]), name=cell_data["name"], pins=pins, views=views)


def view_from_dict(view_data: dict) -> SchematicView:
    instances = {}
    for i in view_data["instances"]:
        inst = Instance(
            id=InstanceId(i["id"]), name=i["name"], cell=CellId(i["cell"]), params=i["params"]
        )
        if inst.id in instances:
            raise ValueError(f"duplicate instance id {inst.id}")
        instances[inst.id] = inst
    nets = {}
    for n in view_data["nets"]:
        net = net_from_dict(n)
        if net.id in nets:
            raise ValueError(f"duplicate net id {net.id}")
        nets[net.id] = net
    port_map = {PinId(pid): NetId(nid) for pid, nid in view_data["port_map"]}
    view = SchematicView(
        owner=CellId(view_data["owner"]),
        instances=instances,
        nets=nets,
        pin_to_net={},
        port_map=port_map,
    )
    view.pin_to_net = recompute_index(view)  # rebuild derived index
    return view


def net_from_dict(n: dict) -> Net:
    pins = {InstancePin(InstanceId(inst), PinId(pin)) for inst, pin in n["pins"]}
    return Net(id=NetId(n["id"]), name=n["name"], pins=pins)


def load(path: str) -> Design:
    with open(path) as f:
        data = json.load(f)
    return design_from_dict(data)


# ====================================================================
# VERSION/MIGRATION HANDLING
# ====================================================================
CURRENT_VERSION = 1


def _migrate_0_to_1(data: dict) -> dict:
    """v0 stored counter as 'counter', v1 renamed it 'next_id'."""
    data = dict(data)
    data["next_id"] = data.pop("counter")
    return data


# register by the version you're migrating from
MIGRATIONS = {
    0: _migrate_0_to_1,
}


def _migrate_to_current(data: dict) -> dict:
    version = data["version"]
    if version > CURRENT_VERSION:
        raise ValueError(
            f"file version {version} is newer than this build supports "
            f"(max{CURRENT_VERSION}); upgrade the software"
        )
    while version < CURRENT_VERSION:
        migrate = MIGRATIONS.get(version)
        if migrate is None:
            raise ValueError(f"no migration path from version {version}")
        data = migrate(data)
        version += 1  # increase v(N) to v(N+1)
    return data

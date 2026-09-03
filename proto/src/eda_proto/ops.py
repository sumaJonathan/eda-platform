from eda_proto.ids import CellId, InstanceId, InstancePin, NetId, PinId
from eda_proto.model import Cell, Design, Direction, Instance, Net, Pin, SchematicView


## HELPERS
def ipin(
    design: Design, view: SchematicView, instance_id: InstanceId, pin_name: str
) -> InstancePin:
    """Resolve 'R1's pin named a' into an InstancePin(R1, <pin ID>).

    Callers can say ipin(d, sch, R1, "a") instead of hunting
    down the pin's numeric ID by hand. Also a validity check: if cell
    has no pin with that name, it flags so you cannot create an
    InstancePin that would violate invariant rules.
    """
    inst = view.instances.get(instance_id)
    if inst is None:
        raise ValueError(f"Instance with ID {instance_id} is not in this view.")
    cell = design.library[inst.cell]
    for p in cell.pins.values():
        if p.name == pin_name:
            return InstancePin(instance_id, p.id)
    raise ValueError(f"{cell.name} has no pin '{pin_name}'")


def _attach(view: SchematicView, ipin: InstancePin, net_id: NetId) -> None:
    """The ONLY function that adds a pin to a net. Updates both sides together.

    Leading underscore = 'internal to this module'. Nothing outside ops.py
    should call this; callers use connect().
    """
    assert ipin not in view.pin_to_net
    view.nets[net_id].pins.add(ipin)  # set side
    view.pin_to_net[ipin] = net_id  # index side


def _detach(view: SchematicView, ipin: InstancePin) -> None:
    """The ONLY function that removes a pin from a net. No-op if not connected.

    The net-emptiness policy lives here, in exactly one place.
    """
    net_id = view.pin_to_net.pop(ipin, None)
    if net_id is None:  # if pin wasn't connected
        return
    net = view.nets[net_id]
    net.pins.discard(ipin)  # remove if present, no error
    if not net.pins:
        del view.nets[net_id]


## MAIN OPERATIONS
def add_cell(design: Design, name: str, pin_specs: list[tuple[str, Direction]]) -> CellId:
    """Add a new leaf cell (a blueprint) to the library. Returns its id.

    pin_specs: your chosen shape for declaring pins. If you went with
    [("a", Direction.PASSIVE), ("b", Direction.PASSIVE)], the steps below
    assume that. If you went with ["a", "b"] + a passive default, adjust step 3.
    """
    for cell in design.library.values():
        if cell.name == name:  # reject duplicate cell name
            raise ValueError(f"a cell name '{name}' already exists")

    cid = design.new_cell_id()  # create cell id
    pins: dict[PinId, Pin] = {}  # build pins dict, rejecting duplicates
    seen_names: set[str] = set()
    for pin_name, direction in pin_specs:
        if pin_name in seen_names:
            raise ValueError(f"cell '{name}' declares two pins named '{pin_name}'")
        seen_names.add(pin_name)
        pid = design.new_pin_id()
        pins[pid] = Pin(id=pid, name=pin_name, direction=direction)
    cell = Cell(id=cid, name=name, pins=pins, views={})  # construct the cell
    design.library[cid] = cell  # add it to library with its own id

    return cid


def _reaches(design: Design, start_cell: CellId, target_cell: CellId) -> bool:
    """True if start_cell contains target_cell anywhere below it or IS it. (DFS)"""
    seen = set()  # already visited cells
    stack = [start_cell]
    while stack:
        cid = stack.pop()
        if cid == target_cell:
            return True  # found path to target
        if cid in seen:
            continue
        seen.add(cid)
        cell = design.library.get(cid)
        if cell is None:
            continue  # untethered reference
        v = cell.views.get("schematic")
        if isinstance(v, SchematicView):
            for inst in v.instances.values():
                stack.append(inst.cell)  # go to children
    return False  # no path found in tree


def add_instance(design: Design, view: SchematicView, cell_id: CellId, name: str) -> InstanceId:
    """Place an instance of cell_id into view. Returns the instance's id.

    An instance REFERENCES its cell by id. It never copies it. Ten instances
    of 'resistor' are ten small objects all pointing at one library cell.
    """
    # reject unknown cell
    if cell_id not in design.library:
        raise ValueError(f"no cell with ID {cell_id} in the library")

    # reject duplicate instance name in the given view
    for inst in view.instances.values():
        if inst.name == name:
            raise ValueError(f"'{name}' already names an instance in this view")

    # reject hierarchy cycles, no cell in same cell
    if cell_id == view.owner or _reaches(design, cell_id, view.owner):
        raise ValueError(
            f"placing cell {cell_id} in cell {view.owner}'s schematicwould create a hierarchy cycle"
        )

    # create ID, construct instance, and add to view
    iid = design.new_instance_id()
    view.instances[iid] = Instance(id=iid, name=name, cell=cell_id, params={})
    return iid


def create_net(design: Design, view: SchematicView, name: str | None = None) -> NetId:
    """Make a new, empty net in view. name=None means anonymous.

    An empty net is a TRANSIENT state: you create it, then connect pins to it.
    Invariant 6 forbids empty nets AT REST, so run check_invariants only at
    operation boundaries (after a create+connect sequence), never mid-build.
    Your divider tests already follow this -- nets created, then filled, then
    checked at the end.
    """
    if name is not None:
        for net in view.nets.values():
            if net.name == name:
                raise ValueError(f"net '{net.name}' already exists in this view")
    nid = design.new_net_id()
    view.nets[nid] = Net(id=nid, name=name, pins=set())
    return nid


def connect(design: Design, view: SchematicView, ipin: InstancePin, net_id: NetId) -> None:
    """Wire ipin onto net_id. The public front door to _attach."""
    # validate instance
    if ipin.instance not in view.instances:
        raise ValueError(f"pin {ipin.pin} instance does not exist in this view's instances")

    # validate pin belongs to the instance's cell
    inst = view.instances[ipin.instance]
    cell = design.library[inst.cell]
    if ipin.pin not in cell.pins:
        raise ValueError(f"{cell.name} has no pin with ID {ipin.pin}")

    # validate net exists
    if net_id not in view.nets:
        raise ValueError(f"no net with ID {net_id} in this view")

    # handle already connected pin/net
    existing = view.pin_to_net.get(ipin)
    if existing is not None:
        if existing == net_id:
            return
        else:
            raise ValueError(
                f"pin {ipin.pin} already connected to net {existing}, disconnect first"
            )
    _attach(view, ipin, net_id)


def disconnect(design: Design, view: SchematicView, ipin: InstancePin) -> None:
    """Unwire ipin. Front door to _detach. No-op if it wasn't connected."""
    _detach(view, ipin)


def merge_nets(design: Design, view: SchematicView, keep: NetId, drop: NetId) -> None:
    """Fuse net 'drop' into net 'keep'. After this, 'drop' no longer exists,
    and all its pins are on 'keep'.
    """
    # validate both nets exist in this view
    if keep not in view.nets:
        raise ValueError(f"no net with ID {keep} in this view")
    if drop not in view.nets:
        raise ValueError(f"no net with ID {drop} in this view")
    if keep == drop:
        return  # nothing to do

    # move all pins from drop to keep
    drop_net = view.nets[drop]
    for ipin in list(drop_net.pins):
        view.nets[keep].pins.add(ipin)  # set aside
        view.pin_to_net[ipin] = keep  # rewrite index
    # delete the now-empty drop net
    del view.nets[drop]


def split_net(
    design: Design, view: SchematicView, net_id: NetId, pins_to_move: set[InstancePin]
) -> NetId:
    """Peel a subset of pins off net_id onto a new net. Returns new net's ID.
    Choice of split: user decides which pins form the new group assuming there's
    no wire topology to decide for them. Phase 2 with use wire-graph connectivity
    to compute pins_to_move automatically. For now, it's supplied.
    """
    # validate net exists
    if net_id not in view.nets:
        raise ValueError(f"no net with ID {net_id} in this view")
    # validate pins_to_move is non-empty
    if not pins_to_move:
        raise ValueError("pins_to_move cannot be empty")
    # validate pins_to_move are all on net_id
    for pin in pins_to_move:
        if view.pin_to_net.get(pin) != net_id:
            raise ValueError(f"pin {pin} is not on net {net_id}")
    # validate pins_to_move ALL of the net's pins
    remaining = view.nets[net_id].pins - pins_to_move  # set difference
    if not remaining:
        raise ValueError(f"split will leave net {net_id} empty; not a proper split")
    # create new net
    new_net_id = create_net(design, view)  # anonymous; caller can name later
    # move pins to new net
    for pin in pins_to_move:
        _detach(view, pin)
        _attach(view, pin, new_net_id)

    return new_net_id


def pins_on_net(view: SchematicView, net_id: NetId) -> frozenset[InstancePin]:
    """Every pin wired to net_id. The query from the Done-when line."""
    return frozenset(view.nets[net_id].pins)


def nets_on_instance(
    design: Design, view: SchematicView, instance_id: InstanceId
) -> dict[PinId, NetId | None]:
    """For each of an instance's pins, which net it's on (or None if unwired)."""
    inst = view.instances[instance_id]
    cell = design.library[inst.cell]
    result: dict[PinId, NetId | None] = {}
    for pid in cell.pins:
        result[pid] = view.pin_to_net.get(InstancePin(instance_id, pid))
    return result


def delete_instance(design: Design, view: SchematicView, instance_id: InstanceId) -> None:
    """Remove an instance and unwire all its pins."""
    if instance_id not in view.instances:
        raise ValueError(f"Instance {instance_id} does not exist in this view")
    inst = view.instances[instance_id]
    cell = design.library[inst.cell]

    # detach every pin first to avoid floating pins
    for pid in cell.pins:
        _detach(view, InstancePin(instance_id, pid))

    # delete any port_maps that point to deleted nets
    for pid, nid in list(view.port_map.items()):
        if nid not in view.nets:
            del view.port_map[pid]

    del view.instances[instance_id]

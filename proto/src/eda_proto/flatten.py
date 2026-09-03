from dataclasses import dataclass

from eda_proto.ids import CellId, InstancePin, PinId
from eda_proto.model import Cell, Design, SchematicView

FlatPin = tuple[str, PinId]


@dataclass
class FlatNetlist:
    instances: dict[str, CellId]
    nets: dict[int, set[FlatPin]]
    _next: int = 0

    def new_net(self) -> int:
        self._next += 1
        self.nets[self._next] = set()
        return self._next


def flatten(design: Design, top_cell_id: CellId) -> FlatNetlist:
    """Collapse a hierarchical design into a flat netlist of leaf instances."""
    flat = FlatNetlist(instances={}, nets={})
    top = design.library[top_cell_id]
    _expand(design, top, prefix="", port_to_flat={}, flat=flat)
    return flat


def _is_leaf(cell: Cell) -> bool:
    """Determine if a cell is a leaf node (has no hierarchical children)."""
    return not isinstance(cell.views.get("schematic"), SchematicView)


def _expand(
    design: Design, cell: Cell, prefix: str, port_to_flat: dict[PinId, int], flat: FlatNetlist
) -> None:
    """Expand one hierarchical cell into a flat netlist.
    prefix:         path so far like "X/"
    port_to_flat:   {this cell's PinId, flat net id it should identify
                    with supplied by the parent. Empty at top level.}
    """
    view = cell.views.get("schematic")
    if not isinstance(view, SchematicView):
        raise ValueError(f"cell {cell.name} has no schematic view to expand")
    # invert port_map to know if an internal net is a port
    net_to_port = {net_id: pin_id for pin_id, net_id in view.port_map.items()}
    # UNIFICATION: decide flat net for every internal net of this view
    local_to_flat: dict[int, int] = {}
    for original_net in view.nets:
        port_pin = net_to_port.get(original_net)
        if port_pin is not None and port_pin in port_to_flat:
            # net is a port, the parent already wired->reuse parent's flat net
            local_to_flat[original_net] = port_to_flat[port_pin]
        else:
            # net is internal, create new flat net
            local_to_flat[original_net] = flat.new_net()

    # Walk instances in this view
    for inst in view.instances.values():
        subcell = design.library[inst.cell]
        path = prefix + inst.name

        if _is_leaf(subcell):
            # a real device -> emit it
            flat.instances[path] = subcell.id
            for pid in subcell.pins:
                net_id = view.pin_to_net.get(InstancePin(inst.id, pid))
                if net_id is not None:  # skip unwired pins
                    flat.nets[local_to_flat[net_id]].add((path, pid))
        else:
            # hierarchical -> recurse. First build the child's port map:
            # for each subcell's port pins, find which flat net this view
            # view wires it to, and hand that down.
            child_port_to_flat: dict[PinId, int] = {}
            for pid in subcell.pins:
                net_id = view.pin_to_net.get(InstancePin(inst.id, pid))
                if net_id is not None:
                    child_port_to_flat[pid] = local_to_flat[net_id]

            _expand(design, subcell, path + "/", child_port_to_flat, flat)

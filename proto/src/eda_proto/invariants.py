"""Constistency checks on a given users Design. Read-only; never change the design."""

from collections.abc import Callable, Iterable, Iterator
from typing import TypeVar

from eda_proto.ids import InstancePin, NetId
from eda_proto.model import Cell, Design, SchematicView

T = TypeVar("T")


## HEADERS: for formatting error messagess
def _schematic_views(design) -> Iterator[tuple[Cell, SchematicView]]:
    # Yield cell & view for each cell with schematic view.
    # Leaf cells like resistors do not have schematic views & are skipped.
    for cell in design.library.values():
        v = cell.views.get("schematic")
        if isinstance(v, SchematicView):
            yield (cell, v)


def _iname(view, iid) -> str:
    # Format instance ID for error message readability
    inst = view.instances.get(iid)
    if inst is None:
        return f"<missing instance ID = {iid}>"
    return f"{inst.name} (ID = {iid})"


def _pname(design, view, ipin) -> str:
    # Format InstancePin name for error reference eg. "R1.b" if resolved, diagnostic msg if not
    inst = view.instances.get(ipin.instance)
    if inst is None:
        return f"<pin {ipin.pin} missing on instance {ipin.instance}>"
    cell = design.library.get(inst.cell)
    if cell is None:
        return f"{inst.name}.<pin {ipin.pin}, cell missing>"
    pin = cell.pins.get(ipin.pin)
    if pin is None:
        return f"{inst.name}.<undeclared pin ID={ipin.pin}>"
    return f"{inst.name}.{pin.name}"


## INVARIANT checks
# INV 1: Every InstanceId mentioned anywhere in a view exists in that view.
def _check_instances_resolve(design) -> list[str]:
    problems = []
    for cell, view in _schematic_views(design):
        # dict key must agree with the object it holds
        for iid, inst in view.instances.items():
            if inst.id != iid:
                problems.append(
                    f"cell '{cell.name}': instances dict key {iid} "
                    f"holds an instance whose own id is {inst.id}"
                )
        # every instance referenced by a net must live in this view
        for net in view.nets.values():
            for ipin in net.pins:
                if ipin.instance not in view.instances:
                    problems.append(
                        f"cell '{cell.name}': net {net.name or net.id} holds a pin "
                        f"on instance ID {ipin.instance}, which is not in this view"
                    )
        # same for the index
        for ipin in view.pin_to_net:
            if ipin.instance not in view.instances:
                problems.append(
                    f"cell '{cell.name}': pin_to_net has an entry for "
                    f"instance ID {ipin.instance}, which is not in this view"
                )
    return problems


# INV 2: Every instance references a cell that exists in the library.
def _check_cells_resolve(design) -> list[str]:
    problems = []
    for cell, view in _schematic_views(design):
        for inst in view.instances.values():
            if inst.cell not in design.library:
                problems.append(
                    f"cell '{cell.name}': instance {_iname(view, inst.id)} "
                    f"references missing cell id {inst.cell}"
                )
    # check same loop shape
    for cid, c in design.library.items():
        if c.id != cid:
            problems.append(f"library key {cid} holds a cell whose own id is {c.id}")
        for pid, p in c.pins.items():
            if p.id != pid:
                problems.append(
                    f"cell '{c.name}': pins dict key {pid} holds a pin whose own id is {p.id}"
                )
    # check design top cell is in library
    if design.top is not None and design.top not in design.library:
        problems.append(f"design.top points at missing cell id {design.top}")
    return problems


# INV 3: Every InstancePin names a pin actually declared by the instance's cell.
def _check_pins_belong_to_cell(design) -> list[str]:
    problems = []
    for cell, view in _schematic_views(design):
        # collect every InstancePin in this view
        all_pins = set()
        for net in view.nets.values():
            all_pins |= net.pins
        all_pins |= set(view.pin_to_net.keys())

        for ipin in all_pins:
            inst = view.instances.get(ipin.instance)
            if inst is None:
                continue  # invariant 1 already reported
            c = design.library.get(inst.cell)
            if c is None:
                continue  # invariant 2 already reported
            if ipin.pin not in c.pins:
                problems.append(
                    f"cell '{cell.name}': instance {_iname(view, ipin.instance)} "
                    f"is a '{c.name}', which has no pin with ID {ipin.pin}"
                )
    return problems


# INV 4: pin_to_net and net.pins agree in both directions
def _check_index_is_inverse(design) -> list[str]:
    problems = []
    for cell, view in _schematic_views(design):
        # FORWARD: index -> sets
        for ipin, nid in view.pin_to_net.items():
            if nid not in view.nets:
                problems.append(
                    f"cell '{cell.name}': index says {_pname(design, view, ipin)} is "
                    f"on net {nid}, which does not exist in this view"
                )
                continue
            if ipin not in view.nets[nid].pins:
                problems.append(
                    f"cell '{cell.name}': index says {_pname(design, view, ipin)} is "
                    f"on net {nid}, but the net lacks this pin"
                )
        # BACKWARD: sets -> index
        for net in view.nets.values():
            for ipin in net.pins:
                if ipin not in view.pin_to_net:
                    problems.append(
                        f"cell '{cell.name}': net {net.id} contains {_pname(design, view, ipin)},"
                        f"but the index has no entry for it"
                    )
                elif view.pin_to_net[ipin] != net.id:
                    problems.append(
                        f"cell '{cell.name}': net {net.id} contains {_pname(design, view, ipin)},"
                        f"but the index says it is on net {view.pin_to_net[ipin]}"
                    )
    return problems


# INV 5: No InstancePin appears in two different nets' pin sets.
def _check_pin_in_at_most_one_net(design) -> list[str]:
    problems = []
    for cell, view in _schematic_views(design):
        seen: dict[InstancePin, NetId] = {}  # InstancePin -> first NetId it appeared in
        for net in view.nets.values():
            for ipin in net.pins:
                if ipin in seen:
                    problems.append(
                        f"cell '{cell.name}': {_pname(design, view, ipin)} is in "
                        f"both net {seen[ipin]} and net {net.id}"
                    )
                else:
                    seen[ipin] = net.id
    return problems


# INV 6: A net with zero pins is garbage; collect it in _detach.
def _check_no_empty_nets(design) -> list[str]:
    problems = []
    for cell, view in _schematic_views(design):
        for net in view.nets.values():
            if len(net.pins) == 0:
                problems.append(f"cell '{cell.name}': net {net.name or net.id} has no pins")
    return problems


# INV 7: The owning cell's pins map to nets that exist inside it.
def _check_port_map(design) -> list[str]:
    problems = []
    for cell, view in _schematic_views(design):
        if view.owner != cell.id:
            problems.append(
                f"cell '{cell.name}' (ID={cell.id}) holds a schematic "
                f"view that belongs to cell {view.owner}"
            )
        for pid, nid in view.port_map.items():
            if pid not in cell.pins:
                problems.append(
                    f"cell '{cell.name}': port_map has an entry for "
                    f"pin ID {pid}, which this cell does not declare"
                )
            if nid not in view.nets:
                problems.append(
                    f"cell '{cell.name}': port_map maps pin {pid} to "
                    f"net {nid}, which does not exist in this view"
                )
    return problems


# INV 8: No cell contains, even indirectly, an instance of itself.
def _check_no_cycles(design) -> list[str]:
    problems = []
    visiting = set()  # cells on current path down from the root
    done = set()  # cells already on proven clean, don't rewalk

    def walk(cid, path):
        def _name_of(xid):
            c = design.library.get(xid)
            return c.name if c is not None else f"<ID {xid}>"

        if cid in done:
            return
        if cid in visiting:
            chain = " -> ".join(_name_of(x) for x in (path + [cid]))
            problems.append(f"hierarchy cycle: {chain}")
            return
        visiting.add(cid)
        c = design.library.get(cid)
        if c is not None:
            v = c.views.get("schematic")
            if isinstance(v, SchematicView):
                for inst in v.instances.values():
                    walk(inst.cell, path + [cid])
        visiting.discard(cid)
        done.add(cid)

    for cid in design.library:
        walk(cid, [])
    return problems


# INV 9: Names are a UI convenience but must resolve unambiguously.
def _check_names_unique(design) -> list[str]:
    # Helper: given objects & fxn that extracts a name from each
    # return names that appear more than once
    def _dupes(items: Iterable[T], keyfn: Callable[[T], object]) -> list[tuple[object, list[T]]]:
        groups: dict[object, list[T]] = {}  # collect any list longer than 1
        for item in items:
            name = keyfn(item)
            groups.setdefault(name, []).append(item)
        return [(name, objs) for (name, objs) in groups.items() if len(objs) > 1]

    problems = []
    # 1. cell names unique across the whole library
    for name, cells in _dupes(design.library.values(), lambda c: c.name):
        problems.append(
            f"library has {len(cells)} cells named '{name}' (IDs {sorted(c.id for c in cells)})"
        )

    # 2. pin names unique within each cell
    for cell in design.library.values():
        for name, pins in _dupes(cell.pins.values(), lambda p: p.name):
            problems.append(f"cell '{cell.name}' declares {len(pins)} pins named '{name}'")

    # 3. instance names unique within each view
    for cell, view in _schematic_views(design):
        for name, insts in _dupes(view.instances.values(), lambda i: i.name):
            problems.append(f"cell '{cell.name}': {len(insts)} instances named '{name}'")

    # 4. net names unique within each view, ignoring anonymous nets
    for cell, view in _schematic_views(design):
        named = [n for n in view.nets.values() if n.name is not None]
        for name, nets in _dupes(named, lambda n: n.name):
            problems.append(f"cell '{cell.name}': {len(nets)} nets named '{name}'")

    return problems


# INV 10: the id counter is at least as large as every id in use.
def _check_counter_covers_ids(design) -> list[str]:
    problems = []
    max_seen = 0
    for cid, cell in design.library.items():
        max_seen = max(max_seen, cid)
        for pid in cell.pins:
            max_seen = max(max_seen, pid)
        v = cell.views.get("schematic")
        if isinstance(v, SchematicView):
            for iid in v.instances:
                max_seen = max(max_seen, iid)
            for nid in v.nets:
                max_seen = max(max_seen, nid)
    if max_seen > design._next_id:
        problems.append(
            f"id counter _next_id={design._next_id} is below the largest id "
            f"in use ({max_seen}); a new id would collide"
        )
    return problems


## ALTOGETHER: combined function call
_CHECKS = [
    _check_cells_resolve,
    _check_instances_resolve,
    _check_pins_belong_to_cell,
    _check_index_is_inverse,
    _check_pin_in_at_most_one_net,
    _check_no_empty_nets,
    _check_port_map,
    _check_no_cycles,
    _check_names_unique,
    _check_counter_covers_ids,
]


def check_invariants(design: Design) -> None:
    """Raise AssertionError listing every violation found. No errors found if clean."""
    problems = [p for check in _CHECKS for p in check(design)]
    if problems:
        raise AssertionError(f"{len(problems)} invariant violation(s):\n " + "\n ".join(problems))

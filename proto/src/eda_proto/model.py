"""Define Pin, Cell, Instance, Net, SchematicView, Design"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from eda_proto.ids import CellId, InstanceId, InstancePin, NetId, PinId


class Direction(Enum):
    """Direction of a Pin or Port"""

    IN = "input"
    OUT = "output"
    INOUT = "inout"
    PASSIVE = "passive"


class View:
    """A View is a representation of a Cell or Instance"""

    pass


@dataclass
class Pin:
    """A Pin is a connection point on a Cell or Instance"""

    id: PinId
    name: str
    direction: Direction


@dataclass
class Cell:
    """A Cell is a reusable building block in a design"""

    id: CellId
    name: str
    pins: dict[PinId, Pin]  # External interface of cell
    views: dict[str, View]  # "symbol" | "spice" | "schematic"


@dataclass
class Instance:
    """An Instance is a specific occurrence of a Cell in a SchematicView"""

    id: InstanceId
    name: str
    cell: CellId
    params: dict[str, Any]  # eg. R1 resistance = 1000


@dataclass
class Net:
    """A Net is a collection of connected pins in a SchematicView"""

    id: NetId
    name: str | None  # None = "unnamed/autonamed net"
    pins: set[InstancePin] = field(default_factory=set)  # pins connected to the net


@dataclass
class SchematicView(View):
    """A SchematicView is a graphical representation of a Cell or Instance"""

    owner: CellId
    instances: dict[InstanceId, Instance] = field(
        default_factory=dict
    )  # Instances in the schematic
    nets: dict[NetId, Net] = field(default_factory=dict)  # Nets in the schematic
    pin_to_net: dict[InstancePin, NetId] = field(default_factory=dict)  # the index
    port_map: dict[PinId, NetId] = field(default_factory=dict)  # owner's pin -> nets


@dataclass
class Design:
    """A Design is a collection of Cells and SchematicViews"""

    library: dict[CellId, Cell] = field(default_factory=dict)  # all cells in the design
    top: CellId | None = None  # top-level cell in the design
    _next_id: int = 0  # internal counter for generating new ids

    def new_id(self) -> int:
        """Generate a new unique id for a Cell, Instance, Pin, or Net"""
        self._next_id += 1
        return self._next_id

    def new_cell_id(self) -> CellId:
        """Generate a new unique CellId"""
        return CellId(self.new_id())

    def new_instance_id(self) -> InstanceId:
        """Generate a new unique InstanceId"""
        return InstanceId(self.new_id())

    def new_pin_id(self) -> PinId:
        """Generate a new unique PinId"""
        return PinId(self.new_id())

    def new_net_id(self) -> NetId:
        """Generate a new unique NetId"""
        return NetId(self.new_id())

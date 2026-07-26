from dataclasses import dataclass
from typing import NewType

# ============ IDS for each cell, instance, pin, and net ============
CellId = NewType("CellId", int)
InstanceId = NewType("InstanceId", int)
PinId = NewType("PinId", int)
NetId = NewType("NetId", int)


@dataclass(frozen=True)
class InstancePin:
    instance: InstanceId
    pin: PinId

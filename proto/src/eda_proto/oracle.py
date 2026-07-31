from eda_proto.ids import InstancePin, NetId
from eda_proto.model import SchematicView


def recompute_index(view: SchematicView) -> dict[InstancePin, NetId]:
    """Rebuild pin_to_net from scratch, using net.pins as the only source.

    The obviously-correct version: walk every net and record where each pin is.
    """
    index: dict[InstancePin, NetId] = {}
    for net_id, net in view.nets.items():
        for pin in net.pins:
            index[pin] = net_id
    return index

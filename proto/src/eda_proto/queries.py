from eda_proto.ids import InstanceId, NetId
from eda_proto.model import Design, SchematicView
from eda_proto.ops import nets_on_instance


def instances_on_net(view: SchematicView, net_id: NetId) -> set[InstanceId]:
    """Which instances have at least one pin on this net?"""
    instances: set[InstanceId] = set()
    for ipin in view.nets[net_id].pins:
        instances.add(ipin.instance)
    return instances


def nets_on_instance_set(
    design: Design, view: SchematicView, instance_id: InstanceId
) -> set[NetId]:
    """Which nets does this instance touch? (dropping which pin connects to which)"""
    per_pin = nets_on_instance(design, view, instance_id)
    nets: set[NetId] = set()
    for net_id in per_pin.values():
        if net_id is not None:
            nets.add(net_id)
    return nets


def neighbors(design: Design, view: SchematicView, instance_id: InstanceId) -> set[InstanceId]:
    """Which instances share a net with the given one? (electrical adjacency)"""
    result: set[InstanceId] = set()
    for net_id in nets_on_instance_set(design, view, instance_id):
        for instance in instances_on_net(view, net_id):
            result.add(instance)
    result.discard(instance_id)  # remove the reference instance
    return result

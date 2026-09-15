from dataclasses import dataclass

from eda_proto import ops
from eda_proto.ids import CellId, InstanceId, InstancePin, NetId
from eda_proto.model import Design, Instance, Net, SchematicView
from eda_proto.serialize import cell_equal


# helper to recreate a deleted net with the original ID
def restore_net(design: Design, view: SchematicView, net_id: NetId, name: str, pins: set) -> None:
    view.nets[net_id] = Net(id=net_id, name=name, pins=set())
    for ipin in pins:
        ops._attach(view, ipin, net_id)  # rewire each pin
    design._next_id = max(design._next_id, net_id)


def designs_equivalent(d1: Design, d2: Design) -> bool:
    """Like designs_equal but keeps the counter going"""
    if d1.top != d2.top:
        return False
    if set(d1.library) != set(d2.library):
        return False
    for cid in d1.library:
        if not cell_equal(d1.library[cid], d2.library[cid]):
            return False
    return True


@dataclass
class AddInstanceCmd:
    cell_id: CellId
    name: str
    created_id: InstanceId | None = None  # filled at apply

    def apply(self, design: Design, view: SchematicView) -> InstanceId:
        if self.created_id is None:
            # fresh edit (create a new id)
            iid = ops.add_instance(design, view, self.cell_id, self.name)
            self.created_id = iid
        else:
            # replay
            iid = self.created_id
            view.instances[iid] = Instance(id=iid, name=self.name, cell=self.cell_id, params={})
            design._next_id = max(design._next_id, iid)  # keep counting
        return iid

    def invert(self):
        assert self.created_id is not None, "cannot invert before apply"
        return DeleteInstanceCmd(instance_id=self.created_id)

    def to_dict(self) -> dict:
        return {
            "op": "add_instance",
            "cell_id": self.cell_id,
            "name": self.name,
            "created_id": self.created_id,
        }

    @staticmethod
    def from_dict(d):
        return AddInstanceCmd(d["cell_id"], d["name"], d["created_id"])


@dataclass
class DeleteInstanceCmd:
    instance_id: InstanceId
    name: str | None = None
    cell: CellId | None = None
    params: dict | None = None
    memberships: dict | None = None  # {pin_id: net_id}
    emptied_nets: list | None = None  # [(net_id, name)]
    port_map_entries: list | None = None  # [(pin_in, net_id)]

    def apply(self, design: Design, view: SchematicView):
        inst = view.instances[self.instance_id]
        self.name = inst.name
        self.cell = inst.cell
        self.params = dict(inst.params)
        self.memberships = ops.nets_on_instance(design, view, self.instance_id)

        touched = {nid for nid in self.memberships.values() if nid is not None}
        self.emptied_nets = [
            (nid, view.nets[nid].name)
            for nid in touched
            if all(p.instance == self.instance_id for p in ops.pins_on_net(view, nid))
        ]
        emptied_ids = {nid for nid, _ in self.emptied_nets}
        self.port_map_entries = [
            (pid, nid) for pid, nid in view.port_map.items() if nid in emptied_ids
        ]
        ops.delete_instance(design, view, self.instance_id)

    def invert(self):
        assert self.name is not None
        assert self.cell is not None
        assert self.params is not None
        assert self.memberships is not None
        assert self.emptied_nets is not None
        assert self.port_map_entries is not None
        return RestoreInstanceCmd(
            self.instance_id,
            self.name,
            self.cell,
            self.params,
            self.memberships,
            self.emptied_nets,
            self.port_map_entries,
        )


@dataclass
class RestoreInstanceCmd:
    instance_id: InstanceId
    name: str
    cell: CellId
    params: dict
    memberships: dict  # {pin_id: net_id}
    emptied_nets: list  # [(net_id, name)]
    port_map_entries: list  # [(pid, net_id)]

    def apply(self, design: Design, view: SchematicView):
        view.instances[self.instance_id] = Instance(
            id=self.instance_id, name=self.name, cell=self.cell, params=dict(self.params)
        )
        # recreate nets that were emptied
        for net_id, net_name in self.emptied_nets:
            view.nets[net_id] = Net(id=net_id, name=net_name, pins=set())
        # reattach each pin to net it was on
        for pin_id, net_id in self.memberships.items():
            if net_id is not None:
                ops._attach(view, InstancePin(self.instance_id, pin_id), net_id)
        # restore removed port_map entries
        for pid, net_id in self.port_map_entries:
            view.port_map[pid] = net_id

    def invert(self):
        return DeleteInstanceCmd(self.instance_id)  # redo, delete again


@dataclass
class ConnectCmd:
    ipin: InstancePin
    net_id: NetId

    def apply(self, design: Design, view: SchematicView):
        ops.connect(design, view, self.ipin, self.net_id)

    def invert(self):
        return DisconnectCmd(self.ipin, self.net_id)

    def to_dict(self):
        return {
            "op": "connect",
            "instance": self.ipin.instance,
            "pin": self.ipin.pin,
            "net_id": self.net_id,
        }

    @staticmethod
    def from_dict(d):
        return ConnectCmd(InstancePin(d["instance"], d["pin"]), d["net_id"])


@dataclass
class DisconnectCmd:
    ipin: InstancePin
    net_id: NetId | None = None  # net it was on
    net_name: str | None = None
    net_deleted: bool = False  # did detach empty & delete it?

    def apply(self, design: Design, view: SchematicView) -> None:
        self.net_id = view.pin_to_net.get(self.ipin)
        if self.net_id is not None:
            self.net_name = view.nets[self.net_id].name
        ops.disconnect(design, view, self.ipin)
        self.net_deleted = self.net_id is not None and self.net_id not in view.nets

    def invert(self):
        return ReconnectCmd(self.ipin, self.net_id, self.net_name, self.net_deleted)


@dataclass
class ReconnectCmd:
    """Inverse of Disconnect, rewire pin, recreate net if emptied and deleted"""

    ipin: InstancePin
    net_id: NetId | None
    net_name: str | None
    net_deleted: bool

    def apply(self, design: Design, view: SchematicView) -> None:
        if self.net_id is None:
            return
        if self.net_deleted:
            view.nets[self.net_id] = Net(id=self.net_id, name=self.net_name, pins=set())
        ops._attach(view, self.ipin, self.net_id)  # rewire the pin

    def invert(self):
        return DisconnectCmd(self.ipin)  # redo = disconnect again


@dataclass
class MergeNetsCmd:
    keep: NetId
    drop: NetId
    drop_pins: set | None = None  # filled out at apply
    drop_name: str | None = None  # same here

    def apply(self, design: Design, view: SchematicView) -> None:
        drop_pins = set(ops.pins_on_net(view, self.drop))
        drop_name = view.nets[self.drop].name
        ops.merge_nets(design, view, self.keep, self.drop)
        self.drop_pins = drop_pins
        self.drop_name = drop_name

    def invert(self):
        assert self.drop_pins is not None
        return RestoreSplitCmd(self.keep, self.drop, self.drop_name, self.drop_pins)


@dataclass
class RestoreSplitCmd:
    """Inverse of MergeNets, puts dropped net back with its original id."""

    keep: NetId
    net_id: NetId  # net's original ID
    net_name: str | None
    pins: set  # pins that belong to drop

    def apply(self, design: Design, view: SchematicView) -> None:
        # recreate net with its original ID
        view.nets[self.net_id] = Net(id=self.net_id, name=self.net_name, pins=set())
        # move pins from keep to the retored net
        for ipin in self.pins:
            ops._detach(view, ipin)
            ops._attach(view, ipin, self.net_id)

    def invert(self):
        return MergeNetsCmd(keep=self.keep, drop=self.net_id)


@dataclass
class SplitNetCmd:
    net_id: NetId
    pins_to_move: set[InstancePin]
    new_net_id: NetId | None = None

    def apply(self, design: Design, view: SchematicView):
        if self.new_net_id is None:
            self.new_net_id = ops.split_net(design, view, self.net_id, self.pins_to_move)
        else:
            nid = self.new_net_id
            view.nets[nid] = Net(id=nid, name=None, pins=set())
            for ipin in self.pins_to_move:
                ops._detach(view, ipin)  # from the original net
                ops._attach(view, ipin, nid)  # to reused-id net
            design._next_id = max(design._next_id, nid)
        return self.new_net_id

    def invert(self):
        assert self.new_net_id is not None
        return MergeNetsCmd(keep=self.net_id, drop=self.new_net_id)

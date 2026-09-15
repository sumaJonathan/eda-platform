import copy

from eda_proto.commands import (
    AddInstanceCmd,
    ConnectCmd,
    DeleteInstanceCmd,
    DisconnectCmd,
    MergeNetsCmd,
    SplitNetCmd,
)
from eda_proto.model import Design, SchematicView

COMMANDS = {
    "add_instance": AddInstanceCmd,
    "connect": ConnectCmd,
    "disconnect": DisconnectCmd,
    "split_net": SplitNetCmd,
    "merge_nets": MergeNetsCmd,
    "delete_instance": DeleteInstanceCmd,
}


def command_from_dict(d):
    return COMMANDS[d["op"]].from_dict(d)


def top_schematic(design: Design) -> SchematicView:
    """Find top cell's schematic view within given design"""
    assert design.top is not None
    view = design.library[design.top].views["schematic"]
    assert isinstance(view, SchematicView)
    return view


class CommandLog:
    def __init__(self):
        self.commands = []  # ordered history
        self.cursor = 0  # cmds applied

    def record(self, cmd, design: Design, view: SchematicView):
        del self.commands[self.cursor :]  # new edit kills redo
        cmd.apply(design, view)
        self.commands.append(cmd)  # log it
        self.cursor += 1

    def undo(self, design: Design, view: SchematicView):
        if self.cursor == 0:
            return
        cmd = self.commands[self.cursor - 1]
        cmd.invert().apply(design, view)
        self.cursor -= 1

    def redo(self, design, view):
        if self.cursor == len(self.commands):
            return
        cmd = self.commands[self.cursor]
        cmd.apply(design, view)  # reuse ids
        self.cursor += 1

    def replay(self, base_design, view_of, upto=None):
        design = copy.deepcopy(base_design)
        for cmd in self.commands[:upto]:  # upto some index
            cmd.apply(design, view_of(design))  # view_of finds the right view
        return design

"""Property-based test: random sequence of net edits must preseve the invariants
and keep the incremental index equal to a frrom scratch recomputation.

The state machine has bookkeeping (free pins, live nets, etc) so each rule it
fires is a valid operation. A net is never empty at rest (inv 6), so we only ever
remove a pin from a net with 2+, and forget a net after merge/split.
"""

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from eda_proto.ids import InstancePin, NetId
from eda_proto.invariants import check_invariants
from eda_proto.ops import (
    add_instance,
    connect,
    create_net,
    disconnect,
    ipin,
    merge_nets,
    split_net,
)
from eda_proto.oracle import recompute_index
from eda_proto.serialize import design_from_dict, design_to_dict, designs_equal
from tests.helpers import scaffold


class NetlistMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.d, self.sch, self.ids = scaffold()
        self.free_pins: list[InstancePin] = []
        # net id-> set of pins currently on it (the mirror of truth)
        self.net_pins: dict[NetId, set[InstancePin]] = {}
        self._inst_count = 0
        for _ in range(3):
            self._new_instance()

    # helpers used by the rules
    def _new_instance(self) -> None:
        name = f"R{self._inst_count}"
        self._inst_count += 1
        inst = add_instance(self.d, self.sch, self.ids.res, name)
        self.free_pins.append(ipin(self.d, self.sch, inst, "a"))
        self.free_pins.append(ipin(self.d, self.sch, inst, "b"))

    def _fresh_net_with(self, pin: InstancePin) -> NetId:
        nid = create_net(self.d, self.sch)
        connect(self.d, self.sch, pin, nid)
        self.net_pins[nid] = {pin}
        return nid

    # ==========================================================================
    # Rules
    # ==========================================================================
    @rule()
    def add_resistor(self) -> None:
        self._new_instance()

    @precondition(lambda self: bool(self.free_pins))
    @rule()
    def connect_new_net(self) -> None:
        pin = self.free_pins.pop()
        self._fresh_net_with(pin)

    @precondition(lambda self: bool(self.free_pins) and bool(self.net_pins))
    @rule(data=st.data())
    def connect_existing_net(self, data) -> None:
        pin = self.free_pins.pop()
        nid = data.draw(st.sampled_from(sorted(self.net_pins)))
        connect(self.d, self.sch, pin, nid)
        self.net_pins[nid].add(pin)

    @precondition(lambda self: any(len(p) >= 2 for p in self.net_pins.values()))
    @rule(data=st.data())
    def disconnect_a_pin(self, data) -> None:
        nid = data.draw(st.sampled_from(sorted(n for n, p in self.net_pins.items() if len(p) >= 2)))
        pin = next(iter(self.net_pins[nid]))
        disconnect(self.d, self.sch, pin)
        self.net_pins[nid].remove(pin)
        self.free_pins.append(pin)

    @precondition(lambda self: len(self.net_pins) >= 2)
    @rule(data=st.data())
    def merge_two_nets(self, data) -> None:
        keep, drop = data.draw(
            st.lists(
                st.sampled_from(sorted(self.net_pins)),
                min_size=2,
                max_size=2,
                unique=True,
            )
        )
        merge_nets(self.d, self.sch, keep, drop)
        self.net_pins[keep] |= self.net_pins[drop]
        del self.net_pins[drop]

    @precondition(lambda self: any(len(p) >= 2 for p in self.net_pins.values()))
    @rule(data=st.data())
    def split_a_net(self, data) -> None:
        nid = data.draw(st.sampled_from(sorted(n for n, p in self.net_pins.items() if len(p) >= 2)))
        pins = list(self.net_pins[nid])  # any stable order; no need to sort
        k = data.draw(st.integers(min_value=1, max_value=len(pins) - 1))
        # pick a non-empty subset of pins to move to a new net
        to_move = set(pins[:k])
        new_nid = split_net(self.d, self.sch, nid, to_move)
        self.net_pins[nid] -= to_move
        self.net_pins[new_nid] = to_move

    # ==========================================================================
    # Invariants/Property Checks
    # ==========================================================================
    @invariant()
    def stays_consistent(self) -> None:
        check_invariants(self.d)
        assert self.sch.pin_to_net == recompute_index(self.sch)

    @invariant()
    def survuves_serialization_roundtrip(self) -> None:
        assert designs_equal(design_from_dict(design_to_dict(self.d)), self.d)

    @invariant()
    def bookkeeping_matches_truth(self) -> None:
        for nid, pins in self.net_pins.items():
            assert nid in self.sch.nets
            assert self.sch.nets[nid].pins == pins


TestNestList = NetlistMachine.TestCase

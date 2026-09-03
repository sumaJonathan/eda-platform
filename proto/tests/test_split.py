from types import SimpleNamespace

import pytest

from eda_proto.ids import NetId
from eda_proto.invariants import check_invariants
from eda_proto.model import Design, SchematicView
from eda_proto.ops import (
    add_instance,
    connect,
    create_net,
    ipin,
    merge_nets,
    pins_on_net,
    split_net,
)
from eda_proto.oracle import recompute_index
from tests.helpers import scaffold


def net_with_two_pins() -> tuple[Design, SchematicView, SimpleNamespace]:
    """One splittable net holding R1.a & R2.a"""
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    r2 = add_instance(d, sch, ids.res, "R2")
    n = create_net(d, sch, "shared")
    connect(d, sch, ipin(d, sch, r1, "a"), n)
    connect(d, sch, ipin(d, sch, r2, "a"), n)
    h = SimpleNamespace(res=ids.res, top=ids.top, R1=r1, R2=r2, n=n)
    return d, sch, h


# ==========================================================================
# Good path test
# ==========================================================================
def test_split_peels_subset_onto_new_net() -> None:
    d, sch, h = net_with_two_pins()
    r2a = ipin(d, sch, h.R2, "a")
    new_net = split_net(d, sch, h.n, {r2a})
    assert pins_on_net(sch, h.n) == {ipin(d, sch, h.R1, "a")}
    assert pins_on_net(sch, new_net) == {r2a}
    assert new_net != h.n
    check_invariants(d)
    assert sch.pin_to_net == recompute_index(sch)  # sanity check


# ==========================================================================
# Guard tests
# ==========================================================================
def test_split_rejects_empty_subset() -> None:
    d, sch, h = net_with_two_pins()
    with pytest.raises(ValueError):
        split_net(d, sch, h.n, set())
    check_invariants(d)


def test_split_rejects_moving_all_pins() -> None:
    d, sch, h = net_with_two_pins()
    all_pins = {ipin(d, sch, h.R1, "a"), ipin(d, sch, h.R2, "a")}
    with pytest.raises(ValueError):
        split_net(d, sch, h.n, all_pins)
    check_invariants(d)


def test_split_rejects_pin_not_on_net() -> None:
    d, sch, h = net_with_two_pins()
    other = create_net(d, sch, "other")
    r1b = ipin(d, sch, h.R1, "b")
    connect(d, sch, r1b, other)
    with pytest.raises(ValueError):
        split_net(d, sch, h.n, {r1b})
    check_invariants(d)


def test_split_rejects_unknown_net() -> None:
    d, sch, h = net_with_two_pins()
    with pytest.raises(ValueError):
        split_net(d, sch, NetId(99999), {ipin(d, sch, h.R1, "a")})


def test_split_rejects_unconnected_pin() -> None:
    d, sch, h = net_with_two_pins()
    lone = add_instance(d, sch, h.res, "LONE")
    with pytest.raises(ValueError):
        split_net(d, sch, h.n, {ipin(d, sch, lone, "a")})
    check_invariants(d)


# ==========================================================================
# Merge then split round trip test
# ==========================================================================
def test_merge_then_split_round_trips() -> None:
    d, sch, ids = scaffold()
    r1 = add_instance(d, sch, ids.res, "R1")
    r2 = add_instance(d, sch, ids.res, "R2")
    a = create_net(d, sch, "a")
    b = create_net(d, sch, "b")
    connect(d, sch, ipin(d, sch, r1, "a"), a)
    connect(d, sch, ipin(d, sch, r2, "a"), b)
    a_before = pins_on_net(sch, a)
    b_before = pins_on_net(sch, b)
    merge_nets(d, sch, a, b)  # fuse the nets to a, b is gone
    # split R2.a back to a new net
    new_net = split_net(d, sch, a, {ipin(d, sch, r2, "a")})
    # ensure a has what it started with, new net holds what b started with
    assert pins_on_net(sch, a) == a_before
    assert pins_on_net(sch, new_net) == b_before
    check_invariants(d)
    assert sch.pin_to_net == recompute_index(sch)  # sanity check

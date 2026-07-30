from eda_proto.invariants import check_invariants
from eda_proto.ops import add_instance
from eda_proto.queries import instances_on_net, neighbors
from tests.helpers import scaffold, wired_divider


def test_instances_on_net_out() -> None:
    _, sch, h = wired_divider()
    assert instances_on_net(sch, h.out) == {h.R1, h.R2}


def test_neighbors_of_r1() -> None:
    d, sch, h = wired_divider()
    # r1 has neighbors (V1,R2)
    assert neighbors(d, sch, h.R1) == {h.V1, h.R2}


def test_queries_are_read_only() -> None:
    d, sch, h = wired_divider()
    neighbors(d, sch, h.R1)
    instances_on_net(sch, h.out)
    check_invariants(d)  # nothing should have changed


def test_neighbors_of_isolated_instance() -> None:
    d, sch, ids = scaffold()
    lone = add_instance(d, sch, ids.res, "LONE")  # place unwired
    assert neighbors(d, sch, lone) == set()


def test_neighbors_of_isolated_instance_read_only() -> None:
    # the isolated case must ALSO not mutate
    d, sch, ids = scaffold()
    lone = add_instance(d, sch, ids.res, "LONE")
    neighbors(d, sch, lone)
    check_invariants(d)


def test_nets_on_instance_set_collapses_shared_net() -> None:
    # if you wire BOTH of a resistor's pins to one net, the set version
    # should report that net once only
    d, sch, ids = scaffold()
    from eda_proto.ops import connect, create_net, ipin
    from eda_proto.queries import nets_on_instance_set

    r = add_instance(d, sch, ids.res, "R")
    n = create_net(d, sch, "n")
    connect(d, sch, ipin(d, sch, r, "a"), n)
    connect(d, sch, ipin(d, sch, r, "b"), n)
    assert nets_on_instance_set(d, sch, r) == {n}  # one net, not two

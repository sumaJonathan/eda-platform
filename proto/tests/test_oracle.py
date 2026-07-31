from eda_proto.ids import NetId
from eda_proto.oracle import recompute_index
from tests.helpers import wired_divider


def test_index_matches_recompute() -> None:
    _, sch, _ = wired_divider()
    assert sch.pin_to_net == recompute_index(sch)


def test_recompute_detects_stale_index() -> None:
    _, sch, _ = wired_divider()
    # corrupt the maintained index: point R1.b at the wrong net,
    # WITHOUT touching net.pins (truth source)
    some_pin = next(iter(sch.pin_to_net))
    sch.pin_to_net[some_pin] = NetId(99999)
    assert sch.pin_to_net != recompute_index(sch)  # oracle should catch

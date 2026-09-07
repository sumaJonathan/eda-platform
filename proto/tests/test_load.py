import json
from pathlib import Path

import pytest

from eda_proto.model import Design, SchematicView
from eda_proto.ops import add_instance, connect, create_net, ipin
from eda_proto.oracle import recompute_index
from eda_proto.serialize import (
    design_from_dict,
    design_to_dict,
    designs_equal,
    load,
    save,
)
from tests.helpers import build_hierarchical_divider, scaffold, wired_divider


def _roundtrip(d: Design) -> Design:
    """dict round trip, no disk: the fidelity path."""
    return design_from_dict(design_to_dict(d))


def _dumps(d: Design) -> str:
    return json.dumps(design_to_dict(d), sort_keys=True, indent=2)


# ==========================================================================
# Fidelity: load(save(d)) equals d
# ==========================================================================
def test_roundtrip_divider_is_faithful() -> None:
    d, _, _ = wired_divider()
    assert designs_equal(_roundtrip(d), d)


def test_roundtrip_hierarchical_is_faithful() -> None:
    d, _ = build_hierarchical_divider()
    assert designs_equal(_roundtrip(d), d)


def test_roundtrip_empty_is_faithful() -> None:
    assert designs_equal(_roundtrip(Design()), Design())


def test_roundtrip_anonymous_net_is_faithful() -> None:
    d, sch, ids = scaffold()
    r = add_instance(d, sch, ids.res, "R1")
    n = create_net(d, sch)  # anonymous
    connect(d, sch, ipin(d, sch, r, "a"), n)
    assert designs_equal(_roundtrip(d), d)


def test_roundtrip_preserves_float_param() -> None:
    # params is dict[str, Any]; a float must survive the JSON round trip exactly
    d, sch, ids = scaffold()
    r = add_instance(d, sch, ids.res, "R1")
    n = create_net(d, sch, "n")
    connect(d, sch, ipin(d, sch, r, "a"), n)
    sch.instances[r].params["resistance"] = 1000.0
    assert designs_equal(_roundtrip(d), d)


# ==========================================================================
# Byte-stability: save(load(save(d))) == save(d)   [the Done-when]
# ==========================================================================
def test_byte_stable_through_load_divider() -> None:
    d, _, _ = wired_divider()
    once = _dumps(d)
    twice = _dumps(design_from_dict(json.loads(once)))
    assert once == twice


def test_byte_stable_through_load_hierarchical() -> None:
    d, _ = build_hierarchical_divider()
    once = _dumps(d)
    twice = _dumps(design_from_dict(json.loads(once)))
    assert once == twice


# ==========================================================================
# ID preservation + index rebuild
# ==========================================================================
def test_roundtrip_preserves_ids_and_counter() -> None:
    d, _, _ = wired_divider()
    back = _roundtrip(d)
    assert sorted(back.library) == sorted(d.library)
    assert back._next_id == d._next_id
    assert back.top == d.top


def test_loaded_index_is_rebuilt_and_correct() -> None:
    # pin_to_net isn't saved; after load it must exist and match the truth
    d, _, _ = wired_divider()
    back = _roundtrip(d)
    assert back.top is not None
    view = back.library[back.top].views["schematic"]
    assert isinstance(view, SchematicView)
    assert view.pin_to_net == recompute_index(view)
    assert len(view.pin_to_net) > 0


def test_pin_to_net_absent_from_serialized_form() -> None:
    d, _, _ = wired_divider()
    assert "pin_to_net" not in _dumps(d)


# ==========================================================================
# File round trip (save to disk, load from disk)
# ==========================================================================
def test_file_roundtrip_is_faithful(tmp_path) -> None:
    d, _, _ = wired_divider()
    path = tmp_path / "d.json"
    save(d, str(path))
    back = load(str(path))
    assert designs_equal(back, d)


def test_file_roundtrip_is_byte_stable(tmp_path) -> None:
    d, _ = build_hierarchical_divider()
    p1 = tmp_path / "one.json"
    p2 = tmp_path / "two.json"
    save(d, str(p1))
    save(load(str(p1)), str(p2))
    assert p1.read_text() == p2.read_text()


# ==========================================================================
# Must-refuse: impossible-but-parseable files (caught by check_invariants)
# ==========================================================================
def _good_divider_dict() -> dict:
    d, _, _ = wired_divider()
    return design_to_dict(d)


def test_load_refuses_net_referencing_deleted_instance() -> None:
    data = _good_divider_dict()
    div = next(c for c in data["library"] if c["name"] == "divider")
    _, sview = div["views"][0]
    sview["instances"] = sview["instances"][:-1]  # drop an instance, keep its pins
    with pytest.raises(AssertionError):
        design_from_dict(data)


def test_load_refuses_pin_in_two_nets() -> None:
    data = _good_divider_dict()
    div = next(c for c in data["library"] if c["name"] == "divider")
    _, sview = div["views"][0]
    stolen = sview["nets"][0]["pins"][0]
    sview["nets"][1]["pins"].append(stolen)  # same pin now in two nets
    with pytest.raises(AssertionError):
        design_from_dict(data)


def test_load_refuses_port_map_to_missing_net() -> None:
    d, _ = build_hierarchical_divider()
    data = design_to_dict(d)
    for cell in data["library"]:
        for _kind, view in cell["views"]:
            if view["port_map"]:
                view["port_map"][0][1] = 999999  # net that doesn't exist
    with pytest.raises(AssertionError):
        design_from_dict(data)


# ==========================================================================
# Must refuse malformed files
# ==========================================================================
def test_load_refuses_invalid_direction() -> None:
    data = _good_divider_dict()
    res = next(c for c in data["library"] if c["name"] == "resistor")
    res["pins"][0]["direction"] = "sideways"
    with pytest.raises(ValueError):
        design_from_dict(data)


def test_load_refuses_missing_key() -> None:
    data = _good_divider_dict()
    del data["next_id"]
    with pytest.raises(KeyError):
        design_from_dict(data)


def test_load_refuses_unknown_version() -> None:
    data = _good_divider_dict()
    data["version"] = 99
    with pytest.raises(ValueError):
        design_from_dict(data)


def test_load_refuses_duplicate_instance_id() -> None:
    import copy

    data = _good_divider_dict()
    div = next(c for c in data["library"] if c["name"] == "divider")
    _, sview = div["views"][0]
    sview["instances"].append(copy.deepcopy(sview["instances"][0]))
    with pytest.raises(ValueError):
        design_from_dict(data)


def test_load_refuses_duplicate_cell_id() -> None:
    import copy

    data = _good_divider_dict()
    data["library"].append(copy.deepcopy(data["library"][0]))
    with pytest.raises(ValueError):
        design_from_dict(data)


# ==========================================================================
# A clean file should still load
# ==========================================================================
def test_clean_dict_loads() -> None:
    data = _good_divider_dict()
    d = design_from_dict(data)
    assert d.top is not None


# ==========================================================================
# Testing hardcoded json file to load
# ==========================================================================
def test_handwritten_fixture_loads_and_validates() -> None:
    path = Path(__file__).parent / "fixtures" / "divider_v1.json"
    data = json.loads(path.read_text())
    d = design_from_dict(data)  # loads even with scrambled order
    assert d.top == 7
    # check round-trip is clean
    assert designs_equal(design_from_dict(json.loads(json.dumps(design_to_dict(d)))), d)

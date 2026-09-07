import json

from eda_proto.model import Design, View
from eda_proto.ops import add_instance, connect, create_net, ipin
from eda_proto.serialize import design_to_dict, save, view_to_dict
from tests.helpers import build_hierarchical_divider, scaffold, wired_divider


def _dumps(d: Design) -> str:
    """The same string-building path save() uses — for byte-stability checks."""
    return json.dumps(design_to_dict(d), sort_keys=True, indent=2)


# ==========================================================================
# design_to_dict — top-level fields
# ==========================================================================
def test_dict_has_version_and_counter() -> None:
    d, _, _ = wired_divider()
    dd = design_to_dict(d)
    assert dd["version"] == 1
    assert dd["next_id"] == d._next_id  # the counter must travel


def test_dict_top_matches() -> None:
    d, _, _ = wired_divider()
    assert design_to_dict(d)["top"] == d.top


def test_dict_empty_design() -> None:
    dd = design_to_dict(Design())
    assert dd["library"] == []
    assert dd["top"] is None
    assert dd["next_id"] == 0


# ==========================================================================
# Ordering (the guts of byte-stability)
# ==========================================================================
def test_cells_sorted_by_id() -> None:
    d, _, _ = wired_divider()
    ids = [c["id"] for c in design_to_dict(d)["library"]]
    assert ids == sorted(ids)


def test_pins_sorted_by_id() -> None:
    d, _, _ = wired_divider()
    res = next(c for c in design_to_dict(d)["library"] if c["name"] == "resistor")
    pids = [p["id"] for p in res["pins"]]
    assert pids == sorted(pids)


def test_net_pins_are_sorted_pairs() -> None:
    # net.pins is a set of InstancePin; each must serialize as a sorted
    # [instance, pin] pair list. This is the guard on the not-orderable
    # InstancePin sort-key hazard.
    d, _, _ = wired_divider()
    divider = next(c for c in design_to_dict(d)["library"] if c["name"] == "divider")
    _, sview = divider["views"][0]
    for net in sview["nets"]:
        assert all(len(pair) == 2 for pair in net["pins"])
        assert net["pins"] == sorted(net["pins"])


# ==========================================================================
# Field-level correctness
# ==========================================================================
def test_direction_serialized_as_string() -> None:
    d, _, _ = wired_divider()
    res = next(c for c in design_to_dict(d)["library"] if c["name"] == "resistor")
    assert all(isinstance(p["direction"], str) for p in res["pins"])
    assert {p["direction"] for p in res["pins"]} == {"passive"}


def test_anonymous_net_serializes_as_null() -> None:
    d, sch, ids = scaffold()
    r = add_instance(d, sch, ids.res, "R1")
    n = create_net(d, sch)  # anonymous — name is None
    connect(d, sch, ipin(d, sch, r, "a"), n)
    divider = next(c for c in design_to_dict(d)["library"] if c["name"] == "divider")
    _, sview = divider["views"][0]
    assert sview["nets"][0]["name"] is None


def test_derived_index_not_serialized() -> None:
    # pin_to_net is the derived index; it must NOT appear — it's rebuilt on load
    d, _, _ = wired_divider()
    assert "pin_to_net" not in _dumps(d)


def test_port_map_serialized_as_sorted_pairs() -> None:
    # the hierarchical design has a non-empty port_map
    d, _ = build_hierarchical_divider()
    dd = design_to_dict(d)
    found = False
    for cell in dd["library"]:
        for _kind, view in cell["views"]:
            if view["port_map"]:
                found = True
                keys = [pair[0] for pair in view["port_map"]]
                assert keys == sorted(keys)
                assert all(len(pair) == 2 for pair in view["port_map"])
    assert found, "expected at least one non-empty port_map"


# ==========================================================================
# view_to_dict — the View narrowing hazard
# ==========================================================================
def test_view_to_dict_rejects_bare_view() -> None:
    import pytest

    with pytest.raises(ValueError):
        view_to_dict(View())


# ==========================================================================
# Byte-stability — the Done-when's first half
# ==========================================================================
def test_dump_is_deterministic_repeated() -> None:
    d, _, _ = wired_divider()
    assert _dumps(d) == _dumps(d)


def test_two_independent_builds_produce_identical_bytes() -> None:
    # nothing may depend on dict-insertion or set-iteration order
    a, _, _ = wired_divider()
    b, _, _ = wired_divider()
    assert _dumps(a) == _dumps(b)


def test_hierarchical_dump_is_stable() -> None:
    d, _ = build_hierarchical_divider()
    assert _dumps(d) == _dumps(d)


# ==========================================================================
# save() — the file I/O wrapper
# ==========================================================================
def test_save_writes_valid_json_file(tmp_path) -> None:
    d, _, _ = wired_divider()
    path = tmp_path / "divider.json"
    save(d, str(path))
    raw = path.read_text()
    assert raw.endswith("\n")  # the trailing-newline choice
    assert json.loads(raw)["version"] == 1


def test_save_file_is_byte_stable(tmp_path) -> None:
    # save the same design twice -> identical file contents
    d, _, _ = wired_divider()
    p1 = tmp_path / "a.json"
    p2 = tmp_path / "b.json"
    save(d, str(p1))
    save(d, str(p2))
    assert p1.read_text() == p2.read_text()

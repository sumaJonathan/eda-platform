import pytest

from eda_proto.serialize import CURRENT_VERSION, design_from_dict, design_to_dict, designs_equal
from tests.helpers import build_hierarchical_divider, wired_divider


# =============
# HELPERS
# =============
def _downgrade_to_v0(data: dict) -> dict:
    """Turn a current (v1) dict into a fake historical v0 file:
    v0 stored the counter under 'counter', not 'next_id'."""
    data = dict(data)
    data["counter"] = data.pop("next_id")
    data["version"] = 0
    return data


# =============
# TESTS
# =============
def test_v0_file_migrates_and_loads() -> None:
    # THE test that proves the migration hook actually carries data.
    d, _, _ = wired_divider()
    v0 = _downgrade_to_v0(design_to_dict(d))
    loaded = design_from_dict(v0)
    assert designs_equal(loaded, d)


def test_v0_migration_preserves_counter() -> None:
    # the renamed field must land back as the counter
    d, _, _ = wired_divider()
    v0 = _downgrade_to_v0(design_to_dict(d))
    assert design_from_dict(v0)._next_id == d._next_id


def test_v0_hierarchical_migrates() -> None:
    d, _ = build_hierarchical_divider()
    v0 = _downgrade_to_v0(design_to_dict(d))
    assert designs_equal(design_from_dict(v0), d)


def test_current_version_still_loads() -> None:
    # a current-version file must pass straight through the seam untouched
    d, _, _ = wired_divider()
    assert designs_equal(design_from_dict(design_to_dict(d)), d)


def test_refuses_future_version() -> None:
    # a file newer than this build understands must refuse clearly, not guess
    d, _, _ = wired_divider()
    data = design_to_dict(d)
    data["version"] = CURRENT_VERSION + 1
    with pytest.raises(ValueError):
        design_from_dict(data)

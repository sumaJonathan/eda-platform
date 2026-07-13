from eda_proto import __version__, hello


def test_version() -> None:
    assert __version__ == "0.0.1"


def test_hello() -> None:
    assert hello() == "eda-proto ready"

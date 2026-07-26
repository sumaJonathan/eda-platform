from eda_proto import __version__
from eda_proto.ids import InstanceId, InstancePin, PinId


def test_version() -> None:
    assert __version__ == "0.0.1"


def test_instance_pin() -> None:
    instance_pin = InstancePin(instance=InstanceId(1), pin=PinId(2))
    assert instance_pin.instance == InstanceId(1)
    assert instance_pin.pin == PinId(2)

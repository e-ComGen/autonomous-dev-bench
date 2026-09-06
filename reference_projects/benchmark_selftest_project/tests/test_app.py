from selftest_app import Client
from selftest_app.worker import child_value


def test_provider_contract() -> None:
    assert Client("upper").send("Hello") == "HELLO"
    assert Client("lower").send("Hello") == "hello"


def test_known_subprocess() -> None:
    assert child_value() == "child-ok"

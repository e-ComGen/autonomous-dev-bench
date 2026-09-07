import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import pytest
from suites.coding.backends.relay import LocalRelay
from suites.coding.settings import Settings


def test_native_relay_binds_loopback_and_refuses_unknown_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-placeholder-not-a-real-key")
    relay = LocalRelay(tmp_path, tmp_path / "relay", Settings(), {"allowed": "stock"})
    try:
        assert relay.server.server_address[0] == "127.0.0.1"
        with pytest.raises(HTTPError) as error:
            urlopen(Request(relay.endpoint("wrong") + "/chat/completions", method="POST",
                            data=json.dumps({"model": "deepseek-v4-flash"}).encode()), timeout=5)
        assert error.value.code == 429
        evidence = relay.receipt.read_text()
        assert "test-placeholder" not in evidence
        assert json.loads(evidence)["stock"]["admitted"] == 0
    finally:
        relay.close()
    assert not relay.thread.is_alive()

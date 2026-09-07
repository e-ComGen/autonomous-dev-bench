from pathlib import Path
import hashlib
import json
import pytest

from tools.launch import verify_wheels
from tools.launcher_lock import launcher_lock


def test_missing_offline_wheels_is_not_success(tmp_path):
    assert verify_wheels(tmp_path) is False


def test_wheel_corruption_is_detected(tmp_path):
    wheel = tmp_path / "example.whl"
    wheel.write_bytes(b"original")
    (tmp_path / "SHA256SUMS.json").write_text(json.dumps({wheel.name: hashlib.sha256(b"original").hexdigest()}))
    assert verify_wheels(tmp_path)
    wheel.write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        verify_wheels(tmp_path)


def test_extra_wheel_is_rejected(tmp_path):
    (tmp_path / "SHA256SUMS.json").write_text('{"example.whl":"hash"}')
    (tmp_path / "example.whl").write_bytes(b"one")
    (tmp_path / "unexpected.whl").write_bytes(b"two")
    with pytest.raises(ValueError, match="match"):
        verify_wheels(tmp_path)


def test_launcher_lock_releases_for_next_run(tmp_path):
    path = tmp_path / "lock"
    with launcher_lock(path):
        assert path.is_file()
    with launcher_lock(path):
        assert path.is_file()

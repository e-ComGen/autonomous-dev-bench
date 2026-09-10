from pathlib import Path
import os
import tempfile
import pytest

from tools.launcher_env import clean_environment


def test_original_scratch_parent_survives_nested_launchers(tmp_path, monkeypatch):
    parent = tmp_path / "os-temp"
    parent.mkdir()
    monkeypatch.setenv("AUTOBENCH_TEST_TMPDIR", str(parent))
    first = clean_environment(tmp_path / "extracted archive")
    for key, value in first.items():
        monkeypatch.setenv(key, value)
    second = clean_environment(tmp_path / "extracted archive/nested run")
    assert second["AUTOBENCH_TEST_TMPDIR"] == str(parent.resolve())
    assert second["TMP"] != second["AUTOBENCH_TEST_TMPDIR"]


def test_scratch_cleanup_cannot_remove_parent_contents(tmp_path):
    sentinel = tmp_path / "do-not-delete"
    sentinel.write_text("retained")
    with tempfile.TemporaryDirectory(prefix="ab-", dir=tmp_path) as owned:
        path = Path(owned)
        (path / "fixture").write_text("temporary")
    assert not path.exists()
    assert sentinel.read_text() == "retained"


def test_missing_operator_scratch_parent_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOBENCH_TEST_TMPDIR", str(tmp_path / "absent"))
    with pytest.raises(ValueError, match="scratch parent"):
        clean_environment(tmp_path / "checkout")

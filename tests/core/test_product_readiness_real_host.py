from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.product_readiness_harbor import _write_wheel_manifest
from tools.product_readiness_linux_campaign import _assert_clean
from tools.qualify_phase3c3_real_adcp_dsh import _configure_adcp_import_paths


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_wsl_clean_check_ignores_only_crlf_normalization(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "autobench-test")
    _git(repo, "config", "user.email", "autobench@example.invalid")
    tracked = repo / "tracked.txt"
    tracked.write_bytes(b"same-content\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "fixture")

    tracked.write_bytes(b"same-content\r\n")
    _assert_clean(repo)

    tracked.write_bytes(b"changed-content\r\n")
    with pytest.raises(RuntimeError, match="tracked changes"):
        _assert_clean(repo)

    _git(repo, "checkout", "--", "tracked.txt")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="untracked files"):
        _assert_clean(repo)


def test_stock_wheel_manifest_recomputes_and_checks_pinned_digests(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    sdk = wheel_dir / "deepseek_harness_sdk-0.1.2rc1-py3-none-any.whl"
    runtime = wheel_dir / "deepseek_harness_runtime_bin-0.1.2rc1-py3-none-manylinux_2_28_x86_64.whl"
    sdk.write_bytes(b"sdk-wheel")
    runtime.write_bytes(b"runtime-wheel")

    lock = {
        "sdk": {
            "wheel": sdk.name,
            "sha256": hashlib.sha256(sdk.read_bytes()).hexdigest(),
        },
        "runtime": {
            "linux_x86_64_wheel": runtime.name,
            "linux_x86_64_sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
        },
    }
    lock_path = tmp_path / "DEEPSEEK_HARNESS.lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    output = tmp_path / "DSH_WHEELS.json"

    manifest = _write_wheel_manifest(lock_path, wheel_dir, output)

    assert manifest["scope"] == "PHASE2_DSH_WHEEL_CLOSURE"
    assert json.loads(output.read_text(encoding="utf-8")) == manifest
    assert {entry["filename"] for entry in manifest["wheels"]} == {sdk.name, runtime.name}

    runtime.write_bytes(b"tampered-runtime-wheel")
    with pytest.raises(RuntimeError, match="wheel pin mismatch"):
        _write_wheel_manifest(lock_path, wheel_dir, output)


def test_real_adcp_qualifier_adds_src_layout_for_shared_contracts(tmp_path: Path) -> None:
    adcp = tmp_path / "adcp"
    shared_src = adcp / "packages" / "shared_contracts" / "src"
    package = shared_src / "shared_contracts"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

    original = list(sys.path)
    try:
        _configure_adcp_import_paths(adcp)
        assert sys.path[0] == str(shared_src)
        assert sys.path[1] == str(adcp)
    finally:
        sys.path[:] = original

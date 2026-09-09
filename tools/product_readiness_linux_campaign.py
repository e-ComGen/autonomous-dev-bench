"""Authoritative fail-closed product readiness for WSL/Linux.

All repositories are prechecked by the Windows launcher. This campaign performs
no Git fetch for private sources: it verifies exact HEAD identities and then
executes the real Linux-only DeepSeek Harness/Harbor runtime stack.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

from tools.product_readiness import live_parity, test_adcp_real_binding, test_phase3d_lock
from tools.product_readiness_campaign import _local_paid_preflight
from tools.product_readiness_harbor import docker_engine, run_adcp_boundary_trial, run_stock_trial


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _run(command: list[str], *, cwd: Path, timeout: int = 1800) -> str:
    print("+", subprocess.list2cmdline(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.returncode:
        raise RuntimeError(
            f"command failed with exit {completed.returncode}: {subprocess.list2cmdline(command)}\n"
            + (completed.stdout or "")[-6000:]
        )
    return completed.stdout or ""


def _git_head(path: Path) -> str:
    return _run(["git", "-C", str(path), "rev-parse", "HEAD"], cwd=path, timeout=60).strip()


def _assert_clean(path: Path) -> None:
    # The accepted Windows host flow checks out pins with Git for Windows and
    # executes the Linux campaign over /mnt/c. WSL Git can otherwise report
    # every CRLF-normalized file as modified. Ignore CR-at-EOL only; actual
    # content changes and untracked files remain fail-closed.
    tracked = _run(
        ["git", "-C", str(path), "diff", "--name-only", "--ignore-cr-at-eol", "HEAD", "--"],
        cwd=path,
        timeout=180,
    ).strip()
    untracked = _run(
        ["git", "-C", str(path), "ls-files", "--others", "--exclude-standard"],
        cwd=path,
        timeout=180,
    ).strip()
    if tracked or untracked:
        details: list[str] = []
        if tracked:
            details.append("tracked changes:\n" + tracked)
        if untracked:
            details.append("untracked files:\n" + untracked)
        raise RuntimeError(f"pinned checkout is dirty: {path}\n" + "\n".join(details))


def _pin_check(name: str, path: Path, expected: str) -> str:
    if not (path / ".git").is_dir():
        raise RuntimeError(f"{name} checkout is missing: {path}")
    observed = _git_head(path)
    if observed != expected:
        raise RuntimeError(f"{name} HEAD mismatch: expected {expected}, got {observed}")
    _assert_clean(path)
    return observed


def _add(checks: list[dict[str, object]], name: str, status: str, detail: str) -> None:
    checks.append({"name": name, "status": status, "detail": detail})
    print(f"[{status}] {name}: {detail}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--adcp-root", type=Path, required=True)
    parser.add_argument("--dsh-root", type=Path, required=True)
    parser.add_argument("--harbor-root", type=Path, required=True)
    parser.add_argument("--tasks-root", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    workspace = args.workspace.resolve()
    adcp_root = args.adcp_root.resolve()
    dsh_root = args.dsh_root.resolve()
    harbor_root = args.harbor_root.resolve()
    tasks_root = args.tasks_root.resolve()
    artifacts = workspace / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, object]] = []
    blockers: list[str] = []

    adcp_lock = _read(root / "ADCP.lock.json")
    dsh_lock = _read(root / "DEEPSEEK_HARNESS.lock.json")
    harbor_lock = _read(root / "HARBOR.lock.json")
    plan = _read(root / "PHASE3D_EXPERIMENT_PLAN.json")
    expected = {
        "BENCH": _git_head(root),
        "ADCP": str(adcp_lock["commit"]),
        "DSH": str(dsh_lock["qualification_reference"]["commit"]),
        "HARBOR": str(harbor_lock["commit"]),
        "TASKS": str(plan["corpus"]["task_repo_commit"]),
    }
    roots = {
        "BENCH": root,
        "ADCP": adcp_root,
        "DSH": dsh_root,
        "HARBOR": harbor_root,
        "TASKS": tasks_root,
    }
    for name in ("BENCH", "ADCP", "DSH", "HARBOR", "TASKS"):
        try:
            observed = _pin_check(name, roots[name], expected[name])
            _add(checks, f"PIN {name}", "PASS", observed)
        except BaseException as error:
            _add(checks, f"PIN {name}", "FAIL", str(error))
            blockers.append(f"PIN_{name}: {error}")

    try:
        installed = importlib.metadata.version("deepseek-harness-sdk")
        required = str(dsh_lock["sdk"]["version"])
        if installed != required:
            raise RuntimeError(f"expected {required}, installed {installed}")
        runtime_version = importlib.metadata.version("deepseek-harness-runtime-bin")
        if runtime_version != required:
            raise RuntimeError(f"runtime expected {required}, installed {runtime_version}")
        _add(checks, "DEEPSEEK HARNESS RUNTIME", "PASS", f"sdk={installed}; runtime={runtime_version}")
    except BaseException as error:
        _add(checks, "DEEPSEEK HARNESS RUNTIME", "FAIL", str(error))
        blockers.append(f"DSH_RUNTIME: {error}")

    try:
        _run([sys.executable, "-m", "pytest"], cwd=root, timeout=1800)
        _run([sys.executable, "-m", "build"], cwd=root, timeout=600)
        _add(checks, "BENCHMARK CORE", "PASS", "full pytest + build")
    except BaseException as error:
        _add(checks, "BENCHMARK CORE", "FAIL", str(error))
        blockers.append(f"BENCHMARK_CORE: {error}")

    try:
        test_phase3d_lock(root, sys.executable, artifacts / "phase3d-lock-replay")
        _add(checks, "PHASE3D LOCK", "PASS", "exact 370-pair plan/schedule replay")
    except BaseException as error:
        _add(checks, "PHASE3D LOCK", "FAIL", str(error))
        blockers.append(f"PHASE3D_LOCK: {error}")

    try:
        test_adcp_real_binding(root, sys.executable, adcp_root, artifacts / "PHASE3C3_REAL_ADCP_DSH.json")
        _add(checks, "ADCP REAL RUNTIME", "PASS", "pinned assured runtime FAIL->repair->PASS")
        _add(checks, "ADCP DSH BINDING", "PASS", "shipping DSH subprocess + real HTTP/SSE transport")
    except BaseException as error:
        _add(checks, "ADCP REAL RUNTIME", "FAIL", str(error))
        _add(checks, "ADCP DSH BINDING", "FAIL", str(error))
        blockers.append(f"ADCP_REAL_RUNTIME: {error}")

    try:
        version = docker_engine()
        _add(checks, "DOCKER ENGINE", "PASS", version or "reachable")
    except BaseException as error:
        _add(checks, "DOCKER ENGINE", "FAIL", str(error))
        blockers.append(f"DOCKER_ENGINE: {error}")

    try:
        run_stock_trial(root, workspace, harbor_root)
        _add(checks, "STOCK REAL HARBOR", "PASS", "shipping DeepSeek Harness inside pinned Harbor/Docker")
    except BaseException as error:
        _add(checks, "STOCK REAL HARBOR", "FAIL", str(error))
        blockers.append(f"STOCK_REAL_HARBOR: {error}")

    try:
        run_adcp_boundary_trial(root, workspace, harbor_root)
        _add(checks, "ADCP HARBOR PROCESS", "PASS", "Harbor agent -> isolated process -> strict receipt")
    except BaseException as error:
        _add(checks, "ADCP HARBOR PROCESS", "FAIL", str(error))
        blockers.append(f"ADCP_HARBOR_PROCESS: {error}")

    try:
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/core/test_adcp_harbor_contract.py",
                "tests/coding/test_harbor_workspace.py",
                "tests/coding/test_harbor_cas_export.py",
            ],
            cwd=root,
            timeout=600,
        )
        _add(checks, "HARBOR CONTRACTS", "PASS", "receipt/workspace/CAS seams")
    except BaseException as error:
        _add(checks, "HARBOR CONTRACTS", "FAIL", str(error))
        blockers.append(f"HARBOR_CONTRACTS: {error}")

    try:
        detail = live_parity(root, sys.executable, artifacts)
        _add(checks, "DEEPSEEK LIVE PARITY", "PASS", detail)
    except BaseException as error:
        _add(checks, "DEEPSEEK LIVE PARITY", "BLOCKED", str(error))
        blockers.append(f"DEEPSEEK_LIVE_PARITY: {error}")

    try:
        ok, detail = _local_paid_preflight(root, workspace)
        if not ok:
            raise RuntimeError(detail)
        _add(checks, "LOCAL PAID PREFLIGHT", "PASS", detail)
    except BaseException as error:
        _add(checks, "LOCAL PAID PREFLIGHT", "BLOCKED", str(error))
        blockers.append(f"LOCAL_PAID_PREFLIGHT: {error}")

    product_ready = not blockers and all(item["status"] == "PASS" for item in checks)
    result = {
        "schema_version": 1,
        "scope": "AUTONOMOUS_DEV_PRODUCT_READINESS_WSL_FINAL",
        "product_ready": product_ready,
        "checks": checks,
        "blockers": blockers,
        "paid_paired_ab_started": False,
        "winner": "UNKNOWN",
        "platform": {
            "os_name": os.name,
            "python": sys.version,
        },
    }
    report = artifacts / "PRODUCT_READINESS_FINAL.json"
    _write(report, result)

    print("\n" + "=" * 88)
    print("FINAL PRODUCT READINESS")
    print("=" * 88)
    for item in checks:
        print(f"{str(item['name']):<30} {str(item['status']):<8} {item['detail']}")
    print("-" * 88)
    print("PRODUCT READY:", "YES" if product_ready else "NO")
    if blockers:
        print("BLOCKERS:")
        for blocker in blockers:
            print(" -", blocker)
    print("370-pair paid experiment started: NO")
    print("Winner: UNKNOWN")
    print("Report:", report)
    print("=" * 88)
    return 0 if product_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Authoritative local product-readiness campaign.

Runs the core fail-closed checks, then executes actual Stock Harness inside
Harbor/Docker, the actual Harbor->ADCP process boundary trial, and a final local
paid-admission preflight using only explicit local qualification evidence. It
never writes qualification state back to Git and never starts the 370-pair A/B.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from benchmark_core.paired_experiment import PaidAdmissionSnapshot
from tools.product_readiness_harbor import run_adcp_boundary_trial, run_stock_trial


REQUIRED_ADMISSION_FILES = (
    "PHASE3D_EXPERIMENT_PLAN.json",
    "DEEPSEEK_V4_ESTIMATOR.lock.json",
    "ADCP.lock.json",
    "DEEPSEEK_HARNESS.lock.json",
    "HARBOR.lock.json",
    "migration/swebench_v5_verified_parity.json",
)


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_core(root: Path, workspace: Path) -> dict[str, object]:
    command = [
        sys.executable,
        str(root / "tools" / "product_readiness.py"),
        "--root",
        str(root),
        "--workspace",
        str(workspace),
    ]
    print("+", subprocess.list2cmdline(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=str(root),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=3600,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    report = workspace / "artifacts" / "PRODUCT_READINESS.json"
    if not report.is_file():
        raise RuntimeError(
            f"core readiness did not produce {report}; exit={completed.returncode}\n"
            + (completed.stdout or "")[-6000:]
        )
    return _read(report)


def _local_paid_preflight(root: Path, workspace: Path) -> tuple[bool, str]:
    artifacts = workspace / "artifacts"
    adcp_evidence_path = artifacts / "PHASE3C3_REAL_ADCP_DSH.json"
    parity_path = artifacts / "deepseek-live-capture.json"
    parity_result_path = artifacts / "deepseek-live-parity.json"
    if not adcp_evidence_path.is_file():
        return False, "real ADCP qualification evidence is missing"
    adcp_evidence = _read(adcp_evidence_path)
    if adcp_evidence.get("status") != "PASS" or adcp_evidence.get("production_ready") is not True:
        return False, "real ADCP qualification evidence is not PASS"
    if not parity_path.is_file():
        return False, "DeepSeek live capture is missing"

    # product_readiness.py runs the verifier and stores its stdout only in the
    # console. Re-run the no-network verifier into a durable JSON artifact.
    cache = artifacts / "deepseek-estimator-cache"
    command = [
        sys.executable,
        str(root / "tools" / "verify_deepseek_v4_usage_parity.py"),
        str(parity_path),
        "--cache-dir",
        str(cache),
    ]
    completed = subprocess.run(
        command,
        cwd=str(root),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    if completed.returncode:
        return False, "DeepSeek live parity verifier is not PASS: " + (completed.stdout or "")[-2000:]
    try:
        parity = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        return False, f"DeepSeek parity verifier returned invalid JSON: {error}"
    _write(parity_result_path, parity)
    if parity.get("status") != "PASS" or parity.get("exact_match") is not True:
        return False, "DeepSeek live prompt-token parity is not exact"

    overlay = workspace / "paid-admission-overlay"
    if overlay.exists():
        shutil.rmtree(overlay)
    for relative in REQUIRED_ADMISSION_FILES:
        source = root / relative
        target = overlay / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    adcp_lock = _read(overlay / "ADCP.lock.json")
    adcp_lock["private_pinned_runtime_qualification_status"] = "PASS"
    adcp_lock["paid_ready"] = True
    adcp_lock["production_blocker"] = None
    adcp_lock["local_product_readiness_evidence"] = {
        "scope": adcp_evidence.get("scope"),
        "binding_id": adcp_evidence.get("binding_id"),
        "runtime_loaded": adcp_evidence.get("runtime_loaded"),
        "real_deepseek_harness_subprocess": adcp_evidence.get("real_deepseek_harness_subprocess"),
        "paid_model_called": adcp_evidence.get("paid_model_called"),
    }
    _write(overlay / "ADCP.lock.json", adcp_lock)

    estimator = _read(overlay / "DEEPSEEK_V4_ESTIMATOR.lock.json")
    estimator["live_provider_prompt_usage_parity"] = True
    estimator["paid_ready"] = True
    estimator["production_blocker"] = None
    estimator["local_product_readiness_evidence"] = {
        "scope": parity.get("scope"),
        "provider_prompt_tokens": parity.get("provider_prompt_tokens"),
        "estimated_input_tokens": parity.get("estimated_input_tokens"),
        "exact_match": parity.get("exact_match"),
    }
    _write(overlay / "DEEPSEEK_V4_ESTIMATOR.lock.json", estimator)

    admission = PaidAdmissionSnapshot.from_repository(overlay)
    if not admission.paid_ready:
        return False, "paid admission remains blocked: " + ", ".join(admission.blockers)
    if admission.blockers:
        return False, "paid admission reports blockers despite paid_ready"
    return True, "all locked design + DeepSeek + ADCP admission gates PASS in local evidence overlay"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    workspace = (args.workspace or (root.parent / "autobench-product-readiness-work")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    core = _run_core(root, workspace)
    checks = list(core.get("checks", []))
    blockers = list(core.get("blockers", []))
    harbor_root = workspace / "harbor"

    try:
        run_stock_trial(root, workspace, harbor_root)
        checks.append({"name": "STOCK REAL HARBOR TRIAL", "status": "PASS", "detail": "shipping DSH inside pinned Harbor/Docker"})
    except BaseException as error:
        checks.append({"name": "STOCK REAL HARBOR TRIAL", "status": "FAIL", "detail": str(error)})
        blockers.append(f"STOCK_REAL_HARBOR: {error}")

    try:
        run_adcp_boundary_trial(root, workspace, harbor_root)
        checks.append({"name": "ADCP REAL HARBOR PROCESS", "status": "PASS", "detail": "Harbor agent -> isolated runner -> strict receipt contract"})
    except BaseException as error:
        checks.append({"name": "ADCP REAL HARBOR PROCESS", "status": "FAIL", "detail": str(error)})
        blockers.append(f"ADCP_REAL_HARBOR_PROCESS: {error}")

    preflight_ok, preflight_detail = _local_paid_preflight(root, workspace)
    checks.append({
        "name": "LOCAL PAID PREFLIGHT",
        "status": "PASS" if preflight_ok else "BLOCKED",
        "detail": preflight_detail,
    })
    if not preflight_ok:
        blockers.append("LOCAL_PAID_PREFLIGHT: " + preflight_detail)

    product_ready = not blockers and all(item.get("status") == "PASS" for item in checks)
    result = {
        "schema_version": 1,
        "scope": "AUTONOMOUS_DEV_PRODUCT_READINESS_FINAL",
        "product_ready": product_ready,
        "checks": checks,
        "blockers": blockers,
        "paid_paired_ab_started": False,
        "winner": "UNKNOWN",
    }
    report = workspace / "artifacts" / "PRODUCT_READINESS_FINAL.json"
    _write(report, result)

    print("\n" + "=" * 80)
    print("FINAL PRODUCT READINESS")
    print("=" * 80)
    for item in checks:
        print(f"{str(item.get('name')):<30} {str(item.get('status')):<8} {item.get('detail')}")
    print("-" * 80)
    print("PRODUCT READY:", "YES" if product_ready else "NO")
    if blockers:
        print("BLOCKERS:")
        for blocker in blockers:
            print(" -", blocker)
    print("370-pair paid experiment started: NO")
    print("Winner: UNKNOWN")
    print("Final report:", report)
    print("=" * 80)
    return 0 if product_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())

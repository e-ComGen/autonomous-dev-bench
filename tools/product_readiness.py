"""Fail-closed one-click product readiness campaign.

This tool is intended to be launched by product_readiness.bat from a clean pinned
checkout. It never starts the 370-pair paid experiment. If an exact prior live
capture exists it is reused; otherwise an explicit DeepSeek credential permits
only the preregistered 8-token live prompt-usage capture. Readiness validates
provider usage against the pinned conservative reservation envelope.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ADCP_REPOSITORY = "https://github.com/e-ComGen/autonomous-dev-control-plane.git"
DSH_REPOSITORY = "https://github.com/deepseek-ai/deepseek-harness.git"
HARBOR_REPOSITORY = "https://github.com/harbor-framework/harbor.git"
TASKS_REPOSITORY = "https://github.com/SWE-bench/swe-bench-tasks.git"


@dataclass(slots=True)
class Check:
    name: str
    status: str
    detail: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    print("+", subprocess.list2cmdline(command), flush=True)
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def require_ok(result: subprocess.CompletedProcess[str], label: str) -> str:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.returncode:
        tail = (result.stdout or "")[-6000:]
        raise RuntimeError(f"{label} failed with exit {result.returncode}:\n{tail}")
    return result.stdout or ""


def git_head(path: Path) -> str:
    result = run(["git", "-C", str(path), "rev-parse", "HEAD"], timeout=60)
    require_ok(result, "git identity")
    return result.stdout.strip()


def sync_repo(url: str, path: Path, commit: str) -> None:
    if not (path / ".git").is_dir():
        if path.exists():
            shutil.rmtree(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        require_ok(run(["git", "clone", "--filter=blob:none", "--no-checkout", url, str(path)], timeout=600), f"clone {url}")
    require_ok(run(["git", "-C", str(path), "remote", "set-url", "origin", url], timeout=60), "set remote")
    fetched = run(["git", "-C", str(path), "fetch", "--depth=1", "origin", commit], timeout=600)
    if fetched.returncode:
        fetched = run(["git", "-C", str(path), "fetch", "origin", commit], timeout=600)
    require_ok(fetched, f"fetch {commit}")
    require_ok(run(["git", "-C", str(path), "checkout", "--detach", "--force", commit], timeout=120), "checkout pin")
    if git_head(path) != commit:
        raise RuntimeError(f"repository pin mismatch for {path}")


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def test_phase3d_lock(root: Path, python: str, output: Path) -> None:
    if output.exists():
        shutil.rmtree(output)
    require_ok(
        run(
            [
                python,
                "tools/phase3d_prepare_design_decision.py",
                "PHASE3D_DESIGN_SCENARIOS.json",
                "PHASE3D_DESIGN_DECISION.json",
                "--plan",
                "PHASE3D_EXPERIMENT_PLAN.prelock.json",
                "--output-dir",
                str(output),
            ],
            cwd=root,
            timeout=600,
        ),
        "Phase 3D lock replay",
    )
    plan = read_json(output / "PHASE3D_EXPERIMENT_PLAN.locked.candidate.json")
    committed_plan = read_json(root / "PHASE3D_EXPERIMENT_PLAN.json")
    evidence = read_json(output / "PHASE3D6_DESIGN_DECISION_EVIDENCE.json")
    schedule = read_json(output / "PHASE3D_PAIR_SCHEDULE.candidate.json")
    lock = read_json(root / "PHASE3D_PAIR_SCHEDULE.lock.json")
    if plan != committed_plan:
        raise RuntimeError("Phase 3D locked plan replay differs from committed plan")
    if plan.get("status") != "LOCKED" or plan.get("paid_paired_ab") != "NOT_RUN" or plan.get("winner") != "UNKNOWN":
        raise RuntimeError("Phase 3D scientific state drift")
    entries = schedule.get("entries")
    if not isinstance(entries, list) or len(entries) != lock.get("pair_count") or len(entries) != 370:
        raise RuntimeError("Phase 3D schedule count drift")
    identity = evidence.get("schedule_identity")
    identity_value = identity.get("value") if isinstance(identity, dict) else None
    if identity_value != lock.get("schedule_identity"):
        raise RuntimeError("Phase 3D schedule digest drift")


def test_adcp_real_binding(root: Path, python: str, adcp_root: Path, output: Path) -> None:
    if output.exists():
        output.unlink()
    require_ok(
        run(
            [python, "tools/qualify_phase3c3_real_adcp_dsh.py", "--adcp-root", str(adcp_root), "--output", str(output)],
            cwd=root,
            timeout=900,
        ),
        "real pinned ADCP + DeepSeek Harness qualification",
    )
    evidence = read_json(output)
    required = {
        "status": "PASS",
        "runtime_loaded": True,
        "real_deepseek_harness_subprocess": True,
        "production_binding_qualified": True,
        "production_ready": True,
        "candidate_ready": True,
        "task_completed": False,
        "paid_model_called": False,
        "workspace_scope_preserved": True,
        "baseline_preserved": True,
    }
    for name, expected in required.items():
        if evidence.get(name) != expected:
            raise RuntimeError(f"ADCP evidence {name} mismatch: {evidence.get(name)!r}")


def wsl_docker_check() -> str:
    if os.name != "nt":
        return require_ok(run(["docker", "info"], timeout=120), "Docker Engine")
    if shutil.which("wsl.exe") is None:
        raise RuntimeError("WSL is not installed")
    return require_ok(
        run(
            ["wsl.exe", "-e", "sh", "-lc", "docker info >/dev/null 2>&1 && docker version --format '{{.Server.Version}}'"],
            timeout=120,
        ),
        "WSL2 Docker Engine",
    ).strip()


def live_parity(root: Path, python: str, artifact_root: Path) -> str:
    cache = artifact_root / "deepseek-estimator-cache"
    cache.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    bootstrap_code = (
        "from benchmark_core.deepseek_v4_estimator import DeepSeekV4RequestEstimator; "
        f"DeepSeekV4RequestEstimator.from_huggingface_revision(cache_dir={str(cache)!r}, allow_network=True); "
        "print('PINNED_ESTIMATOR_ASSETS_READY')"
    )
    require_ok(run([python, "-c", bootstrap_code], cwd=root, env=env, timeout=900), "DeepSeek V4 estimator bootstrap")
    capture = artifact_root / "deepseek-live-capture.json"
    require_ok(
        run(
            [python, "tools/capture_deepseek_v4_live_usage.py", "--output", str(capture), "--text", "Reply with OK.", "--max-tokens", "8"],
            cwd=root,
            env=env,
            timeout=180,
        ),
        "minimal official DeepSeek live capture or exact capture reuse",
    )
    coverage_text = require_ok(
        run([python, "tools/verify_deepseek_v4_usage_parity.py", str(capture), "--cache-dir", str(cache)], cwd=root, env=env, timeout=180),
        "DeepSeek provider prompt-usage coverage",
    )
    value = json.loads(coverage_text)
    required_true = (
        "coverage_pass",
        "request_policy_matches",
        "provider_above_lower_reference",
        "reference_envelope_non_underestimate",
        "effort_prefix_structure_ok",
        "provider_usage_source_of_truth",
    )
    if value.get("status") != "PASS" or any(value.get(name) is not True for name in required_true):
        raise RuntimeError("DeepSeek live provider usage is not safely covered by the pinned reservation model")
    return (
        f"provider_prompt_tokens={value['provider_prompt_tokens']}; "
        f"lower_reference={value['no_effort_prefix_reference_input_tokens']}; "
        f"reservation={value['reference_envelope_input_tokens']}; "
        f"headroom={value['reservation_headroom_tokens']}; coverage=true"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--skip-full-tests", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    workspace = (args.workspace or (root.parent / "autobench-product-readiness-work")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    artifacts = workspace / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    checks: list[Check] = []
    blockers: list[str] = []

    adcp_lock = read_json(root / "ADCP.lock.json")
    dsh_lock = read_json(root / "DEEPSEEK_HARNESS.lock.json")
    harbor_lock = read_json(root / "HARBOR.lock.json")
    task_manifest = read_json(root / "migration/swebench_v5_verified_parity.json")
    plan = read_json(root / "PHASE3D_EXPERIMENT_PLAN.json")
    task_pin = task_manifest.get("task_repo_commit") or task_manifest.get("source_commit")
    if not isinstance(task_pin, str) or not task_pin:
        task_pin = plan["corpus"]["task_repo_commit"]
    pins = {
        "adcp": str(adcp_lock["commit"]),
        "dsh": str(dsh_lock["qualification_reference"]["commit"]),
        "harbor": str(harbor_lock["commit"]),
        "tasks": str(task_pin),
    }
    repos = {
        "adcp": (ADCP_REPOSITORY, workspace / "autonomous-dev-control-plane"),
        "dsh": (DSH_REPOSITORY, workspace / "deepseek-harness"),
        "harbor": (HARBOR_REPOSITORY, workspace / "harbor"),
        "tasks": (TASKS_REPOSITORY, workspace / "swe-bench-tasks"),
    }
    for name, (url, path) in repos.items():
        try:
            sync_repo(url, path, pins[name])
            checks.append(Check(f"PIN {name.upper()}", "PASS", pins[name]))
        except BaseException as error:
            checks.append(Check(f"PIN {name.upper()}", "FAIL", str(error)))
            blockers.append(f"{name.upper()}_PIN: {error}")

    try:
        observed = importlib.metadata.version("deepseek-harness-sdk")
        expected = str(dsh_lock["sdk"]["version"])
        if observed != expected:
            raise RuntimeError(f"expected {expected}, installed {observed}")
        checks.append(Check("DEEPSEEK HARNESS SDK", "PASS", observed))
    except BaseException as error:
        checks.append(Check("DEEPSEEK HARNESS SDK", "FAIL", str(error)))
        blockers.append(f"DSH_SDK: {error}")

    if not args.skip_full_tests:
        try:
            require_ok(run([python, "-m", "pytest"], cwd=root, timeout=1800), "benchmark pytest")
            require_ok(run([python, "-m", "build"], cwd=root, timeout=600), "benchmark build")
            checks.append(Check("BENCHMARK CORE", "PASS", "pytest + build"))
        except BaseException as error:
            checks.append(Check("BENCHMARK CORE", "FAIL", str(error)))
            blockers.append(f"BENCHMARK_CORE: {error}")

    try:
        test_phase3d_lock(root, python, artifacts / "phase3d-lock-replay")
        checks.append(Check("PHASE3D LOCK", "PASS", "370 pairs exact replay"))
    except BaseException as error:
        checks.append(Check("PHASE3D LOCK", "FAIL", str(error)))
        blockers.append(f"PHASE3D_LOCK: {error}")

    adcp_path = repos["adcp"][1]
    if any(check.name == "PIN ADCP" and check.passed for check in checks):
        try:
            test_adcp_real_binding(root, python, adcp_path, artifacts / "PHASE3C3_REAL_ADCP_DSH.json")
            checks.append(Check("ADCP REAL RUNTIME", "PASS", "assured runtime FAIL->repair->PASS"))
            checks.append(Check("ADCP DSH BINDING", "PASS", "real SDK subprocess + HTTP/SSE"))
        except BaseException as error:
            checks.append(Check("ADCP REAL RUNTIME", "FAIL", str(error)))
            checks.append(Check("ADCP DSH BINDING", "FAIL", str(error)))
            blockers.append(f"ADCP_REAL_BINDING: {error}")
    else:
        checks.append(Check("ADCP REAL RUNTIME", "BLOCKED", "pinned ADCP checkout unavailable"))
        checks.append(Check("ADCP DSH BINDING", "BLOCKED", "pinned ADCP checkout unavailable"))
        blockers.append("ADCP_REAL_BINDING: pinned ADCP checkout unavailable")

    try:
        docker_version = wsl_docker_check()
        checks.append(Check("HARBOR / DOCKER", "PASS", docker_version or "Docker Engine reachable"))
    except BaseException as error:
        checks.append(Check("HARBOR / DOCKER", "FAIL", str(error)))
        blockers.append(f"HARBOR_DOCKER: {error}")

    try:
        require_ok(
            run(
                [python, "-m", "pytest", "tests/core/test_adcp_harbor_contract.py", "tests/coding/test_harbor_workspace.py", "tests/coding/test_harbor_cas_export.py"],
                cwd=root,
                timeout=600,
            ),
            "Harbor/Stock/ADCP process contracts",
        )
        checks.append(Check("STOCK HARNESS CONTRACT", "PASS", "workspace + receipt + CAS tests"))
        checks.append(Check("ADCP HARBOR BOUNDARY", "PASS", "strict public process contract"))
    except BaseException as error:
        checks.append(Check("STOCK HARNESS CONTRACT", "FAIL", str(error)))
        checks.append(Check("ADCP HARBOR BOUNDARY", "FAIL", str(error)))
        blockers.append(f"HARBOR_CONTRACTS: {error}")

    try:
        detail = live_parity(root, python, artifacts)
        checks.append(Check("DEEPSEEK LIVE PARITY", "PASS", detail))
    except BaseException as error:
        checks.append(Check("DEEPSEEK LIVE PARITY", "BLOCKED", str(error)))
        blockers.append(f"DEEPSEEK_LIVE_PARITY: {error}")

    product_ready = bool(checks) and not blockers and all(check.passed for check in checks)
    summary = {
        "schema_version": 1,
        "scope": "AUTONOMOUS_DEV_BENCH_PRODUCT_READINESS_LOCAL",
        "product_ready": product_ready,
        "checks": [asdict(check) for check in checks],
        "blockers": blockers,
        "paid_paired_ab_started": False,
        "winner": "UNKNOWN",
    }
    report_path = artifacts / "PRODUCT_READINESS.json"
    report_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("\n" + "=" * 72)
    print("PRODUCT READINESS")
    print("=" * 72)
    for check in checks:
        print(f"{check.name:<28} {check.status:<8} {check.detail}")
    print("-" * 72)
    print("PRODUCT READY:", "YES" if product_ready else "NO")
    if blockers:
        print("BLOCKERS:")
        for blocker in blockers:
            print(" -", blocker)
    print("Paid 370-pair A/B started: NO")
    print("Winner: UNKNOWN")
    print("Report:", report_path)
    print("=" * 72)
    return 0 if product_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())

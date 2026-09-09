"""Local Harbor/Docker product-readiness trials.

On Windows the accepted host profile is WSL2 + Linux Docker Engine, so these
helpers execute the pinned Harbor controller inside WSL. They run the shipping
Stock DeepSeek Harness trial and the real Harbor->ADCP process boundary trial.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess


def _run(command: list[str], *, timeout: int = 1800) -> str:
    print("+", subprocess.list2cmdline(command), flush=True)
    completed = subprocess.run(
        command,
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


def _linux_path(path: Path) -> str:
    path = path.resolve()
    if os.name != "nt":
        return str(path)
    if shutil.which("wsl.exe") is None:
        raise RuntimeError("WSL is not installed")
    return _run(["wsl.exe", "-e", "wslpath", "-a", str(path)], timeout=60).strip()


def docker_engine() -> str:
    if os.name == "nt":
        if shutil.which("wsl.exe") is None:
            raise RuntimeError("WSL is not installed")
        return _run(
            ["wsl.exe", "-e", "sh", "-lc", "docker info >/dev/null 2>&1 && docker version --format '{{.Server.Version}}'"],
            timeout=120,
        ).strip()
    return _run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=120).strip()


def _bash(script: str, *, timeout: int = 1800) -> str:
    if os.name == "nt":
        return _run(["wsl.exe", "-e", "bash", "-lc", script], timeout=timeout)
    return _run(["bash", "-lc", script], timeout=timeout)


def _prepare_task(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _common_script_prefix(root: Path, harbor_root: Path) -> tuple[str, str, str]:
    bench = _linux_path(root)
    harbor = _linux_path(harbor_root)
    venv = "$HOME/.cache/autobench-product-readiness-harbor-venv"
    prefix = f"""
set -euo pipefail
BENCH={shlex.quote(bench)}
HARBOR_SRC={shlex.quote(harbor)}
VENV={venv}
if [ ! -x \"$VENV/bin/python\" ]; then
  python3 -m venv \"$VENV\"
fi
\"$VENV/bin/python\" -m pip install --disable-pip-version-check -U pip setuptools wheel >/dev/null
\"$VENV/bin/python\" -m pip install --disable-pip-version-check -e \"$HARBOR_SRC\" -e \"$BENCH\" >/dev/null
HARBOR=\"$VENV/bin/harbor\"
PY=\"$VENV/bin/python\"
"""
    return prefix, bench, harbor


def run_stock_trial(root: Path, workspace: Path, harbor_root: Path) -> str:
    task = workspace / "harbor-stock-task"
    trials = workspace / "harbor-stock-trials"
    _prepare_task(root / "tests" / "harbor_phase2_stock", task)
    shutil.copyfile(root / "suites" / "coding" / "harbor" / "stock_runtime_runner.py", task / "environment" / "runner.py")

    prefix, bench, _ = _common_script_prefix(root, harbor_root)
    task_linux = _linux_path(task)
    trials_linux = _linux_path(trials)
    script = prefix + f"""
TASK={shlex.quote(task_linux)}
TRIALS={shlex.quote(trials_linux)}
rm -rf \"$TASK/environment/wheels\" \"$TRIALS\"
mkdir -p \"$TASK/environment/wheels\"
DSH_VERSION=\"$($PY -c 'import json; print(json.load(open(\"'\"$BENCH\"'/DEEPSEEK_HARNESS.lock.json\"))[\"sdk\"][\"version\"])')\"
\"$PY\" -m pip download --disable-pip-version-check --only-binary=:all: --dest \"$TASK/environment/wheels\" \"deepseek-harness-sdk==$DSH_VERSION\" >/dev/null
cd \"$BENCH\"
AUTOBENCH_DEEPSEEK_BASE_URL=http://fake-model:8000/v1 \\
AUTOBENCH_DEEPSEEK_API_KEY=PRODUCT_READINESS_FAKE_KEY_DO_NOT_PERSIST \\
AUTOBENCH_DEEPSEEK_USAGE_URL=http://fake-model:8000/stats \\
AUTOBENCH_FAKE_MODEL=1 \\
\"$HARBOR\" trials start -p \"$TASK\" \\
  --agent suites.coding.harbor.stock_agent:StockDeepSeekAgent \\
  --trial-name product-readiness-stock-deepseek \\
  --trials-dir \"$TRIALS\"
\"$PY\" tools/verify_harbor_phase2_stock.py --trials-dir \"$TRIALS\"
echo STOCK_HARBOR_REAL_TRIAL=PASS
"""
    return _bash(script, timeout=1800)


def run_adcp_boundary_trial(root: Path, workspace: Path, harbor_root: Path) -> str:
    task = workspace / "harbor-adcp-boundary-task"
    trials = workspace / "harbor-adcp-boundary-trials"
    _prepare_task(root / "tests" / "harbor_phase3c_adcp_fake", task)
    prefix, _, _ = _common_script_prefix(root, harbor_root)
    task_linux = _linux_path(task)
    trials_linux = _linux_path(trials)
    script = prefix + f"""
TASK={shlex.quote(task_linux)}
TRIALS={shlex.quote(trials_linux)}
rm -rf \"$TRIALS\"
cd \"$BENCH\"
AUTOBENCH_ADCP_FAKE_RUNTIME=1 \\
AUTOBENCH_MODEL_PROXY_BASE_URL=http://127.0.0.1:9/v1 \\
AUTOBENCH_MODEL_PROXY_TOKEN=product-readiness-proxy-token \\
\"$HARBOR\" trials start -p \"$TASK\" \\
  --agent suites.coding.harbor.adcp_agent:ADCPHarborAgent \\
  --trial-name product-readiness-adcp-boundary \\
  --trials-dir \"$TRIALS\"
\"$PY\" tools/verify_phase3c_adcp_fake_harbor.py --trials-dir \"$TRIALS\"
echo ADCP_HARBOR_PROCESS_BOUNDARY=PASS
"""
    return _bash(script, timeout=1800)

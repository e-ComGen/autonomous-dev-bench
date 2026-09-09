"""Run Phase 3C2 against an operator-supplied exact private ADCP checkout.

The private checkout is never copied into the public repository or output
artifact. Its exact committed bytes are exported with ``git archive`` into a
temporary Harbor build context that is deleted after the trial. Only sanitized
JSON evidence survives.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ADCP_COMMIT = "285702063815280398b95ba8696566259c8b5b34"
EXPECTED_ADCP_REPOSITORY = "e-ComGen/autonomous-dev-control-plane"
TEMPLATE = ROOT / "tests" / "harbor_phase3c_adcp_private_template"
RUNNER = ROOT / "tools" / "run_pinned_adcp_harbor.py"
VALIDATOR = ROOT / "tools" / "verify_phase3c_private_adcp_harbor.py"
HARBOR_LOCK = ROOT / "HARBOR.lock.json"


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        list(args),
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=600,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(args)}\n"
            f"stdout:\n{completed.stdout[-8000:]}\n"
            f"stderr:\n{completed.stderr[-8000:]}"
        )
    return completed.stdout.strip()


def verify_private_checkout(path: Path) -> tuple[str, str]:
    path = path.resolve()
    if not (path / ".git").exists():
        # Detached worktrees often have a .git file rather than directory.
        if not (path / ".git").is_file():
            raise ValueError("private checkout is not a Git worktree")
    commit = run("git", "rev-parse", "HEAD", cwd=path)
    if commit != EXPECTED_ADCP_COMMIT:
        raise ValueError(
            f"private ADCP checkout must be exact {EXPECTED_ADCP_COMMIT}, observed {commit}"
        )
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=path)
    if len(tree) != 40:
        raise ValueError("private ADCP checkout has invalid Git tree identity")
    return commit, tree


def verify_benchmark_checkout() -> str:
    commit = run("git", "rev-parse", "HEAD", cwd=ROOT)
    if len(commit) != 40:
        raise ValueError("benchmark checkout has invalid Git commit identity")
    return commit


def verify_harbor_install() -> dict[str, str]:
    lock = json.loads(HARBOR_LOCK.read_text(encoding="utf-8"))
    observed = importlib.metadata.version("harbor")
    if observed != lock["version"]:
        raise ValueError(f"Harbor version mismatch: expected {lock['version']}, observed {observed}")
    source_commit = os.environ.get("AUTOBENCH_HARBOR_SOURCE_COMMIT")
    if source_commit != lock["commit"]:
        raise ValueError(
            "3C2 requires Harbor installed from the exact HARBOR.lock source commit; "
            f"expected {lock['commit']}, observed marker {source_commit!r}"
        )
    return {"version": observed, "commit": source_commit}


def archive_private_checkout(private_checkout: Path, destination: Path) -> None:
    tar_path = destination.parent / "adcp-source.tar"
    with tar_path.open("wb") as handle:
        completed = subprocess.run(
            ["git", "archive", "--format=tar", "HEAD"],
            cwd=private_checkout,
            stdout=handle,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
    if completed.returncode:
        raise RuntimeError(
            "git archive of private ADCP checkout failed: "
            + completed.stderr.decode("utf-8", "replace")[-4000:]
        )
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(tar_path, "r") as archive:
        archive.extractall(destination, filter="data")
    tar_path.unlink()


def build_private_task(private_checkout: Path, task_dir: Path, commit: str, tree: str) -> None:
    shutil.copytree(TEMPLATE, task_dir)
    environment = task_dir / "environment"
    archive_private_checkout(private_checkout, environment / "adcp-source")
    shutil.copy2(RUNNER, environment / "run_adcp_private.py")
    (environment / "adcp_source_identity.json").write_text(
        json.dumps(
            {"repository": EXPECTED_ADCP_REPOSITORY, "commit": commit, "tree": tree},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def ensure_sanitized_output(output_dir: Path) -> None:
    allowed = {"PHASE3C_ADCP_PRIVATE_HARBOR.json"}
    names = {path.name for path in output_dir.iterdir()} if output_dir.exists() else set()
    if not names <= allowed:
        raise RuntimeError(f"3C2 output directory contains non-sanitized files: {sorted(names - allowed)}")


def qualify(private_checkout: Path, output_dir: Path) -> Path:
    private_checkout = private_checkout.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ensure_sanitized_output(output_dir)

    source_commit, source_tree = verify_private_checkout(private_checkout)
    benchmark_commit = verify_benchmark_checkout()
    harbor = verify_harbor_install()

    with tempfile.TemporaryDirectory(prefix="autobench-phase3c2-") as temporary:
        temp_root = Path(temporary)
        task_dir = temp_root / "task"
        trials_dir = temp_root / "trials"
        build_private_task(private_checkout, task_dir, source_commit, source_tree)

        env = dict(os.environ)
        env.pop("AUTOBENCH_ADCP_FAKE_RUNTIME", None)
        env.pop("AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY", None)
        env.update(
            AUTOBENCH_MODEL_PROXY_BASE_URL="http://127.0.0.1:9/v1",
            AUTOBENCH_MODEL_PROXY_TOKEN="phase3c2-no-model-proxy-token",
        )

        run(
            "harbor",
            "trials",
            "start",
            "-p",
            str(task_dir),
            "--agent",
            "suites.coding.harbor.adcp_agent:ADCPHarborAgent",
            "--trial-name",
            "phase3c-adcp-private",
            "--trials-dir",
            str(trials_dir),
            cwd=ROOT,
            env=env,
        )

        evidence_path = output_dir / "PHASE3C_ADCP_PRIVATE_HARBOR.json"
        run(
            sys.executable,
            str(VALIDATOR),
            "--trials-dir",
            str(trials_dir),
            "--source-commit",
            source_commit,
            "--source-tree",
            source_tree,
            "--benchmark-commit",
            benchmark_commit,
            "--harbor-lock",
            str(HARBOR_LOCK),
            "--output",
            str(evidence_path),
            cwd=ROOT,
        )

        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["qualification_host"] = {
            "harbor_version": harbor["version"],
            "harbor_commit": harbor["commit"],
            "private_source_context_deleted_after_trial": True,
        }
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    ensure_sanitized_output(output_dir)
    return output_dir / "PHASE3C_ADCP_PRIVATE_HARBOR.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-checkout", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = qualify(args.private_checkout, args.output_dir)
    print(f"PHASE3C2_PINNED_PRIVATE_ADCP_PASS: {evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

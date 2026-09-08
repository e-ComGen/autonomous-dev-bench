"""Run a real Harbor Trial, cancel it during agent.run(), and verify Docker cleanup."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import subprocess

from harbor.models.environment_type import EnvironmentType
from harbor.models.trial.config import AgentConfig, EnvironmentConfig, TaskConfig, TrialConfig, VerifierConfig
from harbor.trial.trial import Trial

from suites.coding.harbor.probe_agent import HarborCancellationProbeAgent


def running_containers() -> set[str]:
    output = subprocess.run(
        ("docker", "ps", "-q"),
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    return {line.strip() for line in output.splitlines() if line.strip()}


async def qualify(task_path: Path, trials_dir: Path) -> dict[str, object]:
    before = running_containers()
    config = TrialConfig(
        task=TaskConfig(path=task_path),
        trial_name="phase2-cancellation",
        trials_dir=trials_dir,
        agent=AgentConfig(
            import_path="suites.coding.harbor.probe_agent:HarborCancellationProbeAgent",
            override_timeout_sec=120.0,
        ),
        environment=EnvironmentConfig(type=EnvironmentType.DOCKER, delete=True),
        verifier=VerifierConfig(disable=True),
    )
    trial = await Trial.create(config)
    if not isinstance(trial.agent, HarborCancellationProbeAgent):
        raise ValueError("Harbor did not instantiate the cancellation probe agent")

    run_task = asyncio.create_task(trial.run())
    await asyncio.wait_for(trial.agent.running.wait(), timeout=120.0)
    during = running_containers()
    created = during - before
    if not created:
        run_task.cancel()
        raise ValueError("no Harbor Docker container was running during agent.run()")

    run_task.cancel()
    try:
        await run_task
    except asyncio.CancelledError:
        pass
    else:
        raise ValueError("Harbor Trial did not propagate cancellation")

    await asyncio.sleep(0.25)
    after = running_containers()
    leaked = after - before
    if leaked:
        raise ValueError(f"Harbor cancellation leaked running Docker containers: {sorted(leaked)}")
    result_path = trial.paths.result_path
    if not result_path.is_file():
        raise ValueError("cancelled Harbor Trial did not persist result.json")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    exception = result.get("exception_info")
    if not isinstance(exception, dict) or exception.get("exception_type") != "CancelledError":
        raise ValueError(f"cancelled Harbor Trial recorded wrong exception: {exception!r}")
    return {
        "trial_id": str(trial.id),
        "trial_name": trial.config.trial_name,
        "created_container_count": len(created),
        "leaked_container_count": 0,
        "exception_type": exception["exception_type"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, default=Path("tests/harbor_phase2_resources"))
    parser.add_argument("--trials-dir", type=Path, default=Path("artifacts/harbor-phase2/cancellation"))
    parser.add_argument("--harbor-lock", type=Path, default=Path("HARBOR.lock.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/harbor-phase2/PHASE2_HARBOR_CANCELLATION.json"))
    args = parser.parse_args()

    args.trials_dir.mkdir(parents=True, exist_ok=True)
    evidence = asyncio.run(qualify(args.task.resolve(), args.trials_dir.resolve()))
    evidence.update(
        scope="PHASE2_HARBOR_CANCELLATION_NO_MODEL",
        status="PASS",
        model_called=False,
        harbor=json.loads(args.harbor_lock.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Harbor Phase 2 cancellation: PASS; evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the preregistered Phase 3D paired campaign through the durable driver.

Dry run is the default and spends nothing: the fake-model task environment is
used for both arms. A paid run requires ``--authorized`` and is still refused by
the campaign before either arm starts while the admission locks are not
paid-ready, so no arm can be invoked speculatively.

Every pair is committed durably, so an interrupted campaign resumes with the
same command (optionally bounded with ``--max-new-pairs``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_core.paired_experiment import PaidAdmissionSnapshot
from benchmark_core.paired_analysis import PairedExperimentSchedule
from benchmark_core.phase3d_campaign import (
    CampaignRecoveryRequired,
    DurablePhase3DCampaign,
    PaidCampaignAuthorizationRequired,
    Phase3DCampaignError,
    materialize_pair_plan,
)

from suites.coding.phase3d_execution import (
    ADCP_FAKE_ENV,
    STOCK_FAKE_ENV,
    ADCPSemanticsV2ArmExecutor,
    BothArmsCampaignExecutor,
    CampaignArmGrader,
    LocalOfficialEvaluator,
    StockDeepSeekArmExecutor,
    WslHarborLauncher,
)


def _pairs(values: list[str], flag: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        key, _, raw = value.partition("=")
        if not key or not raw:
            raise SystemExit(f"{flag} expects KEY=VALUE, got {value!r}")
        mapping[key] = raw
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--harbor-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--task-dir",
        action="append",
        default=[],
        metavar="TASK_ID=PATH",
        help="Harbor task directory for one cohort task; repeat per task",
    )
    parser.add_argument("--environment-image-digest", required=True)
    parser.add_argument("--expected-benchmark-commit", required=True)
    parser.add_argument("--max-new-pairs", type=int, default=None)
    parser.add_argument(
        "--authorized",
        action="store_true",
        help="explicitly authorize the campaign; without it no arm is ever invoked",
    )
    parser.add_argument("--stock-env", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--adcp-env", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--swebench", default="swebench")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--swebench-task-repo", type=Path, default=None)
    args = parser.parse_args()

    root = args.root.resolve()
    admission = PaidAdmissionSnapshot.from_repository(root)
    schedule = PairedExperimentSchedule.from_design(admission.experiment_design)
    task_dirs = {key: Path(value).expanduser().resolve() for key, value in _pairs(args.task_dir, "--task-dir").items()}

    stock_env = _pairs(args.stock_env, "--stock-env")
    adcp_env = _pairs(args.adcp_env, "--adcp-env")
    if not args.authorized:
        stock_env.setdefault(STOCK_FAKE_ENV, "1")
        adcp_env.setdefault(ADCP_FAKE_ENV, "1")

    launcher = WslHarborLauncher(bench_root=root, harbor_root=args.harbor_root)
    executor = BothArmsCampaignExecutor(
        StockDeepSeekArmExecutor(task_dirs=task_dirs, launcher=launcher, controller_env=stock_env),
        ADCPSemanticsV2ArmExecutor(task_dirs=task_dirs, launcher=launcher, controller_env=adcp_env),
    )
    grader = CampaignArmGrader(
        LocalOfficialEvaluator(
            working_directory=args.workspace / "grading",
            executable=args.swebench,
            workers=args.workers,
            task_repo=args.swebench_task_repo,
        )
    )
    campaign = DurablePhase3DCampaign(
        repository_root=root,
        workspace=args.workspace,
        expected_benchmark_commit=args.expected_benchmark_commit,
        admission=admission,
        schedule=schedule,
        plan_factory=lambda entry: materialize_pair_plan(
            admission, entry, environment_image_digest=args.environment_image_digest
        ),
        executor=executor,
        grader=grader,
    )
    try:
        progress = campaign.run(
            paid_authorized=args.authorized, max_new_pairs=args.max_new_pairs
        )
    except (
        PaidCampaignAuthorizationRequired,
        CampaignRecoveryRequired,
        Phase3DCampaignError,
    ) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, indent=2, sort_keys=True))
        return 2
    print(json.dumps({"status": "PASS", **progress.to_public_dict()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

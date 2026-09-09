from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_core.paired_experiment import PaidAdmissionSnapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read Phase 3 design/evidence locks and report whether paid paired execution is admitted."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--require-paid-ready",
        action="store_true",
        help="return exit code 2 while any paid admission gate is blocked",
    )
    args = parser.parse_args()

    snapshot = PaidAdmissionSnapshot.from_repository(args.root)
    design = snapshot.experiment_design
    result = {
        "scope": "PHASE3D_PAIRED_PAID_ADMISSION_PREFLIGHT",
        "status": "PAID_READY" if snapshot.paid_ready else "BLOCKED",
        "paid_ready": snapshot.paid_ready,
        "expected_model": snapshot.expected_model,
        "expected_provider": snapshot.expected_provider,
        "experiment_design_status": design.status,
        "experiment_design_paid_ready": design.design_paid_ready,
        "experiment_design_blockers": list(design.design_blockers),
        "blockers": list(snapshot.blockers),
        "evidence": {
            "experiment_plan": str(design.plan_digest),
            "cohort_source": str(design.cohort_source_digest),
            "harbor_lock": str(design.harbor_lock_digest),
            "deepseek_estimator_lock": str(snapshot.estimator_lock_digest),
            "adcp_lock": str(snapshot.adcp_lock_digest),
            "stock_harness_lock": str(snapshot.stock_harness_lock_digest),
        },
        "model_called": False,
        "paid_model_called": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.require_paid_ready and not snapshot.paid_ready:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

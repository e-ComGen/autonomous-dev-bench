from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_core.experiment_preregistration import ExperimentDesignSnapshot
from benchmark_core.paired_analysis import (
    ExclusionReason,
    IncompletePairedSchedule,
    PairOutcomeAttempt,
    PairedExperimentSchedule,
    analyze_final_paired_binary,
    audit_paired_ledger,
)


def _read_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"cannot read paired ledger: {path}") from error
    if not isinstance(value, dict):
        raise SystemExit("paired ledger must be a JSON object")
    return value


def _digest_or_none(value: object, name: str):
    if value is None:
        return None
    if not isinstance(value, str):
        raise SystemExit(f"{name} must be a sha256 string or null")
    return value


def _parse_attempt(raw: object) -> PairOutcomeAttempt:
    if not isinstance(raw, dict):
        raise SystemExit("every paired ledger attempt must be an object")
    required = {
        "pair_id",
        "task_id",
        "repeat_index",
        "seed",
        "attempt_index",
        "stock_manifest_identity",
        "adcp_manifest_identity",
        "stock_resolved",
        "adcp_resolved",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise SystemExit("paired ledger attempt missing: " + ",".join(missing))
    exclusion_raw = raw.get("exclusion_reason")
    exclusion = None if exclusion_raw is None else ExclusionReason(exclusion_raw)
    return PairOutcomeAttempt(
        pair_id=raw["pair_id"],
        task_id=raw["task_id"],
        repeat_index=raw["repeat_index"],
        seed=raw["seed"],
        attempt_index=raw["attempt_index"],
        stock_manifest_identity=raw["stock_manifest_identity"],
        adcp_manifest_identity=raw["adcp_manifest_identity"],
        stock_resolved=raw.get("stock_resolved"),
        adcp_resolved=raw.get("adcp_resolved"),
        stock_grader_evidence=_digest_or_none(raw.get("stock_grader_evidence"), "stock_grader_evidence"),
        adcp_grader_evidence=_digest_or_none(raw.get("adcp_grader_evidence"), "adcp_grader_evidence"),
        exclusion_reason=exclusion,
        exclusion_evidence=_digest_or_none(raw.get("exclusion_evidence"), "exclusion_evidence"),
    )


def _audit_payload(audit) -> dict[str, object]:
    return {
        "scope": "PHASE3D3_PAIRED_LEDGER_AUDIT",
        "mode": "AUDIT_ONLY",
        "complete": audit.complete,
        "expected_pairs": audit.expected_pairs,
        "completed_pairs": audit.completed_pairs,
        "excluded_attempts": audit.excluded_attempts,
        "missing_pair_ids": list(audit.missing_pair_ids),
        "schedule_identity": str(audit.schedule_identity),
        "treatment_effect_exposed": False,
        "p_value_exposed": False,
        "winner_exposed": False,
    }


def _final_payload(report) -> dict[str, object]:
    return {
        "scope": "PHASE3D3_FINAL_PAIRED_BINARY_ANALYSIS",
        "mode": "FINAL_COMPLETE_SCHEDULE",
        "schedule_identity": str(report.schedule_identity),
        "pair_count": report.pair_count,
        "stock_resolved_count": report.stock_resolved_count,
        "adcp_resolved_count": report.adcp_resolved_count,
        "both_resolved_count": report.both_resolved_count,
        "neither_resolved_count": report.neither_resolved_count,
        "stock_only_count": report.stock_only_count,
        "adcp_only_count": report.adcp_only_count,
        "discordant_pair_count": report.discordant_pair_count,
        "stock_resolution_rate": report.stock_resolution_rate,
        "adcp_resolution_rate": report.adcp_resolution_rate,
        "paired_effect_adcp_minus_stock": report.paired_effect_adcp_minus_stock,
        "exact_mcnemar_two_sided_p": report.exact_mcnemar_two_sided_p,
        "alpha": report.alpha,
        "statistically_significant": report.statistically_significant,
        "winner": report.winner.value,
        "excluded_attempt_count": report.excluded_attempt_count,
        "pair_outcomes": [item.to_dict() for item in report.pair_outcomes],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit or finalize the preregistered Stock-vs-ADCP paired outcome ledger."
    )
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--final",
        action="store_true",
        help="compute the preregistered treatment effect/test; fails while any pair is incomplete",
    )
    args = parser.parse_args()

    design = ExperimentDesignSnapshot.from_repository(args.root)
    schedule = PairedExperimentSchedule.from_design(design)
    raw = _read_object(args.ledger)
    if set(raw) != {"schema_version", "design_identity", "attempts"}:
        raise SystemExit("paired ledger fields must be exactly schema_version, design_identity, attempts")
    if raw.get("schema_version") != 1:
        raise SystemExit("unsupported paired ledger schema_version")
    if raw.get("design_identity") != str(design.plan_digest):
        raise SystemExit("paired ledger is bound to a different experiment design")
    attempts_raw = raw.get("attempts")
    if not isinstance(attempts_raw, list):
        raise SystemExit("paired ledger attempts must be a list")
    attempts = tuple(_parse_attempt(item) for item in attempts_raw)

    if not args.final:
        print(json.dumps(_audit_payload(audit_paired_ledger(schedule, attempts)), indent=2, sort_keys=True))
        return 0

    try:
        report = analyze_final_paired_binary(schedule, attempts)
    except IncompletePairedSchedule as error:
        audit = audit_paired_ledger(schedule, attempts)
        payload = _audit_payload(audit)
        payload["mode"] = "FINAL_BLOCKED_INCOMPLETE_SCHEDULE"
        payload["error"] = str(error)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    print(json.dumps(_final_payload(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

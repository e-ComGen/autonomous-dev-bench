"""Deterministic quality qualification, independent of OMP execution and cost."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

REQUIREMENTS = {
    "required_existing_suite": "EXISTING_SUITE",
    "required_targeted_oracle": "NARROW_ORACLE",
    "required_differential_checks": "DIFFERENTIAL_CHECK",
    "required_metamorphic_checks": "METAMORPHIC_CHECK",
    "required_cross_component_checks": "CROSS_COMPONENT_CHECK",
}
STATUSES = {"PASS", "FAIL", "ERROR", "NOT_RUN"}
RESOURCE_FIELDS = (
    "input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens",
    "provider_total_tokens", "model_turns", "tool_calls", "read_calls", "unique_files_read",
    "packet_bytes", "source_bytes", "source_item_count", "zoning_time", "planning_time",
    "preprocessing_wall_time", "model_wall_time", "total_wall_time", "patch_size", "changed_files",
    "retries", "provider_reported_cost", "total_cost", "quota_usage",
)


def plan_digest(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def validate_plan(plan: dict, *, predeclared: bool = False) -> dict:
    if plan.get("schema_version") != 1 or not isinstance(plan.get("benchmark_id"), str) or not plan["benchmark_id"]:
        raise ValueError("Evaluation plan needs schema_version=1 and benchmark_id")
    if plan.get("phase") not in ("PREDECLARED", "POST_HOC_ANALYSIS"):
        raise ValueError("Evaluation phase must be explicit")
    if predeclared and plan["phase"] != "PREDECLARED":
        raise ValueError("Post-hoc requirements cannot authorize a primary run")
    for key in REQUIREMENTS:
        if type(plan.get(key)) is not bool:
            raise ValueError(f"Missing explicit requirement: {key}")
    evaluators = plan.get("evaluators")
    if not isinstance(evaluators, list):
        raise ValueError("Plan needs declared evaluators")
    seen = set()
    for evaluator in evaluators:
        name = evaluator.get("id")
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError("Evaluator IDs must be nonempty and unique")
        seen.add(name)
        if evaluator.get("category") not in REQUIREMENTS.values():
            raise ValueError("Unknown evaluator category")
        if evaluator.get("runner") not in ("pytest", "frozen_oracle", "differential", "external_evidence"):
            raise ValueError("Unknown deterministic evaluator runner")
        runner = evaluator["runner"]
        if runner == "pytest" and (not isinstance(evaluator.get("args"), list) or not evaluator["args"]
                                    or not all(isinstance(arg, str) for arg in evaluator["args"])):
            raise ValueError("Suite evaluator requires explicit arguments")
        stems = ("oracle",) if runner == "frozen_oracle" else ("cases", "reference", "probe") if runner == "differential" else ()
        for stem in stems:
            if not isinstance(evaluator.get(stem + "_path"), str) or not evaluator[stem + "_path"]:
                raise ValueError(f"Evaluator requires {stem}_path")
            digest = evaluator.get(stem + "_sha256")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError(f"Evaluator requires a SHA256 for {stem}")
    for key, category in REQUIREMENTS.items():
        if plan[key] and not any(e["category"] == category for e in evaluators):
            raise ValueError(f"Required category has no evaluator: {category}")
    # A narrow-only legacy result is recordable, but never qualified equivalence.
    if predeclared and not any(plan[key] for key in (
            "required_differential_checks", "required_metamorphic_checks", "required_cross_component_checks")):
        raise ValueError("Qualified future runs need a predeclared behavioral evaluator")
    return deepcopy(plan)


def aggregate_status(statuses: list[str], required: bool) -> str:
    if not statuses:
        return "NOT_RUN" if required else "NOT_REQUIRED"
    if "FAIL" in statuses:
        return "FAIL"
    if "ERROR" in statuses:
        return "ERROR"
    if "NOT_RUN" in statuses:
        return "NOT_RUN"
    return "PASS"


def qualify_arm(plan: dict, evidence: dict, resources: dict) -> dict:
    """Missing/mismatched evidence cannot silently qualify a semantic success."""
    validate_plan(plan)
    digest = plan_digest(plan)
    if evidence.get("plan_digest") != digest:
        raise ValueError("Evidence is not bound to this evaluation plan")
    observations = evidence.get("evaluators", {})
    declared = {e["id"] for e in plan["evaluators"]}
    if set(observations) - declared:
        raise ValueError("Undeclared checks belong in POST_HOC_ANALYSIS")
    checks = {}
    required_statuses = []
    for key, category in REQUIREMENTS.items():
        statuses = []
        for evaluator in plan["evaluators"]:
            if evaluator["category"] != category:
                continue
            row = observations.get(evaluator["id"], {"status": "NOT_RUN"})
            status = row.get("status")
            if status not in STATUSES:
                raise ValueError("Invalid evaluator status")
            if category == "DIFFERENTIAL_CHECK" and status in ("PASS", "FAIL"):
                total, differ = row.get("cases_total"), row.get("cases_differ")
                if (type(total) is not int or type(differ) is not int or total <= 0
                        or not 0 <= differ <= total or (status == "PASS") != (differ == 0)):
                    raise ValueError("Differential status must agree with nonempty case counts")
            statuses.append(status)
        checks[category] = aggregate_status(statuses, plan[key])
        if plan[key]:
            required_statuses.append(checks[category])
    scope_qualified = any(plan[key] for key in (
        "required_differential_checks", "required_metamorphic_checks", "required_cross_component_checks"))
    patch_valid = evidence.get("patch_valid")
    if patch_valid is False or "FAIL" in required_statuses:
        semantic = "NO"
    elif patch_valid is True and scope_qualified and required_statuses and all(s == "PASS" for s in required_statuses):
        semantic = "YES"
    else:
        semantic = "INCONCLUSIVE"
    differential = [observations[e["id"]] for e in plan["evaluators"]
                    if e["category"] == "DIFFERENTIAL_CHECK" and e["id"] in observations]
    measured = bool(differential) and all(row.get("status") in ("PASS", "FAIL") for row in differential)
    total = sum(row["cases_total"] for row in differential) if measured else None
    differ = sum(row["cases_differ"] for row in differential) if measured else None
    restores = "YES" if measured and differ == 0 else "NO" if measured else "INCONCLUSIVE"
    if patch_valid is False:
        repair = "INVALID_PATCH"
    elif semantic == "YES":
        repair = "ROOT_CAUSE_REPAIR" if evidence.get("production_matches_clean") is True else "SEMANTICALLY_EQUIVALENT_ALTERNATIVE"
    elif semantic == "NO" and checks["NARROW_ORACLE"] == "PASS" and restores == "NO":
        repair = "BEHAVIORAL_WORKAROUND"
    elif semantic == "NO" and restores == "NO":
        repair = "REGRESSION"
    else:
        repair = "INCONCLUSIVE"
    raw = {name: deepcopy(resources.get(name)) for name in RESOURCE_FIELDS}
    # Never derive monetary marginal cost from the provider's token-plan zero.
    raw["total_cost"] = deepcopy(resources.get("total_cost"))
    return {
        "MODEL_EXECUTED": resources.get("model_executed"), "PATCH_PRODUCED": resources.get("patch_produced"),
        **checks, "SEMANTIC_SUCCESS": semantic, "REPAIR_CLASS": repair,
        "RESTORES_CLEAN_BASE_BEHAVIOR": restores,
        "BEHAVIORAL_EQUIVALENCE_CASES_TOTAL": total, "BEHAVIORAL_EQUIVALENCE_CASES_DIFFER": differ,
        "EVALUATION_PLAN_DIGEST": digest, "EVALUATION_PHASE": plan["phase"],
        "EVALUATION_EVIDENCE": deepcopy(evidence), "RESOURCES": raw,
        "COST_PER_SEMANTIC_SUCCESS": {
            "status": "SUCCESS" if semantic == "YES" else "UNSUCCESSFUL" if semantic == "NO" else "UNRESOLVED",
            "observed_resource_cost": deepcopy(raw) if semantic == "YES" else None,
        },
    }


def compare_quality(a: dict, b: dict) -> str:
    if (not a.get("EVALUATION_PLAN_DIGEST") or a.get("EVALUATION_PLAN_DIGEST") != b.get("EVALUATION_PLAN_DIGEST")
            or a.get("EVALUATION_PHASE") != b.get("EVALUATION_PHASE")):
        return "INCONCLUSIVE"
    if a.get("EVALUATION_PHASE") != "PREDECLARED" and a.get("SEMANTIC_SUCCESS") == b.get("SEMANTIC_SUCCESS") == "YES":
        return "INCONCLUSIVE"  # Never label post-hoc agreement as predeclared equivalence.
    return {("YES", "YES"): "EQUIVALENT_ON_PREDECLARED_EVALUATION",
            ("NO", "YES"): "B_BETTER", ("YES", "NO"): "A_BETTER", ("NO", "NO"): "BOTH_FAIL"}.get(
                (a.get("SEMANTIC_SUCCESS"), b.get("SEMANTIC_SUCCESS")), "INCONCLUSIVE")


def resource_comparison(a: dict, b: dict) -> dict:
    ar, br = a.get("RESOURCES", a), b.get("RESOURCES", b)
    fields = ("input_tokens", "cached_input_tokens", "output_tokens", "provider_total_tokens", "model_wall_time", "total_wall_time")
    deltas = {key: br[key] - ar[key] if isinstance(ar.get(key), (int, float)) and isinstance(br.get(key), (int, float))
              else None for key in fields}
    def saving(av, bv):
        return 1 - bv / av if isinstance(av, (int, float)) and av > 0 and isinstance(bv, (int, float)) else None
    def exposure(row):
        values = [row.get("input_tokens"), row.get("cached_input_tokens")]
        return sum(values) if all(isinstance(v, (int, float)) for v in values) else None
    equal = (compare_quality(a, b) == "EQUIVALENT_ON_PREDECLARED_EVALUATION"
             and a.get("EVALUATION_PHASE") == "PREDECLARED")
    descriptive = saving(ar.get("provider_total_tokens"), br.get("provider_total_tokens"))
    return {"A": deepcopy(ar), "B": deepcopy(br), "B_MINUS_A": deltas,
            "TOKEN_SAVING_B_VS_A": descriptive, "TOKEN_SAVING_SCOPE": "DESCRIPTIVE_RESOURCES_ONLY",
            "UNCACHED_INPUT_SAVING": saving(ar.get("input_tokens"), br.get("input_tokens")),
            "TOTAL_INPUT_EXPOSURE_SAVING": saving(exposure(ar), exposure(br)),
            "EQUAL_QUALITY_COST_COMPARISON": "AVAILABLE" if equal else "NOT_AVAILABLE",
            "EQUAL_QUALITY_TOKEN_SAVING": descriptive if equal else None,
            "MONETARY_COST_COMPARISON": "UNKNOWN" if ar.get("total_cost") is None or br.get("total_cost") is None else "OBSERVED",
            "COST_PER_SEMANTIC_SUCCESS": {"A": a.get("COST_PER_SEMANTIC_SUCCESS"), "B": b.get("COST_PER_SEMANTIC_SUCCESS")}}


def build_report(plan: dict, a: dict, b: dict) -> dict:
    validate_plan(plan, predeclared=True)
    if any(row.get("EVALUATION_PLAN_DIGEST") != plan_digest(plan) for row in (a, b)):
        raise ValueError("Primary arms must share the predeclared plan")
    return {"PRIMARY_RESULT": {"evaluation_plan": deepcopy(plan), "A": deepcopy(a), "B": deepcopy(b)},
            "POST_HOC_ANALYSIS": [], "QUALITY_COMPARISON": compare_quality(a, b),
            "QUALITY_COMPARISON_BASIS": "PREDECLARED", "RESOURCE_COMPARISON": resource_comparison(a, b)}


def attach_post_hoc(primary: dict, plan: dict, a: dict, b: dict) -> dict:
    validate_plan(plan)
    if plan["phase"] != "POST_HOC_ANALYSIS" or any(row.get("EVALUATION_PLAN_DIGEST") != plan_digest(plan) for row in (a, b)):
        raise ValueError("Post-hoc evidence needs a matching explicitly post-hoc plan")
    result = deepcopy(primary)
    result.setdefault("POST_HOC_ANALYSIS", []).append({"label": "POST_HOC_ANALYSIS", "evaluation_plan": deepcopy(plan),
        "A": deepcopy(a), "B": deepcopy(b), "QUALITY_COMPARISON": compare_quality(a, b)})
    result["QUALITY_COMPARISON"] = compare_quality(a, b)
    result["QUALITY_COMPARISON_BASIS"] = "POST_HOC_ANALYSIS"
    result["RESOURCE_COMPARISON"] = resource_comparison(a, b)
    return result


def pair1_report(fixture: dict) -> dict:
    plan = fixture["post_hoc_plan"]
    arms = {arm: qualify_arm(plan, fixture[arm]["evidence"], fixture[arm]["resources"]) for arm in ("A", "B")}
    return attach_post_hoc({"PRIMARY_RESULT": deepcopy(fixture["primary_result"]), "POST_HOC_ANALYSIS": []},
                           plan, arms["A"], arms["B"])


def load_plan(path: Path, *, predeclared: bool = True) -> dict:
    plan = validate_plan(json.loads(path.read_text(encoding="utf-8")), predeclared=predeclared)
    for evaluator in plan["evaluators"]:
        for stem in ("oracle", "cases", "reference", "probe"):
            key = stem + "_path"
            if key not in evaluator:
                continue
            artifact = Path(evaluator[key])
            if not artifact.is_absolute():
                artifact = path.parent / artifact
            artifact = artifact.resolve()
            if hashlib.sha256(artifact.read_bytes()).hexdigest() != evaluator.get(stem + "_sha256"):
                raise ValueError(f"Changed predeclared evaluator artifact: {key}")
            evaluator[key] = str(artifact)
    return plan


def require_runnable(plan: dict) -> None:
    required = {category for key, category in REQUIREMENTS.items() if plan[key]}
    if any(e["runner"] == "external_evidence" and e["category"] in required for e in plan["evaluators"]):
        raise ValueError("Required external evaluator has no installed deterministic runner")


def preflight_plan(plan: dict, *, benchmark_head: str, benchmark_tree: str, task_sha256: str) -> str:
    """Bind a runnable future plan to the observed snapshot and exact task bytes."""
    validate_plan(plan, predeclared=True)
    require_runnable(plan)
    for key, observed, size in (("benchmark_head", benchmark_head, 40),
                                ("benchmark_tree", benchmark_tree, 40),
                                ("task_sha256", task_sha256, 64)):
        value = plan.get(key)
        if (not isinstance(value, str) or len(value) != size
                or any(c not in "0123456789abcdef" for c in value) or value != observed):
            raise ValueError(f"Frozen evaluation plan identity mismatch: {key}")
    return plan_digest(plan)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Re-report saved evidence only; never execute a model")
    parser.add_argument("--pair1-fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = pair1_report(json.loads(args.pair1_fixture.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()

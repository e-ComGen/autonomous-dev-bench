"""Deterministic semantic qualification, paired reports and scoped aggregation."""
from __future__ import annotations

from copy import deepcopy
from statistics import mean, median
import math

CATEGORIES = ("existing_suite", "targeted_oracle", "differential_check", "metamorphic_check", "cross_component_check")
ALIASES = {"differential": "differential_check", "metamorphic": "metamorphic_check", "cross_component": "cross_component_check", "narrow_oracle": "targeted_oracle"}
RESOURCE_FIELDS = ("provider_total_tokens", "total_wall_time", "model_turns", "tool_calls", "read_calls")
QUALITIES = ("A_BETTER", "B_BETTER", "EQUIVALENT_ON_PREDECLARED_EVALUATION", "BOTH_FAIL", "INCONCLUSIVE")


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def qualify_arm(plan, evaluation, metrics, patch_valid=True):
    result = deepcopy(metrics)
    digest = plan.get("evaluation_plan_digest")
    same_plan = bool(digest) and evaluation.get("evaluation_plan_digest") == digest
    required, states = [], {category: [] for category in CATEGORIES}
    observations = evaluation.get("results", {})
    for evaluator in plan.get("evaluators", []):
        category = evaluator["category"].lower()
        category = ALIASES.get(category, category)
        observation = observations.get(evaluator["id"], {})
        status = observation.get("status", "NOT_RUN")
        if status not in {"PASS", "FAIL", "ERROR", "NOT_RUN", "NOT_REQUIRED"}:
            status = "ERROR"
        states[category].append(status)
        if evaluator.get("required") is True:
            required.append(status)
    for category, values in states.items():
        result[category] = next((s for s in ("ERROR", "FAIL", "NOT_RUN") if s in values), "PASS" if values and all(v == "PASS" for v in values) else "NOT_REQUIRED")
    if not same_plan:
        semantic = "INCONCLUSIVE"
    elif patch_valid is False or "FAIL" in required:
        semantic = "NO"
    elif patch_valid is True and required and all(s == "PASS" for s in required):
        semantic = "YES"
    else:
        semantic = "INCONCLUSIVE"
    repair = "INCONCLUSIVE"
    if patch_valid is False:
        repair = "INVALID_PATCH"
    elif same_plan and semantic == "YES":
        # Source equality is optional evidence; semantic success alone does not prove root cause.
        if evaluation.get("production_matches_clean") is True:
            repair = "ROOT_CAUSE_REPAIR"
        elif evaluation.get("behavioral_equivalence_verified") is True:
            repair = "SEMANTICALLY_EQUIVALENT_ALTERNATIVE"
    elif same_plan and result["differential_check"] == "FAIL":
        repair = "BEHAVIORAL_WORKAROUND" if result["targeted_oracle"] == "PASS" else "REGRESSION"
    result.update(semantic_success=semantic, repair_class=repair, patch_valid=patch_valid,
                  evaluation_plan_digest=digest if same_plan else None,
                  evaluation_phase=plan.get("phase"), total_cost=metrics.get("total_cost"),
                  cost_per_semantic_success={"status": "SUCCESS" if semantic == "YES" else "UNSUCCESSFUL" if semantic == "NO" else "UNRESOLVED",
                                             "observed_resources": deepcopy(metrics) if semantic == "YES" else None})
    return result


def paired_summary(plan, a, b):
    digest = plan.get("evaluation_plan_digest")
    eligible_plan = bool(digest) and plan.get("phase") == "PREDECLARED" and all(arm.get("evaluation_plan_digest") == digest and arm.get("evaluation_phase") == "PREDECLARED" for arm in (a, b))
    infra = any(arm.get("execution_success") is not True for arm in (a, b))
    lab_pair = any(arm.get('route') == 'LAB_HOST_ONLY' for arm in (a, b))
    treatment_distinct = (not lab_pair or (all(arm.get('treatment_digest') for arm in (a, b))
                                          and a['treatment_digest'] != b['treatment_digest']))
    quality = "INCONCLUSIVE"
    if eligible_plan and not infra and treatment_distinct:
        quality = {("YES", "YES"): QUALITIES[2], ("YES", "NO"): "A_BETTER", ("NO", "YES"): "B_BETTER", ("NO", "NO"): "BOTH_FAIL"}.get((a.get("semantic_success"), b.get("semantic_success")), quality)
    equal = quality == QUALITIES[2]
    resources = {"equal_quality_cost_comparison": "AVAILABLE" if equal else "NOT_AVAILABLE",
                 "equal_quality_token_saving": None, "token_saving_b_vs_a": None, "raw_differences_b_minus_a": {}}
    for field in RESOURCE_FIELDS:
        av, bv = a.get(field), b.get(field)
        resources["raw_differences_b_minus_a"][field] = bv - av if _numeric(av) and _numeric(bv) else None
    av, bv = a.get("provider_total_tokens"), b.get("provider_total_tokens")
    if treatment_distinct and _numeric(av) and _numeric(bv) and av > 0 and bv >= 0:
        resources["token_saving_b_vs_a"] = 1 - bv / av
        if equal:
            resources["equal_quality_token_saving"] = resources["token_saving_b_vs_a"]
    return {"evaluation_plan_digest": digest, "status": "INFRA_FAILURE" if infra else "COMPLETED",
            **({'comparison_eligible': bool(treatment_distinct),
                'comparison_exclusion_reason': None if treatment_distinct else 'NO_DISTINCT_TREATMENT'} if lab_pair else {}),
            "primary_result": {"A": deepcopy(a), "B": deepcopy(b), "quality_comparison": quality},
            "post_hoc_analysis": None, "quality_comparison": quality,
            "resource_comparison": resources}


def attach_post_hoc(primary, analysis):
    result = deepcopy(primary)
    result["post_hoc_analysis"] = deepcopy(analysis)
    return result


def _distribution(values):
    return {"count": len(values), "mean": mean(values) if values else None,
            "median": median(values) if values else None, "min": min(values) if values else None,
            "max": max(values) if values else None}


def campaign_summary(pairs):
    """Each unique completed pair counts once. Duplicate IDs fail closed entirely."""
    counts = {"pairs_total": len(pairs), "pairs_valid": 0, "pairs_infra_failed": 0,
              "pairs_excluded": 0,
              "pairs_invalid": 0, "pairs_incomplete": 0,
              "A_semantic_successes": 0, "B_semantic_successes": 0}
    counts.update({quality: 0 for quality in QUALITIES})
    ids = [p.get("pair_run_id") for p in pairs]
    distributions = {field: [] for field in RESOURCE_FIELDS}
    for pair in pairs:
        run_id = pair.get("pair_run_id")
        if not run_id or ids.count(run_id) != 1:
            counts["pairs_invalid"] += 1
            continue
        if pair.get("status") == "INFRA_FAILURE":
            counts["pairs_infra_failed"] += 1
            continue
        if pair.get('comparison_eligible') is False:
            counts['pairs_excluded'] += 1
            continue
        if pair.get("status") in {"PLANNED", "VALIDATED", "READY", "PACKETS_IMPORTED", "RUNNING_A", "RUNNING_B", "EVALUATING"}:
            counts["pairs_incomplete"] += 1
            continue
        primary = pair.get("primary_result", {})
        a, b = primary.get("A", {}), primary.get("B", {})
        quality = primary.get("quality_comparison")
        if pair.get("status") != "COMPLETED" or quality not in QUALITIES or not a or not b:
            counts["pairs_invalid"] += 1
            continue
        if any(arm.get("execution_success") is not True for arm in (a,b)):
            counts["pairs_infra_failed"] += 1
            continue
        if quality != "INCONCLUSIVE":
            recomputed = paired_summary({"evaluation_plan_digest": pair.get("evaluation_plan_digest"), "phase": "PREDECLARED"}, a, b)
            if recomputed["quality_comparison"] != quality:
                counts["pairs_invalid"] += 1
                continue
        counts["pairs_valid"] += 1
        counts[quality] += 1
        for arm, values in (("A", a), ("B", b)):
            counts[f"{arm}_semantic_successes"] += values.get("semantic_success") == "YES"
        if quality == QUALITIES[2]:
            for field in RESOURCE_FIELDS:
                av, bv = a.get(field), b.get(field)
                if _numeric(av) and _numeric(bv):
                    distributions[field].append(bv - av)
    denominator = counts["pairs_valid"]
    counts["rate_denominator"] = {"name": "pairs_valid", "count": denominator}
    counts["quality_win_rate"] = {arm: counts[f"{arm}_BETTER"] / denominator if denominator else None for arm in ("A", "B")}
    counts["success_rate_A"] = counts["A_semantic_successes"] / denominator if denominator else None
    counts["success_rate_B"] = counts["B_semantic_successes"] / denominator if denominator else None
    counts["equal_quality_resource_statistics_b_minus_a"] = {field: _distribution(values) for field, values in distributions.items()}
    return counts

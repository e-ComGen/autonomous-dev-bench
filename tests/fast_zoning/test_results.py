from copy import deepcopy
import json
from pathlib import Path

import pytest

from benchmark_core.fast_zoning.results import attach_post_hoc, campaign_summary, paired_summary, qualify_arm

PLAN = {"phase": "PREDECLARED", "evaluation_plan_digest": "f" * 64,
        "evaluators": [{"id": "oracle", "category": "targeted_oracle", "required": True},
                       {"id": "diff", "category": "differential_check", "required": True}]}


def arm(status="PASS", **metrics):
    evaluation = {"evaluation_plan_digest": PLAN["evaluation_plan_digest"], "results": {"oracle": {"status": "PASS"}, "diff": {"status": status}}}
    return qualify_arm(PLAN, evaluation, {"execution_success": True, **metrics})


@pytest.mark.parametrize("a,b,quality", [("PASS","PASS","EQUIVALENT_ON_PREDECLARED_EVALUATION"), ("FAIL","PASS","B_BETTER"), ("PASS","FAIL","A_BETTER"), ("FAIL","FAIL","BOTH_FAIL"), ("ERROR","PASS","INCONCLUSIVE")])
def test_quality_and_equal_cost_are_separate(a, b, quality):
    result = paired_summary(PLAN, arm(a, provider_total_tokens=100), arm(b, provider_total_tokens=50))
    assert result["quality_comparison"] == quality
    assert result["resource_comparison"]["token_saving_b_vs_a"] == 0.5
    assert result["resource_comparison"]["equal_quality_token_saving"] == (0.5 if a == b == "PASS" else None)


def test_narrow_pass_cannot_hide_differential_fail():
    result = arm("FAIL")
    assert result["targeted_oracle"] == "PASS"
    assert result["semantic_success"] == "NO"
    assert result["repair_class"] == "BEHAVIORAL_WORKAROUND"
    assert result["cost_per_semantic_success"]["observed_resources"] is None


def test_equivalent_alternative_requires_behavior_evidence_not_source_equality():
    evaluation = {"evaluation_plan_digest": PLAN["evaluation_plan_digest"], "results": {"oracle":{"status":"PASS"},"diff":{"status":"PASS"}}, "behavioral_equivalence_verified": True, "production_matches_clean": False}
    result = qualify_arm(PLAN, evaluation, {"provider_reported_cost": 0})
    assert result["semantic_success"] == "YES"
    assert result["repair_class"] == "SEMANTICALLY_EQUIVALENT_ALTERNATIVE"
    assert result["total_cost"] is None
    assert qualify_arm(PLAN, evaluation, {}, patch_valid=False)["semantic_success"] == "NO"


def test_infrastructure_failure_and_plan_mismatch_preclude_equal_success():
    a, b = arm(), arm()
    a["execution_success"] = False
    assert paired_summary(PLAN,a,b)["status"] == "INFRA_FAILURE"
    a["execution_success"] = True
    a["evaluation_plan_digest"] = "x"
    assert paired_summary(PLAN,a,b)["quality_comparison"] == "INCONCLUSIVE"


@pytest.mark.parametrize("status", ["ERROR", "NOT_RUN", "NOT_REQUIRED"])
def test_missing_required_evidence_never_success(status):
    assert arm(status)["semantic_success"] == "INCONCLUSIVE"


def test_empty_evaluator_plan_cannot_vacuously_succeed():
    plan = {**PLAN,"evaluators":[]}
    result = qualify_arm(plan,{"evaluation_plan_digest":PLAN["evaluation_plan_digest"],"results":{}},{})
    assert result["semantic_success"] == "INCONCLUSIVE"


def test_unknown_patch_and_unrecognized_evaluator_status_fail_closed():
    evidence = {"evaluation_plan_digest": PLAN["evaluation_plan_digest"],
                "results":{"oracle":{"status":"PASS"},"diff":{"status":"PASS"}}}
    assert qualify_arm(PLAN,evidence,{},patch_valid=None)["semantic_success"] == "INCONCLUSIVE"
    evidence["results"]["diff"]["status"] = "LOOKS_GOOD"
    result = qualify_arm(PLAN,evidence,{})
    assert result["differential_check"] == "ERROR"
    assert result["semantic_success"] == "INCONCLUSIVE"


def fixture_reports():
    fixture = json.loads((Path(__file__).parent / "fixtures/pairs123.json").read_text())
    reports = []
    for pair in fixture["pairs"]:
        arms = [arm("PASS" if s == "YES" else "FAIL" if s == "NO" else "NOT_RUN", **pair[name]) for name,s in zip(("A","B"),pair["primary_semantic"])]
        report = paired_summary(PLAN,*arms)
        report["pair_run_id"] = pair["pair_run_id"]
        if "post_hoc" in pair:
            report = attach_post_hoc(report,pair["post_hoc"])
        reports.append(report)
    return reports


def test_pair1_posthoc_never_rewrites_primary():
    report = fixture_reports()[0]
    assert report["primary_result"]["quality_comparison"] == "INCONCLUSIVE"
    assert report["post_hoc_analysis"]["quality_comparison"] == "B_BETTER"
    original = deepcopy(report)
    appended = attach_post_hoc(report, {"quality_comparison":"A_BETTER"})
    assert appended["primary_result"] == report["primary_result"]
    assert report == original


def test_pair2_failed_solutions_do_not_become_cheap_success():
    report = fixture_reports()[1]
    assert report["quality_comparison"] == "BOTH_FAIL"
    assert report["resource_comparison"]["equal_quality_token_saving"] is None


def test_pair3_equal_success_token_saving_and_aggregate_scope():
    reports = fixture_reports()
    assert reports[2]["resource_comparison"]["equal_quality_token_saving"] == pytest.approx(.324335)
    summary = campaign_summary(reports)
    assert summary["pairs_valid"] == 3
    assert summary["B_BETTER"] == 0
    assert summary["A_semantic_successes"] == summary["B_semantic_successes"] == 1
    dist = summary["equal_quality_resource_statistics_b_minus_a"]["provider_total_tokens"]
    assert dist == {"count":1,"mean":-254343,"median":-254343,"min":-254343,"max":-254343}


def test_duplicate_runs_and_forged_quality_do_not_pollute_aggregates():
    reports = fixture_reports()
    reports[1]["primary_result"]["quality_comparison"] = "EQUIVALENT_ON_PREDECLARED_EVALUATION"
    summary = campaign_summary(reports + [reports[2]])
    assert summary["pairs_invalid"] == 3
    assert summary["pairs_valid"] == 1


def test_campaign_distinguishes_incomplete_invalid_and_infrastructure():
    reports = [{"pair_run_id":"pending","status":"READY"},
               {"pair_run_id":"broken","status":"INVALID_MANIFEST"},
               {"pair_run_id":"infra","status":"INFRA_FAILURE"}]
    summary = campaign_summary(reports)
    assert summary["pairs_incomplete"] == 1
    assert summary["pairs_invalid"] == 1
    assert summary["pairs_infra_failed"] == 1
    assert summary["pairs_valid"] == 0
    assert summary["success_rate_A"] is None

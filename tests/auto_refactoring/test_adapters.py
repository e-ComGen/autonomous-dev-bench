from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from suites.auto_refactoring import (
    DesignFormServiceAdapter,
    ProductionCliAdapter,
    normalize_production_result,
)


def test_subprocess_adapter_preserves_all_untrusted_fields(tmp_path: Path) -> None:
    script = tmp_path / "production_cli.py"
    payload = {
        "decision": "KEEP_CURRENT",
        "status": "CERTIFIED",
        "certificate": {"safe": True},
        "changed_paths": ["a.py", "b.py"],
        "vendor_extension": {"x": 1},
    }
    script.write_text(
        "import json,sys\n"
        "request=json.load(sys.stdin)\n"
        f"print(json.dumps({payload!r}))\n"
        "print('diagnostic', file=sys.stderr)\n"
        "raise SystemExit(9)\n",
        encoding="utf-8",
    )
    result = ProductionCliAdapter((sys.executable, str(script))).run(tmp_path, {"digest": "candidate"})
    assert result.process_status == 9
    assert result.raw_status == "CERTIFIED"
    assert result.certification_claim == {"safe": True}
    assert result.changed_paths == ("a.py", "b.py")
    assert result.raw_output["vendor_extension"]["x"] == 1
    assert result.stdout
    assert "diagnostic" in result.stderr
    assert result.observation().status.value == "FAIL"  # nonzero execution is captured independently


def test_optional_design_form_has_no_import_time_dependency() -> None:
    adapter = DesignFormServiceAdapter(module_name="definitely_missing_design_form")
    with pytest.raises(RuntimeError, match="optional auto-refactoring"):
        adapter.run(".", {})


def test_optional_service_can_be_faked_without_production_dependency() -> None:
    class FakeAssessment:
        def to_dict(self) -> object:
            return {"decision": "REFACTOR", "family": "strategy"}

    class FakeService:
        def analyze_only(self, repository: Path, affected_scope: str) -> object:
            assert affected_scope == "."
            return FakeAssessment()

    result = DesignFormServiceAdapter(factory=FakeService).run(".", {})
    assert result.decision.value == "REMEDIATE"
    assert result.remediation_family == "strategy"


@pytest.mark.parametrize(
    ("gate", "expected"),
    (("FAIL", "REMEDIATE"), ("PASS", "KEEP_CURRENT"), ("UNKNOWN", "UNKNOWN")),
)
def test_v10_design_gate_is_the_decision_authority(gate: str, expected: str) -> None:
    result = normalize_production_result(
        {
            "no_dominated_design_form": gate,
            "controller_recommendation": "ACCEPT" if gate == "FAIL" else "APPLY_DESIGN_REFACTOR",
            "opportunities": [{"opportunity_id": "unassessed"}],
        }
    )
    assert result.decision.value == expected


def test_v10_design_assessment_details_are_preserved() -> None:
    raw = {
        "no_dominated_design_form": "FAIL",
        "controller_recommendation": "APPLY_DESIGN_REFACTOR",
        "hard_unknowns": ["REPOSITORY_LEVEL_UNKNOWN"],
        "assessments": [
            {
                "opportunity": {
                    "opportunity_id": "opp-1",
                    "kind": "REPEATED_TYPE_DISPATCH",
                    "hard_unknowns": [],
                },
                "selected_form": "STRATEGY",
                "current_form_dominated": True,
                "status": "FAIL",
            },
            {
                "opportunity": {
                    "opportunity_id": "opp-2",
                    "kind": "HIDDEN_MUTABLE_GLOBAL",
                    "hard_unknowns": ["GLOBAL_LIFETIME_UNKNOWN"],
                },
                "selected_form": "KEEP_CURRENT",
                "current_form_dominated": False,
                "status": "UNKNOWN",
            },
            {
                "opportunity": {
                    "opportunity_id": "opp-3",
                    "kind": "CONSTRUCTION_POLICY",
                    "hard_unknowns": [],
                },
                "selected_form": "FACTORY",
                "current_form_dominated": True,
                "status": "FAIL",
            },
        ],
    }
    result = normalize_production_result(raw)
    assert result.decision.value == "REMEDIATE"
    assert result.design_gate == "FAIL"
    assert result.controller_recommendation == "APPLY_DESIGN_REFACTOR"
    assert result.remediation_family == "strategy"
    assert result.remediation_families == ("strategy", "factory")
    assert result.selected_forms == ("STRATEGY", "FACTORY")
    assert result.opportunity_ids == ("opp-1", "opp-2", "opp-3")
    assert result.opportunity_kinds == (
        "REPEATED_TYPE_DISPATCH",
        "HIDDEN_MUTABLE_GLOBAL",
        "CONSTRUCTION_POLICY",
    )
    assert result.opportunity_gates == ("FAIL", "UNKNOWN", "FAIL")
    assert result.hard_unknowns == (
        "REPOSITORY_LEVEL_UNKNOWN",
        "GLOBAL_LIFETIME_UNKNOWN",
    )
    observation = result.observation()
    assert observation.attributes["selected_forms"] == ("STRATEGY", "FACTORY")
    assert observation.attributes["opportunity_ids"] == ("opp-1", "opp-2", "opp-3")


def test_design_cli_uses_repository_and_scope_argv_without_stdin(tmp_path: Path) -> None:
    script = tmp_path / "autorefactor-design.py"
    script.write_text(
        "import json,sys\n"
        "assert sys.argv[1] == 'analyze'\n"
        "assert sys.argv[2] == sys.argv[4]\n"
        "assert sys.argv[3] == '--scope'\n"
        "assert sys.stdin.read() == ''\n"
        "print(json.dumps({'no_dominated_design_form': 'PASS', 'assessments': []}))\n",
        encoding="utf-8",
    )
    result = ProductionCliAdapter((sys.executable, str(script), "analyze")).run(
        tmp_path, {"affected_scope": str(tmp_path)}
    )
    assert result.process_status == 0
    assert result.decision.value == "KEEP_CURRENT"
    assert result.stderr == ""

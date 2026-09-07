"""Adapters to existing ADCP role ports; there is no loop or model API here."""
import json
import shared_contracts as sc
from packages.zone_development import (
    Role, RoleIdentity, LocalPlan, RepairRecipe, ChangeProposal, FileEdit, ReviewReport, Finding,
)


def structured(text):
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("A role response must be a JSON object")
    return result


def strings(value, limit=32):
    if not isinstance(value, list) or not 1 <= len(value) <= limit:
        raise ValueError("Expected a bounded nonempty list")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 2048 for item in value):
        raise ValueError("Expected bounded nonempty strings")
    return tuple(value)


class Architect:
    identity = RoleIdentity(role=Role.ARCHITECT, actor_id="benchmark-architect")

    def __init__(self, driver):
        self.driver = driver

    def plan(self, context):
        prompt = (context.request.objective + "\nYou are the local architect. Inspect the existing code and produce an actionable plan. "
                  "Do not implement the change. Return ONLY JSON: {\"steps\":[\"...\"],\"target_paths\":[\"...\"]}. "
                  "Allowed paths: " + json.dumps(context.request.write_scope.paths))
        response, _ = self.driver.invoke(dict(context.source.files), prompt)
        data = structured(response["text"])
        if set(data) != {"steps", "target_paths"}:
            raise ValueError("Unknown architect response fields")
        targets = strings(data["target_paths"])
        if set(targets) - set(context.request.write_scope.paths):
            raise ValueError("Architect expanded the external scope")
        return LocalPlan(request_digest=sc.contract_digest(context.request), author=self.identity,
                         steps=strings(data["steps"]), target_paths=targets,
                         remedies=(RepairRecipe(family="CHANGE_ALGORITHM", targets=targets),))


class Coder:
    identity = RoleIdentity(role=Role.CODER, actor_id="benchmark-coder")

    def __init__(self, driver):
        self.driver = driver

    def code(self, context):
        files = dict(context.source.files)
        prompt = context.request.objective + "\nImplement the admitted plan in the current repository using your normal tools. "
        prompt += "Do not modify public_tests.py or TASK.md. Run public tests as appropriate.\n"
        prompt += "Plan: " + json.dumps(context.plan.steps) + "\nAllowed plan paths: " + json.dumps(context.plan.target_paths)
        if context.review:
            prompt += "\nReview: " + json.dumps(sc.to_wire(context.review))
        if context.evaluation:
            prompt += "\nPublic deterministic verification: " + json.dumps(sc.to_wire(context.evaluation))[:32000]
        _, after = self.driver.invoke(files, prompt)
        changed = sorted(path for path in set(files) | set(after) if files.get(path) != after.get(path))
        if set(changed) - set(context.plan.target_paths):
            raise ValueError("Coder changed files outside the admitted plan")
        return ChangeProposal(request_digest=sc.contract_digest(context.request), author=self.identity,
                              plan_digest=sc.contract_digest(context.plan), source=context.source_ref,
                              edits=tuple(FileEdit(path=path, content=after.get(path)) for path in changed))


class Reviewer:
    identity = RoleIdentity(role=Role.REVIEWER, actor_id="benchmark-reviewer")

    def __init__(self, driver):
        self.driver = driver

    def review(self, context):
        prompt = (context.request.objective + "\nIndependently review this candidate in the current repository. Inspect code and run public tests. "
                  "Do not modify code. Return ONLY JSON {\"findings\":[{\"detail\":\"...\",\"blocking\":true}]}. "
                  "An empty findings list means no issues found, NOT verification PASS.")
        response, _ = self.driver.invoke(dict(context.source.files), prompt)
        data = structured(response["text"])
        if set(data) != {"findings"} or not isinstance(data["findings"], list) or len(data["findings"]) > 32:
            raise ValueError("Invalid reviewer response")
        findings = []
        for number, value in enumerate(data["findings"]):
            if (not isinstance(value, dict) or set(value) != {"detail", "blocking"}
                    or type(value["blocking"]) is not bool or not isinstance(value["detail"], str)
                    or not 1 <= len(value["detail"]) <= 4096):
                raise ValueError("Invalid review finding")
            findings.append(Finding(finding_id=f"review-{number}", detail=value["detail"], blocking=value["blocking"]))
        return ReviewReport(request_digest=sc.contract_digest(context.request), author=self.identity,
                            candidate=context.candidate.as_ref(), plan_digest=sc.contract_digest(context.plan),
                            findings=tuple(findings))

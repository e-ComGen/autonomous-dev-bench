"""Request admission and provider-reported usage; no model credentials or prompts logged."""
from pathlib import Path
import json
import threading


class AdmissionDenied(ValueError):
    pass


class Ledger:
    def __init__(self, config, output):
        self.config = config
        self.output = Path(output)
        self.lock = threading.Lock()
        self.arms = {token: {"arm": arm, "admitted": 0, "completed": 0,
                             "denied": 0, "records": []} for token, arm in config["tokens"].items()}
        self._persist()

    def _persist(self):
        # Tokens remain server-private, including in audit files.
        value = {state["arm"]: state for state in self.arms.values()}
        temporary = self.output.with_suffix(".tmp")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        temporary.replace(self.output)

    def admit(self, token, body):
        with self.lock:
            if token not in self.arms:
                raise AdmissionDenied("UNKNOWN_ARM")
            state = self.arms[token]
            if state["admitted"] >= self.config["requests_per_arm"]:
                state["denied"] += 1
                self._persist()
                raise AdmissionDenied("REQUEST_BUDGET_EXHAUSTED")
            if body.get("model") != self.config["model"]:
                raise AdmissionDenied("MODEL_BINDING_MISMATCH")
            requested = body.get("max_tokens", self.config["output_tokens_per_request"])
            if type(requested) is not int or requested <= 0:
                raise AdmissionDenied("INVALID_OUTPUT_LIMIT")
            body["max_tokens"] = min(requested, self.config["output_tokens_per_request"])
            if body.get("stream"):
                body["stream_options"] = {"include_usage": True}
            state["admitted"] += 1
            sequence = state["admitted"]
            self._persist()  # Admission precedes any possible billable effect.
            return sequence

    def complete(self, token, sequence, usage, status):
        with self.lock:
            state = self.arms[token]
            if any(record["sequence"] == sequence for record in state["records"]):
                raise ValueError("A provider request must not be accounted twice")
            observed = None
            if isinstance(usage, dict):
                fields = ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
                observed = {key: usage[key] for key in fields if type(usage.get(key)) is int and usage[key] >= 0}
                if not {"prompt_tokens", "completion_tokens"} <= set(observed):
                    observed = None
            state["completed"] += 1
            state["records"].append({"sequence": sequence, "status": status, "usage": observed})
            self._persist()


def totals(state):
    records = state["records"]
    complete = state["admitted"] == len(records) and all(record["usage"] is not None for record in records)
    return {"model_requests": state["admitted"], "denied_requests": state["denied"],
            "usage_complete": complete,
            "input_tokens": sum(record["usage"]["prompt_tokens"] for record in records) if complete else None,
            "output_tokens": sum(record["usage"]["completion_tokens"] for record in records) if complete else None,
            "cost_usd": None, "cost_status": "NOT_PRICED", "records": records}

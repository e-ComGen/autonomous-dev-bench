"""Thin adapter around the official SWE-bench v5 CLI.

This module never re-implements grading. It only writes canonical predictions,
builds pinned official CLI invocations and reads the resulting summary.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Iterable

from .identity import require_identifier, require_nonempty

_VERSION_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")


@dataclass(frozen=True, slots=True)
class SwebenchPrediction:
    instance_id: str
    model_patch: str
    model_name_or_path: str

    def __post_init__(self) -> None:
        require_identifier(self.instance_id, "SWE-bench instance_id")
        require_nonempty(self.model_name_or_path, "model_name_or_path")
        if not isinstance(self.model_patch, str):
            raise ValueError("model_patch must be a string")

    def as_record(self) -> dict[str, str]:
        return {
            "instance_id": self.instance_id,
            "model_patch": self.model_patch,
            "model_name_or_path": self.model_name_or_path,
        }


def write_predictions(path: Path, predictions: Iterable[SwebenchPrediction]) -> None:
    records = list(predictions)
    if not records:
        raise ValueError("at least one prediction is required")
    instance_ids = [record.instance_id for record in records]
    if len(set(instance_ids)) != len(instance_ids):
        raise ValueError("prediction instance_ids must be unique")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record.as_record(), sort_keys=True, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )


def require_v5(version_output: str, minimum: tuple[int, int, int] = (5, 0, 2)) -> tuple[int, int, int]:
    match = _VERSION_RE.search(version_output)
    if match is None:
        raise ValueError("could not parse SWE-bench version")
    version = tuple(int(part) for part in match.groups())
    if version < minimum:
        raise ValueError(f"SWE-bench {minimum[0]}.{minimum[1]}.{minimum[2]}+ required")
    return version


@dataclass(frozen=True, slots=True)
class OfficialSwebenchV5:
    executable: str = "swebench"
    dataset: str = "verified"
    workers: int = 1
    timeout_seconds: int = 1800
    task_repo: Path | None = None

    def __post_init__(self) -> None:
        require_nonempty(self.executable, "SWE-bench executable")
        require_nonempty(self.dataset, "SWE-bench dataset")
        if isinstance(self.workers, bool) or self.workers <= 0:
            raise ValueError("workers must be positive")
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def gold_command(self, run_id: str, instance_ids: Iterable[str]) -> tuple[str, ...]:
        return self._command(run_id, instance_ids, gold=True, predictions=None)

    def prediction_command(self, run_id: str, instance_ids: Iterable[str], predictions: Path) -> tuple[str, ...]:
        return self._command(run_id, instance_ids, gold=False, predictions=predictions)

    def results_path(self, working_directory: Path, run_id: str) -> Path:
        require_identifier(run_id, "run_id")
        return working_directory / "logs" / "evaluation" / run_id / "results.json"

    def load_results(self, working_directory: Path, run_id: str) -> dict[str, object]:
        path = self.results_path(working_directory, run_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("official SWE-bench results.json must contain an object")
        return payload

    def _command(
        self,
        run_id: str,
        instance_ids: Iterable[str],
        *,
        gold: bool,
        predictions: Path | None,
    ) -> tuple[str, ...]:
        require_identifier(run_id, "run_id")
        ids = tuple(instance_ids)
        if not ids:
            raise ValueError("at least one SWE-bench instance is required")
        for instance_id in ids:
            require_identifier(instance_id, "SWE-bench instance_id")
        if len(set(ids)) != len(ids):
            raise ValueError("SWE-bench instance_ids must be unique")
        command = [
            self.executable,
            "eval",
            self.dataset,
            "--run-id",
            run_id,
            "-j",
            str(self.workers),
            "-t",
            str(self.timeout_seconds),
        ]
        if self.task_repo is not None:
            command.extend(("--task-repo", str(self.task_repo)))
        if gold:
            command.append("--gold")
        else:
            if predictions is None:
                raise ValueError("prediction path required")
            command.extend(("-p", str(predictions)))
        for instance_id in ids:
            command.extend(("-i", instance_id))
        return tuple(command)

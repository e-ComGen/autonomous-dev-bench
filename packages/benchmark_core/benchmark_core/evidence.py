"""Canonical, reference-integrity-checked benchmark evidence bundles."""
from __future__ import annotations

from dataclasses import fields, is_dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .cas import FileSystemCAS, CASError
from .identity import Sha256Digest, canonical_json
from .replay import write_replay_scripts
from .result import RunStatus, StageResult

_CAS_REF = re.compile(r"^cas:sha256:[0-9a-f]{64}$")
_REQUIRED_MANIFEST_FIELDS = frozenset({
    "schema_version", "run_id", "experiment_id", "versions", "input",
    "system", "scenario", "suite_results", "metrics", "provenance",
})
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class EvidenceIntegrityError(RuntimeError):
    pass


def _plain(value: Any) -> Any:
    if isinstance(value, Sha256Digest): return str(value)
    if hasattr(value, "value") and not isinstance(value, (str, bytes)): return _plain(value.value)
    if is_dataclass(value): return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping): return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)): return [_plain(item) for item in value]
    return value


def _refs(value: Any) -> Iterable[str]:
    if isinstance(value, str) and _CAS_REF.fullmatch(value): yield value
    elif isinstance(value, Mapping):
        for item in value.values(): yield from _refs(item)
    elif isinstance(value, (tuple, list)):
        for item in value: yield from _refs(item)


def _validate_manifest_envelope(data: Mapping[str, Any], error: type[Exception] = ValueError) -> None:
    missing = _REQUIRED_MANIFEST_FIELDS - data.keys()
    finalized_fields = {"stages", "files", "evidence_root_digest"}
    extra = data.keys() - _REQUIRED_MANIFEST_FIELDS - finalized_fields
    present_finalized = data.keys() & finalized_fields
    if missing:
        raise error("evidence manifest is missing required fields: " + ", ".join(sorted(missing)))
    if extra or (present_finalized and present_finalized != finalized_fields):
        names = extra or (finalized_fields - present_finalized)
        raise error("evidence manifest has unknown or incomplete fields: " + ", ".join(sorted(names)))
    versions = data.get("versions")
    if not isinstance(versions, Mapping) or set(versions) != {"benchmark_spec", "runner", "adapter", "suite", "policy", "acceptance"} or any(not isinstance(item, str) or not item for item in versions.values()):
        raise error("versions must pin benchmark, runner, adapter, suite, policy, and acceptance")
    inputs = data.get("input")
    required_inputs = {"project_digest", "task_digest", "checkpoint_digest", "environment_digest"}
    if not isinstance(inputs, Mapping) or set(inputs) != required_inputs or any(not _SHA256.fullmatch(str(inputs[name])) for name in required_inputs):
        raise error("input must contain exact content digests for project, task, checkpoint, and environment")
    system = data.get("system")
    if not isinstance(system, Mapping) or set(system) != {"system_id", "commit", "configuration_digest"} or not _COMMIT.fullmatch(str(system.get("commit", ""))) or not _SHA256.fullmatch(str(system.get("configuration_digest", ""))):
        raise error("system identity must pin id, full commit, and configuration digest")
    scenario = data.get("scenario")
    if not isinstance(scenario, Mapping) or set(scenario) != {"scenario_id", "scenario_version", "content_digest"} or not _SHA256.fullmatch(str(scenario.get("content_digest", ""))):
        raise error("scenario identity must be fully content-pinned")
    suites = data.get("suite_results")
    if not isinstance(suites, Mapping) or not suites:
        raise error("suite_results must contain at least one independent capability result")
    for suite_id, result in suites.items():
        if not isinstance(suite_id, str) or not suite_id or not isinstance(result, Mapping):
            raise error("invalid suite result envelope")
        required = {"suite_version", "status", "oracle_results", "suite_gate_outcomes", "global_gate_outcomes"}
        if set(result) != required or not isinstance(result["oracle_results"], Mapping) or not result["oracle_results"]:
            raise error("suite result must pin identity, oracle results, and gate outcomes")
        if result["status"] not in {item.value for item in RunStatus}:
            raise error("suite result has an unknown status")
        if not all(isinstance(gates, Mapping) and all(isinstance(name, str) and isinstance(passed, bool) for name, passed in gates.items()) for gates in (result["suite_gate_outcomes"], result["global_gate_outcomes"])):
            raise error("suite gate outcomes must be boolean mappings")
        for oracle_id, oracle in result["oracle_results"].items():
            if not isinstance(oracle_id, str) or not isinstance(oracle, Mapping) or set(oracle) != {"oracle_version", "status", "evidence_refs"}:
                raise error("oracle results must pin version, status, and evidence references")
            if oracle["status"] not in {"PASS", "FAIL", "INFRA_FAILURE", "BASELINE_BROKEN", "UNSUPPORTED", "SKIPPED", "INVALID_EXPERIMENT"}:
                raise error("oracle result has an unknown status")
            if not isinstance(oracle["evidence_refs"], list) or any(not _CAS_REF.fullmatch(str(ref)) for ref in oracle["evidence_refs"]):
                raise error("oracle evidence references must be CAS-backed")
            if oracle["status"] in {"PASS", "FAIL"} and not oracle["evidence_refs"]:
                raise error("evaluated oracle results require independently stored evidence")
    if not isinstance(data.get("metrics"), Mapping) or not isinstance(data.get("provenance"), Mapping) or not data["provenance"]:
        raise error("metrics and non-empty provenance mappings are mandatory")


class EvidenceBundleWriter:
    def __init__(self, directory: str | os.PathLike[str], cas: FileSystemCAS) -> None:
        self.directory = Path(directory); self.cas = cas
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "stages").mkdir(exist_ok=True)
        self._stages: list[dict[str, Any]] = []
        self._stage_components: set[str] = set()
        self._files: dict[str, str] = {}
        self.root_digest: str | None = None

    def write_json(self, relative_path: str, value: Any) -> str:
        path = self._safe_path(relative_path); payload = canonical_json(_plain(value)) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(payload, encoding="utf-8", newline="\n")
        ref = self.cas.put_bytes(payload.encode("utf-8")); self._files[relative_path.replace("\\", "/")] = ref
        return ref

    def write_bytes(self, relative_path: str, value: bytes) -> str:
        path = self._safe_path(relative_path); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(value)
        ref = self.cas.put_bytes(value); self._files[relative_path.replace("\\", "/")] = ref; return ref

    def add_stage(self, stage: "StageResult | Mapping[str, Any]") -> str:
        data = _plain(stage)
        if not isinstance(data, dict): raise ValueError("stage must be an object")
        component_value = data.get("component") or data.get("stage_id")
        if not component_value: raise ValueError("stage must have a component or stage_id")
        component = str(component_value)
        if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in component):
            raise ValueError("unsafe stage component")
        if component in self._stage_components:
            raise ValueError(f"duplicate stage component: {component}")
        for ref in _refs(data): self.cas.verify(ref)
        ref = self.write_json(f"stages/{component}.json", data)
        self._stages.append(data)
        self._stage_components.add(component)
        return ref

    def finalize(self, manifest: Mapping[str, Any], *, replay_argv: tuple[str, ...] | None = None,
                 replay_environment: Mapping[str, str] | None = None) -> Path:
        data = dict(_plain(manifest))
        _validate_manifest_envelope(data)
        data["stages"] = list(self._stages)
        if replay_argv:
            sh, bat = write_replay_scripts(self.directory, replay_argv, environment=replay_environment)
            for path in (sh, bat): self._files[path.name] = self.cas.put_file(path)
        for ref in _refs(data): self.cas.verify(ref)
        data["files"] = dict(sorted(self._files.items()))
        data["evidence_root_digest"] = str(Sha256Digest.of({"manifest": data, "files": data["files"]}))
        self.root_digest = data["evidence_root_digest"]
        path = self.directory / "manifest.json"
        path.write_text(canonical_json(data) + "\n", encoding="utf-8", newline="\n")
        return path

    def _safe_path(self, relative: str) -> Path:
        path = self.directory / relative
        try: path.resolve().relative_to(self.directory.resolve())
        except ValueError as exc: raise ValueError("evidence path escapes bundle") from exc
        return path


class EvidenceBundleVerifier:
    def __init__(self, cas: FileSystemCAS) -> None: self.cas = cas

    def verify(self, directory: str | os.PathLike[str], *, expected_root: str) -> dict[str, Any]:
        root = Path(directory); path = root / "manifest.json"
        try: raw = path.read_text(encoding="utf-8"); manifest = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc: raise EvidenceIntegrityError(f"invalid manifest: {exc}") from exc
        if raw != canonical_json(manifest) + "\n": raise EvidenceIntegrityError("manifest is not canonical JSON")
        _validate_manifest_envelope(manifest, EvidenceIntegrityError)
        embedded_root = manifest.get("evidence_root_digest")
        unsigned = dict(manifest); unsigned.pop("evidence_root_digest", None)
        actual_root = str(Sha256Digest.of({"manifest": unsigned, "files": unsigned.get("files", {})}))
        if embedded_root != actual_root or expected_root != actual_root:
            raise EvidenceIntegrityError("evidence root digest does not match external receipt")
        files = manifest.get("files", {})
        if not isinstance(files, dict): raise EvidenceIntegrityError("manifest files must be an object")
        actual_entries: set[str] = set()
        for candidate in root.rglob("*"):
            if candidate.is_symlink() or (not candidate.is_file() and not candidate.is_dir()):
                raise EvidenceIntegrityError(f"symlink or special bundle entry is forbidden: {candidate}")
            if candidate.is_file():
                actual_entries.add(candidate.relative_to(root).as_posix())
        expected_entries = set(files) | {"manifest.json"}
        if actual_entries != expected_entries:
            raise EvidenceIntegrityError("bundle entries do not exactly match the manifest")
        try:
            for relative, ref in files.items():
                target = (root / relative)
                target.resolve().relative_to(root.resolve())
                if not target.is_file(): raise EvidenceIntegrityError(f"missing evidence file: {relative}")
                data = target.read_bytes()
                if FileSystemCAS.ref_for(data) != ref: raise EvidenceIntegrityError(f"bundle file digest mismatch: {relative}")
                if self.cas.get_bytes(ref) != data: raise EvidenceIntegrityError(f"CAS mismatch: {relative}")
            for ref in _refs(manifest): self.cas.verify(ref)
        except (CASError, KeyError, ValueError) as exc: raise EvidenceIntegrityError(str(exc)) from exc
        stages = manifest.get("stages", [])
        if not isinstance(stages, list): raise EvidenceIntegrityError("stages must be a list")
        seen_components: set[str] = set()
        for stage in stages:
            component = (stage.get("component") or stage.get("stage_id")) if isinstance(stage, dict) else None
            if not component or f"stages/{component}.json" not in files: raise EvidenceIntegrityError(f"missing stage record: {component}")
            if component in seen_components: raise EvidenceIntegrityError(f"duplicate stage record: {component}")
            seen_components.add(component)
            try: stage_file = json.loads((root / f"stages/{component}.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc: raise EvidenceIntegrityError(f"invalid stage record: {component}") from exc
            if stage_file != stage: raise EvidenceIntegrityError(f"stage manifest mismatch: {component}")
        for script in ("replay.sh", "replay.bat"):
            if script in files and not (root / script).is_file(): raise EvidenceIntegrityError(f"missing {script}")
        return manifest


def verify_bundle(directory: str | os.PathLike[str], cas: FileSystemCAS, *, expected_root: str) -> dict[str, Any]:
    return EvidenceBundleVerifier(cas).verify(directory, expected_root=expected_root)

"""Immutable CAS export for completed Harbor trial artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from benchmark_core.cas import FileSystemCAS
from benchmark_core.identity import canonical_json


@dataclass(frozen=True, slots=True)
class HarborCASExport:
    manifest_ref: str
    manifest: dict[str, object]


def _forbidden_bytes(values: Iterable[str | bytes]) -> tuple[bytes, ...]:
    forbidden: list[bytes] = []
    for value in values:
        payload = value.encode("utf-8") if isinstance(value, str) else value
        if not isinstance(payload, bytes) or not payload:
            raise ValueError("forbidden CAS values must be non-empty strings or bytes")
        forbidden.append(payload)
    return tuple(forbidden)


def export_harbor_trial_to_cas(
    trial_dir: str | Path,
    cas: FileSystemCAS,
    *,
    forbidden_values: Iterable[str | bytes] = (),
    provenance: Mapping[str, object] | None = None,
) -> HarborCASExport:
    """Export every regular trial artifact after a whole-trial secret scan.

    The source directory itself is intentionally absent from the manifest so the
    same trial bytes exported from a different host path have the same identity.
    """

    root = Path(trial_dir)
    if not root.is_dir():
        raise ValueError(f"Harbor trial directory does not exist: {root}")
    forbidden = _forbidden_bytes(forbidden_values)
    files: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ValueError(f"Harbor CAS export rejects symlinks: {path.relative_to(root)}")
        if path.is_file():
            files.append(path)
    if not files:
        raise ValueError("Harbor trial contains no files to export")

    # Scan the complete source set before writing anything to CAS. A discovered
    # secret therefore cannot leave a partially exported sensitive trial.
    if forbidden:
        leaked: list[str] = []
        for path in files:
            payload = path.read_bytes()
            if any(value in payload for value in forbidden):
                leaked.append(path.relative_to(root).as_posix())
        if leaked:
            raise ValueError(f"Harbor trial contains forbidden secret material: {leaked}")

    entries: list[dict[str, object]] = []
    for path in files:
        payload = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": len(payload),
                "ref": cas.put_bytes(payload),
            }
        )

    result_entries = [entry for entry in entries if entry["path"] == "result.json"]
    if len(result_entries) != 1:
        raise ValueError(f"Harbor trial CAS export requires one root result.json, found {len(result_entries)}")
    patch_entries = [entry for entry in entries if entry["path"] == "agent/PATCH.diff"]
    if len(patch_entries) > 1:
        raise ValueError("Harbor trial CAS export found multiple agent/PATCH.diff files")

    manifest: dict[str, object] = {
        "schema_version": 1,
        "scope": "HARBOR_TRIAL_CAS_EXPORT",
        "files": entries,
        "result_ref": result_entries[0]["ref"],
        "patch_ref": patch_entries[0]["ref"] if patch_entries else None,
        "provenance": dict(provenance or {}),
    }
    manifest_ref = cas.put_text(canonical_json(manifest))
    return HarborCASExport(manifest_ref=manifest_ref, manifest=manifest)

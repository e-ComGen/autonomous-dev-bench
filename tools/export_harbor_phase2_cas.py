"""Export one completed Harbor trial and its pinned provenance into the existing CAS."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages" / "benchmark_core")]

from benchmark_core.cas import FileSystemCAS
from suites.coding.harbor.cas_export import export_harbor_trial_to_cas


def unique_file(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} under {root}, found {len(matches)}")
    return matches[0]


def read_forbidden_env(names: list[str]) -> list[str]:
    values: list[str] = []
    for name in names:
        value = os.environ.get(name)
        if value is None or not value:
            raise ValueError(f"forbidden environment variable is absent or empty: {name}")
        values.append(value)
    return values


def preflight_forbidden(paths: list[Path], forbidden_values: list[str]) -> None:
    if not forbidden_values:
        return
    encoded = [value.encode("utf-8") for value in forbidden_values]
    leaked: list[str] = []
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"CAS preflight rejects symlinks: {path}")
        if path.is_file():
            payload = path.read_bytes()
            if any(value in payload for value in encoded):
                leaked.append(str(path))
    if leaked:
        raise ValueError(f"forbidden secret material found before CAS export: {leaked}")


def put_provenance(cas: FileSystemCAS, files: dict[str, Path]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for name, path in files.items():
        if not path.is_file():
            raise ValueError(f"provenance file does not exist: {path}")
        refs[name] = cas.put_file(path)
        if not cas.verify(refs[name]):
            raise ValueError(f"CAS verification failed for provenance {name}")
    return refs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials-dir", type=Path, required=True)
    parser.add_argument("--cas-root", type=Path, default=ROOT / "artifacts" / "harbor-phase2" / "cas")
    parser.add_argument("--harbor-lock", type=Path, default=ROOT / "HARBOR.lock.json")
    parser.add_argument("--dsh-lock", type=Path, default=ROOT / "DEEPSEEK_HARNESS.lock.json")
    parser.add_argument(
        "--wheel-manifest",
        type=Path,
        default=ROOT / "artifacts" / "harbor-phase2" / "DSH_WHEELS.json",
    )
    parser.add_argument("--forbid-env", action="append", default=[])
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "harbor-phase2" / "PHASE2_HARBOR_CAS_EXPORT.json",
    )
    args = parser.parse_args()

    if not args.trials_dir.is_dir():
        raise ValueError(f"trials directory does not exist: {args.trials_dir}")
    result_path = unique_file(args.trials_dir, "result.json")
    trial_dir = result_path.parent
    forbidden_values = read_forbidden_env(args.forbid_env)
    provenance_files = {
        "harbor_lock": args.harbor_lock,
        "deepseek_harness_lock": args.dsh_lock,
        "deepseek_harness_wheel_closure": args.wheel_manifest,
    }
    for path in provenance_files.values():
        if not path.is_file():
            raise ValueError(f"provenance file does not exist: {path}")

    # Preflight the complete source set before constructing FileSystemCAS, so a
    # detected credential cannot leave even harmless provenance objects behind.
    trial_files = [path for path in sorted(trial_dir.rglob("*")) if path.is_file() or path.is_symlink()]
    preflight_forbidden(trial_files + list(provenance_files.values()), forbidden_values)

    cas = FileSystemCAS(args.cas_root)
    provenance_refs = put_provenance(cas, provenance_files)
    exported = export_harbor_trial_to_cas(
        trial_dir,
        cas,
        forbidden_values=forbidden_values,
        provenance=provenance_refs,
    )

    if not cas.verify(exported.manifest_ref):
        raise ValueError("Harbor CAS manifest did not verify")
    for entry in exported.manifest["files"]:
        ref = entry.get("ref") if isinstance(entry, dict) else None
        if not isinstance(ref, str) or not cas.verify(ref):
            raise ValueError(f"Harbor CAS file ref did not verify: {ref!r}")
    for name, ref in provenance_refs.items():
        if not cas.verify(ref):
            raise ValueError(f"Harbor CAS provenance ref did not verify: {name}")

    file_entries = exported.manifest["files"]
    total_bytes = sum(int(entry["bytes"]) for entry in file_entries)
    evidence = {
        "scope": "PHASE2_HARBOR_CAS_EXPORT",
        "status": "PASS",
        "paid_model_called": False,
        "manifest_ref": exported.manifest_ref,
        "result_ref": exported.manifest["result_ref"],
        "patch_ref": exported.manifest["patch_ref"],
        "provenance_refs": provenance_refs,
        "file_count": len(file_entries),
        "total_bytes": total_bytes,
        "forbidden_env_names_checked": sorted(args.forbid_env),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "Harbor Phase 2 CAS export: PASS "
        f"files={len(file_entries)} bytes={total_bytes} manifest={exported.manifest_ref}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

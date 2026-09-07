"""Discover existing ProjectSpecs without executing third-party source."""
from dataclasses import dataclass
from pathlib import Path

from benchmark_core.manifest import load_json, project_from_mapping
from benchmark_core.identity import Sha256Digest


@dataclass(frozen=True)
class CatalogEntry:
    project_id: str
    scale: str
    repository: str
    commit: str
    source_digest: str
    manifest_digest: str
    manifest_path: Path


def read_catalog(root: Path) -> tuple[CatalogEntry, ...]:
    entries = []
    for path in sorted((root / "corpus/projects").glob("*.json")):
        if path.stat().st_size > 65536:
            raise ValueError("Project manifest exceeds 64 KiB")
        data = load_json(path)
        project = project_from_mapping(data)
        entries.append(CatalogEntry(str(project.project_id), data["classification"]["scale"],
                                    data["source"]["repository"], data["source"]["commit_sha"],
                                    data["source"]["source_tree_digest"], str(Sha256Digest.of(data)), path))
    if not entries or len({item.project_id for item in entries}) != len(entries):
        raise ValueError("Empty catalog or duplicate project IDs")
    return tuple(entries)

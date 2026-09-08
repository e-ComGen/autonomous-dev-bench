"""User-configurable acquisition and qualification limits; no production task authority."""
from dataclasses import dataclass, fields
from datetime import date
import re

REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


@dataclass(frozen=True)
class IssuePolicy:
    repositories: tuple[str, ...] = ()
    repository_pool: int = 50
    max_repositories: int = 20
    pulls_per_repository: int = 30
    max_candidates: int = 40
    tasks_per_project: int = 1
    min_stars: int = 20
    max_stars: int = 1000000
    since: str = "2022-01-01"
    max_api_requests: int = 200
    api_seconds: int = 1800
    max_response_bytes: int = 4194304
    prepare_seconds: int = 1800
    fetch_seconds: int = 180
    build_seconds: int = 300
    qualification_repeats: int = 2
    public_test_files: int = 8
    max_repository_bytes: int = 67108864
    max_file_bytes: int = 16777216
    max_code_bytes: int = 16777216
    small_projects: int = 0
    medium_projects: int = 0
    large_projects: int = 0
    licenses: tuple[str, ...] = ("MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC")

    def __post_init__(self):
        bounds = {"repository_pool": (1, 300), "max_repositories": (1, 100), "pulls_per_repository": (1, 100),
                  "max_candidates": (1, 300), "tasks_per_project": (1, 20), "min_stars": (0, 1000000),
                  "max_stars": (0, 1000000), "max_api_requests": (1, 2000), "api_seconds": (10, 86400),
                  "max_response_bytes": (1024, 8388608), "prepare_seconds": (30, 86400),
                  "fetch_seconds": (5, 900), "build_seconds": (10, 1800), "qualification_repeats": (2, 5),
                  "public_test_files": (1, 100), "max_repository_bytes": (1024, 268435456),
                  "max_file_bytes": (1024, 16777216), "max_code_bytes": (1024, 33488896),
                  "small_projects": (0, 100), "medium_projects": (0, 100), "large_projects": (0, 100)}
        for name, (low, high) in bounds.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"github.{name} must be an integer in [{low}, {high}]")
        date.fromisoformat(self.since)
        if self.min_stars > self.max_stars:
            raise ValueError("github.min_stars exceeds max_stars")
        if any(not REPOSITORY.fullmatch(value) for value in self.repositories):
            raise ValueError("github.repositories requires owner/name identifiers")
        if len(set(self.repositories)) != len(self.repositories) or not self.licenses:
            raise ValueError("Duplicate repositories or empty license allowlist")


def policy_from_mapping(data):
    unknown = set(data) - {field.name for field in fields(IssuePolicy)}
    if unknown:
        raise ValueError(f"Unknown github settings: {sorted(unknown)}")
    values = dict(data)
    for key in ("repositories", "licenses"):
        if key in values:
            if not isinstance(values[key], list) or any(not isinstance(item, str) for item in values[key]):
                raise ValueError(f"github.{key} must be an array of strings")
            values[key] = tuple(values[key])
    return IssuePolicy(**values)

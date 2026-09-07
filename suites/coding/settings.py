"""Strict, bounded settings for a whole paired experiment."""
from dataclasses import dataclass, fields
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class Settings:
    model: str = "deepseek-v4-flash"
    projects: tuple[str, ...] = ("httpx.pinned_001", "requests.pinned_001", "pluggy.pinned_001")
    tasks: int = 1
    repeats: int = 1
    arm_seconds: int = 600
    check_seconds: int = 45
    requests_per_arm: int = 16
    output_tokens_per_request: int = 4096
    request_bytes: int = 262144
    memory_mb: int = 2048
    cpus: int = 2
    max_patch_bytes: int = 262144

    def __post_init__(self):
        bounds = {"tasks": (1, 6), "repeats": (1, 5), "arm_seconds": (30, 3600),
                  "check_seconds": (5, 300), "requests_per_arm": (1, 128),
                  "output_tokens_per_request": (256, 32768), "request_bytes": (4096, 1048576),
                  "memory_mb": (512, 16384), "cpus": (1, 16), "max_patch_bytes": (1024, 1000000)}
        for key, (low, high) in bounds.items():
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key} must be an integer in [{low}, {high}]")
        if self.model not in {"deepseek-v4-flash", "deepseek-v4-pro"}:
            raise ValueError("The official DSH provider requires an explicitly supported model")
        if not self.projects or len(self.projects) != len(set(self.projects)):
            raise ValueError("projects must be nonempty and unique")
        if any(project not in {"httpx.pinned_001", "requests.pinned_001", "pluggy.pinned_001"}
               for project in self.projects):
            raise ValueError("Unknown seed project; discovery candidates are not qualified tasks")


def load_settings(path: Path) -> Settings:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown = set(data) - {field.name for field in fields(Settings)}
    if unknown:
        raise ValueError(f"Unknown A/B settings: {sorted(unknown)}")
    if "projects" in data:
        if not isinstance(data["projects"], list) or not all(isinstance(x, str) for x in data["projects"]):
            raise ValueError("projects must be an array of project identifiers")
        data["projects"] = tuple(data["projects"])
    return Settings(**data)

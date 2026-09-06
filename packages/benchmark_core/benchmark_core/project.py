"""Immutable project-corpus specifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Mapping

from .identity import (
    CanonicalModel,
    CommitPin,
    FrozenDict,
    Sha256Digest,
    VersionIdentity,
    freeze_json,
    require_identifier,
    require_nonempty,
    require_unique,
)


def _digest(value: Sha256Digest | str) -> Sha256Digest:
    return value if isinstance(value, Sha256Digest) else Sha256Digest(value)


def _strings(values: tuple[str, ...], name: str, *, required: bool = False) -> tuple[str, ...]:
    result = tuple(values)
    if required and not result:
        raise ValueError(f"{name} must not be empty")
    for value in result:
        require_identifier(value, name)
    return require_unique(result, name)


@dataclass(frozen=True, slots=True)
class ProjectSource(CanonicalModel):
    repository: str
    commit_sha: CommitPin | str
    source_tree_digest: Sha256Digest | str

    def __post_init__(self) -> None:
        require_nonempty(self.repository, "repository")
        if self.repository.casefold() == "latest":
            raise ValueError("repository cannot be 'latest'")
        object.__setattr__(self, "commit_sha", self.commit_sha if isinstance(self.commit_sha, CommitPin) else CommitPin(self.commit_sha))
        object.__setattr__(self, "source_tree_digest", _digest(self.source_tree_digest))


@dataclass(frozen=True, slots=True)
class LegalSpec(CanonicalModel):
    license_spdx: str
    license_file_digest: Sha256Digest | str
    license_file: str = "LICENSE"

    def __post_init__(self) -> None:
        require_nonempty(self.license_spdx, "license_spdx")
        require_nonempty(self.license_file, "license_file")
        object.__setattr__(self, "license_file_digest", _digest(self.license_file_digest))


@dataclass(frozen=True, slots=True)
class PlatformSpec(CanonicalModel):
    operating_systems: tuple[str, ...]
    python_versions: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "operating_systems", _strings(self.operating_systems, "operating_systems", required=True))
        versions = tuple(self.python_versions)
        if not versions or any(not isinstance(v, str) or not v.startswith("3.") for v in versions):
            raise ValueError("python_versions must contain supported Python 3 versions")
        object.__setattr__(self, "python_versions", require_unique(versions, "python_versions"))


@dataclass(frozen=True, slots=True)
class InstallSpec(CanonicalModel):
    command_id: str
    argv: tuple[str, ...]
    timeout_seconds: int = 1200
    environment: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        require_identifier(self.command_id, "command_id")
        argv = tuple(self.argv)
        if not argv or any(not isinstance(item, str) or not item for item in argv):
            raise ValueError("install argv must contain non-empty strings")
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("install timeout_seconds must be positive")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "environment", freeze_json(self.environment))


@dataclass(frozen=True, slots=True)
class BootstrapSpec(CanonicalModel):
    adapter_id: str
    dependency_spec_digests: tuple[Sha256Digest | str, ...]
    dependency_spec_paths: tuple[str, ...]
    extras: tuple[str, ...] = ()
    install: InstallSpec | None = None

    def __post_init__(self) -> None:
        require_identifier(self.adapter_id, "adapter_id")
        digests = tuple(_digest(v) for v in self.dependency_spec_digests)
        paths = tuple(self.dependency_spec_paths)
        if len(paths) != len(digests) or not paths:
            raise ValueError("dependency spec paths and digests must form a non-empty bijection")
        for path in paths:
            candidate = PurePosixPath(path)
            if candidate.is_absolute() or ".." in candidate.parts or str(candidate) != path:
                raise ValueError("dependency spec paths must be safe canonical relative paths")
        object.__setattr__(self, "dependency_spec_digests", digests)
        object.__setattr__(self, "dependency_spec_paths", require_unique(paths, "dependency_spec_paths"))
        object.__setattr__(self, "extras", _strings(self.extras, "extras"))


@dataclass(frozen=True, slots=True)
class CommandSpec(CanonicalModel):
    command_id: str
    argv: tuple[str, ...]
    timeout_seconds: int
    environment: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        require_identifier(self.command_id, "command_id")
        argv = tuple(self.argv)
        if not argv or any(not isinstance(arg, str) or not arg for arg in argv):
            raise ValueError("argv must contain at least one non-empty argument")
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "environment", freeze_json(self.environment))


@dataclass(frozen=True, slots=True)
class BaselineSpec(CanonicalModel):
    commands: tuple[CommandSpec, ...]
    required_status: str = "passing"
    baseline_health_revision: str = "1"

    def __post_init__(self) -> None:
        commands = tuple(self.commands)
        if not commands:
            raise ValueError("baseline commands must not be empty")
        ids = tuple(command.command_id for command in commands)
        require_unique(ids, "baseline command ids")
        require_identifier(self.required_status, "required_status")
        require_identifier(self.baseline_health_revision, "baseline_health_revision")
        object.__setattr__(self, "commands", commands)


@dataclass(frozen=True, slots=True)
class ClassificationSpec(CanonicalModel):
    scale: str
    domains: tuple[str, ...]
    architecture_features: tuple[str, ...] = ()
    dynamic_features: tuple[str, ...] = ()
    capabilities_exercised: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.scale, "scale")
        object.__setattr__(self, "domains", _strings(self.domains, "domains", required=True))
        for name in ("architecture_features", "dynamic_features", "capabilities_exercised"):
            object.__setattr__(self, name, _strings(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class SecuritySpec(CanonicalModel):
    build_network_policy: str
    execution_network_policy: str

    def __post_init__(self) -> None:
        require_identifier(self.build_network_policy, "build_network_policy")
        require_identifier(self.execution_network_policy, "execution_network_policy")


@dataclass(frozen=True, slots=True)
class CorpusSpec(CanonicalModel):
    release: str
    partition: str

    def __post_init__(self) -> None:
        require_identifier(self.release, "release")
        require_identifier(self.partition, "partition")


@dataclass(frozen=True, slots=True)
class ProjectSpec(CanonicalModel):
    """A complete, immutable description of one pinned corpus snapshot."""

    project_id: str
    spec_version: str
    source: ProjectSource
    legal: LegalSpec
    platforms: PlatformSpec
    bootstrap: BootstrapSpec
    baseline: BaselineSpec
    classification: ClassificationSpec
    security: SecuritySpec
    corpus: CorpusSpec

    def __post_init__(self) -> None:
        require_identifier(self.project_id, "project_id")
        require_identifier(self.spec_version, "spec_version")

    @property
    def identity(self) -> VersionIdentity:
        return VersionIdentity(self.project_id, self.spec_version, self.content_digest)

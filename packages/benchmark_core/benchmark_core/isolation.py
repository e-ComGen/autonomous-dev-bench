"""Explicit execution isolation policies and fail-closed validation."""
from __future__ import annotations

from dataclasses import dataclass, is_dataclass
from enum import Enum
import inspect
from types import MappingProxyType
from collections.abc import Mapping

from .identity import Sha256Digest, require_identifier


class NetworkPolicy(str, Enum):
    NONE = "none"
    PACKAGE_INDICES_ONLY = "package_indices_only"
    UNRESTRICTED = "unrestricted"


class ExecutionMode(str, Enum):
    SAME_PROCESS = "same_process"
    FRESH_PROCESS = "fresh_process"
    RESTART_PROCESS = "restart_process"


@dataclass(frozen=True)
class IsolationPolicy:
    execution_mode: ExecutionMode = ExecutionMode.FRESH_PROCESS
    network: NetworkPolicy = NetworkPolicy.NONE
    fresh_worktree: bool = True
    fresh_temp_directory: bool = True
    process_tree_cleanup: bool = True
    authoritative: bool = True
    trusted_provider_id: str | None = None
    trusted_provider_digest: str | None = None

    def __post_init__(self) -> None:
        if (self.trusted_provider_id is None) != (self.trusted_provider_digest is None):
            raise ValueError("sandbox provider id and digest must be pinned together")
        if self.trusted_provider_id is not None:
            require_identifier(self.trusted_provider_id, "trusted_provider_id")
            Sha256Digest(self.trusted_provider_digest)


@dataclass(frozen=True)
class IsolationCapabilities:
    network_none: bool = False
    network_allowlist: bool = False
    fresh_process: bool = True
    process_tree_cleanup: bool = True
    filesystem_isolation: bool = False


@dataclass(frozen=True)
class SandboxAttestation:
    provider_id: str
    provider_version: str
    implementation_digest: str
    capabilities: IsolationCapabilities

    def __post_init__(self) -> None:
        require_identifier(self.provider_id, "provider_id")
        require_identifier(self.provider_version, "provider_version")
        Sha256Digest(self.implementation_digest)


def sandbox_provider_artifact_digest(provider: object) -> str:
    """Independently hash loaded provider code and immutable configuration."""
    provider_type = type(provider)
    try:
        source = inspect.getsource(provider_type)
    except (OSError, TypeError) as exc:
        raise ValueError("trusted sandbox provider source is not inspectable") from exc
    configuration = provider if is_dataclass(provider) else dict(vars(provider))
    return str(Sha256Digest.of({"provider_type": f"{provider_type.__module__}.{provider_type.__qualname__}",
                                "source": source, "configuration": configuration}))


@dataclass(frozen=True, slots=True)
class SandboxTrustStore:
    """Operator-owned allowlist; SUT-controlled provider objects cannot self-register."""

    providers: Mapping[str, object]

    def __post_init__(self) -> None:
        frozen = dict(self.providers)
        for provider_id, provider in frozen.items():
            require_identifier(provider_id, "trusted provider id")
            attestation = provider.attest()
            if attestation.provider_id != provider_id:
                raise ValueError("trusted provider key does not match its attestation")
            if attestation.implementation_digest != sandbox_provider_artifact_digest(provider):
                raise ValueError("provider self-attestation does not match independently hashed code/configuration")
        object.__setattr__(self, "providers", MappingProxyType(frozen))

    def resolve(self, provider_id: str, implementation_digest: str) -> object:
        try:
            provider = self.providers[provider_id]
        except KeyError as exc:
            raise IsolationUnavailable("sandbox provider is absent from the operator trust store") from exc
        attestation = provider.attest()
        if attestation.implementation_digest != implementation_digest:
            raise IsolationUnavailable("sandbox provider implementation is not operator-pinned")
        return provider


class IsolationUnavailable(RuntimeError):
    pass


def validate_isolation(policy: IsolationPolicy, capabilities: IsolationCapabilities) -> None:
    missing: list[str] = []
    if policy.execution_mode != ExecutionMode.SAME_PROCESS and not capabilities.fresh_process:
        missing.append("fresh process")
    if policy.process_tree_cleanup and not capabilities.process_tree_cleanup:
        missing.append("process-tree cleanup")
    if policy.fresh_worktree and not capabilities.filesystem_isolation:
        missing.append("filesystem isolation")
    if policy.network == NetworkPolicy.NONE and not capabilities.network_none:
        missing.append("network denial")
    if policy.network == NetworkPolicy.PACKAGE_INDICES_ONLY and not capabilities.network_allowlist:
        missing.append("network allowlist")
    if missing and policy.authoritative:
        raise IsolationUnavailable("authoritative isolation unavailable: " + ", ".join(missing))


def local_process_capabilities() -> IsolationCapabilities:
    """Plain subprocesses cannot honestly claim network/filesystem sandboxing."""
    return IsolationCapabilities(network_none=False, network_allowlist=False,
                                 fresh_process=True, process_tree_cleanup=True,
                                 filesystem_isolation=False)

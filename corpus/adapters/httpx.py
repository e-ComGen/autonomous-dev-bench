"""Deterministic public development overlay for the pinned HTTPX workload."""
from __future__ import annotations

from dataclasses import dataclass
import inspect
import hashlib
from pathlib import Path

from benchmark_core.identity import Sha256Digest
from benchmark_core.overlay import InvalidExperiment
from mutations import DUPLICATE_PROVIDER_DISPATCH
import mutations.base as mutation_base_module
import mutations.recipes as mutation_recipes_module


_REGISTRY_SOURCE = '''"""Named sync/async transport provider factories."""
from __future__ import annotations
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from ._transports.base import AsyncBaseTransport, BaseTransport
from ._transports.default import AsyncHTTPTransport, HTTPTransport

@dataclass
class TransportProviderRegistry:
    sync_factories: Mapping[str, Callable[..., BaseTransport]]
    async_factories: Mapping[str, Callable[..., AsyncBaseTransport]]

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "__module__" and name in self.__dict__:
            raise TypeError("TransportProviderRegistry is immutable")
        object.__setattr__(self, name, value)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sync_factories", MappingProxyType(dict(self.sync_factories)))
        object.__setattr__(self, "async_factories", MappingProxyType(dict(self.async_factories)))

    def with_provider(self, name: str, *, sync_factory: Callable[..., BaseTransport], async_factory: Callable[..., AsyncBaseTransport]) -> "TransportProviderRegistry":
        if not name or name in self.sync_factories or name in self.async_factories:
            raise ValueError(f"transport provider already registered or invalid: {name!r}")
        sync, async_ = dict(self.sync_factories), dict(self.async_factories)
        sync[name], async_[name] = sync_factory, async_factory
        return TransportProviderRegistry(MappingProxyType(sync), MappingProxyType(async_))

    def create(self, name: str, *, async_mode: bool, **kwargs: Any) -> BaseTransport | AsyncBaseTransport:
        providers = self.async_factories if async_mode else self.sync_factories
        try:
            factory = providers[name]
        except KeyError as exc:
            raise ValueError(f"unknown transport provider: {name!r}") from exc
        return factory(**kwargs)

DEFAULT_TRANSPORT_PROVIDERS = TransportProviderRegistry(
    MappingProxyType({"default": HTTPTransport}), MappingProxyType({"default": AsyncHTTPTransport})
)
'''


def _replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise InvalidExperiment(f"HTTPX fixture anchor cardinality changed: {old[:60]!r}")
    return text.replace(old, new)


@dataclass(frozen=True, slots=True)
class HttpxDevelopmentBindings:
    task_overlay_id: str = "task:httpx.add_transport_provider.v1"
    fixture_overlay_id: str = "fixture:httpx.transport_provider_candidate.v1"

    @staticmethod
    def task_overlay(workspace: Path) -> None:
        # The task is projected through the invocation, never written into SUT files.
        if not (workspace / "httpx" / "_client.py").is_file():
            raise InvalidExperiment("pinned HTTPX source layout is missing")

    @staticmethod
    def fixture_overlay(workspace: Path) -> None:
        client = workspace / "httpx" / "_client.py"
        if not client.is_file():
            raise InvalidExperiment("pinned HTTPX _client.py is missing")
        text = client.read_text(encoding="utf-8")
        text = _replace_once(text, "from ._transports.default import AsyncHTTPTransport, HTTPTransport\n", "from ._transports.default import AsyncHTTPTransport, HTTPTransport\nfrom ._transport_providers import DEFAULT_TRANSPORT_PROVIDERS, TransportProviderRegistry\n")
        text = _replace_once(text, "        transport: BaseTransport | None = None,\n        default_encoding:", "        transport: BaseTransport | None = None,\n        transport_provider: str | None = None,\n        transport_provider_registry: TransportProviderRegistry = DEFAULT_TRANSPORT_PROVIDERS,\n        default_encoding:")
        text = _replace_once(text, "            transport=transport,\n        )\n        self._mounts: dict[URLPattern, BaseTransport | None]", "            transport=transport,\n            transport_provider=transport_provider,\n            transport_provider_registry=transport_provider_registry,\n        )\n        self._mounts: dict[URLPattern, BaseTransport | None]")
        text = _replace_once(text, "        transport: BaseTransport | None = None,\n    ) -> BaseTransport:\n        if transport is not None:\n            return transport\n\n        return HTTPTransport(", "        transport: BaseTransport | None = None,\n        transport_provider: str | None = None,\n        transport_provider_registry: TransportProviderRegistry = DEFAULT_TRANSPORT_PROVIDERS,\n    ) -> BaseTransport:\n        if transport is not None and transport_provider is not None:\n            raise ValueError(\"transport and transport_provider are mutually exclusive\")\n        if transport is not None:\n            return transport\n        if transport_provider is not None:\n            transport = transport_provider_registry.create(transport_provider, async_mode=False, verify=verify, cert=cert, trust_env=trust_env, http1=http1, http2=http2, limits=limits)\n            return transport\n\n        return HTTPTransport(")
        text = _replace_once(text, "        transport: AsyncBaseTransport | None = None,\n        trust_env:", "        transport: AsyncBaseTransport | None = None,\n        transport_provider: str | None = None,\n        transport_provider_registry: TransportProviderRegistry = DEFAULT_TRANSPORT_PROVIDERS,\n        trust_env:")
        text = _replace_once(text, "            transport=transport,\n        )\n\n        self._mounts: dict[URLPattern, AsyncBaseTransport | None]", "            transport=transport,\n            transport_provider=transport_provider,\n            transport_provider_registry=transport_provider_registry,\n        )\n\n        self._mounts: dict[URLPattern, AsyncBaseTransport | None]")
        text = _replace_once(text, "        transport: AsyncBaseTransport | None = None,\n    ) -> AsyncBaseTransport:\n        if transport is not None:\n            return transport\n\n        return AsyncHTTPTransport(", "        transport: AsyncBaseTransport | None = None,\n        transport_provider: str | None = None,\n        transport_provider_registry: TransportProviderRegistry = DEFAULT_TRANSPORT_PROVIDERS,\n    ) -> AsyncBaseTransport:\n        if transport is not None and transport_provider is not None:\n            raise ValueError(\"transport and transport_provider are mutually exclusive\")\n        if transport is not None:\n            return transport\n        if transport_provider is not None:\n            transport = transport_provider_registry.create(transport_provider, async_mode=True, verify=verify, cert=cert, trust_env=trust_env, http1=http1, http2=http2, limits=limits)\n            return transport\n\n        return AsyncHTTPTransport(")
        client.write_text(text, encoding="utf-8", newline="\n")
        public_api = workspace / "httpx" / "__init__.py"
        public_text = public_api.read_text(encoding="utf-8")
        public_text = _replace_once(public_text, "from ._transports import *\n", "from ._transports import *\nfrom ._transport_providers import DEFAULT_TRANSPORT_PROVIDERS, TransportProviderRegistry\n")
        public_text = _replace_once(public_text, '    "Client",\n', '    "Client",\n    "DEFAULT_TRANSPORT_PROVIDERS",\n    "TransportProviderRegistry",\n')
        public_api.write_text(public_text, encoding="utf-8", newline="\n")
        (workspace / "httpx" / "_transport_providers.py").write_text(_REGISTRY_SOURCE, encoding="utf-8", newline="\n")

    @property
    def overlay_handlers(self):
        return {self.task_overlay_id: self.task_overlay, self.fixture_overlay_id: self.fixture_overlay}

    @property
    def mechanics_identities(self):
        return {
            self.task_overlay_id: str(Sha256Digest.of({
                "implementation": inspect.getsource(type(self).task_overlay),
            })),
            self.fixture_overlay_id: str(Sha256Digest.of({
                "implementation": inspect.getsource(type(self).fixture_overlay),
                "replace_implementation": inspect.getsource(_replace_once), "registry_source": _REGISTRY_SOURCE,
            })),
            "mutation:DUPLICATE_PROVIDER_DISPATCH": str(Sha256Digest.of({
                "implementation": inspect.getsource(type(DUPLICATE_PROVIDER_DISPATCH)),
                "recipes_module_sha256": hashlib.sha256(Path(mutation_recipes_module.__file__).read_bytes()).hexdigest(),
                "base_module_sha256": hashlib.sha256(Path(mutation_base_module.__file__).read_bytes()).hexdigest(),
                "recipe": DUPLICATE_PROVIDER_DISPATCH.descriptor,
                "parameters": self.mutation_parameters["DUPLICATE_PROVIDER_DISPATCH"],
            })),
        }

    @property
    def mutation_recipes(self):
        return {DUPLICATE_PROVIDER_DISPATCH.descriptor.mutation_id: DUPLICATE_PROVIDER_DISPATCH}

    @property
    def mutation_parameters(self):
        line = "            transport = transport_provider_registry.create(transport_provider, async_mode=False, verify=verify, cert=cert, trust_env=trust_env, http1=http1, http2=http2, limits=limits)"
        return {"DUPLICATE_PROVIDER_DISPATCH": {"path": "httpx/_client.py", "anchor": line, "duplicate": line}}


HTTPX_DEVELOPMENT_BINDINGS = HttpxDevelopmentBindings()

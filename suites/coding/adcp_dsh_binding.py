"""Production-side binding from ADCP role calls to the pinned DeepSeek Harness SDK.

The ADCP source remains pinned and model-agnostic. This host adapter owns the
DeepSeek Harness transport, validates the exact SDK version, isolates each role
from the candidate workspace, and converts small semantic model responses into
the existing ADCP v2 role contracts. The deterministic ECACC verifier remains a
separate local role and is intentionally not delegated to the model.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.metadata import PackageNotFoundError, version as package_version
import json
from pathlib import Path
from typing import Callable, Mapping


DSH_SDK_VERSION = "0.1.2rc1"
DSH_BINDING_ID = "deepseek-harness-sdk/0.1.2rc1:adcp-role-semantic-v1"
COMMAND_SCHEMA = "autobench.adcp-dsh-command/1"
RESULT_SCHEMA = "autobench.adcp-dsh-result/1"
MODEL_ROUTE = "deepseek-v4-flash"
PROVIDER_ROUTE = "deepseek-official"


class DeepSeekBindingError(ValueError):
    """The pinned DeepSeek Harness binding cannot prove a valid role result."""


@dataclass(frozen=True, slots=True)
class DeepSeekRoleCommand:
    binding_id: str
    call_id: str
    call_digest: str
    actor_id: str
    role: str
    input_json: str
    output_schema: str
    instruction: str
    required_capabilities: tuple[str, ...]
    max_output_bytes: int


@dataclass(frozen=True, slots=True)
class DeepSeekRoleResult:
    binding_id: str
    call_id: str
    execution_id: str
    session_id: str
    provider: str
    model: str
    finish_reason: str | None
    final_response: str
    sdk_version: str


class DeepSeekHarnessProtocol:
    """Tier-0 protocol port backed by the real DeepSeek Harness Python SDK."""

    def __init__(
        self,
        *,
        state_root: Path,
        base_url: str,
        api_key: str,
        model: str = MODEL_ROUTE,
        provider: str = PROVIDER_ROUTE,
        profile: str = "sdk-minimal",
        request_timeout_seconds: float = 120.0,
        harness_factory: Callable[..., object] | None = None,
        require_installed_sdk: bool = True,
    ) -> None:
        if not base_url.strip() or not api_key.strip():
            raise DeepSeekBindingError("DeepSeek Harness protocol requires an explicit proxy route and credential")
        if model != MODEL_ROUTE or provider != PROVIDER_ROUTE:
            raise DeepSeekBindingError("binding changed the preregistered model/provider identity")
        self.state_root = Path(state_root).resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.profile = profile
        self.request_timeout_seconds = request_timeout_seconds
        self._harness_factory = harness_factory
        self.model_calls = 0
        if require_installed_sdk:
            try:
                installed = package_version("deepseek-harness-sdk")
            except PackageNotFoundError as error:
                raise DeepSeekBindingError("deepseek-harness-sdk is not installed") from error
            if installed != DSH_SDK_VERSION:
                raise DeepSeekBindingError(
                    f"DeepSeek Harness SDK version drift: expected {DSH_SDK_VERSION}, got {installed}"
                )

    def describe_capabilities(self) -> dict[str, object]:
        return {
            "schema": "autobench.deepseek-harness-capabilities/1",
            "binding_id": DSH_BINDING_ID,
            "sdk_version": DSH_SDK_VERSION,
            "provider": self.provider,
            "model": self.model,
            "roles": ("LOCAL_ARCHITECT", "CODER", "REVIEWER"),
            "context_modes": ("FRESH",),
            "capabilities": ("source.read", "evidence.read", "patch.propose"),
        }

    def run_agent(self, command: object) -> DeepSeekRoleResult:
        if type(command) is not DeepSeekRoleCommand:
            raise DeepSeekBindingError("DeepSeek protocol received a foreign command type")
        if command.binding_id != DSH_BINDING_ID:
            raise DeepSeekBindingError("DeepSeek command targets another binding")
        if command.role not in {"LOCAL_ARCHITECT", "CODER", "REVIEWER"}:
            raise DeepSeekBindingError("unsupported model-backed ADCP role")

        factory = self._harness_factory
        if factory is None:
            try:
                from deepseek_harness import DeepSeekHarness
            except ImportError as error:
                raise DeepSeekBindingError("deepseek_harness import failed") from error
            factory = DeepSeekHarness

        actor_key = hashlib.sha256(command.actor_id.encode("utf-8")).hexdigest()[:16]
        dsh_home = self.state_root / "homes" / actor_key
        cwd = self.state_root / "isolated-role-workspaces" / actor_key
        dsh_home.mkdir(parents=True, exist_ok=True)
        cwd.mkdir(parents=True, exist_ok=True)
        session_id = "adcp-" + hashlib.sha256(command.call_id.encode("utf-8")).hexdigest()[:24]
        prompt = _role_prompt(command)
        max_tokens = max(256, min(16384, command.max_output_bytes // 4))

        harness = factory(
            dsh_home=str(dsh_home),
            cwd=str(cwd),
            profile=self.profile,
            provider=self.provider,
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key,
            max_tokens=max_tokens,
            request_timeout_seconds=self.request_timeout_seconds,
        )
        self.model_calls += 1
        try:
            if hasattr(harness, "__enter__"):
                with harness as active:
                    result = active.run(prompt, session_id=session_id)
            else:
                result = harness.run(prompt, session_id=session_id)
                close = getattr(harness, "close", None)
                if callable(close):
                    close()
        except BaseException:
            raise

        final_response = getattr(result, "final_response", None)
        finish_reason = getattr(result, "finish_reason", None)
        if not isinstance(final_response, str) or not final_response.strip():
            raise DeepSeekBindingError("DeepSeek Harness returned no committed root response")
        if finish_reason != "completed":
            raise DeepSeekBindingError(f"DeepSeek Harness turn did not complete: {finish_reason!r}")
        if len(final_response.encode("utf-8")) > command.max_output_bytes:
            raise DeepSeekBindingError("DeepSeek Harness role response exceeds issued byte bound")

        return DeepSeekRoleResult(
            binding_id=DSH_BINDING_ID,
            call_id=command.call_id,
            execution_id="dsh:" + hashlib.sha256((session_id + command.call_digest).encode("utf-8")).hexdigest()[:24],
            session_id=session_id,
            provider=self.provider,
            model=self.model,
            finish_reason=finish_reason,
            final_response=final_response,
            sdk_version=DSH_SDK_VERSION,
        )

    def cancel_execution(self, execution_id: str) -> dict[str, object]:
        if not isinstance(execution_id, str) or not execution_id.startswith("dsh:"):
            raise DeepSeekBindingError("foreign DeepSeek execution id")
        return {"status": "NOT_ACTIVE", "execution_id": execution_id}

    def checkpoint_context(self, context_id: str) -> object:
        raise DeepSeekBindingError("this binding intentionally supports only FRESH role contexts")


class DeepSeekHarnessBinding:
    """Strict ADCP ProtocolBinding for the pinned DeepSeek Harness SDK."""

    binding_id = DSH_BINDING_ID

    def describe_support(self, manifest: object):
        from packages.harness_bridge.contracts import AgentRole, ContextMode, HarnessSupport

        if not isinstance(manifest, Mapping):
            raise DeepSeekBindingError("DeepSeek capability manifest must be an object")
        expected = {
            "binding_id": DSH_BINDING_ID,
            "sdk_version": DSH_SDK_VERSION,
            "provider": PROVIDER_ROUTE,
            "model": MODEL_ROUTE,
        }
        for name, value in expected.items():
            if manifest.get(name) != value:
                raise DeepSeekBindingError(f"DeepSeek capability manifest drift: {name}")
        return HarnessSupport(
            protocol_binding_id=DSH_BINDING_ID,
            roles=(AgentRole.LOCAL_ARCHITECT, AgentRole.CODER, AgentRole.REVIEWER),
            context_modes=(ContextMode.FRESH,),
            capabilities=("source.read", "evidence.read", "patch.propose"),
        )

    def encode_command(self, call) -> bytes:
        import shared_contracts as sc
        from packages.harness_bridge.contracts import RoleCall

        if type(call) is not RoleCall:
            raise DeepSeekBindingError("binding requires the exact ADCP RoleCall")
        if call.protocol_binding_id != DSH_BINDING_ID:
            raise DeepSeekBindingError("RoleCall targets another binding")
        value = {
            "schema": COMMAND_SCHEMA,
            "binding_id": DSH_BINDING_ID,
            "call_id": call.call_id,
            "call_digest": sc.contract_digest(call).value,
            "actor_id": call.actor_id,
            "role": call.role.value,
            "input_json": call.input_json,
            "output_schema": call.output_schema,
            "instruction": call.instruction,
            "required_capabilities": list(call.required_capabilities),
            "max_output_bytes": call.max_output_bytes,
        }
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def decode_command(self, payload: bytes) -> DeepSeekRoleCommand:
        if type(payload) is not bytes or not payload:
            raise DeepSeekBindingError("encoded DeepSeek command must be non-empty bytes")
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DeepSeekBindingError("invalid DeepSeek command JSON") from error
        keys = {
            "schema", "binding_id", "call_id", "call_digest", "actor_id", "role",
            "input_json", "output_schema", "instruction", "required_capabilities", "max_output_bytes",
        }
        if not isinstance(value, dict) or set(value) != keys:
            raise DeepSeekBindingError("DeepSeek command fields mismatch")
        if value["schema"] != COMMAND_SCHEMA or value["binding_id"] != DSH_BINDING_ID:
            raise DeepSeekBindingError("DeepSeek command schema/binding mismatch")
        capabilities = value["required_capabilities"]
        if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
            raise DeepSeekBindingError("DeepSeek command capabilities are invalid")
        if value["role"] not in {"LOCAL_ARCHITECT", "CODER", "REVIEWER"}:
            raise DeepSeekBindingError("DeepSeek command role is unsupported")
        for name in ("call_id", "call_digest", "actor_id", "input_json", "output_schema", "instruction"):
            if not isinstance(value[name], str) or not value[name]:
                raise DeepSeekBindingError(f"DeepSeek command {name} is invalid")
        maximum = value["max_output_bytes"]
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
            raise DeepSeekBindingError("DeepSeek command output bound is invalid")
        return DeepSeekRoleCommand(
            binding_id=value["binding_id"],
            call_id=value["call_id"],
            call_digest=value["call_digest"],
            actor_id=value["actor_id"],
            role=value["role"],
            input_json=value["input_json"],
            output_schema=value["output_schema"],
            instruction=value["instruction"],
            required_capabilities=tuple(capabilities),
            max_output_bytes=maximum,
        )

    def decode_result(self, result: object, expected):
        import shared_contracts as sc
        from packages.harness_bridge.contracts import ReplyStatus, RoleCall, RoleReply
        from packages.harness_bridge.zone import decode_role_input
        from packages.zone_development import wire
        from packages.zone_development.contracts import (
            BlockerKind,
            ChangeProposal,
            FileEdit,
            Finding,
            LocalPlan,
            OutwardBlocker,
            RepairRecipe,
            ReviewReport,
        )

        if type(expected) is not RoleCall:
            raise DeepSeekBindingError("result binding requires the exact expected RoleCall")
        if type(result) is not DeepSeekRoleResult:
            raise DeepSeekBindingError("DeepSeek Harness returned a foreign result type")
        if (
            result.binding_id != DSH_BINDING_ID
            or result.call_id != expected.call_id
            or result.provider != PROVIDER_ROUTE
            or result.model != MODEL_ROUTE
            or result.sdk_version != DSH_SDK_VERSION
            or result.finish_reason != "completed"
        ):
            raise DeepSeekBindingError("DeepSeek Harness result identity drift")
        try:
            semantic = json.loads(result.final_response)
        except json.JSONDecodeError as error:
            raise DeepSeekBindingError("role response must be one exact JSON object without Markdown") from error
        if not isinstance(semantic, dict):
            raise DeepSeekBindingError("role semantic response must be an object")

        context = decode_role_input(expected.input_json)
        author = context.action.actor
        request_digest = sc.contract_digest(context.request)
        blockers = _blockers(semantic.get("blockers", []), BlockerKind, OutwardBlocker)

        if expected.role.value == "LOCAL_ARCHITECT":
            _exact_semantic_keys(semantic, {"steps", "target_paths", "alternatives", "remedies", "blockers"})
            remedies_raw = _list_of_dicts(semantic["remedies"], "remedies")
            remedies = tuple(
                RepairRecipe(
                    family=_text(item.get("family"), "remedy family"),
                    targets=tuple(_text_list(item.get("targets"), "remedy targets")),
                )
                for item in remedies_raw
            )
            payload = LocalPlan(
                request_digest=request_digest,
                author=author,
                steps=tuple(_text_list(semantic["steps"], "steps")),
                target_paths=tuple(_text_list(semantic["target_paths"], "target_paths")),
                alternatives=tuple(_text_list(semantic["alternatives"], "alternatives", allow_empty=True)),
                remedies=remedies,
                blockers=blockers,
            )
        elif expected.role.value == "CODER":
            _exact_semantic_keys(semantic, {"edits", "blockers"})
            if context.plan is None:
                raise DeepSeekBindingError("Coder result has no exact admitted plan")
            edits_raw = _list_of_dicts(semantic["edits"], "edits")
            edits = tuple(
                FileEdit(
                    path=_text(item.get("path"), "edit path"),
                    content=_optional_text(item.get("content"), "edit content"),
                )
                for item in edits_raw
            )
            payload = ChangeProposal(
                request_digest=request_digest,
                author=author,
                plan_digest=sc.contract_digest(context.plan),
                source=context.source_ref,
                edits=edits,
                blockers=blockers,
            )
        elif expected.role.value == "REVIEWER":
            _exact_semantic_keys(semantic, {"findings", "blockers"})
            if context.plan is None or context.candidate is None:
                raise DeepSeekBindingError("Reviewer result has no exact plan/candidate")
            findings_raw = _list_of_dicts(semantic["findings"], "findings")
            findings = tuple(
                Finding(
                    finding_id=_text(item.get("finding_id"), "finding id"),
                    detail=_text(item.get("detail"), "finding detail"),
                    blocking=_boolean(item.get("blocking"), "finding blocking"),
                )
                for item in findings_raw
            )
            payload = ReviewReport(
                request_digest=request_digest,
                author=author,
                candidate=context.candidate.as_ref(),
                plan_digest=sc.contract_digest(context.plan),
                findings=findings,
                blockers=blockers,
            )
        else:
            raise DeepSeekBindingError("unsupported model-backed ADCP role result")

        payload_json = wire.dumps(payload)
        if len(payload_json.encode("utf-8")) > expected.max_output_bytes:
            raise DeepSeekBindingError("normalized ADCP payload exceeds the issued result bound")
        return RoleReply(
            call_id=expected.call_id,
            call_digest=sc.contract_digest(expected),
            actor_id=expected.actor_id,
            role=expected.role,
            protocol_binding_id=DSH_BINDING_ID,
            status=ReplyStatus.RETURNED,
            payload_json=payload_json,
            execution_id=result.execution_id,
        )


def _role_prompt(command: DeepSeekRoleCommand) -> str:
    schema = {
        "LOCAL_ARCHITECT": (
            '{"steps":["..."],"target_paths":["path"],"alternatives":[], '
            '"remedies":[{"family":"CHANGE_ALGORITHM","targets":["symbol"]}],"blockers":[]}'
        ),
        "CODER": '{"edits":[{"path":"path","content":"complete replacement text"}],"blockers":[]}',
        "REVIEWER": (
            '{"findings":[{"finding_id":"id","detail":"...","blocking":true}],"blockers":[]}'
        ),
    }[command.role]
    return (
        "You are one isolated ADCP development role. Do not call tools and do not mutate files. "
        "Use only the immutable input below. Return exactly one JSON object, with no Markdown, "
        "prose, comments, or code fences.\n\n"
        f"ROLE: {command.role}\n"
        f"ROLE INSTRUCTION:\n{command.instruction}\n\n"
        f"IMMUTABLE ROLE INPUT:\n{command.input_json}\n\n"
        f"REQUIRED SEMANTIC RESPONSE SHAPE:\n{schema}\n"
        "All paths must stay inside the declared write scope. A Coder edit content value is the "
        "complete replacement file content. If the task cannot be completed safely, return an empty "
        "edit/plan/finding set and one blocker instead of inventing authority."
    )


def _exact_semantic_keys(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise DeepSeekBindingError(
            f"role semantic fields mismatch; missing={sorted(expected - set(value))}, extra={sorted(set(value) - expected)}"
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeepSeekBindingError(f"{label} must be non-empty text")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DeepSeekBindingError(f"{label} must be text or null")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise DeepSeekBindingError(f"{label} must be boolean")
    return value


def _text_list(value: object, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise DeepSeekBindingError(f"{label} must be {'a' if allow_empty else 'a non-empty'} list")
    return [_text(item, label) for item in value]


def _list_of_dicts(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise DeepSeekBindingError(f"{label} must be a list of objects")
    return value


def _blockers(value: object, blocker_kind, outward_blocker) -> tuple[object, ...]:
    raw = _list_of_dicts(value, "blockers")
    result = []
    for item in raw:
        if set(item) not in ({"kind", "code", "detail"}, {"kind", "code", "detail", "dependency"}):
            raise DeepSeekBindingError("blocker fields mismatch")
        try:
            kind = blocker_kind(_text(item.get("kind"), "blocker kind"))
        except ValueError as error:
            raise DeepSeekBindingError("unknown blocker kind") from error
        dependency = item.get("dependency")
        result.append(
            outward_blocker(
                kind=kind,
                code=_text(item.get("code"), "blocker code"),
                detail=_text(item.get("detail"), "blocker detail"),
                dependency=_optional_text(dependency, "blocker dependency"),
            )
        )
    return tuple(result)

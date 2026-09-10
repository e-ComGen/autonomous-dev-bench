"""DeepSeek Harness protocol for real repository-sized ADCP role work.

The durable ADCP RoleCall still contains the exact compressed source snapshot.
This adapter materializes that snapshot into an isolated per-role mirror before
invoking the shipping DeepSeek Harness, so the model explores code through normal
filesystem tools instead of receiving the entire repository inline in its prompt.
The canonical candidate worktree is never exposed to a model role.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat

from suites.coding.adcp_dsh_binding import (
    DSH_BINDING_ID,
    DSH_SDK_VERSION,
    MODEL_ROUTE,
    PROVIDER_ROUTE,
    DeepSeekBindingError,
    DeepSeekHarnessProtocol,
    DeepSeekRoleCommand,
    DeepSeekRoleResult,
)


class WorkspaceDeepSeekHarnessProtocol(DeepSeekHarnessProtocol):
    """Pinned DSH transport with a fresh exact source mirror for every role call."""

    def __init__(self, *args, profile: str = "sdk", **kwargs) -> None:
        super().__init__(*args, profile=profile, **kwargs)

    def run_agent(self, command: object) -> DeepSeekRoleResult:
        if type(command) is not DeepSeekRoleCommand:
            raise DeepSeekBindingError("DeepSeek protocol received a foreign command type")
        if command.binding_id != DSH_BINDING_ID:
            raise DeepSeekBindingError("DeepSeek command targets another binding")
        if command.role not in {"LOCAL_ARCHITECT", "CODER", "REVIEWER"}:
            raise DeepSeekBindingError("unsupported model-backed ADCP role")

        try:
            from packages.harness_bridge.zone import decode_role_input
            from packages.zone_development import wire
        except ImportError as error:
            raise DeepSeekBindingError("pinned ADCP runtime is not importable") from error

        context = decode_role_input(command.input_json)
        if context.action.actor.actor_id != command.actor_id or context.action.actor.role.value != command.role:
            raise DeepSeekBindingError("role mirror context does not match command actor")

        factory = self._harness_factory
        if factory is None:
            try:
                from deepseek_harness import DeepSeekHarness
            except ImportError as error:
                raise DeepSeekBindingError("deepseek_harness import failed") from error
            factory = DeepSeekHarness

        actor_key = hashlib.sha256(command.actor_id.encode("utf-8")).hexdigest()[:16]
        call_key = hashlib.sha256(command.call_id.encode("utf-8")).hexdigest()[:16]
        dsh_home = self.state_root / "homes" / actor_key
        cwd = self.state_root / "isolated-role-workspaces" / actor_key / call_key
        dsh_home.mkdir(parents=True, exist_ok=True)
        if cwd.exists():
            shutil.rmtree(cwd)
        cwd.mkdir(parents=True)
        self._materialize_snapshot(context.source, cwd)

        prompt_view = {
            "input_schema": "autobench.adcp-role-workspace-view/1",
            "action": context.action,
            "request": context.request,
            "source_ref": context.source_ref,
            "candidate": context.candidate,
            "plan": context.plan,
            "review": context.review,
            "evaluation": context.evaluation,
            "repair": context.repair,
            "advisories": context.advisories,
            "workspace_note": "Exact immutable source snapshot is materialized in the current working directory.",
        }
        prompt = _workspace_role_prompt(command, wire.dumps(prompt_view))
        max_tokens = max(256, min(16384, command.max_output_bytes // 4))
        session_id = "adcp-" + hashlib.sha256(command.call_id.encode("utf-8")).hexdigest()[:24]

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
            env={
                "DSH_PERMISSION_MODE": "danger-full-access",
                "DSH_TELEMETRY_DISABLED": "1",
                "DSH_SESSION_STORE": "jsonl",
            },
        )
        self.model_calls += 1
        if hasattr(harness, "__enter__"):
            with harness as active:
                result = active.run(prompt, session_id=session_id)
        else:
            try:
                result = harness.run(prompt, session_id=session_id)
            finally:
                close = getattr(harness, "close", None)
                if callable(close):
                    close()

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
            provider=PROVIDER_ROUTE,
            model=MODEL_ROUTE,
            finish_reason=finish_reason,
            final_response=final_response,
            sdk_version=DSH_SDK_VERSION,
        )

    @staticmethod
    def _materialize_snapshot(snapshot, root: Path) -> None:
        modes = dict(snapshot.modes)
        for relative, _ in snapshot.files:
            target = root.joinpath(*relative.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            mode = modes.get(relative, "100644")
            payload = snapshot.blob_bytes(relative)
            if mode == "120000":
                try:
                    link_target = payload.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise DeepSeekBindingError("Git symlink target is not UTF-8") from error
                os.symlink(link_target, target)
                continue
            target.write_bytes(payload)
            target.chmod(
                stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
                | (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH if mode == "100755" else 0)
            )


def _workspace_role_prompt(command: DeepSeekRoleCommand, prompt_view: str) -> str:
    schema = {
        "LOCAL_ARCHITECT": (
            '{"steps":["..."],"target_paths":["path"],"alternatives":[], '
            '"remedies":[{"family":"CHANGE_ALGORITHM","targets":["symbol"]}],"blockers":[]}'
        ),
        "CODER": '{"edits":[{"path":"path","content":"complete replacement text"}],"blockers":[]}',
        "REVIEWER": '{"findings":[{"finding_id":"id","detail":"...","blocking":true}],"blockers":[]}',
    }[command.role]
    return (
        "You are one isolated ADCP development role. The current directory is an exact source mirror, "
        "not the canonical candidate worktree. You MAY use filesystem/search/read-only exploration tools "
        "to understand the repository. Do not treat edits in this mirror as output; only the final JSON is "
        "authoritative. Return exactly one JSON object, with no Markdown or prose.\n\n"
        f"ROLE: {command.role}\n"
        f"ROLE INSTRUCTION:\n{command.instruction}\n\n"
        f"IMMUTABLE ROLE METADATA:\n{prompt_view}\n\n"
        f"REQUIRED SEMANTIC RESPONSE SHAPE:\n{schema}\n"
        "All proposed paths must stay inside the declared write scope. Coder content is complete UTF-8 "
        "replacement text. If safe completion is impossible, return a blocker instead of inventing authority."
    )

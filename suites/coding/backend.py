"""Execution backend selection and explicit local-code consent, not a new control plane."""
import os
import sys


def backend_name(settings):
    selected = settings.execution_backend
    return ("native" if os.name == "nt" else "docker") if selected == "auto" else selected


def authorize_local(allowed=False):
    if allowed:
        return
    print("Native mode: downloaded build scripts, tests and agent commands run as your Windows/user account.")
    print("A venv does not protect your documents or keys. There is no filesystem/network sandbox or CPU/RAM cap.")
    if not sys.stdin.isatty():
        raise ValueError("Native execution needs explicit --allow-local-execution; Docker was NOT required")
    if input("Type LOCAL to allow local execution for this campaign: ").strip() != "LOCAL":
        raise ValueError("LOCAL_EXECUTION_NOT_AUTHORIZED")


def create_runtime(root, scratch, settings, *, allow_local=False):
    if backend_name(settings) == "native":
        authorize_local(allow_local)
        from .backends.native import NativeRuntime
        return NativeRuntime(root, scratch, settings)
    from .docker_runtime import DockerRuntime
    return DockerRuntime(root, scratch, settings)


def validate_environment(runtime, identity):
    if getattr(runtime, "backend", "docker") == "native":
        runtime.validate_environment(identity)
        return
    if not identity.startswith("sha256:"):
        raise ValueError("REPLAY_BACKEND_MISMATCH")
    available = runtime.command(("image", "inspect", identity, "--format", "{{.Id}}"), required=False)
    if not available.succeeded or available.stdout.strip() != identity:
        raise ValueError("REPLAY_IMAGE_MISSING; saved tasks were not silently rebuilt")

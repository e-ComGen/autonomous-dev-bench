"""The same real DSH driver works in native Windows processes and Docker."""
from pathlib import Path
import json
import os
import subprocess
import sys


def main():
    scratch = Path(os.environ.get("AUTOBENCH_SCRATCH", "/tmp"))
    home, cache = scratch / "home", scratch / "cache"
    home.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.update(HOME=str(home), USERPROFILE=str(home), XDG_CACHE_HOME=str(cache))
    from deepseek_harness import DeepSeekHarness
    inputs = Path(os.environ.get("AUTOBENCH_INPUT", "/input"))
    outputs = Path(os.environ.get("AUTOBENCH_RESULTS", "/results"))
    workspace = Path(os.environ.get("AUTOBENCH_WORKSPACE", "/workspace"))
    request = json.loads((inputs / "request.json").read_text(encoding="utf-8"))
    if not (workspace / ".git").exists():
        for args in (("init", "-b", "benchmark"), ("config", "user.name", "Benchmark"),
                     ("config", "user.email", "benchmark@example.invalid"), ("config", "core.autocrlf", "false"),
                     ("add", "."), ("commit", "-qm", "Public task baseline")):
            subprocess.run(["git", "-C", str(workspace), *args], check=True, capture_output=True, timeout=30)
    with DeepSeekHarness(cwd=str(workspace), dsh_home=str(scratch / "dsh-home"), profile="sdk",
                         provider="deepseek-official", model=request["model"],
                         max_tokens=request["max_tokens"], base_url=request["endpoint"],
                         api_key="run-scoped-relay", request_timeout_seconds=request["timeout"],
                         initialize_timeout_seconds=60) as harness:
        if request.get("boot_only"):
            result = {"status": "BOOTED", "model_called": False}
        else:
            prompt = request["prompt"]
            if os.name == "nt":
                prompt += "\nExecution environment: native Windows. The repository working directory is " + str(workspace)
                prompt += ". Use the available Windows shell and the environment's python for tools; do not require WSL."
            returned = harness.run(prompt, session_id=request["session_id"])
            value = returned.final_response
            if len(value.encode("utf-8")) > 131072:
                raise ValueError("Native final response exceeded bound")
            result = {"status": "RETURNED", "text": value, "finish_reason": returned.finish_reason,
                      "event_count": len(returned.events), "session_id": returned.session_id}
    (outputs / "native.json").write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()

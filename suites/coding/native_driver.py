"""Actual native SDK invocation. Imported only inside the isolated agent container."""
from pathlib import Path
import json
import os
import subprocess
import sys


def main():
    # Bundled native modules must unpack into writable scratch, not the read-only root.
    Path("/tmp/home").mkdir(exist_ok=True)
    Path("/tmp/cache").mkdir(exist_ok=True)
    os.environ.update(HOME="/tmp/home", XDG_CACHE_HOME="/tmp/cache")
    from deepseek_harness import DeepSeekHarness
    request = json.loads(Path("/input/request.json").read_text())
    workspace = Path("/workspace")
    if not (workspace / ".git").exists():
        for args in (("init", "-b", "benchmark"), ("config", "user.name", "Benchmark"),
                     ("config", "user.email", "benchmark@example.invalid"), ("config", "core.autocrlf", "false"),
                     ("add", "."), ("commit", "-qm", "Public task baseline")):
            subprocess.run(["git", "-C", str(workspace), *args], check=True, capture_output=True)
    with DeepSeekHarness(cwd=str(workspace), dsh_home="/tmp/dsh-home", profile="sdk",
                         provider="deepseek-official", model=request["model"],
                         max_tokens=request["max_tokens"], base_url=request["endpoint"],
                         api_key="run-scoped-relay", request_timeout_seconds=request["timeout"],
                         initialize_timeout_seconds=60) as harness:
        if request.get("boot_only"):
            result = {"status": "BOOTED", "model_called": False}
        else:
            returned = harness.run(request["prompt"], session_id=request["session_id"])
            value = returned.final_response
            if len(value.encode("utf-8")) > 131072:
                raise ValueError("Native final response exceeded bound")
            result = {"status": "RETURNED", "text": value, "finish_reason": returned.finish_reason,
                      "event_count": len(returned.events), "session_id": returned.session_id}
    Path("/results/native.json").write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()

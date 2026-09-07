"""Real DSH SDK invocation. This is the only Python driver inside agent images."""
from pathlib import Path
import json
import sys
import subprocess


def main():
    from deepseek_harness import DeepSeekHarness
    request = json.loads(Path("/input/request.json").read_text())
    workspace = Path("/workspace")
    if not (workspace / ".git").exists():
        for args in (("init", "-b", "benchmark"), ("config", "user.name", "Benchmark"),
                     ("config", "user.email", "benchmark@example.invalid"), ("add", "."),
                     ("commit", "-qm", "Public task baseline")):
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
            text = returned.final_response
            if len(text.encode("utf-8")) > 131072:
                raise ValueError("Native final response exceeded bound")
            result = {"status": "RETURNED", "text": text, "finish_reason": returned.finish_reason,
                      "event_count": len(returned.events), "session_id": returned.session_id}
    Path("/results/native.json").write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()

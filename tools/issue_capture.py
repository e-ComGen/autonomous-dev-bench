"""Bounded acquisition worker. The parent uses the existing ProcessRunner for its deadline."""
from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]


def main():
    from corpus.qualification.capture import acquire_task
    from corpus.qualification.policy import policy_from_mapping
    from tools.launcher_env import clean_environment
    from benchmark_core.cas import FileSystemCAS
    from benchmark_core.identity import canonical_json
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    environment = clean_environment(ROOT)
    os.environ.clear()
    os.environ.update(environment)
    try:
        task = acquire_task(data["candidate"], ROOT, policy_from_mapping(data["policy"]))
        ref = FileSystemCAS(ROOT / ".bench/cas").put_text(canonical_json(task))
        result = {"status": "CAPTURED", "task_ref": ref}
    except (ValueError, OSError, RuntimeError) as error:
        result = {"status": "REJECTED", "reason": str(error)[:1000]}
    Path(sys.argv[2]).write_text(json.dumps(result), encoding="utf-8")
    return 0 if result["status"] == "CAPTURED" else 2


if __name__ == "__main__":
    raise SystemExit(main())

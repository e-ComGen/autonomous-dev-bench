"""Export existing discovery reasons from CAS without credentials, network or model calls."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]
from benchmark_core.cas import FileSystemCAS
from corpus.discovery.diagnostics import summarize, reason_code


def export(root):
    root = Path(root).resolve()
    runs = root / ".bench/runs"
    paths = [path for path in runs.glob("*/discovery.json") if path.is_file() and not path.is_symlink()]
    if not paths:
        raise ValueError("NO_SAVED_DISCOVERY_REPORT")
    source = max(paths, key=lambda path: path.stat().st_mtime_ns)
    if not source.resolve().is_relative_to(runs.resolve()) or source.stat().st_size > 1048576:
        raise ValueError("INVALID_DISCOVERY_REPORT")
    original = json.loads(source.read_text(encoding="utf-8-sig"))
    details = json.loads(FileSystemCAS(root / ".bench/cas").get_text(original["details_ref"]))
    result = summarize(details, requested=original.get("requested_tasks"), qualified=original.get("qualified", 0),
                       stop_reason=original.get("stop_reason", "UNKNOWN_IN_OLD_REPORT"),
                       counts=original.get("counts"), searches=original.get("searches"))
    result["events"] = [{"stage": stage, "repository": str(row.get("repository", ""))[:160],
                          "pull": row.get("pull") if type(row.get("pull")) is int else None,
                          "reason": reason_code(row.get("reason", "UNKNOWN_ERROR"))}
                         for stage, name in (("metadata", "intake_rejections"), ("execution", "qualification_rejections"))
                         for row in details.get(name, [])]
    destination = source.parent / "discovery_details.json"
    if destination.is_symlink():
        raise ValueError("LINKED_DIAGNOSTIC_OUTPUT")
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return destination


def main():
    try:
        destination = export(ROOT)
        print("Saved: " + str(destination))
        print("No model or network was used. No issue bodies, API keys or process logs were exported.")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print("EXPORT_FAILED: " + type(error).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

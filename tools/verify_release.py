"""Exercise the packaged checkout in a fresh path, not the developer installation."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_release() -> None:
    stage = ROOT / "artifacts/autobenchmark"
    metadata = json.loads((stage / ".bench/release.json").read_text(encoding="utf-8"))
    for relative, expected in metadata["files"].items():
        if digest(stage / relative) != expected:
            raise ValueError(f"Stage integrity failure: {relative}")
    evidence = ROOT / "artifacts/release-evidence"
    evidence.mkdir(exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="bench release with spaces ") as temporary:
        checkout = Path(temporary) / "autobenchmark"
        shutil.copytree(stage, checkout)
        assert not (checkout / ".git").exists()
        for mode in ("test", "projects", "plan"):
            if os.name == "nt":
                argv = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "START.cmd", mode, "--offline"]
            else:
                argv = [sys.executable, "-I", "tools/launch.py", mode, "--offline"]
            executed = subprocess.run(argv, cwd=checkout, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=1200, shell=False)
            (evidence / (mode + ".log")).write_text(executed.stdout + "\n" + executed.stderr, encoding="utf-8")
            print(executed.stdout)
            if executed.returncode:
                print(executed.stderr, file=sys.stderr)
                bootstrap = checkout / ".bench/bootstrap.log"
                if bootstrap.is_file():
                    print(bootstrap.read_text(encoding="utf-8", errors="replace")[-6000:], file=sys.stderr)
                raise RuntimeError(f"Packaged {mode} exited {executed.returncode}")
            pointer = json.loads((checkout / ".bench/latest.json").read_text(encoding="utf-8"))
            summary = checkout / pointer["report"]
            value = json.loads(summary.read_text(encoding="utf-8"))
            shutil.copyfile(summary, evidence / (mode + ".json"))
            for junit in summary.parent.glob("*.xml"):
                shutil.copyfile(junit, evidence / junit.name)
            expected = {"test": "CHECKED", "projects": "PREPARED", "plan": "PLAN_ONLY"}[mode]
            if value["status"] != expected:
                raise ValueError(f"Incorrect packaged {mode} status: {value['status']}")
            results.append({"mode": mode, "status": value["status"], "returncode": executed.returncode})
        for relative, expected in metadata["files"].items():
            if digest(checkout / relative) != expected:
                raise ValueError(f"Launcher changed shipped input: {relative}")
    report = {"source_commit": metadata["source_commit"], "platform": sys.platform,
              "python": sys.version, "path_with_spaces": True, "git_checkout_required": False,
              "offline_flag_used": True, "os_network_confinement_asserted": False,
              "live_model_called": False, "results": results}
    (evidence / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run_release()

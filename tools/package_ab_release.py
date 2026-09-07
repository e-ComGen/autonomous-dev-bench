"""Private release assembly over the existing public packager and source owners."""
from pathlib import Path
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.package_release import assemble, sha256
from suites.coding.adcp_loading import load_adcp


def main():
    identity = load_adcp(ROOT)
    stage = assemble()
    shutil.copytree(ROOT / ".bench/adcp", stage / ".bench/adcp", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    metadata_path = stage / ".bench/release.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["adcp"] = identity
    metadata["default_command"] = "ab"
    metadata["files"] = {path.relative_to(stage).as_posix(): sha256(path)
                         for path in sorted(stage.rglob("*")) if path.is_file() and path != metadata_path}
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"stage": str(stage), "default_command": "ab", "adcp": identity}))


if __name__ == "__main__":
    main()

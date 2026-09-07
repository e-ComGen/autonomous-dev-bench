"""Source-checkout entry point; works without installation or a .git folder."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]

if __name__ == "__main__":
    from tools.launcher_env import clean_environment
    from cli.oneclick.main import main

    environment = clean_environment(ROOT, github="discover" in sys.argv[1:2])
    os.environ.clear()
    os.environ.update(environment)
    raise SystemExit(main(ROOT))

"""Source-checkout entry point; works without installation or a .git folder."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]

if __name__ == "__main__":
    from tools.launch import command_name, host_environment
    from cli.oneclick.main import main

    # Reuse the command-scoped host policy; worker environments remain separate.
    command = command_name(sys.argv[1:])
    environment = host_environment(ROOT, command)
    os.environ.clear()
    os.environ.update(environment)
    raise SystemExit(main(ROOT))

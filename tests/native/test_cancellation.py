from pathlib import Path
import sys
import threading
import time
from benchmark_core.execution import ProcessRunner, CommandSpec
from suites.coding.backends.environment import private_environment


def test_native_cancellation_reaps_only_owned_command(tmp_path):
    runner = ProcessRunner()
    ready = tmp_path / "ready.txt"
    script = "import pathlib,time;pathlib.Path(" + repr(str(ready)) + ").write_text('ready');time.sleep(30)"
    observations = []
    def execute():
        observations.append(runner.run(CommandSpec((sys.executable, "-I", "-c", script), 40,
            environment=private_environment(tmp_path / "home"), inherit_environment=False)))
    worker = threading.Thread(target=execute, daemon=True)
    worker.start()
    deadline = time.monotonic() + 5
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready.is_file()
    runner.cancel_running()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert len(observations) == 1 and not observations[0].succeeded
    assert not runner._active

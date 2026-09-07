"""Native venv provisioning through the existing process owner; no global installs."""
from pathlib import Path
import json
import time
import sys
from benchmark_core.execution import CommandSpec, ProcessRunner
from .environment import private_environment, python_path, verify_wheels, wheel_manifest


class Provisioner:
    def __init__(self, runner=None):
        self.runner = runner or ProcessRunner()

    def execute(self, argv, directory, deadline, *, environment=None, label="install"):
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("NATIVE_PREPARATION_DEADLINE")
        result = self.runner.run(CommandSpec(tuple(map(str, argv)), seconds, str(directory),
            environment or private_environment(directory / ".process"), inherit_environment=False))
        log = directory / (label + ".log")
        log.write_text(result.stdout[-32768:] + result.stderr[-32768:], encoding="utf-8")
        if not result.succeeded:
            raise RuntimeError(f"NATIVE_{label.upper()}_FAILED: {log}; " + result.stderr[-800:])
        return result

    def venv(self, directory, deadline):
        directory = Path(directory).resolve()
        if directory.exists():
            raise FileExistsError("A native execution venv must be fresh")
        self.execute((sys.executable, "-I", "-m", "venv", directory), directory.parent, deadline, label="venv")
        return python_path(directory)

    def pip(self, python, args, directory, deadline, *, environment=None):
        return self.execute((python, "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", *args),
                            directory, deadline, environment=environment)

    def install_wheels(self, wheelhouse, manifest, environment, deadline):
        verify_wheels(wheelhouse, manifest)
        python = self.venv(environment, deadline)
        args = ("install", "--no-index", "--no-deps", *[str(Path(wheelhouse) / name) for name in sorted(manifest)])
        self.pip(python, args, Path(environment).parent, deadline)
        return python

    def download(self, requirements, wheelhouse, deadline, python=sys.executable):
        wheelhouse = Path(wheelhouse).resolve()
        wheelhouse.mkdir(parents=True, exist_ok=True)
        self.pip(python, ("download", "--only-binary=:all:", "--no-deps", "--dest", wheelhouse,
                         "-r", requirements), wheelhouse.parent, deadline)
        return wheel_manifest(wheelhouse)

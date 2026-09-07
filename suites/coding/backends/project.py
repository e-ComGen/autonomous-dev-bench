"""Derive the existing pre-fix recipe and build native dependency wheels, never a fix image."""
from pathlib import Path
import json
import tempfile
import time
from benchmark_core.identity import Sha256Digest
from corpus.qualification.files import materialize
from .environment import private_environment, wheel_manifest


def build_native_project(runtime, task, policy, deadline):
    from corpus.qualification.recipes import infer_recipe
    recipe = infer_recipe(task["base_files"])
    deadline = min(deadline, time.monotonic() + policy.build_seconds)
    environments = runtime.environments
    directory = Path(tempfile.mkdtemp(prefix="project-", dir=environments.root))
    source = directory / "source"
    materialize(source, task["base_files"])
    provision = environments.provision
    python = provision.venv(directory / "build-env", deadline)
    environment = private_environment(directory / "build-home")
    environment.update(recipe["environment"])
    provision.pip(python, ("install", "--only-binary=:all:", "pytest==8.4.2", "setuptools==80.9.0", "wheel==0.45.1"),
                  source, deadline, environment=environment)
    for requirements in recipe["requirements"]:
        provision.pip(python, ("install", "--only-binary=:all:", "-r", requirements), source, deadline, environment=environment)
    provision.pip(python, ("install", "--only-binary=:all:", "-e", recipe["install"]), source, deadline, environment=environment)
    # Resolve dependencies once. Local base source is built separately; no reference fix enters these assets.
    packages = provision.pip(python, ("list", "--exclude-editable", "--format=json"), source, deadline,
                             environment=environment)
    selected = json.loads(packages.stdout)
    lock = directory / "dependencies.txt"
    lock.write_text(''.join(f"{item['name']}=={item['version']}\n" for item in sorted(selected, key=lambda x: x['name'])),
                    encoding="utf-8")
    provision.download(lock, directory / "wheels", deadline, python)
    provision.pip(python, ("wheel", "--no-deps", "--wheel-dir", directory / "wheels", "."),
                  source, deadline, environment=environment)
    wheels = wheel_manifest(directory / "wheels")
    if not wheels:
        raise ValueError("NATIVE_PROJECT_WHEELS_MISSING")
    identity = environments.store("project", directory, wheels, {"recipe": recipe,
        "base_source_digest": task["base_source_digest"], "sdk": environments.sdk_id})
    return identity, recipe

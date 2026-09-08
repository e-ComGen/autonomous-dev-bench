"""Build exact pre-fix dependency wheels; sdists are allowed, never reference fixes."""
from pathlib import Path
import json
import tempfile
import time
from corpus.qualification.files import materialize
from .environment import private_environment, wheel_manifest
from .platform_dependencies import compatibility_dependencies, POLICY_VERSION


def build_native_project(runtime, task, policy, deadline):
    from corpus.qualification.recipes import infer_recipe
    recipe = infer_recipe(task["base_files"])
    dependencies = compatibility_dependencies(task["base_files"])
    recipe = {**recipe, "native_build_policy": POLICY_VERSION,
              "platform_dependencies": list(dependencies)}
    deadline = min(deadline, time.monotonic() + policy.build_seconds)
    environments = runtime.environments
    directory = Path(tempfile.mkdtemp(prefix="project-", dir=environments.root))
    source = directory / "source"
    materialize(source, task["base_files"])
    provision = environments.provision
    python = provision.venv(directory / "build-env", deadline)
    environment = private_environment(directory / "build-home")
    environment.update(recipe["environment"])
    print("Build: native dependency resolution; source distributions allowed", flush=True)
    provision.pip(python, ("install", "--only-binary=:all:", "pytest==8.4.2", "setuptools==80.9.0", "wheel==0.45.1"),
                  source, deadline, environment=environment)
    if dependencies:
        print("Build: platform dependencies: " + ", ".join(dependencies), flush=True)
        provision.pip(python, ("install", "--only-binary=:all:", *dependencies), source, deadline, environment=environment)
    for requirements in recipe["requirements"]:
        provision.pip(python, ("install", "--prefer-binary", "-r", requirements), source, deadline, environment=environment)
    provision.pip(python, ("install", "--prefer-binary", "-e", recipe["install"]), source, deadline, environment=environment)
    provision.pip(python, ("check",), source, deadline, environment=environment)
    packages = provision.pip(python, ("list", "--exclude-editable", "--format=json"), source, deadline,
                             environment=environment)
    selected = json.loads(packages.stdout)
    lock = directory / "dependencies.txt"
    lock.write_text(''.join(f"{item['name']}=={item['version']}\n" for item in sorted(selected, key=lambda x: x['name'])),
                    encoding="utf-8")
    # Build, rather than binary-only download, locked dependencies such as atomicwrites 1.4.1.
    print("Build: freeze exact versions into a verified wheelhouse", flush=True)
    provision.pip(python, ("wheel", "--prefer-binary", "--no-deps", "--wheel-dir", directory / "wheels", "-r", lock),
                  source, deadline, environment=environment)
    provision.pip(python, ("wheel", "--no-deps", "--wheel-dir", directory / "wheels", "."),
                  source, deadline, environment=environment)
    wheels = wheel_manifest(directory / "wheels")
    if not wheels:
        raise ValueError("NATIVE_PROJECT_WHEELS_MISSING")
    identity = environments.store("project", directory, wheels, {"recipe": recipe,
        "base_source_digest": task["base_source_digest"], "sdk": environments.sdk_id})
    return identity, recipe

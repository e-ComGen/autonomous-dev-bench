"""Build exact pre-fix dependency wheels, including declared test groups and local plugins."""
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
    print("Build: recipe-v3; declared test dependencies and local projects", flush=True)
    provision.pip(python, ("install", "--only-binary=:all:", "pytest==8.4.2", "setuptools==80.9.0", "wheel==0.45.1"),
                  source, deadline, environment=environment)
    if dependencies:
        print("Build: platform dependencies: " + ", ".join(dependencies), flush=True)
        provision.pip(python, ("install", "--only-binary=:all:", *dependencies), source, deadline, environment=environment)
    arguments = list(recipe["test_dependencies"])
    for requirements in recipe["requirements"]:
        arguments.extend(("-r", requirements))
    # Resolve declarations together. Explicit repository pytest pins are not replaced by our fallback.
    provision.pip(python, ("install", "--prefer-binary", "-e", recipe["install"], *arguments),
                  source, deadline, environment=environment)
    probe = Path(__file__).resolve().parents[3] / "corpus/qualification/installed_extras.py"
    metadata = provision.execute((python, "-I", probe, source), source, deadline,
                                 environment=environment, label="test-extra-metadata")
    extra = json.loads(metadata.stdout)
    if extra is not None and extra not in {"test", "tests", "testing", "dev"}:
        raise ValueError("INVALID_INSTALLED_TEST_EXTRA")
    install = ".[" + extra + "]" if extra and recipe["install"] == "." else recipe["install"]
    local = [part for path in recipe["local_projects"] for part in ("-e", "./" + path)]
    if install != recipe["install"] or local:
        provision.pip(python, ("install", "--prefer-binary", "-e", install, *arguments, *local),
                      source, deadline, environment=environment)
    recipe = {**recipe, "install": install, "resolved_test_extra": extra}
    provision.pip(python, ("check",), source, deadline, environment=environment)
    packages = provision.pip(python, ("list", "--exclude-editable", "--format=json"), source, deadline,
                             environment=environment)
    selected = json.loads(packages.stdout)
    lock = directory / "dependencies.txt"
    lock.write_text(''.join(f"{item['name']}=={item['version']}\n" for item in sorted(selected, key=lambda x: x['name'])),
                    encoding="utf-8")
    print("Build: freeze exact versions and local project wheels for both arms", flush=True)
    provision.pip(python, ("wheel", "--prefer-binary", "--no-deps", "--wheel-dir", directory / "wheels", "-r", lock),
                  source, deadline, environment=environment)
    # Editable local packages were excluded above; build their exact captured bytes, never their PyPI names.
    for path in (".", *("./" + name for name in recipe["local_projects"])):
        provision.pip(python, ("wheel", "--no-deps", "--wheel-dir", directory / "wheels", path),
                      source, deadline, environment=environment)
    wheels = wheel_manifest(directory / "wheels")
    if not wheels:
        raise ValueError("NATIVE_PROJECT_WHEELS_MISSING")
    identity = environments.store("project", directory, wheels, {"recipe": recipe,
        "base_source_digest": task["base_source_digest"], "sdk": environments.sdk_id})
    return identity, recipe

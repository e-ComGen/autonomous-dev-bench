"""Bounded Python/pytest recipes derived only from the pre-fix repository."""
from pathlib import PurePosixPath
import configparser
import json
import tomllib
from .files import text, is_test


def infer_recipe(files):
    if not any(name in files for name in ("pyproject.toml", "setup.py", "setup.cfg")):
        raise ValueError("PYTHON_PACKAGE_METADATA_MISSING")
    configuration = tomllib.loads(text(files["pyproject.toml"])) if "pyproject.toml" in files else {}
    extras = configuration.get("project", {}).get("optional-dependencies", {})
    if not extras and "setup.cfg" in files:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text(files["setup.cfg"]))
        if parser.has_section("options.extras_require"):
            extras = dict(parser["options.extras_require"])
    chosen = next((name for name in ("test", "tests", "testing", "dev") if name in extras), None)
    install = ".[" + chosen + "]" if chosen else "."
    requirements = tuple(name for name in ("requirements-test.txt", "requirements-tests.txt", "requirements/testing.txt",
                                           "requirements/tests.txt", "requirements/test.txt", "requirements-dev.txt") if name in files)
    test_files = sorted(path for path in files if is_test(path) and (PurePosixPath(path).name.startswith("test_")
                                    or PurePosixPath(path).name.endswith("_test.py")))
    if not test_files:
        raise ValueError("PYTEST_TEST_FILES_MISSING")
    return {"version": "python-pytest-recipe/2", "install": install, "requirements": list(requirements[:2]),
            "public_candidates": test_files, "environment": {"SETUPTOOLS_SCM_PRETEND_VERSION": "0.0.0"}}


def build_project_image(docker, task, policy, deadline):
    if getattr(docker, "backend", "docker") == "native":
        return docker.build_project_environment(task, policy, deadline)
    from .files import materialize
    from benchmark_core.identity import Sha256Digest
    import time
    base_image = docker.image
    recipe = infer_recipe(task["base_files"])
    identity = str(Sha256Digest.of({"base_image": base_image, "tree": task["base_source_digest"], "recipe": recipe}))
    tag = "autobenchmark-project:" + identity.removeprefix("sha256:")[:24]
    inspected = docker.command(("image", "inspect", tag, "--format", "{{.Id}} {{index .Config.Labels \"autobenchmark.project\"}}"), required=False)
    if inspected.succeeded:
        image, label = inspected.stdout.strip().split()
        if label != identity:
            raise ValueError("PROJECT_IMAGE_INPUT_CONFLICT")
        return image, recipe
    base_tag = "autobenchmark-base:" + base_image.removeprefix("sha256:")[:24]
    docker.command(("image", "tag", base_image, base_tag))
    resolved = docker.command(("image", "inspect", base_tag, "--format", "{{.Id}}"))
    if resolved.stdout.strip() != base_image:
        raise ValueError("BASE_IMAGE_ALIAS_CONFLICT")
    directory = docker.scratch / ("build-" + identity[-12:])
    directory.mkdir()
    materialize(directory / "source", task["base_files"])
    installer = '''import json, subprocess\nfrom pathlib import Path\nconfig = json.loads(Path('/recipe.json').read_text())\npython = '/opt/project/bin/python'\nsubprocess.run([python, '-m', 'pip', 'install', 'pytest==8.4.2', 'setuptools', 'wheel'], check=True)\nfor path in config['requirements']:\n    subprocess.run([python, '-m', 'pip', 'install', '-r', path], check=True)\nsubprocess.run([python, '-m', 'pip', 'install', '-e', config['install']], check=True)\n'''
    (directory / "install.py").write_text(installer, encoding="utf-8")
    (directory / "recipe.json").write_text(json.dumps(recipe), encoding="utf-8")
    (directory / "Dockerfile").write_text(
        f"FROM {base_tag}\nUSER root\nRUN /usr/local/bin/python -m venv /opt/project\n"
        "COPY source/ /workspace/\nCOPY recipe.json /recipe.json\nCOPY install.py /install.py\n"
        "WORKDIR /workspace\nENV SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0\n"
        "RUN /usr/local/bin/python /install.py && /opt/project/bin/python -m pip freeze --all > /opt/project-freeze.txt\n"
        "RUN rm -rf /workspace /recipe.json /install.py && mkdir /workspace\n"
        "ENV PATH=/opt/project/bin:$PATH PYTHONPATH=/workspace/src:/workspace\n"
        "ENTRYPOINT [\"/usr/local/bin/python\"]\n", encoding="utf-8")
    seconds = min(policy.build_seconds, deadline - time.monotonic())
    if seconds <= 0:
        raise TimeoutError("PREPARATION_BUDGET_EXHAUSTED")
    result = docker.command(("build", "--label", "autobenchmark.project=" + identity, "-t", tag, directory), seconds, required=False)
    (directory / "process.log").write_text(result.stdout[-32768:] + result.stderr[-32768:], encoding="utf-8")
    if not result.succeeded:
        raise RuntimeError("PROJECT_BUILD_FAILED: " + result.stderr[-1800:])
    image = docker.command(("image", "inspect", tag, "--format", "{{.Id}}"))
    return image.stdout.strip(), recipe

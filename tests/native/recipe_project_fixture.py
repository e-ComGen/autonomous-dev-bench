"""Small real build fixture, not a production task or replacement for historical qualification."""
from pathlib import Path


def write_project(root):
    files = {
        "pyproject.toml": '''[build-system]
requires=["setuptools>=68", "wheel"]
build-backend="setuptools.build_meta"
[dependency-groups]
dev=["pytest==8.4.2", "pytest-asyncio>=1.0,<2", "GitPython>=3.1.45,<4"]
[tool.pytest.ini_options]
asyncio_mode="auto"
''',
        "setup.py": '''from setuptools import setup
setup(name="autobench-recipe-probe", version="0.1.0", py_modules=["recipe_root"],
      package_dir={"": "src"}, extras_require=dict(testing=["attrs>=23"]))
''',
        "src/recipe_root.py": "value=1\n",
        "tox.ini": '''[testenv]
commands =
    {py,winpy}{311,312,313,314,}: python -m pip install "{toxinidir}/plugins/example"
''',
        "plugins/example/pyproject.toml": '''[build-system]
requires=["setuptools>=68", "wheel"]
build-backend="setuptools.build_meta"
[project]
name="autobench-recipe-plugin"
version="0.1.0"
[project.entry-points."autobench.recipe"]
example="recipe_plugin:answer"
[tool.setuptools]
py-modules=["recipe_plugin"]
package-dir={""="src"}
''',
        "plugins/example/src/recipe_plugin.py": "def answer():\n    return 7\n",
        "tests/test_image.png": "protected-fixture-bytes\n",
        "tests/test_recipe.py": '''import asyncio, getpass, os
from pathlib import Path
from importlib.metadata import entry_points
import pytest

@pytest.mark.asyncio
async def test_async_execution():
    await asyncio.sleep(0)
    assert True

def test_gitpython_identity(tmp_path):
    from git import Repo
    repo=Repo.init(tmp_path)
    (tmp_path/'value.txt').write_text('value')
    repo.index.add(['value.txt'])
    commit=repo.index.commit('fixture commit')
    assert commit.author.name == 'autobenchmark'
    assert getpass.getuser() == 'autobenchmark'

def test_dynamic_extra():
    import attrs
    assert callable(attrs.define)

def test_local_plugin_uses_current_source():
    import recipe_plugin
    plugin=next(iter(entry_points(group='autobench.recipe')))
    assert plugin.load()() == 7
    assert Path(recipe_plugin.__file__).resolve().is_relative_to(Path.cwd().resolve())

def test_asset_and_no_host_credentials():
    assert Path('tests/test_image.png').read_text() == 'protected-fixture-bytes\\n'
    assert not any(name in os.environ for name in ('GITHUB_TOKEN','GH_TOKEN','DEEPSEEK_API_KEY'))
''',
    }
    for name, content in files.items():
        path = Path(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return files

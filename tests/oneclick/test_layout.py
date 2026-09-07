from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[2]


def test_new_modules_are_small_and_have_no_placeholder_executors():
    paths = list((ROOT / "cli/oneclick").glob("*.py")) + list((ROOT / "corpus/discovery").glob("*.py"))
    paths += [ROOT / "tools" / name for name in ("launch.py", "bench.py", "launcher_env.py", "launcher_lock.py")]
    for path in paths:
        source = path.read_text()
        assert len(source.splitlines()) <= 220, path
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id != "NotImplementedError", path
            if isinstance(node, ast.Import):
                assert not any(item.name.split(".")[0] in {"openai", "anthropic", "deepseek_harness"} for item in node.names)


def test_generated_context_is_excluded_from_search():
    ignore = (ROOT / ".ignore").read_text()
    for value in (".bench/", "vendor/", "reports/", "benchmark-info.md"):
        assert value in ignore
    assert len((ROOT / "AGENTS.md").read_text().splitlines()) <= 50

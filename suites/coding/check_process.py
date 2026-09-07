"""Trusted evaluator entrypoint. Mounted only in verification containers, never agents."""
from pathlib import Path
import copy
import importlib
import json
import sys


def normalized(value):
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, (tuple, list)):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError("Unsupported probe result type")


def observe(function, case):
    arguments = copy.deepcopy(case.get("args", []))
    mode = case.get("mode", "call")
    try:
        if mode == "signature":
            namespace = {}
            signature = case["signature"]
            kind = case["kind"]
            if kind == "function":
                exec(f"def target({signature}): pass", namespace)
                argument = namespace["target"]
            else:
                method = "__init__" if kind == "class" else "__call__" if kind == "callable" else "method"
                parameters = "self" + (", " + signature if signature else "")
                exec(f"class Target:\n    def {method}({parameters}): pass", namespace)
                target = namespace["Target"]
                argument = target if kind == "class" else target() if kind == "callable" else target().method
            value = function(argument)
        else:
            value = function(*arguments, **copy.deepcopy(case.get("kwargs", {})))
            if mode == "mutate":
                value = {"return": value, "argument": arguments[0]}
        return {"value": normalized(value)}
    except Exception as error:
        return {"exception": type(error).__name__}


def evaluate(workspace, checks):
    sys.path.insert(0, str(workspace))
    results = []
    for check in checks:
        module = importlib.import_module(check["module"])
        if not Path(module.__file__).resolve().is_relative_to(workspace.resolve()):
            raise ValueError("Probe imported an installed reference instead of candidate source")
        function = getattr(module, check["symbol"])
        results.append({"id": check["id"], "observation": observe(function, check["case"])})
    return results


def main():
    checks = json.loads(Path(sys.argv[1]).read_text())
    results = evaluate(Path("/workspace"), checks)
    destination = Path("/results/observations.json")
    destination.write_text(json.dumps({"observations": results}), encoding="utf-8")


if __name__ == "__main__":
    main()

"""Read a bounded subset of declared local pip installs; this does not run or emulate tox."""
import configparser
import re
import shlex
import sys
from .files import safe_path, text


def expand_factors(value):
    expanded = [value]
    for _ in range(8):
        output, changed = [], False
        for item in expanded:
            match = re.search(r"\{([^{}]*)\}", item)
            if match:
                changed = True
                output.extend(item[:match.start()] + option + item[match.end():]
                              for option in match.group(1).split(","))
            else:
                output.append(item)
        expanded = output
        if len(expanded) > 128:
            raise ValueError("TOX_TEST_FACTOR_LIMIT")
        if not changed:
            return [option for item in expanded for option in item.split(",")]
    raise ValueError("TOX_TEST_FACTOR_LIMIT")


def local_test_projects(files, *, version=None, windows=None):
    if "tox.ini" not in files:
        return []
    version = version or sys.version_info[:2]
    windows = sys.platform == "win32" if windows is None else windows
    py = "py" + str(version[0]) + str(version[1])
    active = {"py", py}
    if windows:
        active |= {"winpy", "win" + py}
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text(files["tox.ini"]))
    preferred = (["testenv:win" + py, "testenv:winpy"] if windows else [])
    preferred += ["testenv:" + py, "testenv:py", "testenv"]
    section = next((name for name in preferred if parser.has_option(name, "commands")), None)
    if section is None:
        return []
    projects = []
    for raw in parser.get(section, "commands").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        conditional = re.match(r"^([A-Za-z0-9_{},!.-]+):\s*(.*)$", line)
        if conditional:
            alternatives = expand_factors(conditional.group(1))
            matches = any(all((part[1:] not in active if part.startswith("!") else part in active)
                              for part in option.split("-")) for option in alternatives)
            if not matches:
                continue
            line = conditional.group(2)
        # Other tox commands stay outside this recipe; never execute a shell fragment.
        if not re.match(r"^python(?:\d+(?:\.\d+)?)?\s+-m\s+pip\s+install\s+", line):
            continue
        if "{toxinidir}" not in line:
            continue
        words = shlex.split(line, posix=True)
        arguments = words[4:]
        if arguments and arguments[0] == "-e":
            arguments = arguments[1:]
        if len(arguments) != 1 or not arguments[0].startswith("{toxinidir}/"):
            raise ValueError("UNSUPPORTED_LOCAL_TEST_INSTALL_DECLARATION")
        path = arguments[0][len("{toxinidir}/"):]
        if path in {"", "."}:
            continue
        safe_path(path)
        if "{" in path or "}" in path or not any(path + "/" + name in files
                for name in ("pyproject.toml", "setup.py", "setup.cfg")):
            raise ValueError("LOCAL_TEST_PROJECT_METADATA_MISSING: " + path)
        projects.append(path)
        if len(projects) > 32:
            raise ValueError("LOCAL_TEST_PROJECT_LIMIT")
    return list(dict.fromkeys(projects))

"""Explicit host-only credentials. Parse data, never source a shell or print secrets."""
from contextlib import contextmanager
from pathlib import Path
import os

KEYS = ("GITHUB_TOKEN", "GH_TOKEN", "DEEPSEEK_API_KEY", "AUTOBENCH_ALLOW_PAID")
TEMPLATE = """# Keep this file private. Values are plain text, not encrypted.
# Read-only GitHub access is required for discovery and the private ADCP source.
GITHUB_TOKEN=
DEEPSEEK_API_KEY=
# Change to YES only to authorize paid benchmark calls without another prompt.
# Request/time caps are configured in AB.toml; there is no guaranteed dollar cap.
AUTOBENCH_ALLOW_PAID=NO
"""


def parse_credentials(content):
    result = {}
    for number, line in enumerate(content.lstrip("\ufeff").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if key not in KEYS:
            continue
        if not separator or key in result:
            raise ValueError(f"INVALID_CREDENTIAL_CONFIG: line {number}; values are not logged")
        value = value.strip()
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"INVALID_CREDENTIAL_CONFIG: line {number}; unmatched quote")
            value = value[1:-1]
        if len(value) > 8192 or any(character.isspace() or ord(character) < 32 for character in value):
            raise ValueError(f"INVALID_CREDENTIAL_CONFIG: line {number}; whitespace/control character")
        result[key] = value
    return result


def read_credentials(root, environment=None):
    environment = os.environ if environment is None else environment
    path = Path(root) / ".env"
    values = {}
    if path.is_symlink():
        raise ValueError("LINKED_CREDENTIAL_CONFIG")
    if path.exists():
        if not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("CREDENTIAL_CONFIG_SIZE_LIMIT")
        values = parse_credentials(path.read_text(encoding="utf-8-sig"))
    clean = {key: environment.get(key, "").strip() for key in KEYS}
    # An environment alias must not lose to a different alias in a file.
    github = clean["GITHUB_TOKEN"] or clean["GH_TOKEN"] or values.get("GITHUB_TOKEN") or values.get("GH_TOKEN", "")
    return {"GITHUB_TOKEN": github, "GH_TOKEN": github,
            "DEEPSEEK_API_KEY": clean["DEEPSEEK_API_KEY"] or values.get("DEEPSEEK_API_KEY", ""),
            "AUTOBENCH_ALLOW_PAID": clean["AUTOBENCH_ALLOW_PAID"] or values.get("AUTOBENCH_ALLOW_PAID", "NO")}


def create_template(root):
    path = Path(root) / ".env"
    if path.is_symlink():
        raise ValueError("LINKED_CREDENTIAL_CONFIG")
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(TEMPLATE)
    except FileExistsError:
        pass
    return path


def paid_authorized(value):
    return value.strip().casefold() in {"yes", "true", "1", "on"}


@contextmanager
def host_credentials(values):
    previous = {key: os.environ.get(key) for key in KEYS}
    try:
        for key in KEYS:
            if values.get(key):
                os.environ[key] = values[key]
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

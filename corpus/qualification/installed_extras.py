"""Inspect installed root metadata without importing setup.py or any project module."""
from importlib.metadata import distributions
from pathlib import Path
from urllib.parse import unquote
import json
import os
import re
import sys


def root_test_extra(source, installed=None):
    expected = unquote(Path(source).resolve().as_uri()).rstrip("/")
    if os.name == "nt":
        expected = expected.casefold()
    roots = []
    for distribution in distributions() if installed is None else installed:
        direct = json.loads(distribution.read_text("direct_url.json") or "{}")
        url = unquote(direct.get("url", "")).rstrip("/")
        if os.name == "nt":
            url = url.casefold()
        if url == expected and direct.get("dir_info", {}).get("editable") is True:
            extras = distribution.metadata.get_all("Provides-Extra") or []
            roots.append({re.sub(r"[-_.]+", "-", value).lower() for value in extras})
    if len(roots) != 1:
        raise ValueError("ROOT_EDITABLE_METADATA_AMBIGUOUS")
    return next((name for name in ("test", "tests", "testing", "dev") if name in roots[0]), None)


if __name__ == "__main__":
    print(json.dumps(root_test_extra(sys.argv[1])))

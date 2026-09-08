"""Exact tree inventory and a bounded one-process Git blob reader.

No text conversion, shell expansion, cache of verdicts, or per-file subprocesses.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess
import tempfile
import threading
from .git_errors import CheckoutError


@dataclass(frozen=True)
class TreeEntry:
    mode: bytes
    oid: bytes
    path: bytes
    size: int


def tree_entries(bare, commit):
    result = subprocess.run(["git", "--git-dir", str(bare), "ls-tree", "-r", "-z", "-l", "--full-tree", commit],
                            capture_output=True, check=False, timeout=60)
    if result.returncode:
        raise CheckoutError("Cannot inventory the pinned Git tree")
    entries = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            header, path = raw.split(b"\t", 1)
            mode, kind, oid, size = header.split()
            size = int(size)
        except (ValueError, TypeError) as error:
            raise CheckoutError("Invalid Git tree metadata") from error
        if kind != b"blob" or mode not in {b"100644", b"100755", b"120000"} or size < 0:
            raise CheckoutError("Unsupported Git tree entry")
        entries.append(TreeEntry(mode, oid, path, size))
    return entries


class BlobReader:
    """Stream objects in one Git process, verifying both size and Git object identity."""
    def __init__(self, bare, timeout=120):
        self.bare, self.timeout = Path(bare), timeout
        self.process = None
        self.timer = None
        self.errors = None

    def __enter__(self):
        self.errors = tempfile.TemporaryFile()
        try:
            self.process = subprocess.Popen(["git", "--git-dir", str(self.bare), "cat-file", "--batch"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors, shell=False)
        except BaseException:
            self.errors.close()
            raise
        self.timer = threading.Timer(self.timeout, self._expire)
        self.timer.daemon = True
        self.timer.start()
        return self

    def _expire(self):
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.kill()
            except OSError:
                pass

    def read(self, oid, expected_size=None):
        if isinstance(oid, str):
            oid = oid.encode("ascii")
        if len(oid) not in (40, 64) or any(c not in b"0123456789abcdef" for c in oid):
            raise CheckoutError("Invalid blob object id")
        try:
            self.process.stdin.write(oid + b"\n")
            self.process.stdin.flush()
            header = self.process.stdout.readline(256)
            object_id, kind, length = header.rstrip(b"\n").split()
            size = int(length)
            if object_id != oid or kind != b"blob" or size < 0 or (expected_size is not None and size != expected_size):
                raise CheckoutError("Blob header disagrees with pinned inventory")
            payload = self.process.stdout.read(size)
            if len(payload) != size or self.process.stdout.read(1) != b"\n":
                raise CheckoutError("Truncated Git object stream")
        except (OSError, ValueError) as error:
            raise CheckoutError("Git object stream failed or timed out") from error
        algorithm = "sha1" if len(oid) == 40 else "sha256"
        actual = hashlib.new(algorithm, b"blob " + str(size).encode() + b"\0" + payload).hexdigest().encode()
        if actual != oid:
            raise CheckoutError("Git blob digest mismatch")
        return payload

    def __exit__(self, *args):
        if self.timer is not None:
            self.timer.cancel()
        if self.process is not None:
            self._expire()
            self.process.wait(timeout=5)
            self.process.stdin.close()
            self.process.stdout.close()
        if self.errors is not None:
            self.errors.close()


def digest_tree(bare, entries):
    digest = hashlib.sha256()
    with BlobReader(bare) as reader:
        for entry in entries:
            payload = reader.read(entry.oid, entry.size)
            kind = b"L" if entry.mode == b"120000" else b"F"
            executable = b"1" if entry.mode == b"100755" else b"0"
            for part in (kind, executable, entry.path, payload):
                digest.update(len(part).to_bytes(8, "big"))
                digest.update(part)
    return "sha256:" + digest.hexdigest()

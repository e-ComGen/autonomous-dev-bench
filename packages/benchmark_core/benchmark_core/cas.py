"""Digest-verifying filesystem content-addressed storage."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile

_REF = re.compile(r"^cas:sha256:([0-9a-f]{64})$")


class CASError(RuntimeError):
    pass


class CASCorruptionError(CASError):
    pass


class MissingCASObject(CASError, KeyError):
    pass


class FileSystemCAS:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        (self.root / "sha256").mkdir(parents=True, exist_ok=True)

    @staticmethod
    def ref_for(data: bytes) -> str:
        return "cas:sha256:" + hashlib.sha256(data).hexdigest()

    @staticmethod
    def parse_ref(ref: str) -> str:
        match = _REF.fullmatch(ref)
        if not match:
            raise ValueError("CAS ref must be cas:sha256:<64 lowercase hex>")
        return match.group(1)

    def path_for(self, ref: str) -> Path:
        digest = self.parse_ref(ref)
        return self.root / "sha256" / digest[:2] / digest

    def put_bytes(self, data: bytes) -> str:
        if not isinstance(data, bytes):
            raise TypeError("CAS accepts bytes")
        ref = self.ref_for(data); target = self.path_for(ref)
        if target.exists():
            self.get_bytes(ref)
            return ref
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".cas-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            try: os.unlink(temporary)
            except FileNotFoundError: pass
        return ref

    def put_text(self, text: str) -> str:
        return self.put_bytes(text.encode("utf-8"))

    def put_file(self, path: str | os.PathLike[str]) -> str:
        return self.put_bytes(Path(path).read_bytes())

    def get_bytes(self, ref: str) -> bytes:
        target = self.path_for(ref)
        try: data = target.read_bytes()
        except FileNotFoundError as exc: raise MissingCASObject(ref) from exc
        if self.ref_for(data) != ref:
            raise CASCorruptionError(f"digest mismatch for {ref}")
        return data

    def get_text(self, ref: str) -> str:
        return self.get_bytes(ref).decode("utf-8")

    def verify(self, ref: str) -> bool:
        self.get_bytes(ref); return True

    def contains(self, ref: str, *, verify: bool = True) -> bool:
        path = self.path_for(ref)
        if not path.is_file(): return False
        if verify: self.get_bytes(ref)
        return True

CAS = FileSystemCAS

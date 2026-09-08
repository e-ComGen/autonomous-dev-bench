"""Crash-released advisory lock for one checkout's managed bootstrap."""
from contextlib import contextmanager
from pathlib import Path
import os


@contextmanager
def launcher_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        try:
            # Windows prevents reading a byte locked by another handle. Inspect
            # metadata instead, then acquire that byte without reading its content.
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Another launcher is using this checkout or its lock is inaccessible") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

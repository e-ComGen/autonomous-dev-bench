"""Pinned transport for the existing SharedGitCache, with OS-released repository locks."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import tempfile
import time
from .git_errors import CheckoutError


def run_git(*arguments, cwd=None, check=True):
    completed = subprocess.run(["git", *map(str, arguments)], cwd=cwd, capture_output=True,
        text=True, encoding="utf-8", errors="replace", shell=False)
    if check and completed.returncode:
        raise CheckoutError(completed.stderr.strip()[-2000:])
    return completed


@contextmanager
def repository_lock(path, timeout=120):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise CheckoutError("PINNED_CACHE_LOCK_TIMEOUT") from error
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def ensure_commit(bare, repository, commit, progress=None):
    bare = Path(bare)
    notify = progress or (lambda stage, **details: None)
    notify("cache_lock")
    with repository_lock(bare.parent / "acquire.lock"):
        if not bare.exists():
            # Initialization is atomic; an interrupted fetch cannot leave a fake bare repository.
            with tempfile.TemporaryDirectory(prefix="init-", dir=bare.parent) as temporary:
                staging = Path(temporary) / "anchor.git"
                args = ["init", "--bare"]
                if len(commit) == 64:
                    args.append("--object-format=sha256")
                run_git(*args, staging)
                run_git("--git-dir", staging, "remote", "add", "origin", repository)
                staging.replace(bare)
        actual = run_git("--git-dir", bare, "remote", "get-url", "origin").stdout.strip()
        if actual != repository:
            raise CheckoutError("shared cache repository identity mismatch")
        present = run_git("--git-dir", bare, "cat-file", "-e", commit + "^{commit}", check=False).returncode == 0
        if not present:
            notify("fetch_pinned_commit", commit=commit)
            args = ["--git-dir", bare, "-c", "gc.auto=0", "fetch", "--no-tags", "--no-recurse-submodules"]
            # Local bundles are finite offline transports; Git cannot shallow-fetch from a bundle.
            if not Path(repository).is_file():
                args.append("--depth=1")
            run_git(*args, "origin", commit + ":refs/benchmark/pins/" + commit)
        else:
            notify("cached_commit", commit=commit)
        resolved = run_git("--git-dir", bare, "rev-parse", "--verify", commit + "^{commit}").stdout.strip().lower()
        if resolved != commit:
            raise CheckoutError("Pinned commit resolved unexpectedly")
        run_git("--git-dir", bare, "update-ref", "refs/benchmark/pins/" + commit, commit)

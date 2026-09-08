"""Bounded acquisition progress, with a passive heartbeat over the existing process owner."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import threading
import time


class Progress:
    def __init__(self, path):
        self.path = Path(path)
        self.started = self.changed = time.monotonic()
        self.stage = "starting"
        self.durations = {}
        self("starting")

    def __call__(self, stage, **details):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", stage):
            raise ValueError("Invalid acquisition stage")
        now = time.monotonic()
        self.durations[self.stage] = self.durations.get(self.stage, 0.0) + now - self.changed
        self.changed, self.stage = now, stage
        record = {"stage": stage, "elapsed_seconds": round(now - self.started, 3),
                  "stage_seconds": {key: round(value, 3) for key, value in self.durations.items()},
                  "details": {key: value for key, value in details.items() if key in {"files", "source_bytes", "commit"}}}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record), encoding="utf-8")
        temporary.replace(self.path)


def read_progress(path):
    try:
        path = Path(path)
        if path.is_symlink() or path.stat().st_size > 32768:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


@contextmanager
def heartbeat(path, *, interval=5):
    stopped = threading.Event()
    started = time.monotonic()
    def observe():
        while not stopped.wait(interval):
            record = read_progress(path)
            stage = record.get("stage", "starting")
            if not isinstance(stage, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", stage):
                stage = "unknown"
            print(f"  Source: {stage}; elapsed={time.monotonic() - started:.0f}s", flush=True)
    observer = threading.Thread(target=observe, name="acquisition-heartbeat", daemon=True)
    observer.start()
    try:
        yield
    finally:
        stopped.set()
        observer.join(timeout=max(1, interval))

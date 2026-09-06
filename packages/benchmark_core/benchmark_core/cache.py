"""SQLite action cache whose values are independently stored CAS objects."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import re
from threading import RLock
from typing import Iterator

from .cas import FileSystemCAS, MissingCASObject, CASCorruptionError
from .identity import Sha256Digest

_ACTION_KEY = re.compile(r"^sha256:[0-9a-f]{64}$")


def observation_action_key(*, input_checkpoint_digest: str, invocation: object,
                           system_commit: str, system_configuration: object,
                           environment_digest: str, isolation_policy: object, resource_policy: object,
                           adapter_id: str, adapter_version: str, adapter_configuration: object,
                           model_provider: str | None, model_id: str | None,
                           prompt_version: str, policy_version: str, tools: object,
                           seed: int, execution_mode: str) -> str:
    return str(Sha256Digest.of({
        "input_checkpoint_digest": input_checkpoint_digest, "invocation": invocation,
        "system_commit": system_commit, "system_configuration": system_configuration,
        "environment_digest": environment_digest, "isolation_policy": isolation_policy,
        "resource_policy": resource_policy, "adapter_id": adapter_id,
        "adapter_version": adapter_version, "adapter_configuration": adapter_configuration,
        "model_provider": model_provider, "model_id": model_id,
        "prompt_version": prompt_version, "policy_version": policy_version,
        "tools": tools, "seed": seed, "execution_mode": execution_mode,
    }))


def oracle_action_key(*, observation_digest: str, plan_digest: str, oracle_id: str, oracle_version: str,
                      suite_id: str, suite_version: str, policy_version: str,
                      private_context_digest: str) -> str:
    return str(Sha256Digest.of({
        "observation_digest": observation_digest, "plan_digest": plan_digest, "oracle_id": oracle_id,
        "oracle_version": oracle_version, "suite_id": suite_id, "suite_version": suite_version,
        "policy_version": policy_version, "private_context_digest": private_context_digest,
    }))


class ActionCache:
    def __init__(self, database: str | os.PathLike[str], cas: FileSystemCAS) -> None:
        self.database = Path(database); self.database.parent.mkdir(parents=True, exist_ok=True)
        self.cas = cas; self._lock = RLock()
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS action_cache (action_key TEXT PRIMARY KEY, result_ref TEXT NOT NULL, created_at TEXT NOT NULL)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=30)
        try: yield connection; connection.commit()
        finally: connection.close()

    def put_ref(self, action_key: str, result_ref: str) -> None:
        if not _ACTION_KEY.fullmatch(action_key):
            raise ValueError("action key must be sha256:<64 lowercase hex>")
        self.cas.verify(result_ref)
        with self._lock, self._connect() as connection:
            connection.execute("INSERT INTO action_cache(action_key,result_ref,created_at) VALUES(?,?,?) ON CONFLICT(action_key) DO UPDATE SET result_ref=excluded.result_ref, created_at=excluded.created_at",
                               (action_key, result_ref, datetime.now(timezone.utc).isoformat()))

    def put_bytes(self, action_key: str, result: bytes) -> str:
        ref = self.cas.put_bytes(result); self.put_ref(action_key, ref); return ref

    def get_ref(self, action_key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT result_ref FROM action_cache WHERE action_key=?", (action_key,)).fetchone()
        if row is None: return None
        ref = str(row[0])
        try: self.cas.verify(ref)
        except (MissingCASObject, CASCorruptionError):
            self.delete(action_key)
            raise
        return ref

    def get_bytes(self, action_key: str) -> bytes | None:
        ref = self.get_ref(action_key)
        return None if ref is None else self.cas.get_bytes(ref)

    def delete(self, action_key: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM action_cache WHERE action_key=?", (action_key,))

    def clear(self) -> None:
        with self._lock, self._connect() as connection: connection.execute("DELETE FROM action_cache")

"""Cheap exact-tree admission before source hashing, worktrees and Python installers."""
from .files import safe_path, is_code


def validate_inventory(entries, policy, *, check_code_size=True):
    total = code_bytes = 0
    seen = set()
    for entry in entries:
        relative = entry.path.decode("utf-8")
        safe_path(relative)
        if relative.casefold() in seen:
            raise ValueError("CASE_COLLIDING_SOURCE")
        seen.add(relative.casefold())
        if entry.mode not in {b"100644", b"100755"}:
            raise ValueError("UNSUPPORTED_GIT_FILE_MODE")
        total += entry.size
        if entry.size > policy.max_file_bytes:
            raise ValueError(f"SOURCE_SIZE_LIMIT: file={relative}; bytes={entry.size}; limit={policy.max_file_bytes}; stage=inventory")
        if total > policy.max_repository_bytes:
            raise ValueError(f"SOURCE_SIZE_LIMIT: bytes>{policy.max_repository_bytes}; stage=inventory")
        if is_code(relative):
            code_bytes += entry.size
    if check_code_size and (not code_bytes or code_bytes > policy.max_code_bytes):
        raise ValueError(f"ADCP_SOURCE_VIEW_UNSUPPORTED: bytes={code_bytes}; limit={policy.max_code_bytes}; stage=inventory")
    return {"files": len(entries), "source_bytes": total, "code_bytes": code_bytes}

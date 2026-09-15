"""OMP JSONL accounting. Missing usage is unknown, never an implicit zero."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

USAGE = {"input_tokens": "input", "cached_input_tokens": "cacheRead",
         "cache_write_tokens": "cacheWrite", "output_tokens": "output",
         "reasoning_tokens": "reasoningTokens", "provider_total_tokens": "totalTokens"}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _file_key(path, workspace):
    # OMP line selectors refer to the same file. Preserve original strings separately.
    path = re.sub(r"(?::\d+(?::\d+)?|#L\d+(?:-L?\d+)?)$", "", path).replace("\\", "/")
    if workspace:
        root = str(workspace.resolve()).replace("\\", "/").rstrip("/")
        if path.lower().startswith(root.lower() + "/"):
            path = path[len(root) + 1:]
        elif not Path(path).is_absolute() and not re.match(r"^[A-Za-z]:/", path):
            path = str(Path(path)).replace("\\", "/")
    return path


def parse_jsonl(raw: bytes, exit_code: int | None, workspace: Path | None = None) -> dict:
    """Retain failed read attempts; unique files counts successful non-directory reads."""
    events, errors = [], []
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        lines = []
        errors.append(str(exc))
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("event must be an object")
            events.append(event)
        except (ValueError, TypeError) as exc:
            errors.append(f"line {number}: {exc}")
    messages, tools, terminal, stops = [], [], None, []
    by_id = {}
    for event in events:
        kind = event.get("type")
        if kind == "message_end" and isinstance(event.get("message"), dict):
            message = event["message"]
            if message.get("role") == "assistant":
                messages.append(message)
                stops.append(message.get("stopReason"))
        elif kind == "agent_end":
            terminal = event.get("isTerminal") is True
        elif kind == "tool_execution_start":
            arguments = event.get("args", event.get("arguments", {}))
            if not isinstance(arguments, dict):
                arguments = {"raw": arguments}
            tool = {"name": event.get("toolName", event.get("name")),
                    "intent": arguments.get("intent", event.get("intent")),
                    "arguments": arguments, "tool_call_id": event.get("toolCallId"),
                    "success": None, "error": None, "result": None}
            tools.append(tool)
            by_id[event.get("toolCallId")] = tool
        elif kind == "tool_execution_end":
            tool = by_id.get(event.get("toolCallId"))
            if tool:
                tool["success"] = event.get("isError") is False
                tool["error"] = event.get("result") if event.get("isError") else None
                tool["result"] = event.get("result")
    result = {}
    usages = [m.get("usage") if isinstance(m.get("usage"), dict) else {} for m in messages]
    for output, field in USAGE.items():
        values = [usage.get(field) for usage in usages]
        result[output] = sum(values) if values and all(_number(v) for v in values) else None
    costs = [usage["cost"].get("total") if isinstance(usage.get("cost"), dict) else None for usage in usages]
    result["provider_reported_cost"] = sum(costs) if costs and all(_number(c) for c in costs) else None
    reads, files = [], set()
    for tool in tools:
        if tool["name"] != "read":
            continue
        args = tool["arguments"]
        raw_path = args.get("path", args.get("file_path"))
        value = tool["result"] if isinstance(tool["result"], dict) else {}
        details = value.get("details", {})
        details = details if isinstance(details, dict) else {}
        resolved = details.get("resolvedPath", value.get("resolvedPath", raw_path))
        is_directory = details.get("isDirectory") is True or details.get("type") == "directory"
        if isinstance(resolved, str) and workspace and not is_directory:
            candidate = Path(resolved) if Path(resolved).is_absolute() else workspace / resolved
            is_directory = candidate.is_dir()
        reads.append({"path": raw_path, "resolved_path": resolved,
                      "success": tool["success"], "is_directory": is_directory})
        if tool["success"] is True and not is_directory and isinstance(resolved, str):
            files.add(_file_key(resolved, workspace))
    result.update(model_turns=len(messages), tool_calls=len(tools), read_calls=len(reads),
                  unique_files_read=len(files), exact_read_paths=reads, unique_read_paths=sorted(files),
                  tools=tools, stop_reasons=stops, parse_errors=errors,
                  exit_code=exit_code, terminal=terminal,
                  execution_success=exit_code == 0 and terminal is True and not errors,
                  total_cost=None, quota_usage=None)
    return result

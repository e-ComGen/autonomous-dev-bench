"""TEST ONLY: request one actual DSH shell tool; the filesystem is the success oracle."""
from http.server import BaseHTTPRequestHandler
import json

COMMAND = 'python -c "from pathlib import Path; Path(\'source.py\').write_text(\'VALUE = 2\'+chr(10), encoding=\'utf-8\'); print(\'native-tool-ok\')"'


def shell_call(tools):
    for entry in tools:
        function = entry.get("function", {})
        name = function.get("name", "")
        if not any(word in name.lower() for word in ("bash", "pwsh", "shell", "powershell", "exec", "run_command")):
            continue
        schema = function.get("parameters", {})
        properties = schema.get("properties", {})
        for key in ("command", "cmd", "script"):
            if properties.get(key, {}).get("type") != "string" or "enum" in properties[key]:
                continue
            arguments = {key: COMMAND}
            for required in schema.get("required", []):
                if required == key:
                    continue
                if required in {"description", "purpose"}:
                    arguments[required] = "Run the native test fixture in its disposable workspace"
                elif required in {"timeout", "timeout_ms"}:
                    arguments[required] = 60000
                elif required in {"background"}:
                    arguments[required] = False
                else:
                    break
            else:
                return name, arguments
    raise ValueError("No recognized native shell tool schema: " + repr([item.get("function", {}).get("name") for item in tools]))


class ToolHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length < 1048576:
            self.send_error(413)
            return
        data = json.loads(self.rfile.read(length))
        self.server.requests += 1
        if self.server.requests > 3:
            self.send_error(429)
            return
        self.server.last_request = data
        has_result = any(message.get("role") == "tool" for message in data["messages"])
        if not has_result:
            try:
                name, arguments = shell_call(data.get("tools", []))
            except ValueError as error:
                self.server.error = str(error)
                self.send_error(400, "Unrecognized fixture tool schema")
                return
            self.server.selected_tool = name
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "native-test-call", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}
            finish = "tool_calls"
        else:
            message, finish = {"role": "assistant", "content": "native-tool-done"}, "stop"
        model = data["model"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if data.get("stream") else "application/json")
        self.send_header("Connection", "close")
        self.end_headers()
        usage = {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}
        if data.get("stream"):
            delta = dict(message)
            if "tool_calls" in delta:
                delta["tool_calls"] = [{"index": 0, **item} for item in delta["tool_calls"]]
            header = {"id": "tool-fixture-only", "object": "chat.completion.chunk", "created": 1, "model": model}
            for chunk in (dict(header, choices=[{"index": 0, "delta": delta, "finish_reason": None}]),
                          dict(header, choices=[{"index": 0, "delta": {}, "finish_reason": finish}], usage=usage)):
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.wfile.write(json.dumps({"id": "tool-fixture-only", "object": "chat.completion", "created": 1, "model": model,
                "choices": [{"index": 0, "message": message, "finish_reason": finish}], "usage": usage}).encode())
        self.wfile.flush()
        self.close_connection = True

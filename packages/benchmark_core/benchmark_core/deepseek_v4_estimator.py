"""Exact DeepSeek-V4 wire-request estimator for the shared model budget proxy.

The estimator intentionally does not reimplement the DeepSeek chat template. It
loads DeepSeek's pinned reference ``encoding_dsv4.py`` and the tokenizer from an
immutable Hugging Face revision, then prices the exact OpenAI-compatible wire
request seen by the proxy.

Paid execution is fail-closed: ambiguous or unsupported wire shapes are rejected
before upstream dispatch rather than estimated with character/token heuristics.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import importlib.util
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from .model_proxy import ExactTokenEstimateUnavailable, RequestBudgetEstimate


DEEPSEEK_V4_REPO_ID = "deepseek-ai/DeepSeek-V4-Flash-0731"
DEEPSEEK_V4_REVISION = "9e165c30e2704aec5d9d593cce3eebd58bbef1cb"
DEEPSEEK_V4_ENCODING_FILE = "encoding/encoding_dsv4.py"
DEEPSEEK_V4_MODEL = "deepseek-v4-flash"


class _Tokenizer(Protocol):
    def encode(self, text: str, *args, **kwargs) -> Sequence[int]: ...


class DeepSeekV4EstimatorAssetError(RuntimeError):
    """Pinned encoder/tokenizer assets are missing or cannot be loaded."""


@dataclass(frozen=True, slots=True)
class DeepSeekV4EstimatorIdentity:
    repo_id: str = DEEPSEEK_V4_REPO_ID
    revision: str = DEEPSEEK_V4_REVISION
    encoding_file: str = DEEPSEEK_V4_ENCODING_FILE
    model: str = DEEPSEEK_V4_MODEL


class DeepSeekV4RequestEstimator:
    """Price one exact text-only DeepSeek-V4 chat-completions request.

    ``encode_messages`` must be DeepSeek's reference encoder from the pinned
    revision (or a test double with the same call contract). ``tokenizer`` must
    expose the same ``encode(prompt)`` behavior as ``AutoTokenizer`` for the
    pinned tokenizer assets.
    """

    _TOP_LEVEL_FIELDS = frozenset(
        {
            "model",
            "messages",
            "stream",
            "stream_options",
            "thinking",
            "reasoning_effort",
            "tools",
            "temperature",
            "max_tokens",
            "stop",
        }
    )

    def __init__(
        self,
        encode_messages: Callable[..., str],
        tokenizer: _Tokenizer,
        *,
        expected_model: str = DEEPSEEK_V4_MODEL,
        identity: DeepSeekV4EstimatorIdentity | None = None,
    ) -> None:
        if not callable(encode_messages):
            raise TypeError("encode_messages must be callable")
        if not hasattr(tokenizer, "encode"):
            raise TypeError("tokenizer must expose encode(text)")
        if not expected_model.strip():
            raise ValueError("expected_model must be non-empty")
        self._encode_messages = encode_messages
        self._tokenizer = tokenizer
        self._expected_model = expected_model
        self._identity = identity or DeepSeekV4EstimatorIdentity(model=expected_model)

    @property
    def identity(self) -> DeepSeekV4EstimatorIdentity:
        return self._identity

    @classmethod
    def from_huggingface_revision(
        cls,
        *,
        expected_model: str = DEEPSEEK_V4_MODEL,
        repo_id: str = DEEPSEEK_V4_REPO_ID,
        revision: str = DEEPSEEK_V4_REVISION,
        cache_dir: str | Path | None = None,
        allow_network: bool = False,
    ) -> "DeepSeekV4RequestEstimator":
        """Load only the immutable official encoder/tokenizer assets.

        ``allow_network`` defaults to ``False`` so a paid trial cannot silently
        fetch a mutable dependency. Qualification/bootstrap may set it to true;
        both downloads still use the exact immutable revision.
        """
        try:
            from huggingface_hub import hf_hub_download
            from transformers import AutoTokenizer
        except ImportError as error:  # pragma: no cover - optional production extra
            raise DeepSeekV4EstimatorAssetError(
                "DeepSeek-V4 estimator requires the optional deepseek-estimator dependencies"
            ) from error

        local_only = not allow_network
        try:
            encoding_path = hf_hub_download(
                repo_id=repo_id,
                filename=DEEPSEEK_V4_ENCODING_FILE,
                revision=revision,
                cache_dir=str(cache_dir) if cache_dir is not None else None,
                local_files_only=local_only,
            )
            tokenizer = AutoTokenizer.from_pretrained(
                repo_id,
                revision=revision,
                cache_dir=str(cache_dir) if cache_dir is not None else None,
                local_files_only=local_only,
                trust_remote_code=False,
            )
        except Exception as error:  # pragma: no cover - exercised by qualification workflow
            mode = "local cache" if local_only else "pinned Hugging Face revision"
            raise DeepSeekV4EstimatorAssetError(
                f"could not load DeepSeek-V4 estimator assets from {mode}"
            ) from error

        module = cls._load_reference_encoder(Path(encoding_path))
        encode_messages = getattr(module, "encode_messages", None)
        if not callable(encode_messages):
            raise DeepSeekV4EstimatorAssetError("pinned encoding_dsv4.py has no encode_messages")

        return cls(
            encode_messages,
            tokenizer,
            expected_model=expected_model,
            identity=DeepSeekV4EstimatorIdentity(
                repo_id=repo_id,
                revision=revision,
                encoding_file=DEEPSEEK_V4_ENCODING_FILE,
                model=expected_model,
            ),
        )

    @staticmethod
    def _load_reference_encoder(path: Path):
        spec = importlib.util.spec_from_file_location("autobench_pinned_deepseek_v4_encoding", path)
        if spec is None or spec.loader is None:
            raise DeepSeekV4EstimatorAssetError(f"cannot load reference encoder: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def estimate(self, request: Mapping[str, object]) -> RequestBudgetEstimate:
        unknown = set(request) - self._TOP_LEVEL_FIELDS
        if unknown:
            raise ExactTokenEstimateUnavailable(
                "unsupported DeepSeek-V4 wire field(s): " + ", ".join(sorted(unknown))
            )
        if request.get("model") != self._expected_model:
            raise ExactTokenEstimateUnavailable("DeepSeek-V4 estimator model identity mismatch")

        max_output = self._positive_int(request.get("max_tokens"), "max_tokens")
        messages = self._normalize_messages(request.get("messages"))
        thinking_mode, reasoning_effort = self._thinking_policy(request)
        tools = request.get("tools")
        if tools is not None:
            self._attach_tools(messages, tools)

        try:
            prompt = self._encode_messages(
                messages,
                thinking_mode=thinking_mode,
                reasoning_effort=reasoning_effort,
            )
        except Exception as error:
            raise ExactTokenEstimateUnavailable(
                "pinned DeepSeek-V4 reference encoder rejected the wire request"
            ) from error
        if not isinstance(prompt, str) or not prompt:
            raise ExactTokenEstimateUnavailable("DeepSeek-V4 reference encoder returned an invalid prompt")

        try:
            # Match the official model-card example exactly: tokenizer.encode(prompt).
            encoded = self._tokenizer.encode(prompt)
            input_tokens = len(encoded)
        except Exception as error:
            raise ExactTokenEstimateUnavailable("pinned DeepSeek-V4 tokenizer rejected the prompt") from error
        if input_tokens <= 0:
            raise ExactTokenEstimateUnavailable("pinned DeepSeek-V4 tokenizer returned zero input tokens")

        return RequestBudgetEstimate(
            input_tokens=input_tokens,
            max_output_tokens=max_output,
            max_total_tokens=input_tokens + max_output,
        )

    @classmethod
    def _normalize_messages(cls, raw: object) -> list[dict[str, object]]:
        if not isinstance(raw, list) or not raw:
            raise ExactTokenEstimateUnavailable("DeepSeek-V4 wire messages must be a non-empty list")
        normalized: list[dict[str, object]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, Mapping):
                raise ExactTokenEstimateUnavailable(f"message {index} is not an object")
            message = dict(item)
            role = message.get("role")
            if role not in {"system", "developer", "user", "assistant", "tool"}:
                raise ExactTokenEstimateUnavailable(f"unsupported DeepSeek-V4 message role: {role!r}")

            allowed = {
                "system": {"role", "content"},
                "developer": {"role", "content"},
                "user": {"role", "content"},
                "assistant": {"role", "content", "reasoning_content", "tool_calls"},
                "tool": {"role", "tool_call_id", "content"},
            }[role]
            extra = set(message) - allowed
            if extra:
                raise ExactTokenEstimateUnavailable(
                    f"unsupported field(s) on {role} message: " + ", ".join(sorted(extra))
                )

            content = message.get("content")
            if role == "assistant":
                if content is not None and not isinstance(content, str):
                    raise ExactTokenEstimateUnavailable("assistant content must be text or null")
                reasoning = message.get("reasoning_content")
                if reasoning is not None and not isinstance(reasoning, str):
                    raise ExactTokenEstimateUnavailable("assistant reasoning_content must be text")
                cls._validate_tool_calls(message.get("tool_calls"))
            else:
                if not isinstance(content, str):
                    # The paid Flash arm is text-only. Image/file parts require a
                    # separate image-token admission contract and are rejected here.
                    raise ExactTokenEstimateUnavailable(f"{role} content must be text")
                if role == "tool":
                    tool_call_id = message.get("tool_call_id")
                    if not isinstance(tool_call_id, str) or not tool_call_id:
                        raise ExactTokenEstimateUnavailable("tool message requires tool_call_id")
            normalized.append(deepcopy(message))
        return normalized

    @staticmethod
    def _validate_tool_calls(raw: object) -> None:
        if raw is None:
            return
        if not isinstance(raw, list):
            raise ExactTokenEstimateUnavailable("assistant tool_calls must be a list")
        for call in raw:
            if not isinstance(call, Mapping) or call.get("type") != "function":
                raise ExactTokenEstimateUnavailable("unsupported assistant tool call")
            function = call.get("function")
            if not isinstance(function, Mapping):
                raise ExactTokenEstimateUnavailable("tool call function must be an object")
            if not isinstance(function.get("name"), str) or not function.get("name"):
                raise ExactTokenEstimateUnavailable("tool call function requires a name")
            if not isinstance(function.get("arguments"), str):
                raise ExactTokenEstimateUnavailable("tool call arguments must be the wire JSON string")
            extra = set(call) - {"id", "type", "function"}
            if extra:
                raise ExactTokenEstimateUnavailable("unsupported assistant tool call fields")

    @classmethod
    def _attach_tools(cls, messages: list[dict[str, object]], raw_tools: object) -> None:
        if not isinstance(raw_tools, list) or not raw_tools:
            raise ExactTokenEstimateUnavailable("tools must be a non-empty OpenAI function list")
        for tool in raw_tools:
            if not isinstance(tool, Mapping) or tool.get("type") != "function":
                raise ExactTokenEstimateUnavailable("DeepSeek-V4 estimator supports function tools only")
            function = tool.get("function")
            if not isinstance(function, Mapping):
                raise ExactTokenEstimateUnavailable("tool function must be an object")
            if not isinstance(function.get("name"), str) or not function.get("name"):
                raise ExactTokenEstimateUnavailable("tool function requires a name")
            if "parameters" not in function or not isinstance(function.get("parameters"), Mapping):
                raise ExactTokenEstimateUnavailable("tool function requires a parameters schema")

        # DeepSeek's reference tests attach top-level OpenAI tools to a
        # system/developer message before calling encode_messages. Do the same,
        # but refuse to invent a synthetic anchor when the wire request lacks one.
        anchor = next(
            (message for message in messages if message.get("role") in {"system", "developer"}),
            None,
        )
        if anchor is None:
            raise ExactTokenEstimateUnavailable(
                "tool-bearing DeepSeek-V4 request has no system/developer encoder anchor"
            )
        anchor["tools"] = deepcopy(raw_tools)

    @staticmethod
    def _thinking_policy(request: Mapping[str, object]) -> tuple[str, str | None]:
        effort = request.get("reasoning_effort")
        if effort is not None and effort not in {"low", "high", "max"}:
            raise ExactTokenEstimateUnavailable("unsupported DeepSeek-V4 reasoning_effort")

        thinking = request.get("thinking")
        if thinking is None:
            if effort is None:
                raise ExactTokenEstimateUnavailable(
                    "DeepSeek-V4 paid request must carry an explicit thinking state"
                )
            return "thinking", str(effort)
        if not isinstance(thinking, Mapping) or set(thinking) != {"type"}:
            raise ExactTokenEstimateUnavailable("invalid DeepSeek-V4 thinking object")
        kind = thinking.get("type")
        if kind == "enabled":
            return "thinking", str(effort) if effort is not None else "low"
        if kind == "disabled":
            if effort is not None:
                raise ExactTokenEstimateUnavailable("disabled thinking cannot carry reasoning_effort")
            return "chat", None
        raise ExactTokenEstimateUnavailable("unsupported DeepSeek-V4 thinking type")

    @staticmethod
    def _positive_int(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ExactTokenEstimateUnavailable(f"DeepSeek-V4 wire request requires positive {name}")
        return value

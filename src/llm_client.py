"""Reusable OpenAI-compatible chat client with streaming and registered tools."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import openai
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
MAX_RETRIES = 5
BASE_WAIT_S = 1.0


@dataclass
class Reply:
    """Normalized response data, independent of the provider SDK response type."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    streamed: bool = False
    chunks: int = 0
    latency_ms: int = 0


class RunLog:
    """Append JSON-serializable event objects to a JSON Lines file."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = os.fspath(path) if path else None

    def write(self, **event: Any) -> None:
        if self.path:
            with open(self.path, "a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


class LLMClient:
    """Chat client for OpenAI-compatible providers, with bounded 429 retries."""

    def __init__(
        self,
        log: RunLog | None = None,
        max_retries: int = MAX_RETRIES,
        *,
        sleep: Callable[[float], None] = time.sleep,
        retry_base_s: float = BASE_WAIT_S,
        client: Any | None = None,
    ) -> None:
        load_dotenv()
        self.base_url = os.getenv("LLM_BASE_URL", "").strip()
        api_key = os.getenv("LLM_API_KEY", "").strip()
        self.model = os.getenv("LLM_MODEL", "").strip()
        missing = [name for name, value in (("LLM_BASE_URL", self.base_url),
                                             ("LLM_API_KEY", api_key),
                                             ("LLM_MODEL", self.model)) if not value]
        if missing:
            raise ValueError("Missing required LLM configuration: " + ", ".join(missing) +
                             ". Set these variables in the environment or .env file.")
        if max_retries < 1:
            raise ValueError("max_retries must allow at least one total attempt")
        self._client = client or openai.OpenAI(
            base_url=self.base_url,
            api_key=api_key,
            max_retries=0,
            timeout=float(os.getenv("LLM_TIMEOUT", "300")),
        )
        self.create = self._client.chat.completions.create
        self.log = log or RunLog()
        self.max_retries = max_retries
        self._sleep = sleep
        self.retry_base_s = retry_base_s

    @staticmethod
    def _retry_after(error: openai.RateLimitError) -> float | None:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", {}) or {}
        value = headers.get("retry-after") or headers.get("Retry-After")
        if value is None:
            return None
        try:
            delay = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, delay)

    def _call(self, **kwargs: Any) -> Any:
        """Run a request; retry only 429 errors, at most ``max_retries`` times."""
        for attempt in range(1, self.max_retries + 1):
            try:
                return self.create(model=self.model, **kwargs)
            except openai.RateLimitError as error:
                if attempt == self.max_retries:
                    raise
                wait = self._retry_after(error)
                if wait is None:
                    wait = self.retry_base_s * (2 ** (attempt - 1))
                self.log.write(event="retry", status=429, attempt=attempt, wait_s=wait)
                logger.warning("LLM rate limited; retry %s/%s in %s seconds",
                               attempt, self.max_retries - 1, wait)
                self._sleep(wait)
        raise RuntimeError("Unreachable retry state")

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = True,
        on_token: Callable[[str], None] | None = None,
    ) -> Reply:
        """Send a chat request and optionally deliver text chunks as they arrive."""
        started = time.perf_counter()
        params: dict[str, Any] = {"messages": messages}
        if tools:
            params["tools"] = tools
        reply = Reply(streamed=stream, model=self.model)
        if not stream:
            response = self._call(**params)
            message = response.choices[0].message
            reply.content = message.content or ""
            reply.tool_calls = [_normalize_tool_call(tc.id, tc.function.name,
                                                     tc.function.arguments)
                                for tc in (message.tool_calls or [])]
            reply.model = getattr(response, "model", None) or self.model
        else:
            tool_parts: dict[int, dict[str, str]] = {}
            text_parts: list[str] = []
            stream_response = self._call(stream=True, **params)
            for chunk in stream_response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                if isinstance(content, str) and content:
                    text_parts.append(content)
                    reply.chunks += 1
                    if on_token:
                        on_token(content)
                for tool_delta in getattr(delta, "tool_calls", None) or []:
                    part = tool_parts.setdefault(tool_delta.index,
                                                 {"id": "", "name": "", "arguments": ""})
                    if tool_delta.id:
                        part["id"] += tool_delta.id
                    function = getattr(tool_delta, "function", None)
                    if function:
                        if function.name:
                            part["name"] += function.name
                        if function.arguments:
                            part["arguments"] += function.arguments
            reply.content = "".join(text_parts)
            reply.tool_calls = [_normalize_tool_call(p["id"], p["name"], p["arguments"])
                                for _, p in sorted(tool_parts.items())]
        reply.latency_ms = int((time.perf_counter() - started) * 1000)
        return reply


def _normalize_tool_call(call_id: str, name: str, arguments: str | Mapping[str, Any]) -> dict[str, Any]:
    """Parse a completed tool call without evaluating model-provided code."""
    try:
        parsed = json.loads(arguments or "{}") if isinstance(arguments, str) else dict(arguments)
        if not isinstance(parsed, dict):
            raise ValueError("Tool arguments must be a JSON object")
        return {"id": call_id or f"call_{uuid.uuid4().hex[:12]}", "name": name,
                "arguments": parsed}
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        return {"id": call_id or f"call_{uuid.uuid4().hex[:12]}", "name": name,
                "arguments": {}, "error": f"Invalid tool arguments: {error}"}


class Conversation:
    """Persistent OpenAI-format history and allow-listed Python tool execution."""

    def __init__(
        self,
        client: LLMClient,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        functions: dict[str, Callable[..., Any]] | None = None,
        conversation_id: str = "c1",
        *,
        max_tool_rounds: int = 4,
    ) -> None:
        self.client = client
        self.history: list[dict[str, Any]] = ([{"role": "system", "content": system}]
                                               if system else [])
        self.tools = tools
        self.functions = functions or {}
        self.id = conversation_id
        self.turn = 0
        self.max_tool_rounds = max_tool_rounds

    @property
    def messages(self) -> list[dict[str, Any]]:
        """Return the current complete history in OpenAI message format."""
        return self.history

    def add_user_message(self, content: str) -> None:
        self.history.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self.history.append({"role": "assistant", "content": content})

    def add_assistant_tool_calls(self, tool_calls: list[dict[str, Any]], content: str | None = None) -> None:
        self.history.append({"role": "assistant", "content": content, "tool_calls": [
            {"id": call["id"], "type": "function", "function": {
                "name": call["name"], "arguments": json.dumps(call["arguments"])} }
            for call in tool_calls]})

    def add_tool_message(self, tool_call_id: str, content: str, name: str | None = None) -> None:
        message: dict[str, Any] = {"role": "tool", "tool_call_id": tool_call_id,
                                   "content": content}
        if name:
            message["name"] = name
        self.history.append(message)

    def ask(self, text: str, on_token: Callable[[str], None] | None = None) -> str:
        """Add a user turn, process registered tool calls, and return its final answer."""
        self.turn += 1
        self.add_user_message(text)
        self.client.log.write(conversation_id=self.id, turn=self.turn,
                              role="user", content=text)
        for _ in range(self.max_tool_rounds):
            reply = self.client.chat(self.history, tools=self.tools, stream=True,
                                     on_token=on_token)
            if not reply.tool_calls:
                self.add_assistant_message(reply.content)
                self.client.log.write(conversation_id=self.id, turn=self.turn,
                                      role="assistant", content=reply.content,
                                      streamed=reply.streamed, chunks=reply.chunks,
                                      model=reply.model, latency_ms=reply.latency_ms)
                return reply.content
            calls_for_log = [{"id": call["id"], "name": call["name"],
                              "arguments": call["arguments"]} for call in reply.tool_calls]
            self.client.log.write(conversation_id=self.id, turn=self.turn,
                                  role="assistant", content="", tool_calls=calls_for_log,
                                  model=reply.model)
            self.add_assistant_tool_calls(reply.tool_calls, reply.content or None)
            for call in reply.tool_calls:
                function = self.functions.get(call["name"])
                if call.get("error"):
                    result = call["error"]
                elif function is None:
                    result = f"Tool error: unknown tool '{call['name']}'."
                else:
                    try:
                        result = str(function(**call["arguments"]))
                    except Exception as error:  # errors become tool results; never execute arbitrary code
                        logger.exception("Registered tool %s failed", call["name"])
                        result = f"Tool error: {type(error).__name__}: {error}"
                self.add_tool_message(call["id"], result, call["name"])
                self.client.log.write(conversation_id=self.id, turn=self.turn,
                                      role="tool", tool_call_id=call["id"],
                                      name=call["name"], content=result)
        raise RuntimeError("The model kept calling tools without providing a final answer.")


def tool_spec(name: str, description: str, properties: dict[str, Any],
              required: list[str]) -> dict[str, Any]:
    """Build a tool declaration in the OpenAI function calling format."""
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}

"""Unit tests for the reusable client; all provider responses are local mocks."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import httpx
import openai
import pytest

from src.llm_client import Conversation, LLMClient, RunLog


class FakeCompletions:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def fake_client(completions):
    return NS(chat=NS(completions=completions))


def configured(monkeypatch, completions, **kwargs):
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "unit-test-only")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    return LLMClient(client=fake_client(completions), **kwargs)


def response(content="hello", tool_calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls or []))], model="test-model")


def chunk(content=None, tool_calls=None):
    return NS(choices=[NS(delta=NS(content=content, tool_calls=tool_calls or []))])


def rate_limit(headers=None):
    request = httpx.Request("POST", "https://llm.example/v1/chat/completions")
    response_obj = httpx.Response(429, headers=headers or {}, request=request)
    return openai.RateLimitError("rate limited", response=response_obj, body=None)


def test_environment_configuration_validation(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "true")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(ValueError, match="LLM_BASE_URL.*LLM_API_KEY.*LLM_MODEL"):
        LLMClient()


def test_conversation_initialization_and_message_history(monkeypatch):
    client = configured(monkeypatch, FakeCompletions())
    conversation = Conversation(client, system="system prompt")
    conversation.add_user_message("question")
    conversation.add_assistant_message("answer")
    conversation.add_assistant_tool_calls([{"id": "call-1", "name": "lookup",
                                           "arguments": {"x": 1}}])
    conversation.add_tool_message("call-1", "result", "lookup")
    assert [m["role"] for m in conversation.messages] == ["system", "user", "assistant", "assistant", "tool"]
    assert conversation.messages[-1]["tool_call_id"] == "call-1"
    assert json.loads(conversation.messages[-2]["tool_calls"][0]["function"]["arguments"]) == {"x": 1}


def test_non_streaming_response(monkeypatch):
    client = configured(monkeypatch, FakeCompletions(response("non-streamed")))
    reply = client.chat([{"role": "user", "content": "hi"}], stream=False)
    assert reply.content == "non-streamed"
    assert reply.streamed is False


def test_streaming_reconstruction_and_chunk_count(monkeypatch):
    completions = FakeCompletions([chunk("Hello"), chunk(None), chunk(" world"),
                                   NS(choices=[])])
    client = configured(monkeypatch, completions)
    seen = []
    reply = client.chat([], on_token=seen.append)
    assert reply.content == "Hello world"
    assert reply.chunks == 2
    assert seen == ["Hello", " world"]


def test_rate_limit_retries_and_exponential_wait(tmp_path, monkeypatch):
    completions = FakeCompletions(rate_limit(), rate_limit(), response())
    waits = []
    log = RunLog(tmp_path / "run.jsonl")
    client = configured(monkeypatch, completions, sleep=waits.append, log=log)
    assert client.chat([], stream=False).content == "hello"
    assert len(completions.calls) == 3
    assert waits == [1.0, 2.0]
    events = [json.loads(line) for line in (tmp_path / "run.jsonl").read_text().splitlines()]
    assert [event["wait_s"] for event in events] == [1.0, 2.0]


def test_maximum_total_attempts(monkeypatch):
    completions = FakeCompletions(*[rate_limit() for _ in range(5)])
    client = configured(monkeypatch, completions, sleep=lambda _: None)
    with pytest.raises(openai.RateLimitError):
        client.chat([], stream=False)
    assert len(completions.calls) == 5


def test_retry_after_header(monkeypatch):
    completions = FakeCompletions(rate_limit({"Retry-After": "7.5"}), response())
    waits = []
    client = configured(monkeypatch, completions, sleep=waits.append)
    client.chat([], stream=False)
    assert waits == [7.5]


def test_non_429_error_propagates(monkeypatch):
    error = RuntimeError("bad request")
    client = configured(monkeypatch, FakeCompletions(error), sleep=lambda _: None)
    with pytest.raises(RuntimeError, match="bad request"):
        client.chat([], stream=False)


def test_streaming_tool_argument_reconstruction(monkeypatch):
    one = NS(index=0, id="call-", function=NS(name="get_", arguments='{"country":'))
    two = NS(index=0, id=None, function=NS(name="revenue", arguments='"DE"}'))
    client = configured(monkeypatch, FakeCompletions([chunk(tool_calls=[one]), chunk(tool_calls=[two])]))
    reply = client.chat([], tools=[{"type": "function"}])
    assert reply.tool_calls == [{"id": "call-", "name": "get_revenue",
                                 "arguments": {"country": "DE"}}]


def test_registered_tool_execution_and_matching_tool_id(monkeypatch):
    tool_request = NS(id="call-42", function=NS(name="lookup", arguments='{"value": 4}'))
    completions = FakeCompletions([chunk(tool_calls=[NS(index=0, id=tool_request.id,
                        function=NS(name=tool_request.function.name,
                                    arguments=tool_request.function.arguments))])],
                                   [chunk("done")])
    client = configured(monkeypatch, completions)
    conversation = Conversation(client, tools=[{"type": "function"}],
                                functions={"lookup": lambda value: value * 2})
    assert conversation.ask("go") == "done"
    tool_message = next(message for message in conversation.messages if message["role"] == "tool")
    assert tool_message["tool_call_id"] == "call-42"
    assert tool_message["content"] == "8"


def test_invalid_tool_arguments_are_not_executed(monkeypatch):
    tool_request = NS(index=0, id="call-bad", function=NS(name="lookup", arguments="{bad"))
    completions = FakeCompletions([chunk(tool_calls=[tool_request])], [chunk("handled")])
    called = []
    client = configured(monkeypatch, completions)
    conversation = Conversation(client, functions={"lookup": lambda: called.append(True)})
    assert conversation.ask("go") == "handled"
    tool_message = next(message for message in conversation.messages if message["role"] == "tool")
    assert tool_message["tool_call_id"] == "call-bad"
    assert "Invalid tool arguments" in tool_message["content"]
    assert called == []

import json

import ai
import httpx
import pytest
from fastapi import HTTPException


def mock_client(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        ai.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(ai, "get_key", lambda: "mock-key")


@pytest.mark.asyncio
async def test_real_sse_parser_and_call_ai(monkeypatch):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer mock-key"
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: {"choices":[{"delta":{"content":" world"}}]}\n\ndata: [DONE]\n\n',
        )

    mock_client(monkeypatch, handler)
    assert await ai.call_ai("chat", "hello") == "Hello world"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected", [(401, "Key 无效"), (400, "Token"), (402, "余额"), (404, "模型")]
)
async def test_error_mapping(monkeypatch, status, expected):
    mock_client(monkeypatch, lambda request: httpx.Response(status))
    with pytest.raises(HTTPException, match=expected):
        await ai.call_ai("chat", "hello")


@pytest.mark.asyncio
async def test_retry_before_output(monkeypatch):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count < 3:
            return httpx.Response(503)
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
        )

    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(ai.asyncio, "sleep", no_sleep)
    mock_client(monkeypatch, handler)
    assert await ai.call_ai("chat", "hello") == "ok"
    assert count == 3


@pytest.mark.asyncio
async def test_truncated_stream(monkeypatch):
    mock_client(
        monkeypatch,
        lambda request: httpx.Response(
            200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
        ),
    )
    with pytest.raises(HTTPException, match="中断"):
        await ai.call_ai("chat", "hello")


@pytest.mark.asyncio
async def test_output_ceiling_continues_instead_of_failing(monkeypatch):
    """Hitting the per-response ceiling asks the model to keep writing."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        body = json.loads(request.content)
        assert body["max_tokens"] == ai.MAX_OUTPUT_TOKENS
        if calls["n"] == 1:
            return httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"第一段"}}]}\n\n'
                'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'
                "data: [DONE]\n\n",
            )
        # The continuation asks to carry on rather than starting over.
        assert body["messages"][-1]["content"] == ai.CONTINUE_PROMPT
        assert body["messages"][-2]["content"] == "第一段"
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"第二段"}}]}\n\n'
            "data: [DONE]\n\n",
        )

    mock_client(monkeypatch, handler)
    context = {}
    assert await ai.call_ai("chat", "写一篇长文", context) == "第一段第二段"
    assert calls["n"] == 2
    assert context["truncated"] is False and context["continuations"] == 1


@pytest.mark.asyncio
async def test_the_ceiling_is_bounded_but_nothing_is_discarded(monkeypatch):
    mock_client(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"x"}}]}\n\n'
            'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'
            "data: [DONE]\n\n",
        ),
    )
    context = {}
    text = await ai.call_ai("chat", "hello", context)
    assert text == "x" * (ai.MAX_CONTINUATIONS + 1)
    assert context["truncated"] is True
    assert context["continuations"] == ai.MAX_CONTINUATIONS


@pytest.mark.asyncio
async def test_tool_rounds_are_not_spent_by_continuations(monkeypatch):
    """A truncated tool-call answer must still finish the tool round."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        body = json.loads(request.content)
        tool_message = any(m.get("role") == "tool" for m in body["messages"])
        if not tool_message:
            return httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"先读资料"}}]}\n\n'
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
                '"function":{"name":"read_workspace","arguments":"{\\"action\\":\\"list\\",'
                '\\"kind\\":\\"papers\\"}"}}]}}]}\n\n'
                'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'
                "data: [DONE]\n\n",
            )
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"结论"}}]}\n\n'
            "data: [DONE]\n\n",
        )

    mock_client(monkeypatch, handler)
    assert await ai.call_ai("chat", "总结我的文献") == "先读资料结论"
    assert calls["n"] == 2


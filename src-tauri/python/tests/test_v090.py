"""v0.9: a long answer is continued instead of being thrown away."""

import json

import ai
import httpx
import pytest


def test_a_cut_off_reply_is_kept_and_marked(client, monkeypatch):
    async def fake(task, message, context=None):
        context["truncated"] = True
        yield "很长的一段回答"

    monkeypatch.setattr(ai, "stream_ai", fake)
    body = client.post("/chat", json={"message": "写长一点"}).text
    assert '"truncated": true' in body
    assert "继续" in body  # the note is streamed too, so it shows immediately
    saved = client.get("/conversations").json()[-1]["content"]
    assert saved.startswith("很长的一段回答")
    assert "回复「继续」" in saved


def test_an_ordinary_reply_carries_no_note(client, monkeypatch):
    async def fake(task, message, context=None):
        context["continuations"] = 0
        yield "短回答"

    monkeypatch.setattr(ai, "stream_ai", fake)
    body = client.post("/chat", json={"message": "简短回答"}).text
    assert '"truncated": false' in body
    assert client.get("/conversations").json()[-1]["content"] == "短回答"


def test_continuations_are_reported(client, monkeypatch):
    async def fake(task, message, context=None):
        context["continuations"] = 2
        context["truncated"] = False
        yield "续写完成"

    monkeypatch.setattr(ai, "stream_ai", fake)
    body = client.post("/chat", json={"message": "继续写"}).text
    assert '"continuations": 2' in body
    assert "（这篇回复较长" not in body


@pytest.mark.asyncio
async def test_generation_ceiling_is_the_model_maximum(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        ai.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(ai, "get_key", lambda: "mock-key")
    assert await ai.call_ai("summarize", "总结一下") == "ok"
    # A ceiling, not a target: the largest value the model accepts, so a long
    # answer is never cut short by the client.
    assert seen["max_tokens"] == ai.MAX_OUTPUT_TOKENS == 8192
    assert seen["stream"] is True


@pytest.mark.asyncio
async def test_many_continuations_are_bounded_by_the_round_limit(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"段"}}]}\n\n'
            'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'
            "data: [DONE]\n\n",
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        ai.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(ai, "get_key", lambda: "mock-key")
    context = {}
    text = await ai.call_ai("chat", "一直写", context)
    assert calls["n"] == ai.MAX_CONTINUATIONS + 1
    assert len(text) == ai.MAX_CONTINUATIONS + 1
    assert context["truncated"] is True


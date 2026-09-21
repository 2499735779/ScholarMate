import ai
import db
import main
import pytest
import security
from fastapi import HTTPException


def test_authentication(client):
    assert client.get("/status", headers={"Authorization": ""}).status_code == 401
    assert client.get("/status").status_code == 200


def test_key_never_returned_or_stored_in_database(client, isolated):
    secret = "sk-fixture-123456"
    assert (
        client.put("/settings", json={"model": "deepseek-chat", "api_key": secret}).status_code
        == 200
    )
    assert security.get_key() == secret
    result = client.get("/status")
    assert result.json()["has_key"]
    assert secret not in result.text
    assert secret not in str(db.rows("SELECT * FROM settings"))
    client.put("/settings", json={"model": "custom-model"})
    assert security.get_key() == secret


def test_profile_validation_and_roundtrip(client, profile_data):
    assert client.get("/profile").json() is None
    assert client.put("/profile", json={**profile_data, "weekly_hours": 200}).status_code == 422
    assert client.put("/profile", json=profile_data).status_code == 200
    assert client.get("/profile").json()["specific_interests"] == ["LLM", "PyTorch"]


@pytest.mark.parametrize("task", ["chat", "plan", "summarize", "translate"])
def test_profile_injection(client, profile_data, task):
    client.put("/profile", json=profile_data)
    messages = ai.build_messages(task, "介绍你自己", {"period": "3个月"})
    assert "自然语言处理" in messages[0]["content"]
    assert "复现一篇论文" in messages[0]["content"]
    assert "硕士" in messages[0]["content"]
    assert "3个月" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "介绍你自己"}


def test_chat_stream_and_history(client, monkeypatch):
    async def fake(*args, **kwargs):
        yield "你好，"
        yield "研究者。"

    monkeypatch.setattr(ai, "stream_ai", fake)
    result = client.post("/chat", json={"message": "你好"})
    assert '"delta": "你好，"' in result.text
    assert '"done": true' in result.text
    messages = client.get("/conversations").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == "你好，研究者。"
    assert len(ai.build_messages("chat", "下一问")) == 4
    assert "研究者" in client.get("/conversations/export").text
    assert client.delete("/conversations").status_code == 200
    assert client.get("/conversations").json() == []


def test_failed_stream_does_not_persist(client, monkeypatch):
    async def fake(*args, **kwargs):
        yield "partial"
        raise HTTPException(504, "超时")

    monkeypatch.setattr(ai, "stream_ai", fake)
    result = client.post("/chat", json={"message": "你好"})
    assert "超时" in result.text
    assert client.get("/conversations").json() == []


def test_plan_crud_and_exports(client):
    body = {
        "title": "学习计划",
        "goal": "PyTorch",
        "plan_content": "## 第一周\n\n学习张量与自动求导。",
        "status": "进行中",
    }
    response = client.post("/plans", json=body)
    assert response.status_code == 200
    id = response.json()["id"]
    assert client.get("/plans/" + id).json()["title"] == "学习计划"
    assert (
        client.put("/plans/" + id, json={**body, "status": "已完成"}).json()["status"] == "已完成"
    )
    assert "第一周" in client.get(f"/plans/{id}/export?format=md").text
    assert client.get(f"/plans/{id}/export?format=pdf").content.startswith(b"%PDF")
    assert client.delete("/plans/" + id).status_code == 200
    assert client.get("/plans/" + id).status_code == 404


def test_summary_truncates_and_saves(client, monkeypatch):
    db.execute(
        "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path) VALUES(?,?,?,?,?,?,?)",
        (
            "2609.12345",
            "Paper",
            "Author",
            "abstract",
            "https://arxiv.org/pdf/2609.12345",
            "2026",
            "fixture.pdf",
        ),
    )
    monkeypatch.setattr(main.papers, "extract_text", lambda path: "x" * 12000)

    async def fake(task, message, context=None):
        assert task == "summarize"
        # The excerpt is the opening plus the closing of the paper, not just page 1.
        assert message.count("x") == 8000 and "中间正文省略" in message
        assert context == {"excerpt": True}
        return "结构化总结"

    monkeypatch.setattr(ai, "call_ai", fake)
    assert client.post("/paper/summarize?id=2609.12345").json()["summary"] == "结构化总结"
    assert client.get("/paper?id=2609.12345").json()["summary"] == "结构化总结"
    assert client.get("/paper?id=2609.12345").json()["summary_scope"] == "excerpt"


def test_delete_file_only_preserves_summary(client, tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-fixture")
    db.execute(
        "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path,summary) VALUES(?,?,?,?,?,?,?,?)",
        ("2609.12345", "Paper", "Author", "abstract", "url", "2026", str(path), "keep"),
    )
    assert client.delete("/paper?id=2609.12345&remove_record=false").status_code == 200
    assert not path.exists()
    assert client.get("/paper?id=2609.12345").json()["summary"] == "keep"
    assert client.get("/papers").json() == []


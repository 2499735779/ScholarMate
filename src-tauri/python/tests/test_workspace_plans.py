import json
import sqlite3

import ai
import db
import httpx
import pytest
import workspace
from plan_detection import detect_plan


def proposal():
    return (
        "为你制定如下计划：\n```scholarmate-plan\n"
        + json.dumps(
            {
                "title": "PyTorch 三周计划",
                "goal": "完成分类项目",
                "plan_content": "## 第一周\n- 张量训练\n## 第二周\n- 完成实验",
            },
            ensure_ascii=False,
        )
        + "\n```"
    )


def seed_message(content=None):
    db.execute(
        "INSERT INTO conversations(id,role,content) VALUES(?,?,?)",
        ("reply", "assistant", content or proposal()),
    )


def test_adopt_idempotent_and_survives_history_clear(client):
    seed_message()
    history = client.get("/conversations").json()
    assert history[0]["plan_candidate"]["title"] == "PyTorch 三周计划"
    assert len(client.get("/conversations/plan-candidates").json()) == 1
    p = client.post("/plans/adopt", json={"message_id": "reply"}).json()
    again = client.post("/plans/adopt", json={"message_id": "reply"}).json()
    assert p["id"] == again["id"]
    assert len(client.get("/plans").json()) == 1
    assert client.get("/conversations/plan-candidates").json() == []
    assert client.get("/conversations").json()[0]["adopted_plan_id"] == p["id"]
    client.delete("/conversations")
    kept = client.get("/plans/" + p["id"]).json()
    assert kept["source_content"] == proposal()
    assert kept["source_message_id"] == "reply"


def test_no_plan_or_user_message_cannot_adopt(client):
    seed_message("你可以先想想学习目标，再考虑是否生成计划。")
    assert client.post("/plans/adopt", json={"message_id": "reply"}).status_code == 422
    assert client.post("/plans/adopt", json={"message_id": "missing"}).status_code == 422
    db.execute("UPDATE conversations SET role='user',content=?", (proposal(),))
    assert client.post("/plans/adopt", json={"message_id": "reply"}).status_code == 422


def test_legacy_detection():
    content = "# 深度学习学习计划\n\n## 第一周\n- 每天学习张量运算，并进行自动求导实验。\n## 第二周\n- 使用卷积网络完成分类训练，记录准确率与误差曲线。\n## 第三周\n- 完成项目报告，复盘数据增强的实际效果。"
    assert detect_plan(content)["detection"] == "markdown"
    assert detect_plan("学习计划是什么意思？") is None
    assert detect_plan("```scholarmate-plan\nnull\n```") is None


def test_upgrade_migration_preserves_data(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    with sqlite3.connect(tmp_path / "scholarmate.db") as conn:
        conn.execute(
            "CREATE TABLE learning_plans (id TEXT PRIMARY KEY,title TEXT,goal TEXT,plan_content TEXT,created_at TEXT,status TEXT)"
        )
        conn.execute(
            "INSERT INTO learning_plans VALUES('old','旧计划','目标','正文','2026','进行中')"
        )
    db.init_db()
    db.init_db()
    assert db.rows("SELECT * FROM learning_plans")[0]["plan_content"] == "正文"
    assert db.rows("SELECT * FROM learning_plans")[0]["source_message_id"] is None


def seed_workspace():
    db.execute(
        "INSERT INTO learning_plans(id,title,goal,plan_content) VALUES('p1','论文复现','提高准确率','每周八小时，研究对比学习')"
    )
    db.execute(
        "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,summary) VALUES('paper1','Contrastive Learning','Author','Abstract detail','https://arxiv.org/pdf/1','2026','Important summary')"
    )


@pytest.mark.parametrize("task", ["chat", "plan", "summarize", "translate"])
def test_all_tasks_see_saved_workspace(task):
    seed_workspace()
    system = ai.build_messages(task, "你好")[0]["content"]
    assert "每周八小时" in system and "Abstract detail" in system and "Important summary" in system
    db.execute("UPDATE learning_plans SET status='已完成'")
    assert "已完成" in ai.build_messages(task, "你好")[0]["content"]


def test_full_pdf_and_large_plan_paging(monkeypatch):
    seed_workspace()
    db.execute("UPDATE learning_plans SET plan_content=?", ("a" * 50000 + "END",))
    assert json.loads(workspace.snapshot())["incomplete"]
    assert workspace.read_workspace({"action": "list", "kind": "plans"})["total"] == 1
    text = ""
    offset = 0
    while True:
        result = workspace.read_workspace({"action": "plan", "id": "p1", "offset": offset})
        text += result["text"]
        offset = result["next_offset"]
        if offset is None:
            break
    assert "END" in text
    monkeypatch.setattr(workspace, "extract_text", lambda _: "PDF" * 5000 + "FINAL")
    chunk = workspace.read_workspace({"action": "pdf", "id": "paper1", "offset": 8000})
    assert chunk["text"].endswith("FINAL")
    assert workspace.read_workspace({"action": "delete", "id": "p1"}).get("error")


@pytest.mark.asyncio
async def test_stream_tool_roundtrip(monkeypatch):
    seed_workspace()
    original = httpx.AsyncClient
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            chunks = [
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call1",
                            "function": {
                                "name": "read_workspace",
                                "arguments": '{"action":"plan",',
                            },
                        }
                    ]
                },
                {"tool_calls": [{"index": 0, "function": {"arguments": '"id":"p1"}'}}]},
            ]
            return httpx.Response(
                200,
                text="".join(
                    "data: " + json.dumps({"choices": [{"delta": d}]}) + "\n\n" for d in chunks
                )
                + "data: [DONE]\n\n",
            )
        assert payload["messages"][-1]["role"] == "tool"
        assert "每周八小时" in payload["messages"][-1]["content"]
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"结合你的计划回答"}}]}\n\ndata: [DONE]\n\n',
        )

    monkeypatch.setattr(
        ai.httpx, "AsyncClient", lambda **_: original(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(ai, "get_key", lambda: "mock")
    assert await ai.call_ai("chat", "我的计划是什么") == "结合你的计划回答"
    assert len(requests) == 2


def test_connection_test_skips_workspace():
    seed_workspace()
    assert (
        "Important summary"
        not in ai.build_messages("chat", "OK", {"connection_test": True})[0]["content"]
    )


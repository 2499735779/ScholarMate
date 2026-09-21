"""v0.8: several conversations and several profiles side by side."""

import json

import ai
import db
import main


def chat(client, monkeypatch, captured, text, thread_id=""):
    async def fake(task, message, context=None):
        captured.append(ai.build_messages(task, message, context))
        yield "好的，" + message[:6]

    monkeypatch.setattr(ai, "stream_ai", fake)
    body = {"message": text}
    if thread_id:
        body["thread_id"] = thread_id
    return client.post("/chat", json=body).text


def test_legacy_single_profile_and_flat_log_are_migrated(client, profile_data):
    """An upgrade from the single-profile version must keep everything."""
    db.execute("DELETE FROM profiles")
    db.execute("DELETE FROM chat_threads")
    db.execute("UPDATE conversations SET thread_id='',profile_id=''")
    db.execute("UPDATE settings SET active_profile_id='' WHERE id=1")
    db.execute(
        "INSERT OR REPLACE INTO user_profile(id,major,degree,research_field,specific_interests,"
        "short_term_goal,long_term_goal,weekly_hours,language_preference,custom_instructions) "
        "VALUES(1,?,?,?,?,?,?,?,?,?)",
        (
            profile_data["major"],
            profile_data["degree"],
            profile_data["research_field"],
            json.dumps(profile_data["specific_interests"], ensure_ascii=False),
            profile_data["short_term_goal"],
            profile_data["long_term_goal"],
            profile_data["weekly_hours"],
            profile_data["language_preference"],
            profile_data["custom_instructions"],
        ),
    )
    db.execute("INSERT INTO conversations(id,role,content) VALUES('legacy-1','user','旧版消息')")
    db.init_db()

    listing = client.get("/profiles").json()
    assert len(listing["items"]) == 1
    migrated = listing["items"][0]
    assert migrated["name"] == "自然语言处理"
    assert migrated["specific_interests"] == ["LLM", "PyTorch"]
    assert migrated["id"] == listing["active_id"]
    assert client.get("/status").json()["has_profile"] is True

    threads = client.get("/threads").json()
    assert len(threads) == 1 and threads[0]["title"] == "历史对话"
    messages = client.get("/threads/" + threads[0]["id"]).json()["messages"]
    assert [m["content"] for m in messages] == ["旧版消息"]
    assert client.get("/conversations").json()[0]["content"] == "旧版消息"


def test_profiles_keep_each_direction_apart(client, profile_data):
    first = client.put("/profile", json=profile_data).json()
    assert first["name"] == "自然语言处理" and first["active"] is True

    second = client.post(
        "/profiles",
        json={**profile_data, "name": "方向 B · 医学影像", "research_field": "医学影像分割"},
    ).json()
    assert second["active"] is True and second["name"] == "方向 B · 医学影像"
    assert [p["name"] for p in client.get("/profiles").json()["items"]] == [
        "方向 B · 医学影像",
        "自然语言处理",
    ]
    # The active profile is what /profile and every AI task use.
    assert client.get("/profile").json()["research_field"] == "医学影像分割"
    assert client.post(f"/profiles/{first['id']}/activate").json()["active"] is True
    assert client.get("/profile").json()["research_field"] == "自然语言处理"

    client.put(
        f"/profiles/{second['id']}",
        json={**profile_data, "name": "方向 B · 医学影像", "research_field": "医学图像处理"},
    )
    assert client.get("/profile").json()["research_field"] == "自然语言处理"
    edited = [p for p in client.get("/profiles").json()["items"] if p["id"] == second["id"]][0]
    assert edited["research_field"] == "医学图像处理"

    assert client.delete(f"/profiles/{second['id']}").status_code == 200
    assert [p["name"] for p in client.get("/profiles").json()["items"]] == ["自然语言处理"]
    assert client.delete(f"/profiles/{first['id']}").status_code == 409
    assert client.delete("/profiles/pf-missing").status_code == 404


def test_deleting_a_profile_keeps_its_conversations_working(client, profile_data, monkeypatch):
    captured = []
    first = client.put("/profile", json=profile_data).json()
    second = client.post(
        "/profiles", json={**profile_data, "name": "方向 B", "research_field": "医学影像"}
    ).json()
    thread = client.post("/threads", json={"profile_id": second["id"]}).json()
    chat(client, monkeypatch, captured, "在方向 B 里提问", thread["id"])

    client.post(f"/profiles/{first['id']}/activate")
    assert client.delete(f"/profiles/{second['id']}").status_code == 200
    moved = client.get("/threads/" + thread["id"]).json()["thread"]
    assert moved["profile_id"] == first["id"] and moved["profile_name"] == "自然语言处理"
    # The conversation still answers, now with the remaining profile.
    chat(client, monkeypatch, captured, "继续", thread["id"])
    assert "自然语言处理" in captured[-1][0]["content"]


def test_new_conversation_keeps_history_and_resets_context(client, profile_data, monkeypatch):
    captured = []
    client.put("/profile", json=profile_data)
    created_before = client.post("/threads", json={}).json()
    assert created_before["profile_id"] == client.get("/profiles").json()["active_id"]
    # The placeholder title is replaced by the first real question.
    first = chat(client, monkeypatch, captured, "第一条对话的问题", created_before["id"])
    assert '"done": true' in first
    threads = client.get("/threads").json()
    assert len(threads) == 1
    thread = threads[0]
    assert thread["title"] == "第一条对话的问题"
    assert thread["message_count"] == 2

    # A new conversation starts clean instead of continuing the broken one.
    created = client.post("/threads", json={}).json()
    assert created["title"] == "新对话" and created["message_count"] == 0
    chat(client, monkeypatch, captured, "第二条对话的问题", created["id"])
    replayed = json.dumps(captured[-1], ensure_ascii=False)
    assert "第二条对话的问题" in replayed
    assert "第一条对话的问题" not in replayed

    listing = client.get("/threads").json()
    assert [t["id"] for t in listing][0] == created["id"]  # most recent first
    assert listing[0]["message_count"] == 2
    assert "第二条对话的问题" in listing[0]["preview"]
    old = client.get("/threads/" + created_before["id"]).json()
    assert [m["content"] for m in old["messages"]][-1].startswith("好的")


def test_thread_rename_export_and_delete(client, monkeypatch):
    captured = []
    chat(client, monkeypatch, captured, "写一份阅读计划")
    thread = client.get("/threads").json()[0]
    renamed = client.put("/threads/" + thread["id"], json={"title": "论文精读"}).json()
    assert renamed["title"] == "论文精读"
    assert "论文精读" in client.get(f"/threads/{thread['id']}/export").text
    assert client.put("/threads/" + thread["id"], json={"profile_id": "pf-none"}).status_code == 404
    assert client.get("/threads/th-missing").status_code == 404
    assert client.delete("/threads/th-missing").status_code == 404

    # A second conversation survives deleting the first.
    other = client.post("/threads", json={}).json()
    assert client.delete("/threads/" + thread["id"]).status_code == 200
    assert [t["id"] for t in client.get("/threads").json()] == [other["id"]]
    assert client.get("/threads/" + thread["id"]).status_code == 404
    assert client.get("/conversations").json() == []


def test_each_conversation_remembers_its_profile(client, profile_data, monkeypatch):
    captured = []
    client.put("/profile", json=profile_data)
    thread_a = client.post("/threads", json={}).json()
    chat(client, monkeypatch, captured, "方向 A 的问题", thread_a["id"])
    assert "自然语言处理" in captured[-1][0]["content"]

    # The user starts a second direction without editing the first profile.
    second = client.post(
        "/profiles", json={**profile_data, "name": "方向 B", "research_field": "医学影像分割"}
    ).json()
    thread_b = client.post("/threads", json={}).json()
    chat(client, monkeypatch, captured, "方向 B 的问题", thread_b["id"])
    assert "医学影像分割" in captured[-1][0]["content"]

    # Continuing the first conversation still uses direction A.
    chat(client, monkeypatch, captured, "继续方向 A", thread_a["id"])
    assert "自然语言处理" in captured[-1][0]["content"]
    assert "医学影像分割" not in captured[-1][0]["content"]

    # Switching the active profile does not rewrite existing conversations.
    client.post(f"/profiles/{second['id']}/activate")
    assert client.get("/threads/" + thread_a["id"]).json()["thread"]["profile_id"] != second["id"]
    assert client.get("/status").json()["profile_id"] == second["id"]


def test_plan_candidates_see_every_conversation(client, monkeypatch):
    async def fake(*args, **kwargs):
        yield (
            "这是计划：\n```scholarmate-plan\n"
            + json.dumps(
                {"title": "计划", "goal": "目标", "plan_content": "## 第 1 周\n- 读书"},
                ensure_ascii=False,
            )
            + "\n```"
        )

    monkeypatch.setattr(ai, "stream_ai", fake)
    first = client.post("/chat", json={"message": "第一条"}).text
    thread_a = json.loads(
        [line[6:] for line in first.split("\n\n") if '"done"' in line][0]
    )["thread"]["id"]
    client.post("/threads", json={})
    client.post("/chat", json={"message": "第二条"}).text

    candidates = client.get("/conversations/plan-candidates").json()
    assert len(candidates) == 2
    assert {m["plan_candidate"]["title"] for m in candidates} == {"计划"}
    assert len(client.get("/conversations").json()) == 4
    assert len(client.get("/threads/" + thread_a).json()["messages"]) == 2


def test_chat_rejects_a_deleted_conversation(client, monkeypatch):
    captured = []
    chat(client, monkeypatch, captured, "先聊一句")
    thread = client.get("/threads").json()[0]
    client.delete("/threads/" + thread["id"])
    response = client.post("/chat", json={"message": "还在吗", "thread_id": thread["id"]})
    assert response.status_code == 404


def test_a_new_profile_can_be_started_from_just_a_name(client, profile_data):
    """Clicking "新建画像" creates an empty profile the user fills in afterwards."""
    client.put("/profile", json=profile_data)
    created = client.post("/profiles", json={"name": "新画像", "major": "", "research_field": ""})
    assert created.status_code == 200, created.text
    profile = created.json()
    assert profile["name"] == "新画像" and profile["major"] == ""
    assert profile["active"] is True and profile["degree"] == "硕士"
    assert client.get("/profile").json()["name"] == "新画像"
    # It is listed first, so a new profile never hides behind older ones.
    listing = client.get("/profiles").json()
    assert [p["name"] for p in listing["items"]] == ["新画像", "自然语言处理"]
    assert listing["active_id"] == profile["id"]
    # Filling it in later works, and the other profile is untouched.
    filled = client.put(
        f"/profiles/{profile['id']}",
        json={**profile_data, "name": "方向 B", "research_field": "医学影像"},
    ).json()
    assert filled["research_field"] == "医学影像"
    assert [p["research_field"] for p in client.get("/profiles").json()["items"]] == [
        "医学影像",
        "自然语言处理",
    ]


def test_status_reports_the_active_profile(client, profile_data):
    assert client.get("/status").json()["profile_name"] == ""
    client.put("/profile", json=profile_data)
    status = client.get("/status").json()
    assert status["profile_name"] == "自然语言处理"
    assert status["profile_count"] == 1
    assert status["profile_id"] == client.get("/profiles").json()["active_id"]


def test_clear_all_removes_threads_too(client, monkeypatch):
    captured = []
    chat(client, monkeypatch, captured, "一句话")
    client.post("/threads", json={})
    assert client.delete("/conversations").status_code == 200
    assert client.get("/threads").json() == []
    # The next message starts a fresh conversation automatically.
    chat(client, monkeypatch, captured, "重新开始")
    assert len(client.get("/threads").json()) == 1
    assert main.thread_title("  \n  ") == "新对话"


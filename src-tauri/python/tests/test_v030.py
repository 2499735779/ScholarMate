import base64
import json
from datetime import date, timedelta

import ai
import db
import discovery
import httpx
import papers
import pytest
import schedule
import security
from fastapi import HTTPException


def make_plan(client):
    return client.post(
        "/plans",
        json={"title": "试验", "plan_content": "## 第 1 周\n- 阅读基础\n## 第 2 周\n- 完成实验"},
    ).json()


def seed_paper(tmp_path):
    path = tmp_path / "p.pdf"
    path.write_bytes(b"%PDF-fixture")
    db.execute(
        "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path,publication_type,venue,pages) VALUES('p','Neural networks','A, B, C, D','machine learning','','2026',?,'journal','Journal of AI','1-12')",
        (str(path),),
    )
    return path


def test_calendar_tasks_and_progress(client):
    p = make_plan(client)
    assert p["start_date"] == schedule.monday().isoformat()
    data = client.get("/dashboard").json()["plans"][0]
    assert data["current_week"] == 1 and len(data["week_tasks"]) == 1
    task = data["week_tasks"][0]
    assert client.put("/plan-tasks/" + task["id"], json={"done": True}).status_code == 200
    assert client.get("/dashboard").json()["plans"][0]["done_count"] == 1
    client.put("/plans/" + p["id"], json={**p, "title": "改名"})
    assert client.get("/dashboard").json()["plans"][0]["done_count"] == 1
    client.post(f"/plan-schedule/{p['id']}/tasks", json={"week": 1, "title": "自定义"})
    assert client.get("/dashboard").json()["plans"][0]["task_count"] == 3


def test_pause_resume_skips_weeks_and_future_start(client):
    p = make_plan(client)
    old = schedule.monday() - timedelta(weeks=4)
    paused = schedule.monday() - timedelta(weeks=2)
    db.execute(
        "UPDATE learning_plans SET start_date=?,paused_on=? WHERE id=?",
        (old.isoformat(), paused.isoformat(), p["id"]),
    )
    assert client.get(f"/plan-schedule/{p['id']}").json()["current_week"] == 3
    resumed = client.put(f"/plan-schedule/{p['id']}", json={"paused": False}).json()
    assert resumed["current_week"] == 3 and resumed["paused_on"] is None
    future = client.put(
        f"/plan-schedule/{p['id']}",
        json={"start_date": (schedule.monday() + timedelta(weeks=2)).isoformat()},
    ).json()
    assert future["current_week"] == 0


def test_week_parser_chinese_ranges_tables():
    assert schedule.parse_tasks("## 第一至二周\n- 阅读\n## Week 3\n- Exercise") == [
        (1, "阅读"),
        (2, "阅读"),
        (3, "Exercise"),
    ]
    assert schedule.parse_tasks("| 第 4 周 | 训练模型 | 写报告 |") == [(4, "训练模型；写报告")]
    assert schedule.parse_tasks("这是没有明确周数的学习计划。") == []


def test_reject_restore_and_delete_do_not_resurface(client):
    content = (
        "```scholarmate-plan\n"
        + json.dumps({"title": "研究", "goal": "论文", "plan_content": "## 第1周\n- 阅读"})
        + "\n```"
    )
    db.execute("INSERT INTO conversations(id,role,content) VALUES('r','assistant',?)", (content,))
    assert client.put("/conversations/r/proposal", json={"rejected": True}).status_code == 200
    assert client.get("/conversations/plan-candidates").json() == []
    assert client.post("/plans/adopt", json={"message_id": "r"}).status_code == 409
    client.put("/conversations/r/proposal", json={"rejected": False})
    p = client.post("/plans/adopt", json={"message_id": "r"}).json()
    assert client.put("/conversations/r/proposal", json={"rejected": True}).status_code == 409
    client.delete("/plans/" + p["id"])
    assert db.rows("SELECT * FROM plan_tasks") == []
    assert client.get("/conversations/plan-candidates").json() == []


def test_missing_files_hidden_and_return_when_restored(client, tmp_path):
    path = seed_paper(tmp_path)
    assert len(client.get("/papers").json()) == 1
    path.unlink()
    assert client.get("/papers").json() == []
    assert client.get("/paper?id=p").json()["title"] == "Neural networks"
    path.write_bytes(b"%PDF-restored")
    assert len(client.get("/papers").json()) == 1


def test_citation_real_type_original_title_and_missing_fields(client, tmp_path):
    seed_paper(tmp_path)
    db.execute("UPDATE papers SET title_zh='神经网络' WHERE id='p'")
    c = client.get("/paper/citation?id=p").json()
    assert "Neural networks[J]" in c["text"] and "et al." in c["text"]
    assert "神经网络" not in c["text"] and c["complete"]
    # Unknown elements are dropped instead of printed as placeholders.
    db.execute("UPDATE papers SET publication_type='thesis',publisher='',place='' WHERE id='p'")
    c = client.get("/paper/citation?id=p").json()
    assert c["text"] == "[1] A, B, C, et al. Neural networks[D]. 2026."
    assert "学位授予单位" in c["missing"] and not c["complete"]
    assert "〔" not in c["text"]


def test_import_deduplicates_and_rejects_non_pdf(client):
    body = {"filename": "中文论文.pdf", "data": base64.b64encode(b"%PDF-fixture").decode()}
    first = client.post("/library/import", json=body)
    assert first.status_code == 200
    assert client.post("/library/import", json=body).json()["id"] == first.json()["id"]
    assert len(client.get("/papers").json()) == 1
    assert (
        client.post(
            "/library/import", json={**body, "data": base64.b64encode(b"not pdf").decode()}
        ).status_code
        == 422
    )


def test_auto_translate_classify_search_and_retry(client, tmp_path, monkeypatch):
    seed_paper(tmp_path)
    security.save_key("fake")

    async def fake(task, message, context=None):
        assert context == {"isolated": True}
        return json.dumps(
            {"title_zh": "神经网络", "category": "计算机与人工智能", "tags": "机器学习,神经网络"}
        )

    monkeypatch.setattr(ai, "call_ai", fake)
    assert client.post("/library/enrich").json()["updated"] == 1
    assert len(client.get("/papers?q=神经网络").json()) == 1
    assert client.post("/library/enrich").json()["updated"] == 0


@pytest.mark.asyncio
async def test_federation_dedup_and_partial_failure(monkeypatch):
    async def fake(source, q, limit):
        if source == "arxiv":
            raise httpx.ConnectError("offline")
        return [{"id": source, "title": "test", "doi": "10.1/same"}]

    monkeypatch.setattr(discovery, "provider_search", fake)
    result = await discovery.search("中文")
    assert len(result["items"]) == 1 and len(result["warnings"]) == 1


def test_crossref_metadata_and_download_boundaries():
    p = discovery.crossref(
        {
            "DOI": "10.1/test",
            "title": ["标题"],
            "type": "journal-article",
            "published": {"date-parts": [[2026, 1, 2]]},
            "container-title": ["期刊"],
            "link": [{"content-type": "application/pdf", "URL": "https://127.0.0.1/private"}],
        }
    )
    assert p["title"] == "标题" and p["publication_type"] == "journal" and p["pdf_url"] == ""
    assert discovery.allowed_pdf("https://europepmc.org/articles/PMC123?pdf=render")
    assert not discovery.allowed_pdf("https://europepmc.org.evil.example/paper.pdf")
    assert not discovery.allowed_pdf("https://user@europepmc.org/paper.pdf")


def test_migration_repeat_preserves_schedule(client):
    p = make_plan(client)
    client.put(f"/plan-schedule/{p['id']}", json={"paused": True})
    db.init_db()
    db.init_db()
    assert client.get(f"/plan-schedule/{p['id']}").json()["paused_on"] == date.today().isoformat()


def test_enrichment_does_not_overwrite_edits_during_request(client, tmp_path, monkeypatch):
    seed_paper(tmp_path)
    security.save_key("fixture")

    async def fake(task, message, context=None):
        db.execute("UPDATE papers SET title_zh='用户校正标题',category='自定义分类' WHERE id='p'")
        return json.dumps({"title_zh": "模型标题", "category": "计算机与人工智能", "tags": "标签"})

    monkeypatch.setattr(ai, "call_ai", fake)
    client.post("/library/enrich")
    p = client.get("/paper?id=p").json()
    assert p["title_zh"] == "用户校正标题" and p["category"] == "自定义分类"


@pytest.mark.asyncio
async def test_europepmc_adapter_uses_open_access_only(monkeypatch):
    original = httpx.AsyncClient

    def response(request):
        assert request.url.params["resultType"] == "core"
        return httpx.Response(
            200,
            json={
                "resultList": {
                    "result": [
                        {
                            "id": "1",
                            "source": "MED",
                            "title": "Paper",
                            "pmcid": "PMC123",
                            "isOpenAccess": "Y",
                            "journalInfo": {"journal": {"title": "Journal"}},
                        },
                        {
                            "id": "2",
                            "source": "MED",
                            "title": "Closed paper",
                            "pmcid": "PMC124",
                            "isOpenAccess": "N",
                        },
                    ]
                }
            },
        )

    monkeypatch.setattr(
        discovery.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(response)),
    )
    items = await discovery.provider_search("europepmc", "test", 2)
    assert items[0]["pdf_url"].startswith("https://europepmc.org/")
    assert items[1]["pdf_url"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect", [False, True])
async def test_multi_source_download_and_redirect_boundary(monkeypatch, tmp_path, redirect):
    original = httpx.AsyncClient

    def response(request):
        if redirect:
            return httpx.Response(302, headers={"location": "https://127.0.0.1/private.pdf"})
        return httpx.Response(200, content=b"%PDF-1.7 fixture")

    monkeypatch.setattr(
        papers.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(response)),
    )

    async def download():
        return [
            p
            async for p in papers.download_pdf(
                "pmc-MED-1", str(tmp_path), "https://europepmc.org/articles/PMC123?pdf=render"
            )
        ]

    if redirect:
        with pytest.raises(HTTPException):
            await download()
        assert not list(tmp_path.glob("*.pdf"))
    else:
        assert (await download())[-1]["progress"] == 100
    assert not list(tmp_path.glob("*.part"))


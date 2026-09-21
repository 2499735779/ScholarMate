"""v0.10: the summary reads both ends of a paper, or digests the whole text."""

import ai
import db
import main
import papers

OPENING = "标题：智慧城市供水管网漏损定位研究\n作者：杨晓蕾\n摘要：本文提出基于拓扑分析的定位方法。" + "开" * 4000
MIDDLE = "方法：本文使用图卷积网络对管段建模，并在三个数据集上做了消融实验。" + "中" * 12000
CLOSING = "结论：该方法将定位误差降低了 37%，在真实管网中同样有效。" + "尾" * 2000


def long_text():
    return OPENING + "\n\n" + MIDDLE + "\n\n" + CLOSING


def seed_paper(text):
    db.execute(
        "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path) "
        "VALUES('p1','Paper','Author','abstract','','2026','fixture.pdf')"
    )
    main.papers.extract_text = lambda path: text


def test_excerpt_reads_the_opening_and_the_closing():
    excerpt, truncated = papers.summary_excerpt(long_text(), 8000)
    assert truncated is True
    assert excerpt.startswith("标题：智慧城市供水管网漏损定位研究")
    # The conclusion at the very end is included, which the old first-8000 slice missed.
    assert "定位误差降低了 37%" in excerpt
    assert "中间正文省略" in excerpt
    assert len(excerpt) <= 8600  # budget plus boundary slack


def test_short_papers_are_used_as_they_are():
    short = "只有一小段正文。"
    excerpt, truncated = papers.summary_excerpt(short, 8000)
    assert excerpt == short and truncated is False


def test_the_excerpt_cuts_on_a_boundary_not_mid_sentence():
    # No paragraph break near the cut: fall back to the nearest sentence end.
    text = ("句子结束。" * 700) + "未完" + ("句子结束。" * 700)
    excerpt, _ = papers.summary_excerpt(text, 8000)
    head = excerpt.split("【……中间正文省略……】")[0]
    assert head.endswith("句子结束。")
    assert "未完" in excerpt  # the tail still carries the middle marker text


def test_digest_chunks_cover_the_whole_document_evenly():
    long_body = "\n\n".join(f"第 {index} 节的正文内容。" + "文" * 900 for index in range(200))
    chunks = papers.digest_chunks(long_body, 7000, 14)
    assert len(chunks) == 14  # a very long document is sampled down to the limit
    assert all(len(chunk) <= 7000 for chunk in chunks)
    assert "第 0 节" in chunks[0] and "第 199 节" in chunks[-1]
    # The middle of the paper is represented too, not just the first pages.
    assert any(
        any(f"第 {index} 节" in chunk for chunk in chunks) for index in range(90, 111)
    )
    assert papers.digest_chunks("   ") == []
    assert len(papers.digest_chunks("一段短文字", 7000, 14)) == 1


def test_digest_chunks_keep_a_short_document_in_one_piece():
    body = "\n\n".join(f"第 {index} 节。" + "文" * 900 for index in range(6))
    chunks = papers.digest_chunks(body, 7000, 14)
    assert len(chunks) == len(papers.digest_chunks(body, 7000, 99)) == 1


def test_excerpt_summary_tells_the_model_what_it_read(client, monkeypatch):
    seen = {}

    async def fake(task, message, context=None):
        seen["task"] = task
        seen["message"] = message
        seen["context"] = context
        seen["system"] = ai.build_messages(task, message, context)[0]["content"]
        return "结构化总结"

    monkeypatch.setattr(ai, "call_ai", fake)
    db.execute(
        "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path) "
        "VALUES('p1','Paper','Author','abstract','','2026','fixture.pdf')"
    )
    monkeypatch.setattr(main.papers, "extract_text", lambda path: long_text())
    result = client.post("/paper/summarize?id=p1&scope=excerpt").json()
    assert result["summary"] == "结构化总结" and result["scope"] == "excerpt"
    assert result["chunks"] == 0 and result["characters"] == len(long_text())
    assert "开头与结尾" in result["note"]
    assert "定位误差降低了 37%" in seen["message"]
    # The system prompt explains the excerpt and points at the read tool.
    assert "read_workspace" in seen["system"]
    saved = client.get("/paper?id=p1").json()
    assert saved["summary_scope"] == "excerpt"
    assert saved["summary_characters"] == len(long_text())


def test_full_summary_digests_every_section_then_merges(client, monkeypatch):
    calls = []

    async def fake(task, message, context=None):
        calls.append((task, message, context))
        if task == "digest":
            return "方法：要点 " + message[-6:]
        return "最终总结"

    monkeypatch.setattr(ai, "call_ai", fake)
    db.execute(
        "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path) "
        "VALUES('p2','Paper','Author','abstract','','2026','fixture.pdf')"
    )
    monkeypatch.setattr(main.papers, "extract_text", lambda path: long_text())
    result = client.post("/paper/summarize?id=p2&scope=full").json()
    digests = [c for c in calls if c[0] == "digest"]
    merges = [c for c in calls if c[0] == "summarize"]
    assert result["summary"] == "最终总结" and result["scope"] == "full"
    assert result["chunks"] == len(digests) >= 2
    assert len(merges) == 1
    # Section digests are focused and cheap, so they skip the workspace context.
    assert all(c[2] == {"isolated": True} for c in digests)
    assert all(c[2] == {"isolated": True} for c in merges)
    assert "分段精读" in merges[0][1] and str(result["characters"]) in merges[0][1]
    assert "定位误差降低了 37%" in digests[-1][1]  # the conclusion section is read
    saved = client.get("/paper?id=p2").json()
    assert saved["summary_scope"] == "full"


def test_summary_modes_reject_unknown_scope(client):
    db.execute(
        "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path) "
        "VALUES('p3','Paper','Author','abstract','','2026','fixture.pdf')"
    )
    assert client.post("/paper/summarize?id=p3&scope=everything").status_code == 422
    assert client.post("/paper/summarize?id=missing").status_code == 404


def test_scanned_pdf_still_reports_a_clear_error(client, monkeypatch):
    db.execute(
        "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path) "
        "VALUES('p4','Paper','Author','abstract','','2026','fixture.pdf')"
    )
    monkeypatch.setattr(
        main.papers,
        "extract_text",
        lambda path: (_ for _ in ()).throw(
            __import__("fastapi").HTTPException(422, "该 PDF 可能是扫描件")
        ),
    )
    assert client.post("/paper/summarize?id=p4&scope=full").status_code == 422


def test_legacy_rows_without_a_scope_still_render(client, monkeypatch):
    """Summaries saved by earlier versions have no scope; the UI falls back."""
    db.execute(
        "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path,summary) "
        "VALUES('p5','Paper','Author','abstract','','2026','fixture.pdf','旧总结')"
    )
    saved = client.get("/paper?id=p5").json()
    assert saved["summary"] == "旧总结" and not saved["summary_scope"]


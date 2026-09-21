import base64
import json

import ai
import bibliography
import db
from pypdf import PdfWriter


def pdf(path):
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.write(path)
    return path


def test_link_no_copy_and_delete_preserves_original(client, tmp_path):
    source = pdf(tmp_path / "original.pdf")
    before = source.read_bytes()
    r = client.post("/library/link", json={"path": str(source)})
    assert r.status_code == 200
    p = r.json()
    assert p["storage_mode"] == "linked" and p["local_path"] == str(source.resolve())
    assert not (db.DATA_DIR / "papers").exists()
    response = client.get("/paper/file", params={"id": p["id"]})
    assert response.content == before and response.headers["cache-control"] == "no-store"
    assert (
        client.get(
            "/paper/file", params={"id": p["id"]}, headers={"Authorization": "bad"}
        ).status_code
        == 401
    )
    client.delete("/paper", params={"id": p["id"], "remove_record": True})
    assert source.read_bytes() == before


def test_relink_only_removes_verified_legacy_copy(client, tmp_path):
    source = pdf(tmp_path / "original.pdf")
    p = client.post(
        "/library/import",
        json={"filename": source.name, "data": base64.b64encode(source.read_bytes()).decode()},
    ).json()
    from pathlib import Path

    old = Path(p["local_path"])
    different = tmp_path / "different.pdf"
    different.write_bytes(source.read_bytes() + b"\n%different")
    assert (
        client.post(
            "/library/link",
            json={"path": str(different), "replace_id": p["id"], "cleanup_copy": True},
        ).status_code
        == 409
    )
    assert old.exists()
    r = client.post(
        "/library/link", json={"path": str(source), "replace_id": p["id"], "cleanup_copy": True}
    ).json()
    assert r["freed_bytes"] == source.stat().st_size
    assert not old.exists() and source.exists()


def test_content_title_uses_body_not_random_name(monkeypatch):
    header = "第52卷第3期\n2026年6月\n信 息 化 研 究\nInformatizationResearch\nVol.52No.3\nJun.2026\nGIS拓扑分析在智慧城市供水管网漏损定位中的\n应用优化与关键技术研究\n杨晓蕾1\n大连理工大学城市学院\n"

    class Page:
        mediabox = type("Box", (), {"height": 800})()

        def extract_text(self, **kwargs):
            return header + "摘要:研究供水管网定位。\n关键词:GIS拓扑分析;供水管网\n"

    monkeypatch.setattr(
        bibliography,
        "PdfReader",
        lambda _: type("Reader", (), {"pages": [Page()], "is_encrypted": False})(),
    )
    p = bibliography.extract_bibliography("unused.pdf", "123456789")
    assert p["title"] == "GIS拓扑分析在智慧城市供水管网漏损定位中的应用优化与关键技术研究"
    assert p["authors"] == "杨晓蕾" and p["venue"] == "信息化研究"
    assert p["tags"] == "GIS拓扑分析,供水管网"


def test_page_translation_validates_ids_and_never_writes_pdf(client, tmp_path, monkeypatch):
    source = pdf(tmp_path / "paper.pdf")
    p = client.post("/library/link", json={"path": str(source)}).json()
    before = source.read_bytes()

    async def translate(task, message, context):
        assert task == "translate" and context == {"isolated": True}
        return json.dumps([{"id": 0, "text": "供水管网"}])

    monkeypatch.setattr(ai, "call_ai", translate)
    url = "/paper/translate-page?id=" + p["id"]
    assert (
        client.post(url, json={"blocks": [{"id": 0, "text": "Water network"}]}).json()["blocks"][0][
            "text"
        ]
        == "供水管网"
    )
    assert (
        client.post(url, json={"blocks": [{"id": 1, "text": "Water network"}]}).status_code == 502
    )
    assert client.post(url, json={"blocks": [{"id": 0, "text": "A"}] * 2}).status_code == 422
    assert source.read_bytes() == before


def test_enrichment_reads_body_even_with_generic_filename(client, tmp_path, monkeypatch):
    import security

    security.save_key("mock")
    source = pdf(tmp_path / "12345.pdf")
    p = client.post("/library/link", json={"path": str(source)}).json()
    monkeypatch.setattr(
        bibliography,
        "indexing_text",
        lambda _: "This paper studies groundwater contamination and water quality.",
    )

    async def classify(task, message, context):
        assert "groundwater contamination" in message
        return json.dumps(
            {"title_zh": "地下水污染研究", "category": "环境与地球科学", "tags": "地下水,水质"}
        )

    monkeypatch.setattr(ai, "call_ai", classify)
    assert client.post("/library/enrich?id=" + p["id"]).json()["updated"] == 1
    assert len(client.get("/papers?q=地下水").json()) == 1


def test_legacy_content_reindex_runs_once_and_preserves_chinese_title(
    client, tmp_path, monkeypatch
):
    import security

    security.save_key("mock")
    source = pdf(tmp_path / "供水管网研究.pdf")
    p = client.post("/library/link", json={"path": str(source)}).json()
    db.execute("UPDATE papers SET title_zh='旧标题',category='其他' WHERE id=?", (p["id"],))
    monkeypatch.setattr(
        bibliography, "indexing_text", lambda _: "研究供水管网中的水质变化及污染物分布。"
    )

    async def classify(*args, **kwargs):
        return json.dumps(
            {"title_zh": "不应改写原题", "category": "环境与地球科学", "tags": "水质"}
        )

    monkeypatch.setattr(ai, "call_ai", classify)
    assert client.post("/library/enrich").json()["updated"] == 1
    assert client.get("/paper?id=" + p["id"]).json()["title_zh"] == "供水管网研究"
    assert client.post("/library/enrich").json()["updated"] == 0


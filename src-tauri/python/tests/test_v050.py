"""v0.5: citation completeness, content-based identity, and C-drive copy cleanup."""

import base64
import json
from pathlib import Path

import ai
import bibliography
import db
import discovery
import library
import security
from pypdf import PdfWriter

CHINESE_HEADER = (
    "第52卷第3期\n2026年6月\n信 息 化 研 究\nInformatizationResearch\n"
    "Vol.52No.3\nJun.2026\n"
    "GIS拓扑分析在智慧城市供水管网漏损定位中的\n应用优化与关键技术研究\n"
    "杨晓蕾1\n大连理工大学城市学院\n"
)
ENGLISH_HEADER = (
    "Journal of Water Resources Planning\nVol. 52, No. 3, 2026, pp. 171-175\n"
    "Topological Analysis of Water Distribution Networks for Leak Location\n"
    "Alice M. Newman, Bob Carter, Chen Wei, Dan Ellis\n"
    "Department of Civil Engineering, Example University\n"
    "Abstract: Leak location is studied.\nKeywords: water network; leak\n"
)


def blank_pdf(path, pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=600, height=800)
    writer.write(path)
    return path


def patch_text(monkeypatch, text, footers=(171, 175)):
    """Serve `text` as the first-page text and `footers` as the page numbers."""

    class Page:
        mediabox = type("Box", (), {"height": 800})()

        def __init__(self, number):
            self.number = number

        def extract_text(self, visitor_text=None, **kwargs):
            if visitor_text:
                # tm/cm place this fragment inside the bottom 12% of the page.
                place = [1, 0, 0, 1, 300, 40]
                visitor_text(str(self.number), place, place, None, 9)
            return text

    class Reader:
        is_encrypted = False

        def __init__(self):
            self.pages = [Page(n) for n in footers]

    monkeypatch.setattr(bibliography, "PdfReader", lambda _: Reader())


def test_generic_names_and_gb_authors():
    for name in ("12345", "download (2)", "cnki_2026", "a1b2c3d4e5f6a7b8", "未命名"):
        assert bibliography.generic_title(name) is True
    assert bibliography.generic_title("GIS拓扑分析在智慧城市供水管网漏损定位中的应用") is False
    assert library.gb_authors("Albert Einstein, Boris Podolsky", False) == (
        "EINSTEIN A, PODOLSKY B"
    )
    # Index records arrive as "given family" and are already-inverted by the time
    # they are stored, so the conversion must be idempotent.
    assert library.gb_authors("Wei Chen", False) == "CHEN W"
    assert library.gb_authors("Chen W", False) == "CHEN W"
    assert library.gb_authors("Smith J, Doe A, Roe R, Poe P", False).endswith(", et al.")
    assert library.gb_authors("杨晓蕾, 王强, 李明, 赵雷", True) == "杨晓蕾，王强，李明, 等"


def test_citation_never_uses_placeholders(client, tmp_path, monkeypatch):
    patch_text(monkeypatch, CHINESE_HEADER)
    source = blank_pdf(tmp_path / "杨晓蕾.pdf")
    p = client.post("/library/link", json={"path": str(source)}).json()
    c = client.get("/paper/citation", params={"id": p["id"]}).json()
    assert "〔" not in c["text"] and "待补" not in c["text"]
    assert c["text"] == (
        "[1] 杨晓蕾. GIS拓扑分析在智慧城市供水管网漏损定位中的应用优化与关键技术研究"
        "[J]. 信息化研究, 2026, 52(3): 171-175."
    )
    assert c["complete"] is True and c["omitted"] == []


def test_citation_omits_unknown_elements_and_reports_them(client, tmp_path):
    source = blank_pdf(tmp_path / "12345.pdf")
    p = client.post("/library/link", json={"path": str(source)}).json()
    c = client.get("/paper/citation", params={"id": p["id"]}).json()
    assert c["text"].endswith(".") and "〔" not in c["text"]
    assert "作者" in c["omitted"] and "年份" in c["omitted"]
    assert "原文标题仍来自文件名" in c["review"] and c["complete"] is False


def test_resolve_never_overwrites_values_the_user_already_has(
    client, tmp_path, monkeypatch
):
    source = blank_pdf(tmp_path / "edited.pdf")
    p = client.post("/library/link", json={"path": str(source)}).json()
    db.execute(
        "UPDATE papers SET title='Leak location in water networks',authors='Alice Newman',"
        "published='2026',venue='我核对的刊名',pages='7-9' WHERE id=?",
        (p["id"],),
    )

    async def candidates(doi="", title="", limit=5):
        return [
            {
                "id": "crossref-x",
                "title": "Leak location in water networks",
                "authors": "Alice Newman",
                "published": "2026",
                "doi": "10.1/example",
                "venue": "A Different Journal",
                "pages": "100-200",
                "volume": "12",
                "publication_type": "journal",
                "source": "crossref",
            }
        ]

    monkeypatch.setattr(discovery, "resolve_candidates", candidates)
    saved = client.post("/paper/citation/resolve", params={"id": p["id"]}).json()["paper"]
    assert saved["venue"] == "我核对的刊名" and saved["pages"] == "7-9"
    assert saved["volume"] == "12" and saved["doi"] == "10.1/example"
    assert "[J]. 我核对的刊名, 2026, 12" in client.get(
        "/paper/citation", params={"id": p["id"]}
    ).json()["text"]


def test_a_named_serial_without_a_url_is_a_journal_not_a_web_page(client, tmp_path):
    source = blank_pdf(tmp_path / "serials.pdf")
    p = client.post("/library/link", json={"path": str(source)}).json()
    db.execute(
        "UPDATE papers SET title='Leak location in water networks',authors='Alice Newman',"
        "published='2026',venue='Journal of Water Resources Planning',publication_type='online'"
        " WHERE id=?",
        (p["id"],),
    )
    c = client.get("/paper/citation", params={"id": p["id"]}).json()
    assert c["text"] == (
        "[1] NEWMAN A. Leak location in water networks[J]. "
        "Journal of Water Resources Planning, 2026."
    )
    assert c["complete"] is True


def test_resolve_fills_fields_from_exact_title_index_match(client, tmp_path, monkeypatch):
    source = blank_pdf(tmp_path / "paper.pdf")
    p = client.post("/library/link", json={"path": str(source)}).json()
    db.execute(
        "UPDATE papers SET title=?,authors='Alice M. Newman, Bob Carter',published='2026',"
        "publication_type='journal',venue='',volume='',issue='',pages='' WHERE id=?",
        ("Topological analysis of water distribution networks", p["id"]),
    )

    async def candidates(doi="", title="", limit=5):
        return [
            {
                "id": "crossref-x",
                "title": "Topological Analysis of Water Distribution Networks",
                "authors": "Alice M Newman, Bob Carter",
                "published": "2026-06-01",
                "doi": "10.1/example",
                "venue": "Journal of Water Resources Planning",
                "volume": "52",
                "issue": "3",
                "pages": "171-175",
                "publisher": "ASCE",
                "publication_type": "journal",
                "landing_url": "https://doi.org/10.1/example",
                "source": "crossref",
            }
        ]

    monkeypatch.setattr(discovery, "resolve_candidates", candidates)
    r = client.post("/paper/citation/resolve", params={"id": p["id"]}).json()
    # The index fills the missing serial fields; the paper keeps its own title spelling.
    assert r["text"] == (
        "[1] NEWMAN A M, CARTER B. Topological analysis of water distribution networks"
        "[J]. Journal of Water Resources Planning, 2026, 52(3): 171-175. DOI: 10.1/example."
    )
    assert r["complete"] is True and "crossref" in r["evidence"]
    assert client.get("/paper", params={"id": p["id"]}).json()["citation_checked"] == 1


def test_resolve_ignores_a_different_work(client, tmp_path, monkeypatch):
    source = blank_pdf(tmp_path / "paper.pdf")
    p = client.post("/library/link", json={"path": str(source)}).json()
    db.execute(
        "UPDATE papers SET title='Leak location in water networks',authors='Alice Newman',"
        "published='2026' WHERE id=?",
        (p["id"],),
    )

    async def unrelated(doi="", title="", limit=5):
        return [
            {
                "id": "other",
                "title": "Leak location in gas networks",
                "authors": "Zoe Other",
                "published": "2019",
                "source": "crossref",
            }
        ]

    monkeypatch.setattr(discovery, "resolve_candidates", unrelated)
    r = client.post("/paper/citation/resolve", params={"id": p["id"]}).json()
    assert "Zoe" not in r["text"] and "gas" not in r["text"]
    assert "来源网址" in r["omitted"]


def test_generic_filename_reads_identity_from_pdf_body(client, tmp_path, monkeypatch):
    security.save_key("mock")
    patch_text(monkeypatch, ENGLISH_HEADER)
    source = blank_pdf(tmp_path / "12345.pdf")
    p = client.post("/library/link", json={"path": str(source)}).json()
    monkeypatch.setattr(bibliography, "indexing_text", lambda *a, **k: ENGLISH_HEADER)

    async def classify(task, message, context):
        return json.dumps(
            {
                "title": "Topological Analysis of Water Distribution Networks for Leak Location",
                "title_zh": "供水管网拓扑分析与漏损定位",
                "category": "工程与材料",
                "tags": "供水管网,漏损定位",
                "authors": "Alice M. Newman",
                "published": "2026",
                "venue": "Journal of Water Resources Planning",
            }
        )

    monkeypatch.setattr(ai, "call_ai", classify)
    assert client.post("/library/enrich", params={"id": p["id"]}).json()["updated"] == 1
    saved = client.get("/paper", params={"id": p["id"]}).json()
    assert saved["title"].startswith("Topological Analysis of Water Distribution")
    assert saved["authors"] == "Alice M. Newman" and saved["published"] == "2026"
    assert saved["venue"] == "Journal of Water Resources Planning"


def test_unverifiable_model_answers_are_discarded(client, tmp_path, monkeypatch):
    security.save_key("mock")
    body = "only this text exists on the page"
    patch_text(monkeypatch, body)
    source = blank_pdf(tmp_path / "999.pdf")
    p = client.post("/library/link", json={"path": str(source)}).json()
    monkeypatch.setattr(bibliography, "indexing_text", lambda *a, **k: body)

    async def invent(task, message, context):
        return json.dumps(
            {
                "title": "A Title Nobody Printed",
                "title_zh": "占位译名",
                "category": "其他",
                "tags": "伪造",
                "authors": "Nobody",
                "published": "1999",
                "venue": "Nowhere Journal",
            }
        )

    monkeypatch.setattr(ai, "call_ai", invent)
    client.post("/library/enrich", params={"id": p["id"]}).json()
    saved = client.get("/paper", params={"id": p["id"]}).json()
    assert saved["title"] == "999" and not saved["authors"]
    assert not saved["published"] and not saved["venue"]


def test_storage_and_dedupe_clears_the_c_drive_copy(client, tmp_path, monkeypatch):
    originals = tmp_path / "home" / "Downloads"
    originals.mkdir(parents=True)
    source = blank_pdf(originals / "my-paper.pdf")
    payload = source.read_bytes()
    monkeypatch.setattr(library, "USER_HOME", tmp_path / "home")

    p = client.post(
        "/library/import",
        json={"filename": "my-paper.pdf", "data": base64.b64encode(payload).decode()},
    ).json()
    copy = Path(p["local_path"])
    assert copy.parent == (db.DATA_DIR / "papers").resolve() and copy.is_file()
    size = copy.stat().st_size
    (tmp_path / "home" / "elsewhere").mkdir()
    (tmp_path / "home" / "elsewhere" / "other.pdf").write_bytes(b"%PDF-unrelated")

    before = client.get("/library/storage").json()
    assert before["managed_count"] == 1 and before["managed_bytes"] == size
    assert before["linked_count"] == 0

    plan = client.post("/library/dedupe", params={"dry_run": True}).json()
    assert [i["id"] for i in plan["items"]] == [p["id"]]
    assert plan["freed_bytes"] == 0 and copy.exists()

    done = client.post("/library/dedupe", params={"dry_run": False}).json()
    assert done["freed_bytes"] == size and not copy.exists()
    assert source.read_bytes() == payload
    linked = client.get("/paper", params={"id": p["id"]}).json()
    assert linked["storage_mode"] == "linked"
    assert Path(linked["local_path"]).samefile(source)
    assert client.post("/library/dedupe", params={"dry_run": False}).json()["items"] == []


def test_dedupe_never_touches_files_outside_the_app_folder(client, tmp_path, monkeypatch):
    monkeypatch.setattr(library, "USER_HOME", tmp_path / "home")
    (tmp_path / "home").mkdir()
    source = blank_pdf(tmp_path / "solo.pdf")
    p = client.post("/library/link", json={"path": str(source)}).json()
    assert client.get("/library/storage").json()["managed_count"] == 0
    assert client.post("/library/dedupe", params={"dry_run": False}).json()["items"] == []
    assert source.exists()
    assert client.get("/paper", params={"id": p["id"]}).json()["local_path"]


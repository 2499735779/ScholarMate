"""v0.7: chat attachments — local document reading, images and the workspace tool."""

import base64
import json
import zipfile
from pathlib import Path

import ai
import attachments
import db
import paths
import workspace

DOCX = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:r><w:t>智慧城市供水管网漏损定位研究</w:t></w:r></w:p>
<w:p><w:r><w:t>摘要：本文提出</w:t></w:r><w:r><w:t>基于拓扑分析的方法。</w:t></w:r></w:p>
</w:body></w:document>
"""
XLSX_SHARED = """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<si><t>泄漏率</t></si><si><t>管段编号</t></si><si><t>A-12</t></si></sst>
"""
XLSX_SHEET = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
<row r="2"><c r="A2"><v>12.5</v></c><c r="B2" t="s"><v>2</v></c></row>
</sheetData></worksheet>
"""
PPTX_SLIDE = """<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
<p:cSld><p:spTree><p:sp><p:txBody>
<a:p><a:r><a:t>答辩提纲</a:t></a:r></a:p>
<a:p><a:r><a:t>研究方法与实验</a:t></a:r></a:p>
</p:txBody></p:sp></p:spTree></p:cSld></p:sld>
"""
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def office(*members):
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in members:
            archive.writestr(name, text)
    return buffer.getvalue()


def upload(client, name, content):
    return client.post(
        "/chat/upload",
        json={"filename": name, "data": base64.b64encode(content).decode()},
    )


def test_docx_xlsx_pptx_and_text_are_read_locally(client):
    docx = office(("word/document.xml", DOCX))
    word = upload(client, "研究报告.docx", docx).json()
    assert word["kind"] == "document" and word["type_label"] == "Word 文档"
    assert "智慧城市供水管网漏损定位研究" in attachments.text_of(word["id"])
    assert "基于拓扑分析的方法" in attachments.text_of(word["id"])

    xlsx = office(
        ("xl/workbook.xml", "<workbook/>"),
        ("xl/sharedStrings.xml", XLSX_SHARED),
        ("xl/worksheets/sheet1.xml", XLSX_SHEET),
    )
    sheet = upload(client, "数据.xlsx", xlsx).json()
    text = attachments.text_of(sheet["id"])
    assert "泄漏率 | 管段编号" in text and "12.5 | A-12" in text

    pptx = office(
        ("ppt/presentation.xml", "<presentation/>"),
        ("ppt/slides/slide1.xml", PPTX_SLIDE),
    )
    slides = upload(client, "答辩.pptx", pptx).json()
    assert "答辩提纲" in attachments.text_of(slides["id"])

    chinese = "主题：管网漏损\n结论：拓扑分析有效".encode("gb18030")
    note = upload(client, "笔记.txt", chinese).json()
    assert "拓扑分析有效" in attachments.text_of(note["id"])
    assert note["characters"] > 0


def test_pdf_attachment_reuses_the_local_parser(client, monkeypatch):
    monkeypatch.setattr(attachments, "_pdf_text", lambda path: "第一篇论文的正文")
    result = upload(client, "论文.pdf", b"%PDF-1.7 fixture").json()
    assert result["type_label"] == "PDF 文档"
    assert attachments.text_of(result["id"]) == "第一篇论文的正文"


def test_upload_rejects_unsupported_and_mismatched_files(client):
    assert upload(client, "脚本.exe", b"MZ\x90\x00").status_code == 422
    assert upload(client, "旧文档.doc", b"\xd0\xcf\x11\xe0").status_code == 422
    assert upload(client, "假的.docx", b"not a zip").status_code == 422
    assert upload(client, "假的.pdf", b"not a pdf").status_code == 422
    assert upload(client, "假的.png", b"\x00\x01\x02").status_code == 422
    assert upload(client, "空的.txt", b"").status_code == 422
    big = b"x" * (attachments.MAX_BYTES + 1)
    assert upload(client, "太大.txt", big).status_code == 413
    assert upload(client, "不支持.tiff", PNG).status_code == 422


def test_image_is_stored_and_served_without_text(client):
    image = upload(client, "示意图.png", PNG).json()
    assert image["kind"] == "image" and image["characters"] == 0
    assert "图片" in image["note"]
    assert attachments.text_of(image["id"]) == ""
    served = client.get("/chat/attachment", params={"id": image["id"]})
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["content-disposition"].startswith("inline")
    assert client.get(
        "/chat/attachment", params={"id": image["id"]}, headers={"Authorization": ""}
    ).status_code == 401
    assert client.get("/chat/attachment", params={"id": "missing"}).status_code == 404


def test_same_bytes_are_stored_once(client, tmp_path):
    first = upload(client, "报告.docx", office(("word/document.xml", DOCX))).json()
    again = upload(client, "另一个名字.docx", office(("word/document.xml", DOCX))).json()
    assert first["id"] == again["id"]
    assert len(db.rows("SELECT * FROM attachments")) == 1
    assert len(list((Path(db.DATA_DIR) / "uploads").glob("*.docx"))) == 1


def test_document_text_reaches_the_model_and_history(client, monkeypatch):
    captured = {}

    async def fake(task, message, context=None):
        captured["task"] = task
        captured["message"] = message
        captured["context"] = context
        yield "根据附件回答。"

    monkeypatch.setattr(ai, "stream_ai", fake)
    word = upload(client, "研究报告.docx", office(("word/document.xml", DOCX))).json()
    result = client.post("/chat", json={"message": "总结这份文档", "attachments": [word["id"]]})
    assert '"done": true' in result.text
    assert captured["context"]["documents"][0]["name"] == "研究报告.docx"
    assert "智慧城市供水管网漏损定位研究" in captured["context"]["documents"][0]["text"]

    messages = client.get("/conversations").json()
    assert messages[0]["content"] == "总结这份文档"
    assert messages[0]["attachments"][0]["id"] == word["id"]
    assert messages[1]["attachments"] == []
    assert "研究报告.docx" in client.get("/conversations/export").text


def test_attachment_only_message_is_allowed(client, monkeypatch):
    async def fake(*args, **kwargs):
        yield "已收到文件。"

    monkeypatch.setattr(ai, "stream_ai", fake)
    word = upload(client, "报告.docx", office(("word/document.xml", DOCX))).json()
    assert client.post("/chat", json={"message": "", "attachments": [word["id"]]}).status_code == 200
    assert client.get("/conversations").json()[0]["content"] == ""
    # Neither text nor a file is still rejected.
    assert client.post("/chat", json={"message": "  "}).status_code == 422


def test_image_parts_follow_the_vision_setting(client, monkeypatch, profile_data):
    client.put("/profile", json=profile_data)
    seen = {}

    async def fake(task, message, context=None):
        seen["messages"] = ai.build_messages(task, message, context)
        yield "ok"

    monkeypatch.setattr(ai, "stream_ai", fake)
    image = upload(client, "图.png", PNG).json()

    # Text-only model: the image is announced, never sent as image content.
    client.put("/settings", json={"model": "deepseek-chat"})
    assert client.get("/status").json()["vision"] is False
    client.post("/chat", json={"message": "看图", "attachments": [image["id"]]})
    content = seen["messages"][-1]["content"]
    assert isinstance(content, str) and "你看不到图像内容" in content

    # Multimodal model: a real image part is attached.
    client.put("/settings", json={"model": "deepseek-vision-preview"})
    assert client.get("/status").json()["vision"] is True
    client.post("/chat", json={"message": "看图", "attachments": [image["id"]]})
    parts = seen["messages"][-1]["content"]
    assert isinstance(parts, list) and parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")

    # An explicit choice beats guessing from the name.
    client.put("/settings", json={"model": "deepseek-vision-preview", "vision": False})
    assert client.get("/status").json()["vision"] is False


def test_workspace_snapshot_and_tool_expose_attachments(client):
    word = upload(client, "长文档.docx", office(("word/document.xml", DOCX))).json()
    snapshot = json.loads(workspace.snapshot())
    assert snapshot["attachment_count"] == 1
    assert snapshot["attachments"][0]["name"] == "长文档.docx"
    read = workspace.read_workspace({"action": "attachment", "id": word["id"]})
    assert "智慧城市供水管网漏损定位研究" in read["text"]
    assert read["next_offset"] is None
    paged = workspace.read_workspace({"action": "attachment", "id": word["id"], "offset": 5})
    assert paged["offset"] == 5 and paged["text"] == read["text"][5:]
    assert "不存在" in workspace.read_workspace({"action": "attachment", "id": "nope"})["error"]
    image = upload(client, "图.png", PNG).json()
    note = workspace.read_workspace({"action": "attachment", "id": image["id"]})
    assert note["total_characters"] == 0 and "编造" in note["note"]


def test_delete_attachment_removes_the_file(client):
    word = upload(client, "临时.docx", office(("word/document.xml", DOCX))).json()
    path = Path(attachments.get(word["id"])["path"])
    assert path.is_file()
    assert client.delete("/chat/attachment", params={"id": word["id"]}).status_code == 200
    assert not path.exists()
    assert client.get("/chat/attachment", params={"id": word["id"]}).status_code == 404
    assert client.delete("/chat/attachment", params={"id": word["id"]}).status_code == 404


def test_missing_attachment_file_is_reported(client, monkeypatch):
    word = upload(client, "报告.docx", office(("word/document.xml", DOCX))).json()
    Path(attachments.get(word["id"])["path"]).unlink()
    assert client.post("/chat", json={"message": "读一下", "attachments": [word["id"]]}).status_code == 404
    assert client.get("/chat/attachment", params={"id": word["id"]}).status_code == 404


def test_data_directory_move_carries_uploads(client, monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "downloads_dir", lambda: tmp_path / "Downloads")
    word = upload(client, "报告.docx", office(("word/document.xml", DOCX))).json()
    original = Path(attachments.get(word["id"])["path"])
    payload = original.read_bytes()
    target = tmp_path / "E" / "moved"
    client.put("/settings/storage", json={"data_dir": str(target)})
    assert not original.exists()
    moved = attachments.get(word["id"])
    assert Path(moved["path"]) == (target / "uploads" / original.name).resolve()
    assert Path(moved["path"]).read_bytes() == payload
    assert attachments.text_of(word["id"]).startswith("智慧城市")
    assert client.get("/chat/attachment", params={"id": word["id"]}).content == payload


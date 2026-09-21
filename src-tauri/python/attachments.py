"""Read text out of an uploaded file on this machine.

Office files are unzipped and parsed with defusedxml, PDFs are read with pypdf and
plain text is decoded. Only the resulting text — or, for a vision model, the image
itself — is ever handed to the configured AI; the file stays in the data directory.
"""

import hashlib
import re
import zipfile
from pathlib import Path

import db
from defusedxml.ElementTree import fromstring
from fastapi import HTTPException
from pypdf import PdfReader

MAX_BYTES = 20 * 1024 * 1024
MAX_MEMBER_BYTES = 80 * 1024 * 1024
MAX_CHARACTERS = 300_000
INLINE_CHARACTERS = 6000
MAX_PAGES = 80

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

IMAGES = {
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".gif": ("image/gif", b"GIF8"),
    ".bmp": ("image/bmp", b"BM"),
}
PLAIN = {
    ".txt": ("text/plain", "文本"),
    ".md": ("text/markdown", "Markdown"),
    ".markdown": ("text/markdown", "Markdown"),
    ".csv": ("text/csv", "CSV 表格"),
    ".tsv": ("text/tab-separated-values", "TSV 表格"),
    ".json": ("application/json", "JSON"),
    ".xml": ("application/xml", "XML"),
    ".yaml": ("application/yaml", "YAML"),
    ".yml": ("application/yaml", "YAML"),
    ".html": ("text/html", "网页"),
    ".htm": ("text/html", "网页"),
    ".tex": ("text/x-tex", "LaTeX"),
    ".bib": ("text/plain", "BibTeX"),
    ".py": ("text/x-python", "Python 源码"),
    ".js": ("text/javascript", "JavaScript 源码"),
    ".ts": ("text/x-typescript", "TypeScript 源码"),
    ".r": ("text/x-rsrc", "R 源码"),
    ".m": ("text/plain", "MATLAB 源码"),
    ".sql": ("text/plain", "SQL"),
    ".log": ("text/plain", "日志"),
    ".srt": ("text/plain", "字幕"),
}
OFFICE = {
    ".docx": ("word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Word 文档"),
    ".xlsx": ("xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "Excel 表格"),
    ".pptx": ("ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "PPT 演示文稿"),
}
TIFF = {".tif", ".tiff"}
OLD_OFFICE = {".doc": "旧版 .doc", ".xls": "旧版 .xls", ".ppt": "旧版 .ppt"}


def uploads_dir():
    return Path(db.DATA_DIR) / "uploads"


def safe_name(value):
    """A display name only; the stored file is named by its content hash."""
    name = re.sub(r"[\x00-\x1f/\\]", "_", str(value or "")).strip()
    name = re.sub(r"\s+", " ", name)[:180]
    return name or "未命名文件"


def type_label(extension, media_type):
    if extension in OFFICE:
        return OFFICE[extension][2]
    if extension in PLAIN:
        return PLAIN[extension][1]
    if extension == ".pdf":
        return "PDF 文档"
    if extension in IMAGES or extension in TIFF:
        return "图片"
    return media_type or "文件"


def classify(name, content):
    extension = Path(name).suffix.lower()
    if extension in OLD_OFFICE:
        raise HTTPException(
            422, f"{OLD_OFFICE[extension]} 无法直接读取，请先另存为 .docx/.xlsx/.pptx 后重新上传。"
        )
    if extension in TIFF:
        raise HTTPException(422, "暂不支持 TIFF 图片，请转换为 PNG 或 JPG 后上传。")
    if extension in IMAGES:
        media_type, magic = IMAGES[extension]
        if not content.startswith(magic):
            raise HTTPException(422, "文件内容与扩展名不符，请确认是有效的图片。")
        return "image", media_type
    if extension in OFFICE:
        if not content.startswith(b"PK\x03\x04") or not zipfile.is_zipfile(_buffer(content)):
            raise HTTPException(422, "文件不是有效的 Office 文档（可能已损坏）。")
        member, media_type, _ = OFFICE[extension]
        try:
            with zipfile.ZipFile(_buffer(content)) as archive:
                if member not in archive.namelist():
                    raise HTTPException(422, "文件内容与扩展名不符，请确认文档类型。")
        except zipfile.BadZipFile:
            raise HTTPException(422, "文件已损坏，无法读取。") from None
        return "document", media_type
    if extension == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(422, "文件不是有效的 PDF。")
        return "document", "application/pdf"
    if extension in PLAIN:
        if b"\x00" in content[:8192]:
            raise HTTPException(422, "这看起来是二进制文件，无法按文本读取。")
        return "document", PLAIN[extension][0]
    raise HTTPException(
        422,
        "暂不支持这种格式。可以上传 Word / Excel / PowerPoint / PDF / 图片，"
        "或 .txt、.md、.csv、.json、.html、.tex、.bib 等文本文件。",
    )


def _buffer(content):
    import io

    return io.BytesIO(content)


def decode_text(content):
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def _docx_text(archive):
    lines = []
    for paragraph in fromstring(archive.read("word/document.xml")).iter(W + "p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == W + "t" and node.text:
                parts.append(node.text)
            elif node.tag == W + "tab":
                parts.append("\t")
            elif node.tag in (W + "br", W + "cr"):
                parts.append("\n")
        lines.append("".join(parts))
    return "\n".join(lines)


def _xlsx_text(archive):
    names = archive.namelist()
    shared = []
    if "xl/sharedStrings.xml" in names:
        for item in fromstring(archive.read("xl/sharedStrings.xml")).iter(S + "si"):
            shared.append("".join(node.text or "" for node in item.iter(S + "t")))
    lines = []
    sheets = sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
    for sheet in sheets:
        lines.append(f"# 工作表 {sheet.rsplit('/', 1)[-1]}")
        for row in fromstring(archive.read(sheet)).iter(S + "row"):
            cells = []
            for cell in row.iter(S + "c"):
                kind = cell.get("t")
                value = cell.find(S + "v")
                if kind == "s" and value is not None and (value.text or "").isdigit():
                    index = int(value.text)
                    cells.append(shared[index] if index < len(shared) else "")
                elif kind == "inlineStr":
                    cells.append("".join(n.text or "" for n in cell.iter(S + "t")))
                else:
                    cells.append(value.text or "" if value is not None else "")
            if any(cells):
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _pptx_text(archive):
    slides = sorted(
        (n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
        key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[-1])[0]),
    )
    blocks = []
    for number, slide in enumerate(slides, 1):
        lines = []
        for paragraph in fromstring(archive.read(slide)).iter(A + "p"):
            text = "".join(node.text or "" for node in paragraph.iter(A + "t"))
            if text.strip():
                lines.append(text)
        if lines:
            blocks.append(f"# 幻灯片 {number}\n" + "\n".join(lines))
    return "\n\n".join(blocks)


def _pdf_text(path):
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(""):
        raise HTTPException(422, "PDF 已加密，无法读取文字。")
    parts, size = [], 0
    for page in reader.pages[:MAX_PAGES]:
        text = page.extract_text() or ""
        parts.append(text)
        size += len(text)
        if size > MAX_CHARACTERS:
            break
    return "\n".join(parts).strip()


def extract(path, extension, content):
    """Return the readable text of a stored file; empty when there is none."""
    if extension in IMAGES or extension in TIFF:
        return ""
    try:
        if extension == ".pdf":
            return _pdf_text(path)
        if extension in PLAIN:
            return decode_text(content).strip()
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.file_size > MAX_MEMBER_BYTES:
                    raise HTTPException(422, "文档内部结构过大，已停止解析。")
            if extension == ".docx":
                return _docx_text(archive).strip()
            if extension == ".xlsx":
                return _xlsx_text(archive).strip()
            return _pptx_text(archive).strip()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "文档内容无法解析，请确认文件未损坏。") from None


def public(row, note=""):
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "media_type": row["media_type"],
        "type_label": type_label(Path(row["name"]).suffix.lower(), row["media_type"]),
        "bytes": row["bytes"],
        "characters": row["characters"],
        "created_at": row["created_at"],
        "note": note,
    }


def note_for(kind, characters, media_type):
    if kind == "image":
        return "图片已保存。若当前模型不支持图片输入，AI 看不到图片内容；可在设置中改用多模态模型。"
    if not characters:
        return "文件已保存，但没有可提取的文字（可能是扫描件或纯图片文档）。"
    return ""


def store(filename, content):
    if not content:
        raise HTTPException(422, "文件为空。")
    if len(content) > MAX_BYTES:
        raise HTTPException(413, f"单个文件请小于 {MAX_BYTES // 1024 // 1024} MB。")
    name = safe_name(filename)
    extension = Path(name).suffix.lower()
    kind, media_type = classify(name, content)
    id = "at-" + hashlib.sha256(content).hexdigest()[:32]
    existing = db.rows("SELECT * FROM attachments WHERE id=?", (id,))
    if existing and Path(existing[0]["path"]).is_file():
        return public(existing[0], note_for(existing[0]["kind"], existing[0]["characters"], media_type))
    folder = uploads_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (id + extension)
    path.write_bytes(content)
    text = extract(path, extension, content)[:MAX_CHARACTERS]
    text_path = ""
    if text:
        target = folder / (id + ".txt")
        target.write_text(text, encoding="utf-8")
        text_path = str(target)
    db.execute(
        "INSERT INTO attachments(id,name,kind,media_type,path,text_path,bytes,characters) "
        "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "name=excluded.name,kind=excluded.kind,media_type=excluded.media_type,path=excluded.path,"
        "text_path=excluded.text_path,bytes=excluded.bytes,characters=excluded.characters",
        (id, name, kind, media_type, str(path), text_path, len(content), len(text)),
    )
    row = db.rows("SELECT * FROM attachments WHERE id=?", (id,))[0]
    return public(row, note_for(kind, len(text), media_type))


def get(id):
    rows = db.rows("SELECT * FROM attachments WHERE id=?", (str(id or ""),))
    if not rows:
        raise HTTPException(404, "附件不存在或已被删除。")
    return rows[0]


def text_of(id):
    row = get(id)
    if row["text_path"] and Path(row["text_path"]).is_file():
        return Path(row["text_path"]).read_text(encoding="utf-8", errors="replace")
    return ""


def recent(limit=12):
    return [
        public(row)
        for row in db.rows("SELECT * FROM attachments ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))
    ]


def inline_excerpt(id, budget=INLINE_CHARACTERS):
    row = get(id)
    text = text_of(id)
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "type_label": type_label(Path(row["name"]).suffix.lower(), row["media_type"]),
        "characters": row["characters"],
        "text": text[:budget],
        "truncated": len(text) > budget,
    }


def remove(id):
    row = get(id)
    for value in (row["path"], row["text_path"]):
        if value:
            Path(value).unlink(missing_ok=True)
    db.execute("DELETE FROM attachments WHERE id=?", (row["id"],))
    return {"ok": True}


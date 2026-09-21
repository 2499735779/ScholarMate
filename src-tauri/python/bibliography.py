"""Extract evidence-backed bibliographic fields; never invent missing citation data.

Everything here is either read from the PDF itself or fetched from an open index
(Crossref / OpenAlex / Europe PMC / arXiv / DataCite). When a field cannot be
confirmed the caller omits it from the reference instead of printing a placeholder.
"""

import re
from pathlib import Path

import db
import discovery
import httpx
from fastapi import HTTPException
from pypdf import PdfReader

# A download name is not a bibliographic title.
GENERIC = re.compile(
    r"^(?:(?:19|20)\d{2}[-_.]?\d{0,2}[-_.]?\d{0,2}"
    r"|\d{1,12}"
    r"|[0-9a-f]{8,}"
    r"|(?:cnki|wanfang|scihub|scholar|cn|doi|pdf|download|document|untitled|scan|paper|fulltext|file|temp|new|copy)"
    r"[\s._-]*(?:\(\d+\)|\d{0,12})"
    r"|(?:下载|导出|扫描|文档|全文|新增|副本|未命名|论文|文献|知网|万方)"
    r"[\s._-]*(?:\(?\d*\)?))$",
    re.I,
)
AFFILIATION = re.compile(
    r"(?i)universit|institut|department|dept\.|college|school|laborator|academy|"
    r"hospital|centre|center|email|e-mail|abstract|keywords|大学|学院|研究所|实验室|"
    r"邮政编码|收稿|基金|作者简介|摘要|关键词"
)
NAME = re.compile(r"^[A-Z][\w'’.\-]*(?:\s+[A-Z][\w'’.\-]*){0,4}\d?$")


def compact(text):
    return re.sub(r"[\W_]", "", str(text or "")).casefold()


def clean_title(title):
    """Drop trailing download decorations such as `标题_作者` or `标题 (1)`."""
    value = re.sub(r"\.pdf$", "", str(title or ""), flags=re.I)
    value = re.sub(r"[_＿]([\u4e00-\u9fff]{2,5})$", "", value)
    return re.sub(r"\s*\((?:1|2|3|\d{1,3})\)$", "", value).strip()


def generic_title(title):
    """True when the stored name carries no usable bibliographic information."""
    value = clean_title(title)
    if len(compact(value)) < 8:
        return True
    if GENERIC.fullmatch(re.sub(r"[\s._-]+$", "", value).strip()):
        return True
    # `12345 - 副本`, `download (3)` and similar still look like file names.
    return bool(GENERIC.fullmatch(re.sub(r"[\s._-]*(?:副本|copy|\(\d+\))$", "", value, flags=re.I).strip()))


def content_title(page, header):
    """Use the first page's prominent text, never the arbitrary download filename."""
    lines = [re.sub(r"\s+", "", line) for line in header.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if index and re.fullmatch(r"[\u4e00-\u9fff]{2,5}[1-9¹²³*]?", line):
            previous = lines[index - 1]
            if (
                len(previous) >= 9
                and re.search(r"[\u4e00-\u9fff]", previous)
                and not re.search(r"大学|学院|研究所|期刊|ISSN", previous)
            ):
                if (
                    index > 1
                    and len(lines[index - 2]) >= 9
                    and re.search(r"[\u4e00-\u9fff]", lines[index - 2])
                    and not re.search(r"年|卷|期|大学|学院|研究所|期刊", lines[index - 2])
                ):
                    previous = lines[index - 2] + previous
                return previous
    fragments = []

    def visit(text, cm, tm, font, size):
        value = text.strip()
        if value and len(compact(value)) >= 4 and compact(value) in compact(header):
            if not re.search(r"(?i)doi|issn|第.*卷|vol\.|学位论文|大学$", value):
                fragments.append((float(size), value))

    page.extract_text(visitor_text=visit)
    if not fragments:
        return ""
    largest = max(x[0] for x in fragments)
    parts = [x[1] for x in fragments if x[0] >= largest * 0.95]
    title = " ".join(parts).strip()
    title = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", title)
    return title if 8 <= len(compact(title)) <= 250 else ""


def indexing_text(path, pages=4):
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(""):
        raise HTTPException(422, "PDF 已加密，无法读取内容。")
    text = "\n".join((p.extract_text() or "") for p in reader.pages[:pages])[:16000]
    if len(text.strip()) < 40:
        raise HTTPException(422, "该 PDF 没有可提取文字（可能是扫描件），需先进行 OCR 识别。")
    return text


def footer_number(page):
    fragments = []

    def visitor(text, cm, tm, font, size):
        text = text.strip()
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        if text and len(text) <= 8 and 0 < y < float(page.mediabox.height) * 0.12:
            fragments.append((round(y / 4), x, text))

    page.extract_text(visitor_text=visitor)
    for row in sorted({f[0] for f in fragments}):
        line = "".join(f[2] for f in sorted(fragments, key=lambda x: x[1]) if f[0] == row)
        if re.fullmatch(r"[·•\s-]*\d{1,5}[·•\s-]*", line):
            return int(re.search(r"\d+", line)[0])
    return None


def latin_byline(header, title):
    """Read the author line that follows the title, without guessing at affiliations."""
    lines = [line.strip() for line in header.splitlines() if line.strip()]
    target = compact(title)
    start = next((i for i, line in enumerate(lines) if target in compact(line)), None)
    if start is None:
        return ""
    for line in lines[start + 1 : start + 4]:
        candidate = re.sub(r"[\d*†‡§¶]+", "", line).strip(" ,;")
        if not 4 <= len(candidate) <= 300 or AFFILIATION.search(candidate):
            continue
        if re.search(r"[\u4e00-\u9fff@=]", candidate) or candidate.endswith("."):
            continue
        parts = [p.strip() for p in re.split(r",|;|\band\b|&", candidate) if p.strip()]
        names = [p for p in parts if NAME.fullmatch(p)]
        if len(names) >= 2 or (len(names) == 1 and len(parts) == 1):
            return ", ".join(names)
    return ""


def extract_bibliography(path, title):
    """Read what the first page states about itself. Returns only confirmed fields."""
    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise HTTPException(422, "PDF 已加密，无法自动识别引用信息。")
        first = reader.pages[0].extract_text() or ""
        header = re.split(r"摘\s*要\s*[:：]|Abstract", first, maxsplit=1, flags=re.I)[0][:5000]
        normalized = compact(header)
        result = {}
        clean = clean_title(title)
        if generic_title(clean) or compact(clean) not in normalized:
            clean = content_title(reader.pages[0], header) or (
                "" if generic_title(clean) else clean
            )
        if len(compact(clean)) > 8 and compact(clean) in normalized:
            result["title"] = clean
            # Locate the byline immediately following the title in extracted text.
            joined = re.sub(r"\s", "", header)
            start = joined.find(re.sub(r"\s", "", clean))
            tail = joined[start + len(re.sub(r"\s", "", clean)) :] if start >= 0 else ""
            author = re.match(r"([\u4e00-\u9fff]{2,5})(?:[1-9¹²³*]|\(|（|\n)", tail)
            suffix = re.search(r"[_＿]([\u4e00-\u9fff]{2,5})$", title)
            if author:
                result["authors"] = author[1]
            elif suffix and suffix[1] in header:
                result["authors"] = suffix[1]
            elif re.search(r"[\u4e00-\u9fff]", clean):
                pass
            else:
                byline = latin_byline(header, clean)
                if byline:
                    result["authors"] = byline
        volume = re.search(r"第\s*(\d+)\s*卷\s*第\s*(\d+)\s*期", header)
        year = re.search(r"((?:19|20)\d{2})\s*年", header)
        if volume:
            result.update(publication_type="journal", volume=volume[1], issue=volume[2])
            if year:
                result["published"] = year[1]
            for line in header.splitlines()[:8]:
                line = re.sub(r"\s", "", line)
                if (
                    re.fullmatch(r"[\u4e00-\u9fff]{2,24}", line)
                    and not line.startswith("第")
                    and line not in clean
                ):
                    result["venue"] = line
                    break
        elif re.search(r"(?:硕士|博士)\s*学位论文", header):
            result["publication_type"] = "thesis"
            for key, pattern in {
                "authors": r"(?:作者姓名|研究生姓名|姓名)\s*[:：]\s*([\u4e00-\u9fff]{2,5})",
                "publisher": r"(?:学位授予单位|学校名称|培养单位)\s*[:：]\s*([^\n]{2,40})",
                "published": r"(?:学位授予时间|答辩日期|提交日期)\s*[:：]\s*((?:19|20)\d{2})",
                "place": r"(?:地\s*址|地址|培养地点)\s*[:：][^\n]{0,30}?([\u4e00-\u9fff]{2,12}市)",
            }.items():
                m = re.search(pattern, header)
                if m:
                    result[key] = m[1].strip()
            if not result.get("authors"):
                coverage = re.search(
                    r"([\u4e00-\u9fff]{2,5})\s*(?:著|编|撰写)", header
                )
                if coverage:
                    result["authors"] = coverage[1]
        else:
            # English journal headers: "Journal of X, Vol. 12, No. 3, 2026, pp. 1-9".
            latin = re.search(
                r"Vol(?:ume)?\.?\s*(\d+)[\s,]*No\.?\s*(\d+)", header, re.I
            )
            if latin:
                result.update(publication_type="journal", volume=latin[1], issue=latin[2])
            iso = re.search(r"\b((?:19|20)\d{2})\b", header)
            if iso and not year:
                result["published"] = iso[1]
        doi = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", header, re.I)
        if doi:
            result["doi"] = doi[0].rstrip(".;)")
        if result.get("publication_type") == "journal":
            a, b = footer_number(reader.pages[0]), footer_number(reader.pages[-1])
            if a is not None and b is not None and b >= a and b - a < len(reader.pages) + 10:
                result["pages"] = str(a) if a == b else f"{a}-{b}"
        abstract = re.search(r"摘\s*要\s*[:：](.*?)(?:关键词|关\s*键\s*词)", first, re.S)
        if abstract:
            result["abstract"] = re.sub(
                r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", abstract[1]
            ).strip()[:30000]
        keywords = re.search(r"(?:关\s*键\s*词|Key\s*words)\s*[:：]\s*([^\n]+)", first, re.I)
        if keywords:
            result["tags"] = re.sub(r"[;；、]", ",", keywords[1]).strip()[:1000]
        return result
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "无法从该 PDF 识别书目信息，可能是扫描件或损坏文件。") from None


FILL_FIELDS = (
    "title",
    "authors",
    "published",
    "doi",
    "venue",
    "volume",
    "issue",
    "pages",
    "publisher",
    "place",
    "publication_type",
    "landing_url",
)


def _compatible(candidate, merged):
    """Accept a hit only when title, byline and year all agree with what we know."""
    if compact(candidate["title"]) != compact(merged["title"]):
        return False
    if merged.get("authors"):
        head = compact(merged["authors"]).split("etal")[0]
        if head and head not in compact(candidate.get("authors")):
            return False
    if merged.get("published") and candidate.get("published"):
        if candidate["published"][:4] != str(merged["published"])[:4]:
            return False
    if merged.get("doi") and candidate.get("doi"):
        if discovery.bare_doi(candidate["doi"]).casefold() != discovery.bare_doi(
            merged["doi"]
        ).casefold():
            return False
    return True


async def resolve(paper):
    """Fill missing citation fields from the PDF and from open indexes."""
    fields, evidence = {}, []
    if paper.get("local_path") and Path(paper["local_path"]).is_file():
        try:
            fields = extract_bibliography(paper["local_path"], paper["title"])
            if fields:
                evidence.append("PDF 首页与页脚")
        except HTTPException:
            pass
    merged = {**paper, **fields}
    indexed = {}
    if not generic_title(merged["title"]):
        try:
            doi = discovery.bare_doi(merged.get("doi"))
            candidates = await discovery.resolve_candidates(doi, merged["title"])
            matches = [c for c in candidates if _compatible(c, merged)]
            filled = set()
            for key in FILL_FIELDS:
                if fields.get(key):
                    continue  # what the file itself states wins
                stored = str(paper.get(key) or "").strip()
                # A generic download name or a default type may be replaced; edits may not.
                replaceable = not stored or (
                    key == "title" and generic_title(stored)
                ) or (key == "publication_type" and stored in ("online", "preprint"))
                if not replaceable:
                    continue
                value = next((m[key] for m in matches if m.get(key)), "")
                if value:
                    indexed[key] = value
                    filled.add(key)
            if filled:
                sources = "、".join(
                    dict.fromkeys(m["source"] for m in matches if m.get("source"))
                )
                evidence.append(f"{sources} 精确标题匹配")
        except (httpx.HTTPError, HTTPException, ValueError, KeyError, TypeError):
            pass
    updates = {**fields, **indexed}
    # Never overwrite what the record already says: only a filename used as a
    # title is a placeholder that reading the PDF content may replace.
    for key in list(updates):
        if key in ("abstract", "tags"):
            continue
        stored = str(paper.get(key) or "").strip()
        if stored and not (key == "title" and generic_title(stored)):
            updates.pop(key)
    if updates:
        updates["metadata_evidence"] = "；".join(dict.fromkeys(evidence)) or "PDF 内容识别"
        db.execute(
            "UPDATE papers SET " + ",".join(k + "=?" for k in updates) + " WHERE id=?",
            (*updates.values(), paper["id"]),
        )
    return evidence


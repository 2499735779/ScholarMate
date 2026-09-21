import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
import paths
from defusedxml import ElementTree
from fastapi import HTTPException
from pypdf import PdfReader

ARXIV_ID = re.compile(r"^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$")
search_lock = asyncio.Lock()
last_search = 0.0


def valid_id(value):
    if not ARXIV_ID.fullmatch(value):
        raise HTTPException(422, "无效 arXiv ID。")
    return value


async def search_papers(keyword: str, max_results: int = 20):
    global last_search
    async with search_lock:
        loop = asyncio.get_running_loop()
        await asyncio.sleep(max(0, 3 - (loop.time() - last_search)))
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                result = await client.get(
                    "https://export.arxiv.org/api/query",
                    params={
                        "search_query": "all:" + keyword,
                        "max_results": min(max_results, 50),
                        "sortBy": "relevance",
                        "sortOrder": "descending",
                    },
                    headers={"User-Agent": "ScholarMate/0.1 (desktop academic reader)"},
                )
                result.raise_for_status()
            root = ElementTree.fromstring(result.content)
            ns = {"a": "http://www.w3.org/2005/Atom"}
            papers = []
            for entry in root.findall("a:entry", ns):
                paper_id = entry.findtext("a:id", "", ns).split("/abs/")[-1]
                valid_id(paper_id)
                papers.append(
                    {
                        "id": paper_id,
                        "title": " ".join(entry.findtext("a:title", "", ns).split()),
                        "authors": ", ".join(
                            a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)
                        ),
                        "abstract": entry.findtext("a:summary", "", ns).strip(),
                        "pdf_url": f"https://arxiv.org/pdf/{paper_id}",
                        "published": entry.findtext("a:published", "", ns),
                    }
                )
            return papers
        except (httpx.HTTPError, ElementTree.ParseError):
            raise HTTPException(502, "arXiv 搜索失败，请检查网络或稍后重试。") from None
        finally:
            last_search = asyncio.get_running_loop().time()


def safe_pdf_url(url):
    p = urlparse(url)
    if (
        p.scheme != "https"
        or p.hostname not in ("arxiv.org", "export.arxiv.org")
        or p.port not in (None, 443)
        or p.username
        or not p.path.startswith("/pdf/")
    ):
        raise HTTPException(502, "论文下载地址不在允许的 arXiv 域名范围。")
    return url


async def download_pdf(paper_id, directory, pdf_url=None):
    if pdf_url is None:
        valid_id(paper_id)
    elif not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", paper_id):
        raise HTTPException(422, "无效文献 ID。")
    folder = Path(directory).expanduser() if directory else paths.download_dir()
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (paper_id.replace("/", "_") + ".pdf")
    if target.exists():
        raise HTTPException(409, "目标文件已存在，请先移除本地副本或更换目录。")
    import uuid

    temporary = target.with_suffix("." + uuid.uuid4().hex + ".part")
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=10), follow_redirects=False
        ) as client:
            url = pdf_url or f"https://arxiv.org/pdf/{paper_id}"
            from discovery import validate_pdf

            validator = validate_pdf if pdf_url else safe_pdf_url
            for redirect in range(5):
                async with client.stream("GET", validator(url)) as response:
                    if response.is_redirect:
                        from urllib.parse import urljoin

                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    response.raise_for_status()
                    total = int(response.headers.get("content-length", 0))
                    if total > 100 * 1024 * 1024:
                        raise HTTPException(413, "PDF 大于 100 MB，已停止下载。")
                    current = 0
                    with temporary.open("xb") as out:
                        async for chunk in response.aiter_bytes(65536):
                            current += len(chunk)
                            if current > 100 * 1024 * 1024:
                                raise HTTPException(413, "PDF 大于 100 MB，已停止下载。")
                            out.write(chunk)
                            yield {
                                "bytes": current,
                                "total": total,
                                "progress": round(current / total * 100) if total else None,
                            }
                    with temporary.open("rb") as source:
                        if b"%PDF-" not in source.read(1024):
                            raise HTTPException(502, "下载链接没有返回有效 PDF。")
                    temporary.rename(target)
                    yield {"path": str(target), "progress": 100}
                    return
            raise HTTPException(502, "论文链接重定向次数过多。")
    except httpx.HTTPError:
        raise HTTPException(502, "PDF 下载失败，链接可能失效或网络不可用。") from None
    finally:
        temporary.unlink(missing_ok=True)


def extract_text(path):
    if not path or not Path(path).is_file():
        raise HTTPException(404, "本地 PDF 不存在，请重新下载。")
    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise HTTPException(422, "PDF 已加密，请先提供未加密版本。")
        parts, size = [], 0
        for page in reader.pages:
            text = page.extract_text() or ""
            parts.append(text)
            size += len(text)
            if size > 2_000_000:
                raise HTTPException(413, "PDF 文本过长，请拆分文档后处理。")
        content = "\n\n".join(parts).strip()
        if not content:
            raise HTTPException(422, "该 PDF 可能是扫描件，暂不支持 OCR，请先识别文字。")
        return content
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "PDF 无法解析，文件可能损坏。") from None


SUMMARY_BUDGET = 8000


def _boundary(text, index):
    """Move a cut index back to the nearest paragraph, line or sentence end."""
    for marker in ("\n\n", "\n", "。", ". ", "; ", "；"):
        position = text.rfind(marker, max(0, index - 400), index)
        if position > 0:
            return position + len(marker)
    return index


def summary_excerpt(text, budget=SUMMARY_BUDGET):
    """The opening *and* the closing of a paper.

    The first pages carry the title, abstract and introduction, but the results
    and conclusions live at the end — so a summary reads both ends instead of the
    first 8,000 characters only.
    """
    body = (text or "").strip()
    if len(body) <= budget:
        return body, False
    head = body[: _boundary(body, int(budget * 0.75))].rstrip()
    start = max(len(head), len(body) - (budget - len(head)))
    tail = body[_boundary(body, start) :].lstrip()
    return head + "\n\n【……中间正文省略……】\n\n" + tail, True


def digest_chunks(text, budget=7000, limit=14):
    """Split the body into sections of readable size for section-by-section reading.

    A long document is sampled evenly across its whole length, so a thesis still
    gets its beginning, middle and end represented instead of only page 1–20.
    """
    body = (text or "").strip()
    if not body:
        return []
    chunks, current = [], ""
    for paragraph in (p for p in re.split(r"\n\s*\n", body) if p.strip()):
        while len(paragraph) > budget:
            room = max(1, budget - len(current))
            current += paragraph[:room]
            chunks.append(current.strip())
            current, paragraph = "", paragraph[room:]
        if current and len(current) + len(paragraph) + 2 > budget:
            chunks.append(current.strip())
            current = ""
        current += paragraph + "\n\n"
    if current.strip():
        chunks.append(current.strip())
    if len(chunks) <= limit:
        return chunks
    # The opening and the closing are always read (that is where the abstract and
    # the conclusions are); the remaining slots spread across the whole document.
    keep = {0, len(chunks) - 1}
    for index in range(1, max(1, limit - 1)):
        keep.add((index * (len(chunks) - 1)) // (limit - 1))
    return [chunks[position] for position in sorted(keep)[:limit]]


import httpx
import papers
import pytest
from fastapi import HTTPException
from pypdf import PdfWriter
from reportlab.pdfgen import canvas


def test_pdf_extract(tmp_path):
    path = tmp_path / "text.pdf"
    c = canvas.Canvas(str(path))
    c.drawString(50, 700, "ScholarMate paper text")
    c.save()
    assert "ScholarMate" in papers.extract_text(path)


def test_broken_missing_scanned_encrypted(tmp_path):
    with pytest.raises(HTTPException, match="不存在"):
        papers.extract_text(tmp_path / "missing.pdf")
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"broken")
    with pytest.raises(HTTPException, match="损坏"):
        papers.extract_text(path)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    path = tmp_path / "scan.pdf"
    writer.write(path)
    with pytest.raises(HTTPException, match="扫描"):
        papers.extract_text(path)
    writer.encrypt("secret")
    path = tmp_path / "encrypted.pdf"
    writer.write(path)
    with pytest.raises(HTTPException, match="加密"):
        papers.extract_text(path)


@pytest.mark.parametrize(
    "url",
    [
        "http://arxiv.org/pdf/1",
        "https://evil.com/pdf/1",
        "https://arxiv.org:8443/pdf/1",
        "https://arxiv.org/account",
        "https://user@arxiv.org/pdf/1",
    ],
)
def test_download_url_restrictions(url):
    with pytest.raises(HTTPException):
        papers.safe_pdf_url(url)


@pytest.mark.parametrize("id", ["../../secret", "x;cmd", "2609.12345/../../x"])
def test_invalid_ids(id):
    with pytest.raises(HTTPException):
        papers.valid_id(id)


@pytest.mark.asyncio
async def test_download_progress_and_cleanup(monkeypatch, tmp_path):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        papers.httpx,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"%PDF-1.7 fixture")
            )
        ),
    )
    events = [e async for e in papers.download_pdf("2609.12345", str(tmp_path))]
    assert events[-1]["progress"] == 100
    assert (tmp_path / "2609.12345.pdf").is_file()
    assert not list(tmp_path.glob("*.part"))
    with pytest.raises(HTTPException, match="已存在"):
        [e async for e in papers.download_pdf("2609.12345", str(tmp_path))]


@pytest.mark.asyncio
async def test_invalid_pdf_download_cleans_temporary(monkeypatch, tmp_path):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        papers.httpx,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"<html>not pdf</html>")
            )
        ),
    )
    with pytest.raises(HTTPException, match="有效 PDF"):
        [e async for e in papers.download_pdf("2609.12345", str(tmp_path))]
    assert not list(tmp_path.glob("*.part"))
    assert not list(tmp_path.glob("*.pdf"))


@pytest.mark.asyncio
async def test_arxiv_atom(monkeypatch):
    xml = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2609.12345v1</id><title> Test Paper </title><author><name>A Researcher</name></author><summary>Summary</summary><published>2026-09-09</published></entry></feed>"""
    original = httpx.AsyncClient
    monkeypatch.setattr(
        papers.httpx,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text=xml))
        ),
    )
    result = await papers.search_papers("research")
    assert result[0]["authors"] == "A Researcher"
    assert result[0]["pdf_url"] == "https://arxiv.org/pdf/2609.12345v1"


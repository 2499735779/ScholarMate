"""Public scholarly indexes. Search coverage is distinct from full-text availability."""

import asyncio
import hashlib
import re
from urllib.parse import quote, urlparse

import httpx
import papers
from fastapi import HTTPException


def plain(value):
    return re.sub(r"<[^>]+>", "", str(value or "")).strip()


UA = "ScholarMate/0.5 (local academic desktop reader; citation lookup)"
# Bibliographic lookup shares these indexes; only open APIs are used, never a login wall.
DOI_SOURCES = ("crossref", "openalex", "datacite")
TITLE_SOURCES = ("crossref", "openalex", "europepmc", "arxiv")
RESOLVE_SOURCES = ("crossref", "openalex", "europepmc", "arxiv", "datacite")


def bare_doi(value):
    return re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", str(value or "").strip(), flags=re.I)


def crossref(item):
    doi = item.get("DOI", "")
    journal = item.get("journal-issue", {})
    parts = item.get("published", {}).get("date-parts", [[]])[0]
    links = item.get("link", [])
    return {
        "id": "doi-" + hashlib.sha256(doi.lower().encode()).hexdigest()[:24],
        "title": plain(next(iter(item.get("title", [])), "未提供标题")),
        "authors": ", ".join(
            " ".join(filter(None, [a.get("given"), a.get("family")])) or a.get("name", "")
            for a in item.get("author", [])
        ),
        "abstract": plain(item.get("abstract")),
        "published": "-".join(map(str, parts)),
        "pdf_url": next(
            (
                a["URL"]
                for a in links
                if a.get("content-type") == "application/pdf" and allowed_pdf(a.get("URL", ""))
            ),
            "",
        ),
        "doi": doi,
        "source": "crossref",
        "landing_url": "https://doi.org/" + quote(doi, safe="/"),
        "venue": next(iter(item.get("container-title", [])), ""),
        "volume": item.get("volume", ""),
        "issue": item.get("issue", journal.get("issue", "")),
        "pages": item.get("page", item.get("article-number", "")),
        "publisher": item.get("publisher", ""),
        "publication_type": {
            "journal-article": "journal",
            "dissertation": "thesis",
            "proceedings-article": "conference",
            "book": "book",
        }.get(item.get("type"), "online"),
    }


def openalex(item):
    doi = bare_doi(item.get("doi"))
    biblio = item.get("biblio") or {}
    first, last = str(biblio.get("first_page") or ""), str(biblio.get("last_page") or "")
    authors = ", ".join(
        (a.get("author") or {}).get("display_name", "")
        for a in item.get("authorships") or []
    ).strip(", ")
    source = ((item.get("primary_location") or {}).get("source") or {})
    return {
        "id": "doi-" + hashlib.sha256(doi.lower().encode()).hexdigest()[:24]
        if doi
        else "openalex-" + str(item.get("id", "")).rsplit("/", 1)[-1],
        "title": plain(item.get("display_name") or item.get("title")),
        "authors": authors,
        "abstract": plain(item.get("abstract")),
        "published": str(item.get("publication_year") or ""),
        "pdf_url": "",
        "doi": doi,
        "source": "openalex",
        "landing_url": item.get("doi") or item.get("id", ""),
        "venue": plain(source.get("display_name")),
        "volume": str(biblio.get("volume") or ""),
        "issue": str(biblio.get("issue") or ""),
        "pages": "-".join(dict.fromkeys(x for x in (first, last) if x)),
        "publisher": plain(source.get("host_organization_name")),
        "publication_type": {
            "article": "journal",
            "review": "journal",
            "dissertation": "thesis",
            "book": "book",
            "book-chapter": "book",
            "proceedings-article": "conference",
            "preprint": "preprint",
            "report": "online",
        }.get(item.get("type"), "online"),
    }


def datacite(item):
    attr = item.get("attributes") or {}
    doi = attr.get("doi", "")
    titles = attr.get("titles") or []
    container = attr.get("container") or {}
    year = str(attr.get("publicationYear") or "")
    return {
        "id": "doi-" + hashlib.sha256(doi.lower().encode()).hexdigest()[:24],
        "title": plain((titles[0] or {}).get("title") if titles else ""),
        "authors": ", ".join(
            c.get("name", "")
            for c in attr.get("creators") or []
            if c.get("name")
        ),
        "abstract": plain(next((d.get("description") for d in attr.get("descriptions") or [] if d.get("description")), "")),
        "published": year,
        "pdf_url": "",
        "doi": doi,
        "source": "datacite",
        "landing_url": attr.get("url") or ("https://doi.org/" + doi if doi else ""),
        "venue": plain((container.get("title") if container else "") or ""),
        "volume": str(container.get("volume") or "") if container else "",
        "issue": str(container.get("issue") or "") if container else "",
        "pages": "",
        "publisher": plain(attr.get("publisher")),
        "publication_type": {
            "Dissertation": "thesis",
            "Text": "online",
            "JournalArticle": "journal",
            "ConferencePaper": "conference",
            "Book": "book",
            "Preprint": "preprint",
        }.get((attr.get("types") or {}).get("resourceTypeGeneral"), "online"),
    }


PDF_HOSTS = {
    "arxiv.org",
    "export.arxiv.org",
    "europepmc.org",
    "www.europepmc.org",
    "pmc.ncbi.nlm.nih.gov",
    "www.ncbi.nlm.nih.gov",
    "www.ebi.ac.uk",
    "journals.plos.org",
    "www.nature.com",
    "link.springer.com",
    "www.mdpi.com",
    "mdpi-res.com",
    "www.frontiersin.org",
    "public-pages-files-2025.frontiersin.org",
    "www.sciencedirect.com",
    "www.cell.com",
}


def allowed_pdf(url):
    try:
        p = urlparse(url)
        return (
            p.scheme == "https"
            and p.hostname in PDF_HOSTS
            and p.port in (None, 443)
            and not p.username
        )
    except ValueError:
        return False


def validate_pdf(url):
    if not allowed_pdf(url):
        raise HTTPException(422, "此来源尚不支持应用内直下，请前往出版页面下载后导入 PDF。")
    return url


async def _crossref_rows(client, params, limit):
    response = await client.get(
        "https://api.crossref.org/works",
        params={**params, "rows": limit, "sort": "relevance"},
    )
    response.raise_for_status()
    return [crossref(i) for i in response.json()["message"]["items"]]


async def _europepmc_rows(client, query, limit):
    response = await client.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": query, "pageSize": limit, "format": "json", "resultType": "core"},
    )
    response.raise_for_status()
    result = []
    for item in response.json().get("resultList", {}).get("result", []):
        pmcid = item.get("pmcid", "")
        info = item.get("journalInfo", {})
        doi = item.get("doi", "")
        result.append(
            {
                "id": "pmc-" + str(item.get("source", "")) + "-" + str(item["id"]),
                "title": plain(item.get("title")),
                "authors": item.get("authorString", ""),
                "abstract": plain(item.get("abstractText")),
                "published": item.get("firstPublicationDate", item.get("pubYear", "")),
                "pdf_url": f"https://europepmc.org/articles/{pmcid}?pdf=render"
                if re.fullmatch(r"PMC\d+", pmcid) and item.get("isOpenAccess") == "Y"
                else "",
                "source": "europepmc",
                "doi": doi,
                "landing_url": f"https://europepmc.org/article/{quote(item.get('source', 'MED'))}/{quote(str(item['id']))}",
                "venue": info.get("journal", {}).get("title", ""),
                "volume": info.get("volume", ""),
                "issue": info.get("issue", ""),
                "pages": item.get("pageInfo", ""),
                "publication_type": "journal",
            }
        )
    return result


async def _openalex_rows(client, params, limit):
    response = await client.get(
        "https://api.openalex.org/works", params={**params, "per-page": limit}
    )
    response.raise_for_status()
    return [openalex(i) for i in response.json().get("results", [])]


async def _datacite_rows(client, doi, limit):
    response = await client.get("https://api.datacite.org/dois/" + quote(doi, safe=""))
    response.raise_for_status()
    return [datacite(response.json().get("data") or {})]


def _client():
    # Every lookup is a short outbound call; a hung index must never stall the UI.
    return httpx.AsyncClient(
        timeout=httpx.Timeout(20, connect=8),
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": UA},
    )


async def provider_lookup(client, source, doi="", title="", limit=5):
    """One index, one query: prefer the DOI (exact) and fall back to a title search."""
    if source == "arxiv" and title:
        return [
            {
                **p,
                "source": "arxiv",
                "publication_type": "preprint",
                "landing_url": "https://arxiv.org/abs/" + p["id"],
            }
            for p in await papers.search_papers(title, limit)
        ]
    if source == "crossref":
        if doi:
            response = await client.get(
                "https://api.crossref.org/works/" + quote(doi, safe="")
            )
            response.raise_for_status()
            return [crossref(response.json()["message"])]
        if title:
            return await _crossref_rows(client, {"query.bibliographic": title}, limit)
    if source == "openalex":
        if doi:
            return await _openalex_rows(client, {"filter": "doi:" + doi}, 1)
        if title:
            return await _openalex_rows(client, {"filter": "title.search:" + title}, limit)
    if source == "europepmc" and (doi or title):
        return await _europepmc_rows(client, f"DOI:{doi}" if doi else title, limit)
    if source == "datacite" and doi:
        return await _datacite_rows(client, doi, limit)
    return []


async def resolve_candidates(doi="", title="", limit=5):
    """Query every index concurrently and keep provider priority order for the caller."""
    tasks = []
    async with _client() as client:
        for source in RESOLVE_SOURCES:
            if not doi and source == "datacite":
                continue
            tasks.append(provider_lookup(client, source, doi, title, limit))
        replies = await asyncio.gather(*tasks, return_exceptions=True)
    items = []
    for reply in replies:
        if not isinstance(reply, BaseException) and reply:
            items.extend(reply)
    return items


async def provider_search(source, keyword, limit):
    if source == "arxiv":
        return [
            {
                **p,
                "source": "arxiv",
                "publication_type": "preprint",
                "landing_url": "https://arxiv.org/abs/" + p["id"],
            }
            for p in await papers.search_papers(keyword, limit)
        ]
    try:
        async with _client() as client:
            if source == "crossref":
                return await _crossref_rows(client, {"query.bibliographic": keyword}, limit)
            return await _europepmc_rows(client, keyword, limit)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502, f"{source} 检索暂时不可用，请稍后刷新。") from None


async def search(keyword, source="all", limit=20):
    sources = ["arxiv", "crossref", "europepmc"] if source == "all" else [source]
    if any(s not in ("arxiv", "crossref", "europepmc") for s in sources):
        raise HTTPException(422, "不支持的检索来源。")
    replies = await asyncio.gather(
        *(provider_search(s, keyword, limit) for s in sources), return_exceptions=True
    )
    items, warnings, seen = [], [], set()
    # Round robin retains top relevant hits from every successful provider.
    for s, reply in zip(sources, replies):
        if isinstance(reply, Exception):
            warnings.append(f"{s} 暂时不可用，其余来源仍可查看。")
    for rank in range(limit):
        for reply in replies:
            if isinstance(reply, Exception) or rank >= len(reply):
                continue
            item = reply[rank]
            key = (item.get("doi") or re.sub(r"\W", "", item["title"])).casefold()
            if key not in seen:
                seen.add(key)
                items.append(item)
    if len(warnings) == len(sources):
        raise HTTPException(502, "检索来源均暂时不可用，请检查网络并重试。")
    return {"items": items, "warnings": warnings}


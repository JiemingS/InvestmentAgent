import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import ipaddress
import json
import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx2
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

from .models import Article

EXA_ENDPOINT = "https://mcp.exa.ai/mcp?tools=web_search_advanced_exa"
MAX_ARTICLES = 6
SEARCH_EXCERPT_CHARS = 700
FETCH_EXCERPT_CHARS = 1200
ARTICLE_FETCH_CHARS = 48_000
TRUNCATION_NOTICE = "<error>Content truncated."


@dataclass(frozen=True)
class FetchedPage:
    url: str
    text: str
    is_partial: bool


class ResearchError(RuntimeError):
    pass


def _short(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]


def public_url(value: str) -> str | None:
    if len(value) > 2048 or re.search(r"[\s\\\x00-\x1f]", value):
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".").encode("idna").decode("ascii")
        if parsed.scheme != "https" or parsed.username is not None or parsed.port not in (None, 443):
            return None
        if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host) or host.endswith((".local", ".localhost", ".internal")):
            return None
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return None
        return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
    except (UnicodeError, ValueError):
        return None


def _identity(url: str) -> str:
    parsed = urlsplit(url)
    kept = [
        (key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in ("fbclid", "gclid")
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(sorted(kept)), ""))


def _publication(value: object, now: datetime) -> tuple[datetime | None, date | None]:
    if not isinstance(value, str):
        return None, None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            day = date.fromisoformat(value)
            return (None, day) if day <= now.date() else (None, None)
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo and stamp <= now:
            return stamp.astimezone(UTC), stamp.date()
    except ValueError:
        pass
    return None, None


def parse_exa(payload: object, retrieved: datetime, cutoff: datetime | None) -> list[Article]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ResearchError("Exa returned an unrecognized search response.")
    seen = set()
    articles = []
    for row in payload["results"]:
        if not isinstance(row, dict) or not isinstance(row.get("url"), str):
            continue
        url = public_url(row["url"])
        if not url:
            continue
        identity = _identity(url)
        if identity in seen:
            continue
        published_at, published_date = _publication(row.get("publishedDate"), retrieved)
        if cutoff and ((published_at and published_at < cutoff) or (published_date and published_date < cutoff.date())):
            continue
        seen.add(identity)
        highlights = row.get("highlights")
        supporting = " ".join(item for item in highlights if isinstance(item, str)) if isinstance(highlights, list) else ""
        if not supporting:
            supporting = row["text"] if isinstance(row.get("text"), str) else ""
        domain = urlsplit(url).hostname or ""
        title = row["title"] if isinstance(row.get("title"), str) else ""
        publisher = row["publisher"] if isinstance(row.get("publisher"), str) else ""
        articles.append(Article(
            id=sha256(identity.encode()).hexdigest()[:32],
            title=_short(title, 300) or domain, url=url, publisher=_short(publisher, 150) or domain.removeprefix("www."),
            published_at=published_at, published_date=published_date, retrieved_at=retrieved,
            evidence=_short(supporting, SEARCH_EXCERPT_CHARS),
        ))
        if len(articles) == MAX_ARTICLES:
            break
    return articles


@asynccontextmanager
async def _exa_transport(api_key: str | None):
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx2.AsyncClient(headers=headers, timeout=12, follow_redirects=False) as http:
        async with streamable_http_client(EXA_ENDPOINT, http_client=http) as (read, write):
            yield read, write


def _text(result) -> str:
    return "\n".join(item.text for item in result.content if getattr(item, "type", None) == "text")


class MCPResearch:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def search(self, query: str, days: int | None, now: datetime, *, news_only: bool = True) -> list[Article]:
        cutoff = now - timedelta(days=days) if days is not None else None
        arguments = {
            "query": query, "numResults": MAX_ARTICLES,
            "enableHighlights": True, "highlightsMaxCharacters": SEARCH_EXCERPT_CHARS,
            "textMaxCharacters": SEARCH_EXCERPT_CHARS,
        }
        if news_only:
            arguments["category"] = "news"
        if cutoff is not None:
            arguments.update(startPublishedDate=cutoff.isoformat(), endPublishedDate=now.isoformat())
        try:
            async with asyncio.timeout(20):
                async with Client(_exa_transport(self.api_key), mode="legacy", read_timeout_seconds=12) as client:
                    result = await client.call_tool("web_search_advanced_exa", arguments)
        except Exception as error:
            raise ResearchError("Exa MCP is unavailable. Try again later.") from error
        if result.is_error:
            if "rate limit" in _text(result).casefold():
                raise ResearchError("Exa MCP search was rate-limited.")
            raise ResearchError("Exa MCP could not complete the search.")
        try:
            payload = result.structured_content or json.loads(_text(result))
        except (TypeError, ValueError) as error:
            message = _text(result).casefold()
            if "rate limit" in message or "429" in message:
                raise ResearchError("Exa MCP search was rate-limited.") from error
            raise ResearchError("Exa MCP returned an unrecognized search response.") from error
        return parse_exa(payload, now, cutoff)

    async def fetch(self, url: str) -> tuple[str, str]:
        page = await self._fetch_page(url, max_length=3500)
        return page.url, _short(page.text, FETCH_EXCERPT_CHARS)

    async def fetch_body(self, url: str) -> FetchedPage:
        return await self._fetch_page(url, max_length=ARTICLE_FETCH_CHARS)

    async def _fetch_page(self, url: str, *, max_length: int) -> FetchedPage:
        if not public_url(url):
            raise ResearchError("The article URL is not a supported public HTTPS address.")
        server = StdioServerParameters(
            command=sys.executable, args=["-m", "mcp_server_fetch", "--no-readability-js"],
            env={"PYTHONIOENCODING": "utf-8"},
        )
        try:
            async with asyncio.timeout(20):
                async with Client(server, read_timeout_seconds=15) as client:
                    result = await client.call_tool("fetch", {
                        "url": url, "max_length": max_length, "timeout_ms": 10000,
                    })
        except Exception as error:
            raise ResearchError("The local MCP Fetch server is unavailable.") from error
        if result.is_error:
            raise ResearchError("MCP Fetch could not access the page. The site may restrict automated reading.")
        text = _text(result)
        header = re.search(r"(?m)^Contents of (\S+):\s*\n", text)
        if not header or "cannot be simplified" in text[:header.start()].casefold():
            raise ResearchError("MCP Fetch did not return readable page text.")
        final_url = public_url(header[1])
        body, truncated, _ = text[header.end():].partition(TRUNCATION_NOTICE)
        body = body.strip()
        if not final_url or not body or body.startswith("<error>"):
            raise ResearchError("MCP Fetch did not return readable page text.")
        return FetchedPage(final_url, body, bool(truncated))

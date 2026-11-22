from datetime import UTC, datetime, timedelta
import sqlite3

from fastapi.testclient import TestClient

from app.main import create_app
from app.research.mcp_research import ResearchError, parse_exa, public_url
from test_portfolio import record

NOW = datetime(2026, 2, 20, 16, tzinfo=UTC)


def test_search_metadata_deduplicates_and_keeps_publication_distinct_from_retrieval():
    items = parse_exa({"results": [
        {"title": "Official release", "url": "https://www.bea.gov/release?utm_source=feed",
         "publishedDate": "2026-02-12T08:30:00-05:00", "highlights": ["Public evidence"]},
        {"title": "Duplicate", "url": "https://www.bea.gov/release"},
        {"title": "No timestamp", "url": "https://news.example/unknown", "text": "Unverified date"},
        {"title": "Date only", "url": "https://news.example/date", "publishedDate": "2026-02-11"},
        {"title": "Too old", "url": "https://news.example/old", "publishedDate": "2025-11-01"},
        {"title": "Private", "url": "https://127.0.0.1/local"},
    ]}, NOW, NOW - timedelta(days=30))
    official, unknown, date_only = items
    assert official.publisher == "bea.gov" and official.url == "https://www.bea.gov/release?utm_source=feed"
    assert official.published_at == datetime(2026, 2, 12, 13, 30, tzinfo=UTC)
    assert official.retrieved_at == NOW and official.evidence == "Public evidence"
    assert unknown.published_at is None and unknown.published_date is None
    assert date_only.published_at is None and date_only.published_date.isoformat() == "2026-02-11"
    for unsafe in ("javascript:alert(1)", "https://localhost", "https://[::1]/", "https://a.internal/",
                   "https://user@news.example/", "https://news.example:8443/"):
        assert public_url(unsafe) is None


def test_search_and_fetch_use_separate_database_cache_and_keep_attribution(tmp_path):
    portfolio = tmp_path / "portfolio.sqlite3"
    app = create_app(portfolio)
    service = app.state.financial_research
    now = [NOW]
    service.clock = lambda: now[0]

    class Provider:
        search_calls = []
        fetch_calls = []
        error = False

        async def search(self, query, days, retrieved):
            self.search_calls.append((query, days))
            if self.error:
                raise ResearchError("Search temporarily unavailable.")
            return parse_exa({"results": [
                {"title": "Official Federal Reserve release", "url": "https://www.federalreserve.gov/release",
                 "publishedDate": "2026-02-12T13:30:00Z", "text": "Public evidence"},
            ]}, retrieved, retrieved - timedelta(days=days))

        async def fetch(self, url):
            self.fetch_calls.append(url)
            if self.error:
                raise ResearchError("Fetch temporarily unavailable.")
            return "https://www.federalreserve.gov/final-page", "<script>text only</script> Official page excerpt"

    service.provider = provider = Provider()
    with TestClient(app) as client:
        record(client, symbol="QQQM", quantity="123.45")
        body = {"query": "  inflation   outlook  ", "days": 30}
        result = client.post("/api/research/search", json=body)
        assert result.status_code == 200
        [article] = result.json()["articles"]
        assert article["published_at"] == "2026-02-12T13:30:00Z"
        assert client.post("/api/research/search", json=body).json() == result.json()
        assert provider.search_calls == [("inflation outlook", 30)]
        assert client.post("/api/research/articles/" + "0" * 32 + "/fetch").status_code == 404
        assert not provider.fetch_calls

        endpoint = "/api/research/articles/" + article["id"] + "/fetch"
        fetched = client.post(endpoint).json()["article"]
        assert fetched["url"] == article["url"]
        assert fetched["fetched_url"] == "https://www.federalreserve.gov/final-page"
        assert fetched["published_at"] == article["published_at"]
        assert fetched["fetched_at"] and "Official page excerpt" in fetched["page_excerpt"]
        assert client.post(endpoint).json()["article"] == fetched
        assert provider.fetch_calls == [article["url"]]
        assert client.get("/api/research/recent").json() == [fetched]

        now[0] += timedelta(days=2)
        provider.error = True
        stale_search = client.post("/api/research/search", json=body).json()
        assert stale_search["is_stale"] and stale_search["retrieved_at"] == result.json()["retrieved_at"]
        stale_fetch = client.post(endpoint).json()
        assert stale_fetch["is_stale"] and stale_fetch["article"] == fetched

    with sqlite3.connect(app.state.research_database) as connection:
        assert connection.execute("SELECT name FROM sqlite_schema WHERE name='transactions'").fetchone() is None
    with sqlite3.connect(portfolio) as connection:
        assert connection.execute("SELECT name FROM sqlite_schema WHERE name='articles'").fetchone() is None

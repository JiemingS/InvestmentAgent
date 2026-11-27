import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Callable

from ..db import connect
from ..agent.ollama import Ollama
from .article_summary import ArticleSummary, SavedArticle, summarize_page
from .mcp_research import MCPResearch, ResearchError
from .models import Article, ArticleResult, SearchResult

SEARCH_TTL = timedelta(minutes=30)
FETCH_TTL = timedelta(days=1)


class ArticleNotFound(LookupError):
    pass


class ResearchService:
    def __init__(
        self, database: Path, provider: MCPResearch, clock: Callable[[], datetime] | None = None,
    ):
        self.database = database
        self.provider = provider
        self.clock = clock or (lambda: datetime.now(UTC))
        self.search_lock = asyncio.Lock()
        self.fetch_lock = asyncio.Lock()
        self.summary_lock = asyncio.Lock()

    def recent(self, limit: int) -> list[Article]:
        with connect(self.database) as connection:
            rows = connection.execute(
                "SELECT * FROM articles ORDER BY retrieved_at DESC, id LIMIT ?", (limit,),
            )
            return [Article.model_validate(dict(row)) for row in rows]

    def _cached_search(self, key: str, days: int) -> SearchResult | None:
        with connect(self.database) as connection:
            row = connection.execute(
                "SELECT * FROM searches WHERE query_key = ? AND days = ?", (key, days),
            ).fetchone()
            if not row:
                return None
            articles = connection.execute(
                """
                SELECT articles.* FROM json_each(?) AS ranked
                JOIN articles ON articles.id = ranked.value ORDER BY ranked.key
                """,
                (row["article_ids"],),
            )
            return SearchResult(
                query=row["query"], days=abs(days), retrieved_at=row["retrieved_at"],
                articles=[Article.model_validate(dict(article)) for article in articles],
            )

    async def search(self, query: str, days: int | None, *, force: bool, news_only: bool = True) -> SearchResult:
        key = query.casefold()
        # Positive keys belong to the existing news UI. Zero/negative keys are general web searches.
        cache_days = (days or 0) * (1 if news_only else -1)
        async with self.search_lock:
            now = self.clock()
            cached = self._cached_search(key, cache_days)
            if cached and not force and now - cached.retrieved_at < SEARCH_TTL:
                return cached
            try:
                if news_only:
                    articles = await self.provider.search(query, days, now)
                else:
                    articles = await self.provider.search(query, days, now, news_only=False)
            except ResearchError as error:
                if not cached:
                    raise
                return cached.model_copy(update={"is_stale": True, "warning": str(error)})
            retrieved = self.clock()
            articles = [article.model_copy(update={"retrieved_at": retrieved}) for article in articles]
            with connect(self.database, write=True) as connection:
                connection.executemany(
                    """
                    INSERT INTO articles
                        (id, title, url, publisher, published_at, published_date, retrieved_at, evidence)
                    VALUES (:id, :title, :url, :publisher, :published_at, :published_date, :retrieved_at, :evidence)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title, url=excluded.url, publisher=excluded.publisher,
                        published_at=COALESCE(excluded.published_at, articles.published_at),
                        published_date=COALESCE(excluded.published_date, articles.published_date),
                        retrieved_at=excluded.retrieved_at, evidence=excluded.evidence
                    """,
                    [article.model_dump(mode="json") for article in articles],
                )
                connection.execute(
                    """
                    INSERT INTO searches VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(query_key, days) DO UPDATE SET query=excluded.query,
                        retrieved_at=excluded.retrieved_at, article_ids=excluded.article_ids
                    """,
                    (key, cache_days, query, retrieved.isoformat(), json.dumps([article.id for article in articles])),
                )
            result = self._cached_search(key, cache_days)
            assert result is not None
            return result

    def _article(self, article_id: str) -> Article:
        with connect(self.database) as connection:
            row = connection.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
            if not row:
                raise ArticleNotFound("The article is not in the local research cache.")
            return Article.model_validate(dict(row))

    async def summarize_article(self, article_id: str, model: Ollama) -> ArticleSummary:
        article = self._article(article_id)
        async with self.summary_lock:
            try:
                async with asyncio.timeout(120):
                    page = await self.provider.fetch_body(article.url)
                    return await summarize_page(model, article.title, page)
            except TimeoutError as error:
                raise ResearchError("Article summarization timed out. Try again later.") from error

    def saved_articles(self) -> list[SavedArticle]:
        with connect(self.database) as connection:
            rows = connection.execute("SELECT * FROM saved_articles ORDER BY saved_at DESC, id")
            return [SavedArticle.model_validate({**dict(row), "summary": json.loads(row["summary"])}) for row in rows]

    def save_article(self, article_id: str, summary: ArticleSummary) -> SavedArticle:
        article = self._article(article_id)
        fields = article.model_dump(include={"id", "title", "url", "publisher", "published_at", "published_date"}, mode="json")
        with connect(self.database, write=True) as connection:
            row = connection.execute(
                """
                INSERT INTO saved_articles (id, title, url, publisher, published_at, published_date, saved_at, summary)
                VALUES (:id, :title, :url, :publisher, :published_at, :published_date, :saved_at, :summary)
                ON CONFLICT(id) DO UPDATE SET summary=excluded.summary
                RETURNING *
                """,
                {**fields, "saved_at": self.clock().isoformat(), "summary": summary.model_dump_json()},
            ).fetchone()
            return SavedArticle.model_validate({**dict(row), "summary": json.loads(row["summary"])})

    async def fetch_article(self, article_id: str, *, force: bool) -> ArticleResult:
        async with self.fetch_lock:
            now = self.clock()
            article = self._article(article_id)
            if article.fetched_at and not force and now - article.fetched_at < FETCH_TTL:
                return ArticleResult(article=article)
            try:
                final_url, excerpt = await self.provider.fetch(article.url)
            except ResearchError as error:
                if not article.fetched_at:
                    raise
                return ArticleResult(article=article, is_stale=True, warning=str(error))
            with connect(self.database, write=True) as connection:
                connection.execute(
                    "UPDATE articles SET fetched_at = ?, fetched_url = ?, page_excerpt = ? WHERE id = ?",
                    (self.clock().isoformat(), final_url, excerpt, article_id),
                )
            return ArticleResult(article=self._article(article_id))

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

CHICAGO = ZoneInfo("America/Chicago")
EASTERN = ZoneInfo("America/New_York")


class Agency(StrEnum):
    FED = "FED"
    BLS = "BLS"
    BEA = "BEA"


class Event(BaseModel):
    id: str
    agency: Agency
    event_type: str
    title: str
    event_date: date
    end_date: date
    scheduled_at_utc: datetime | None = None
    timezone: str
    original_time: str | None = None
    source_url: str
    status: Literal["confirmed", "estimated", "unverified", "cancelled"] = "confirmed"
    provider_id: str | None = None
    sequence: int | None = None
    provider_updated_at: datetime | None = None
    last_verified_at: datetime

    @property
    def display_date(self) -> date:
        return self.scheduled_at_utc.astimezone(CHICAGO).date() if self.scheduled_at_utc else self.event_date


class CalendarStatus(BaseModel):
    agency: Agency
    source_url: str
    status: Literal["never", "ok", "partial", "error", "imported"] = "never"
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_import_at: datetime | None = None
    error_message: str | None = None
    coverage_start: date | None = None
    coverage_end: date | None = None


class CalendarResult(BaseModel):
    events: list[Event]
    sources: list[CalendarStatus]


class SearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=160)
    days: Literal[7, 30, 90] = 30
    force: bool = False


class Article(BaseModel):
    id: str
    title: str
    url: str
    publisher: str
    published_at: datetime | None = None
    published_date: date | None = None
    retrieved_at: datetime
    evidence: str
    fetched_at: datetime | None = None
    fetched_url: str | None = None
    page_excerpt: str | None = None


class SearchResult(BaseModel):
    query: str
    days: int
    provider: str = "Exa"
    retrieved_at: datetime
    articles: list[Article]
    is_stale: bool = False
    warning: str | None = None


class ArticleResult(BaseModel):
    article: Article
    provider: str = "MCP Fetch"
    is_stale: bool = False
    warning: str | None = None

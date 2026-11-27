from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request

from .calendar_service import CalendarService
from .calendars import CalendarError, MAX_CALENDAR_BYTES
from .mcp_research import ResearchError
from .models import Agency, Article, ArticleResult, CalendarResult, CalendarStatus, CHICAGO, SearchInput, SearchResult
from .polymarket import Polymarket, PredictionResult
from .research_service import ArticleNotFound, ResearchService

router = APIRouter(prefix="/api")


def _agencies(agency: Agency | None) -> list[Agency]:
    return [agency] if agency else list(Agency)


@router.get("/events")
async def get_events(
    request: Request, start: date | None = None, end: date | None = None,
    agency: Agency | None = None, refresh: bool = True,
) -> CalendarResult:
    service: CalendarService = request.app.state.economic_calendar
    today = service.clock().astimezone(CHICAGO).date()
    default_start = date.fromordinal(max(1, end.toordinal() - 30)) if end and end < today else today
    first = start or default_start
    last = end or date.fromordinal(min(date.max.toordinal(), first.toordinal() + 30))
    if first > last or (last - first).days > 730:
        raise HTTPException(422, "Choose an ordered calendar range of up to 731 days.")
    agencies = _agencies(agency)
    if refresh:
        await service.refresh(agencies)
    return service.events(first, last, agencies)


@router.post("/events/refresh")
async def refresh_events(request: Request, agency: Agency | None = None) -> list[CalendarStatus]:
    service: CalendarService = request.app.state.economic_calendar
    return await service.refresh(_agencies(agency), force=True)


@router.get("/events/prediction-markets")
async def prediction_markets(
    request: Request, start: date, end: date, agency: Agency | None = None,
) -> PredictionResult:
    calendar = await get_events(request, start, end, agency, refresh=False)
    service: CalendarService = request.app.state.economic_calendar
    provider: Polymarket = request.app.state.polymarket
    return await provider.for_events(calendar.events, service.clock().astimezone(CHICAGO).date())


@router.post("/events/bls/import")
async def import_bls(request: Request) -> list[CalendarStatus]:
    media = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media not in ("text/calendar", "application/octet-stream"):
        raise HTTPException(415, "Send the official BLS .ics file as text/calendar.")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_CALENDAR_BYTES:
            raise HTTPException(413, "The BLS .ics file is larger than 2 MB.")
    service: CalendarService = request.app.state.economic_calendar
    try:
        return await service.import_bls(bytes(content))
    except CalendarError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/research/recent")
def recent_research(request: Request, limit: Annotated[int, Query(ge=1, le=30)] = 20) -> list[Article]:
    service: ResearchService = request.app.state.financial_research
    return service.recent(limit)


@router.post("/research/search")
async def search_research(request: Request, data: SearchInput) -> SearchResult:
    query = " ".join(data.query.split())
    if len(query) < 2:
        raise HTTPException(422, "Enter a public financial topic or ticker.")
    service: ResearchService = request.app.state.financial_research
    try:
        return await service.search(query, data.days, force=data.force)
    except ResearchError as error:
        raise HTTPException(502, str(error)) from error


@router.post("/research/articles/{article_id}/fetch")
async def fetch_article(
    request: Request, article_id: Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")], force: bool = False,
) -> ArticleResult:
    service: ResearchService = request.app.state.financial_research
    try:
        return await service.fetch_article(article_id, force=force)
    except ArticleNotFound as error:
        raise HTTPException(404, str(error)) from error
    except ResearchError as error:
        raise HTTPException(502, str(error)) from error

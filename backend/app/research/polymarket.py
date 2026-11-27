import asyncio
import calendar
import json
import re
from datetime import UTC, date, datetime, timedelta
from time import monotonic

import httpx
from pydantic import BaseModel

from .models import Event

SEARCH_URL = "https://gamma-api.polymarket.com/public-search"
CACHE_SECONDS = 300
RETRY_SECONDS = 30
MONTHS = tuple(calendar.month_name)[1:]
TOPICS = {
    "FOMC decision": ("Fed rate decision", r"\b(?:fed|fomc)\b.*\b(?:decision|interest rates?)\b"),
    "CPI": ("US inflation CPI", r"\b(?:cpi|consumer price index|inflation)\b"),
    "PPI": ("US producer price index PPI", r"\b(?:ppi|producer price index|producer prices)\b"),
    "Employment Situation": ("US unemployment rate nonfarm payrolls", r"\b(?:unemployment|nonfarm payrolls|jobs report)\b"),
    "Personal Income and Outlays / PCE": ("US PCE inflation", r"\b(?:pce|personal consumption expenditures)\b"),
    "GDP": ("US GDP growth", r"\b(?:gdp|gross domestic product)\b"),
}


class MarketOutcome(BaseModel):
    label: str
    probability: float


class PredictionMarket(BaseModel):
    title: str
    url: str
    outcomes: list[MarketOutcome]


class PredictionResult(BaseModel):
    matches: dict[str, list[PredictionMarket]]
    checked_at: datetime | None = None
    unavailable: bool = False


def _period(event: Event) -> str:
    if event.event_type == "FOMC decision":
        return MONTHS[event.end_date.month - 1]
    if event.event_type == "GDP":
        quarter = re.search(r"\b(?:q([1-4])|([1-4])(?:st|nd|rd|th) quarter)\b", event.title, re.I)
        return "Q" + (quarter[1] or quarter[2]) if quarter and "advance" in event.title.lower() else ""
    months = re.findall(r"\b(" + "|".join(MONTHS) + r")\b", event.title, re.I)
    if months:
        return months[-1]
    previous_month = event.event_date.replace(day=1) - timedelta(days=1)
    return MONTHS[previous_month.month - 1]


def _event_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _matches(event: Event, item: dict, period: str) -> bool:
    if item.get("closed") is not False or item.get("active") is not True or item.get("archived"):
        return False
    release = event.end_date if event.event_type == "FOMC decision" else event.event_date
    end = _event_date(item.get("endDate"))
    if end is None or abs((end - release).days) > 2:
        return False
    title = str(item.get("title", "")).lower()
    slug = str(item.get("slug", "")).replace("-", " ").lower()
    if not re.search(rf"\b{re.escape(period.lower())}\b", title + " " + slug):
        return False
    if not re.search(TOPICS[event.event_type][1], title):
        return False
    if event.event_type == "FOMC decision":
        return not re.search(r"\b(?:dissent|dissents|speech|resign|combo)\b", title)
    if event.event_type == "CPI" and re.search(r"\b(?:ppi|pce|producer)\b", title):
        return False
    source = str(item.get("resolutionSource", "")) + " " + str(item.get("description", ""))
    agency = "bea" if event.agency == "BEA" else "bls"
    return bool(re.search(r"\b(?:us|united states)\b", title.replace("u.s.", "us") + " " + slug)
                or re.search(rf"\b{agency}\.gov\b", source.lower()))


def _outcomes(market: dict) -> list[MarketOutcome]:
    labels = market.get("outcomes")
    prices = market.get("outcomePrices")
    try:
        labels = json.loads(labels) if isinstance(labels, str) else labels
        prices = json.loads(prices) if isinstance(prices, str) else prices
        if not isinstance(labels, list) or not isinstance(prices, list) or len(labels) != len(prices):
            return []
        outcomes = [
            MarketOutcome(label=label, probability=float(price))
            for label, price in zip(labels, prices, strict=True)
            if isinstance(label, str) and label.strip() and 0 <= float(price) <= 1
        ]
        return outcomes if len(outcomes) == len(labels) else []
    except (ValueError, TypeError, OverflowError):
        return []


def match_markets(event: Event, items: list[dict], period: str) -> list[PredictionMarket]:
    matches = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not _matches(event, item, period):
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9-]+", slug) or slug in seen:
            continue
        markets = [
            (market, outcomes) for market in item.get("markets") or []
            if isinstance(market, dict) and market.get("active") is True
            and market.get("closed") is False and not market.get("archived")
            and (outcomes := _outcomes(market))
        ]
        if not markets:
            continue
        if len(markets) == 1:
            outcomes = markets[0][1]
        else:
            outcomes = []
            for market, choices in markets:
                label = market.get("groupItemTitle") or market.get("question")
                yes = next((choice for choice in choices if choice.label.casefold() == "yes"), None)
                if isinstance(label, str) and yes:
                    outcomes.append(MarketOutcome(label=label, probability=yes.probability))
                elif isinstance(label, str):
                    outcomes.extend(MarketOutcome(label=f"{label} · {choice.label}", probability=choice.probability)
                                    for choice in choices)
        if outcomes:
            seen.add(slug)
            matches.append(PredictionMarket(
                title=str(item["title"]), url=f"https://polymarket.com/event/{slug}", outcomes=outcomes,
            ))
    return matches


class Polymarket:
    def __init__(self):
        self.cache: dict[str, tuple[float, datetime, list[dict] | None]] = {}
        self.lock = asyncio.Lock()

    async def _search(self, client: httpx.AsyncClient, query: str) -> tuple[datetime, list[dict] | None]:
        try:
            response = await client.get(SEARCH_URL, params={
                "q": query, "limit_per_type": 15, "events_status": "active",
                "search_profiles": "false", "search_tags": "false",
            })
            response.raise_for_status()
            payload = response.json()
            items = payload.get("events") if isinstance(payload, dict) and "events" in payload else None
            if isinstance(payload, dict) and "events" in payload and items is None:
                items = []
            if not isinstance(items, list):
                raise ValueError("Invalid Polymarket search result")
        except (httpx.HTTPError, ValueError):
            items = None
        return datetime.now(UTC), items

    async def for_events(self, events: list[Event], today: date) -> PredictionResult:
        queries: dict[str, list[tuple[Event, str]]] = {}
        decision_dates = {
            event.end_date for event in events
            if event.event_type == "FOMC decision" and event.status != "cancelled"
        }
        for event in events:
            if event.event_type == "FOMC meeting" and event.end_date not in decision_dates:
                # Some official calendar ranges have a meeting without a separate decision row.
                event = event.model_copy(update={"event_type": "FOMC decision"})
            release = event.end_date if event.event_type == "FOMC decision" else event.event_date
            if (event.status == "cancelled" or event.event_type not in TOPICS
                    or not 0 <= (release - today).days <= 90):
                continue
            if period := _period(event):
                query = f"{TOPICS[event.event_type][0]} {period}"
                queries.setdefault(query, []).append((event, period))
        if not queries:
            return PredictionResult(matches={})

        async with self.lock, httpx.AsyncClient(timeout=5, limits=httpx.Limits(max_connections=6)) as client:
            now = monotonic()
            self.cache = {key: value for key, value in self.cache.items() if value[0] > now}
            missing = [query for query in queries if query not in self.cache]
            results = await asyncio.gather(*(self._search(client, query) for query in missing))
            for query, (checked, items) in zip(missing, results, strict=True):
                self.cache[query] = (monotonic() + (CACHE_SECONDS if items is not None else RETRY_SECONDS), checked, items)
            matches = {}
            checks = []
            unavailable = False
            for query, targets in queries.items():
                _, checked, items = self.cache[query]
                if items is None:
                    unavailable = True
                    continue
                checks.append(checked)
                for event, period in targets:
                    if markets := match_markets(event, items, period):
                        matches[event.id] = markets
            return PredictionResult(matches=matches, checked_at=min(checks, default=None), unavailable=unavailable)

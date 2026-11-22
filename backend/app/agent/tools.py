import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
import re
from typing import Annotated, Awaitable, Callable, Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from ..exchange import market_sessions
from ..market import MarketDataService
from ..research.calendar_service import CalendarService
from ..research.mcp_research import ResearchError, public_url
from ..research.models import Agency, CHICAGO, Article
from ..research.research_service import ResearchService
from ..schemas import PortfolioValuation, Transaction
from ..transactions import list_transactions
from ..valuation import value_portfolio
from .models import Evidence, EvidenceID, EvidenceKind
from .public_search import (
    JOURNEY, MACRO, PUBLIC_MACRO_QUERY, SECRET, WORDS, public_clauses, public_terms, query_words, scoped_query, terms_from_text,
)

Ticker = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,3})?$")]
FUND_PROFILES = {
    "VOO": ("https://investor.vanguard.com/investment-products/etfs/profile/voo",
            "VOO tracks the S&P 500, providing exposure to large US companies across industries."),
    "QQQM": ("https://www.invesco.com/us/en/financial-products/etfs/invesco-nasdaq-100-etf.html",
             "QQQM tracks the Nasdaq-100, an index of large non-financial companies listed on Nasdaq, with growth-oriented exposure."),
}
PUBLIC_INSTRUMENTS = {
    "VOO": "VOO Vanguard S&P 500 ETF",
    "QQQM": "QQQM Invesco Nasdaq 100 ETF",
    "SPY": "SPY SPDR S&P 500 ETF",
    "QQQ": "QQQ Invesco Nasdaq 100 ETF",
    "VTI": "VTI Vanguard Total Stock Market ETF",
}


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PortfolioArgs(Args):
    symbols: list[Ticker] = Field(default_factory=list, max_length=5)


class TransactionArgs(PortfolioArgs):
    limit: int = Field(default=8, ge=1, le=12, description="Maximum individual entries displayed. An overview always covers all matching records.")

    @field_validator("limit", mode="before")
    @classmethod
    def cap_milestones(cls, value):
        return min(value, 12) if type(value) is int else value


class HistoryArgs(Args):
    symbols: list[Ticker] = Field(min_length=1, max_length=4)
    days: int = Field(default=14, ge=1, le=90)
    unit: Literal["calendar_days", "completed_sessions"] = "calendar_days"


class EventArgs(Args):
    past_days: int = Field(default=7, ge=0, le=30)
    future_days: int = Field(default=14, ge=0, le=60)


class SearchArgs(Args):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
    days: Annotated[int, Field(ge=1, le=90)] | None = None


class FetchArgs(Args):
    source_id: EvidenceID


class ClockArgs(Args):
    timezone: Annotated[str, StringConstraints(min_length=1, max_length=80)] = "America/Chicago"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Use a valid IANA time zone.") from error
        return value


class ToolRejected(ValueError):
    pass


class SearchRejected(ToolRejected):
    def __init__(self, message: str, suggestions: list[str] | None = None):
        super().__init__(message)
        self.suggestions = suggestions or []


@dataclass
class ToolResult:
    sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ToolContext:
    database: Path
    market: MarketDataService
    calendar: CalendarService
    research: ResearchService
    question: str
    now: Callable[[], datetime]
    expand_public_search: Callable[[list[str], list[str]], Awaitable[list[str]]] | None = None
    evidence: dict[str, Evidence] = field(default_factory=dict)
    article_ids: dict[str, str] = field(default_factory=dict)
    web_matches: dict[str, list[str]] = field(default_factory=dict)
    valuations: dict[tuple[str, ...], PortfolioValuation] = field(default_factory=dict)
    ledger: list[Transaction] | None = None
    public_instruments: set[str] = field(default_factory=set)
    search_ideas: list[str] = field(default_factory=list)
    search_expanded: bool = False

    def add(self, kind: EvidenceKind, title: str, text: str, **details) -> str:
        if details.get("url"):
            details["url"] = public_url(details["url"])
        key = f"E{len(self.evidence) + 1}"
        self.evidence[key] = Evidence(
            id=key, kind=kind, title=title, text=text,
            **{"retrieved_at": self.now(), **details},
        )
        return key

    async def trades(self, symbols: list[str]) -> list[Transaction]:
        if self.ledger is None:
            self.ledger = await asyncio.to_thread(list_transactions, self.database)
        return [row for row in self.ledger if not symbols or row.symbol in symbols]

    async def valuation(self, symbols: list[str]) -> PortfolioValuation:
        key = tuple(sorted(set(symbols)))
        if key not in self.valuations:
            trades = await self.trades(symbols)
            self.valuations[key] = await asyncio.to_thread(value_portfolio, trades, self.market)
        return self.valuations[key]


def _amount(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    with localcontext() as context:
        context.prec = 96
        return f"${value:,.2f}"


def _shares(value: Decimal) -> str:
    formatted = format(value, "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


async def local_time(ctx: ToolContext, args: ClockArgs) -> ToolResult:
    try:
        zone = ZoneInfo(args.timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ToolRejected("Use an IANA time zone such as America/Chicago, Asia/Shanghai or UTC.") from error
    now = ctx.now()
    local = now.astimezone(zone)
    source = ctx.add(
        "clock", "Local system clock",
        f"{local:%A, %Y-%m-%d %H:%M:%S %Z} ({zone.key}, UTC{local:%z}).",
        observed_at=now, retrieved_at=now,
    )
    return ToolResult([source])


async def holdings(ctx: ToolContext, args: PortfolioArgs) -> ToolResult:
    data = await ctx.valuation(args.symbols)
    ctx.public_instruments.update(row.symbol for row in data.positions if row.symbol in PUBLIC_INSTRUMENTS)
    sources = [ctx.add(
        "portfolio", f"Local holdings · {row.symbol}",
        f"{row.symbol}: {_shares(row.shares)} shares; average cost per share {_amount(row.average_cost_per_share)}; "
        f"remaining cost basis {_amount(row.remaining_cost_basis)}.",
    ) for row in data.positions[:12]]
    missing = sorted(set(args.symbols) - {row.symbol for row in data.positions})
    if missing or not data.positions:
        label = ", ".join(missing)
        text = f"No open position in {label} in the local ledger." if label else "No open positions in the local ledger."
        sources.append(ctx.add("portfolio", "Local holdings snapshot", text))
    return ToolResult(sources, warnings=data.summary.warnings[:4])


async def transactions(ctx: ToolContext, args: TransactionArgs) -> ToolResult:
    rows = sorted(await ctx.trades(args.symbols), key=lambda row: (row.trade_date, row.id))
    def source(row: Transaction) -> str:
        return ctx.add(
            "portfolio", f"Local transaction · {row.symbol}",
            f"{row.trade_date}: {row.side} {_shares(row.quantity)} {row.symbol} at "
            f"{_amount(row.unit_price)} per share, fees {_amount(row.fees)}.",
        )

    if not JOURNEY.search(ctx.question):
        sources = [source(row) for row in reversed(rows[-args.limit:])]
        return ToolResult(sources, notes=[f"{len(rows)} matching local transactions; {len(sources)} returned."])
    if not rows:
        return ToolResult([ctx.add("portfolio", "Local transaction history", "No matching transactions in the local ledger.")])
    buys = sum(row.side == "BUY" for row in rows)
    overview = ctx.add(
        "portfolio", "Local transaction history",
        f"Recorded history from {rows[0].trade_date} through {rows[-1].trade_date}: "
        f"{len(rows)} transactions ({buys} buys, {len(rows) - buys} sells). "
        f"First recorded trade: {rows[0].side} {rows[0].symbol}. "
        f"Latest recorded trade: {rows[-1].side} {rows[-1].symbol}.",
    )
    milestones = {}
    for row in rows:
        milestones.setdefault((row.symbol, row.side), row)
    candidates = list(dict.fromkeys(row.id for row in [rows[0], rows[-1], *milestones.values(), *reversed(rows)]))
    selected = set(candidates[:args.limit])
    sources = [overview, *(source(row) for row in rows if row.id in selected)]
    return ToolResult(sources, notes=[f"{len(rows)} matching local transactions; {len(sources)-1} milestones shown in date order."])


def _yahoo_url(symbol: str) -> str:
    return f"https://finance.yahoo.com/quote/{quote(symbol.replace('.', '-'), safe='')}/history/"


async def current_values(ctx: ToolContext, args: PortfolioArgs) -> ToolResult:
    data = await ctx.valuation([])
    total = data.summary.market_value
    selected = [row for row in data.positions if not args.symbols or row.symbol in args.symbols]
    ctx.public_instruments.update(row.symbol for row in selected if row.symbol in PUBLIC_INSTRUMENTS)
    def weight(value):
        if value is None or not total or total <= 0:
            return "unavailable"
        with localcontext() as context:
            context.prec = 64
            return f"{value * 100 / total:.2f}%"
    sources = [ctx.add(
        "market", f"Yahoo Finance / local valuation · {row.symbol}",
        f"{row.symbol}: latest daily price {_amount(row.latest_price)}; position value "
        f"{_amount(row.market_value)}; unrealized P&L {_amount(row.unrealized_pnl)}; "
        f"weight in all open positions {weight(row.market_value)}."
        + (" The daily bar is partial." if row.is_partial else ""),
        url=_yahoo_url(row.symbol), observed_at=row.quote_as_of,
        retrieved_at=row.quote_updated_at or ctx.now(), stale=row.is_stale,
    ) for row in selected[:12]]
    if data.positions:
        sources.append(ctx.add(
            "market", "Local portfolio valuation",
            f"All open positions: market value {_amount(total)}; unrealized P&L {_amount(data.summary.unrealized_pnl)}."
            + (" Weights are unavailable without prices for all open positions." if total is None else ""),
            observed_at=data.summary.quote_as_of, stale=data.summary.is_stale,
        ))
    for row in selected[:12]:
        if row.symbol in FUND_PROFILES:
            url, description = FUND_PROFILES[row.symbol]
            sources.append(ctx.add("market", f"Fund mandate · {row.symbol}", description, url=url))
    return ToolResult(sources, notes=["No open positions to value."] if not sources else [], warnings=data.summary.warnings[:4])


def explicit_window_count(question: str, units: str) -> int | None:
    words = dict(zip("one two three four five six seven eight nine ten".split(), range(1, 11)))
    match = re.search(
        rf"\b(\d{{1,2}}|{'|'.join(words)})\s+(?:{units})\b", question, re.I,
    )
    if match:
        token = match[1].lower()
        return int(token) if token.isdigit() and 1 <= int(token) <= 90 else words.get(token)
    return None


async def history(ctx: ToolContext, args: HistoryArgs) -> ToolResult:
    today = ctx.market.today()
    explicit = explicit_window_count(
        ctx.question, r"(?:completed\s+)?(?:US\s+)?trading\s+(?:days?|sessions?)|completed\s+sessions?",
    )
    calendar_days = explicit_window_count(ctx.question, r"calendar\s+days?") if explicit is None else None
    count = explicit or calendar_days or args.days
    session_mode = explicit is not None or (calendar_days is None and args.unit == "completed_sessions")
    now = ctx.market.clock()
    first = today - timedelta(days=count * 3 + 14 if session_mode else count - 1)
    expected = [session.date for session in market_sessions(first, today) if session.is_final(now)]
    if session_mode:
        expected = expected[-count:]
    result = ToolResult()
    if not expected:
        return ToolResult(warnings=["There are no completed US trading sessions in the requested window."])
    label = f"{count} completed sessions" if session_mode else f"{count} calendar days ({len(expected)} completed sessions)"
    result.notes.append(f"Requested {label}; exchange window {expected[0]} through {expected[-1]}.")
    comparisons = {}
    for symbol in dict.fromkeys(args.symbols):
        data = await asyncio.to_thread(ctx.market.get_market_history, symbol, expected[0], expected[-1])
        if data.warning:
            result.warnings.append(f"{symbol}: {data.warning}")
        bars = [bar for bar in data.bars if bar.is_final and bar.date in expected]
        missing = sorted(set(expected) - {bar.date for bar in bars})
        if missing:
            result.warnings.append(f"{symbol}: {len(bars)} of {len(expected)} completed sessions available. Missing: "
                                   + ", ".join(str(day) for day in missing[:8]) + ".")
        if not bars:
            result.warnings.append(f"{symbol}: no finalized prices in the requested period.")
            continue
        opening, closing = bars[0], bars[-1]
        comparable = not missing and len(bars) > 1 and not any(
            action.is_split and opening.date < action.date <= closing.date for action in data.actions
        )
        with localcontext() as context:
            context.prec = 64
            change = ((closing.close / opening.close) - 1) * 100
        details = ", ".join(f"{bar.date} {_amount(bar.close)}" for bar in bars) if len(expected) <= 10 else ""
        result.sources.append(ctx.add(
            "market", f"Yahoo Finance daily history · {symbol}",
            f"{symbol}: {len(bars)} finalized sessions. Close {_amount(opening.close)} on {opening.date}; "
            f"close {_amount(closing.close)} on {closing.date}."
            + (f" Price-only change {change:+.2f}%." if comparable else "")
            + (f" Daily closes: {details}." if details else ""),
            url=_yahoo_url(symbol), observed_at=closing.price_as_of, retrieved_at=closing.updated_at,
            stale=data.is_stale,
        ))
        if comparable:
            comparisons[symbol] = (change, result.sources[-1])
    if len(comparisons) >= 2:
        ranked = sorted(comparisons, key=lambda symbol: comparisons[symbol][0], reverse=True)
        better, weaker = ranked[0], ranked[-1]
        with localcontext() as context:
            context.prec = 64
            spread = comparisons[better][0] - comparisons[weaker][0]
        references = [comparisons[key][1] for key in (better, weaker)]
        inputs = [ctx.evidence[key] for key in references]
        result.sources.append(ctx.add(
            "market", "Matched-window ETF performance",
            f"Over the same {len(expected)} completed sessions, {better}'s price-only change was "
            f"{spread:.2f} percentage points higher than {weaker}'s." if spread else
            f"{better} and {weaker} had equal price-only changes over the matched window.",
            observed_at=min((item.observed_at for item in inputs if item.observed_at), default=None),
            stale=any(item.stale for item in inputs), derived_from=references,
        ))
    return result


async def calendar(ctx: ToolContext, args: EventArgs) -> ToolResult:
    today = ctx.now().astimezone(CHICAGO).date()
    first, last = today - timedelta(days=args.past_days), today + timedelta(days=args.future_days)
    agencies = list(Agency)
    await ctx.calendar.refresh(agencies)
    data = ctx.calendar.events(first, last, agencies)
    states = {source.agency: source for source in data.sources}
    past = [event for event in data.events if event.display_date < today]
    future = [event for event in data.events if event.display_date >= today]
    sources = []
    for event in [*past[-5:], *future[:7]]:
        when = event.display_date.isoformat()
        if event.scheduled_at_utc:
            when = event.scheduled_at_utc.astimezone(CHICAGO).strftime("%Y-%m-%d %H:%M %Z")
        elif event.end_date != event.event_date:
            when += f" to {event.end_date}; time unpublished"
        else:
            when += "; time unpublished"
        sources.append(ctx.add(
            "calendar", f"{event.agency} · {event.title}",
            f"{event.title} · {when} · {event.status}.",
            url=event.source_url, observed_at=event.scheduled_at_utc, retrieved_at=event.last_verified_at,
            stale=states[event.agency].status in ("partial", "error", "never") or event.status == "unverified",
        ))
    notes = [f"Requested calendar window {first} through {last}; cached events {len(data.events)}."]
    warnings = [f"{row.agency}: {row.error_message}" for row in data.sources if row.error_message]
    return ToolResult(sources, notes, warnings)


def _news_text(article: Article) -> str:
    published = article.published_at.isoformat() if article.published_at else (
        article.published_date.isoformat() if article.published_date else "unavailable"
    )
    return f"Reported by {article.publisher}. Publication metadata: {published}."


async def _public_search_query(ctx: ToolContext, proposal: str) -> str:
    if SECRET.search(ctx.question):
        raise SearchRejected("Search is blocked for a question containing credential-related text. Ask the public question separately.")
    instruments = [PUBLIC_INSTRUMENTS[symbol] for symbol in sorted(ctx.public_instruments)][:5]
    instrument_terms = {word for name in instruments for word in WORDS.findall(name.casefold())}
    macro_terms = terms_from_text(PUBLIC_MACRO_QUERY + " Federal Reserve BEA BLS GDP interest rates CPI")
    has_macro = bool(MACRO.search(ctx.question))
    approved = instrument_terms | macro_terms if has_macro else instrument_terms
    query = scoped_query(ctx.question, proposal, extra_terms=approved)
    if query:
        return query

    if not ctx.search_expanded:
        ctx.search_expanded = True
        clauses = public_clauses(ctx.question)
        if has_macro:
            clauses.append(PUBLIC_MACRO_QUERY)
            ctx.search_ideas.append(PUBLIC_MACRO_QUERY)
        if not clauses and instruments and re.search(r"\b(?:news|headlines)\b|新闻|头条", ctx.question, re.I):
            clauses = ["recent public market news"]
        if ctx.expand_public_search and (clauses or instruments):
            try:
                # The proposed query is deliberately omitted from this isolated call.
                async with asyncio.timeout(8):
                    ideas = await ctx.expand_public_search([clause[:220] for clause in clauses[:6]], instruments)
            except (TimeoutError, ValueError, RuntimeError):
                ideas = []
            allowed_numbers = public_terms(ctx.question) | instrument_terms
            for idea in ideas[:4]:
                words = query_words(idea)
                if words and all(not any(char.isdigit() for char in word) or word in allowed_numbers for word in words):
                    ctx.search_ideas.append(" ".join(words))

    expanded_terms = terms_from_text(" ".join(ctx.search_ideas))
    query = scoped_query(ctx.question, proposal, extra_terms=approved | expanded_terms)
    if query:
        return query
    suggestions = [
        query for idea in ctx.search_ideas
        if (query := scoped_query(ctx.question, idea, extra_terms=approved | expanded_terms))
    ][:3]
    raise SearchRejected(
        "Search must use approved public wording. Use a suggested query or simplify the public keywords; "
        "use the days field for recency and omit private details.", suggestions,
    )


async def web_search(ctx: ToolContext, args: SearchArgs) -> ToolResult:
    query = await _public_search_query(ctx, args.query)
    data = await ctx.research.search(query, args.days, force=False, news_only=False)
    sources = []
    previous = {article_id: source for source, article_id in ctx.article_ids.items()}
    for article in data.articles[:6]:
        source = previous.get(article.id)
        if source is None:
            source = ctx.add(
                "news", article.title, _news_text(article), url=article.url,
                observed_at=article.published_at, retrieved_at=article.retrieved_at,
                stale=data.is_stale, excerpt=article.page_excerpt or article.evidence,
                search_excerpt=article.evidence,
                fetched_at=article.fetched_at,
                fetched_url=public_url(article.fetched_url) if article.fetched_url else None,
            )
            ctx.article_ids[source] = article.id
        sources.append(source)
        matches = set(query.split()) & set(WORDS.findall(f"{article.title} {article.evidence}".casefold()))
        ctx.web_matches[source] = sorted(set(ctx.web_matches.get(source, [])) | matches)[:14]
    window = f"past {args.days} days" if args.days is not None else "no publication-date filter"
    warnings = [data.warning] if data.warning else []
    if not sources:
        warnings.append("Exa returned no usable public sources for this query.")
    return ToolResult(
        sources, [f"Exa web search: {window}; {len(sources)} ranked sources. Public query: {query}."], warnings,
    )


async def fetch(ctx: ToolContext, args: FetchArgs) -> ToolResult:
    article_id = ctx.article_ids.get(args.source_id)
    if not article_id:
        raise ToolRejected("Web Fetch accepts only a source ID returned by this turn's web search.")
    original = ctx.evidence[args.source_id]
    try:
        result = await ctx.research.fetch_article(article_id, force=False)
    except ResearchError as error:
        ctx.evidence[args.source_id] = original.model_copy(update={"fetch_error": str(error)})
        raise
    ctx.evidence[args.source_id] = original.model_copy(update={
        "fetched_url": public_url(result.article.fetched_url or result.article.url),
        "fetched_at": result.article.fetched_at, "excerpt": result.article.page_excerpt or original.excerpt,
        "stale": original.stale or result.is_stale,
        "fetch_error": result.warning,
    })
    return ToolResult([args.source_id], notes=[f"Page excerpt for {args.source_id}."],
                      warnings=[result.warning] if result.warning else [])


@dataclass(frozen=True)
class Tool:
    args: type[Args]
    description: str
    handler: Callable[..., Awaitable[ToolResult]]
    seconds: float = 24

    def schema(self, name: str) -> dict:
        return {"type": "function", "function": {
            "name": name, "description": self.description, "parameters": self.args.model_json_schema(),
        }}


TOOLS = {
    "get_local_datetime": Tool(ClockArgs, "Read the current date, time and weekday from the local clock. Default America/Chicago; set the requested IANA time zone.", local_time, 2),
    "get_portfolio": Tool(PortfolioArgs, "Read actual local holdings and cost basis. Specify named symbols if relevant.", holdings),
    "get_transactions": Tool(TransactionArgs, "Read recorded BUY and SELL history, including chronological milestones. Call with {} for the whole ledger. Optional symbols is an array of ticker strings, and optional limit is an integer from 1 to 12.", transactions),
    "get_current_valuations": Tool(PortfolioArgs, "Get current daily prices, position value and unrealized P&L for local holdings.", current_values),
    "get_market_history": Tool(HistoryArgs, "Get daily closes for named tickers. For N trading days use days=N and unit=completed_sessions; use calendar_days only for elapsed calendar days.", history),
    "get_economic_events": Tool(EventArgs, "Get official Fed, BLS and BEA events for the requested past and future days.", calendar, 27),
    "web_search": Tool(SearchArgs, "Search public web pages across any topic. Use short public keywords; the adapter can validate translated wording. Omit days for unrestricted publication dates or set days from 1 to 90 for recency.", web_search),
    "web_fetch": Tool(FetchArgs, "Retrieve a page excerpt through local MCP Fetch after web search, using one ranked source ID from this turn.", fetch),
}

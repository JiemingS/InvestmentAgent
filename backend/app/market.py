import logging
from datetime import UTC, date, datetime, timedelta
from decimal import localcontext
from fractions import Fraction
from pathlib import Path
from threading import Lock
from typing import Callable, Protocol

from .db import connect
from .exchange import NEW_YORK, Session, market_sessions
from .market_models import Action, CachedBar, MarketHistory
from .yahoo import MarketBatch, ProviderError

LOGGER = logging.getLogger(__name__)
PARTIAL_TTL = timedelta(minutes=15)
RETRY_DELAY = timedelta(minutes=15)
CORRECTION_LOOKBACK = 2


class MarketProvider(Protocol):
    def fetch(self, symbol: str, start: date, end: date) -> MarketBatch: ...


def cached_splits(connection) -> list[tuple[str, Action]]:
    rows = connection.execute(
        "SELECT * FROM market_actions WHERE split_numerator != split_denominator ORDER BY date"
    )
    return [(row["symbol"], Action.model_validate(dict(row))) for row in rows]


def _read_cache(path: Path, symbol: str, start: date):
    with connect(path) as connection:
        params = (symbol, start.isoformat())
        price_rows = connection.execute("SELECT * FROM market_prices WHERE symbol = ? AND date >= ?", params)
        bars = {date.fromisoformat(row["date"]): CachedBar.model_validate(dict(row)) for row in price_rows}
        action_rows = connection.execute("SELECT * FROM market_actions WHERE symbol = ? AND date >= ?", params)
        actions = {date.fromisoformat(row["date"]): Action.model_validate(dict(row)) for row in action_rows}
        state = connection.execute(
            "SELECT * FROM market_sync_state WHERE symbol = ?", (symbol,)
        ).fetchone()
    return bars, actions, state


def _needs_refresh(bar: CachedBar | None, session: Session, now: datetime) -> bool:
    return bar is None or (
        not bar.is_final and (session.is_final(now) or now - bar.updated_at >= PARTIAL_TTL)
    )


def _fetch_groups(sessions: list[Session], bars: dict[date, CachedBar], now: datetime, force: bool):
    indices = [
        index for index, session in enumerate(sessions)
        if force or _needs_refresh(bars.get(session.date), session, now)
    ]
    groups: list[list[Session]] = []
    if indices and indices[-1] == len(sessions) - 1 and any(bar.is_final for bar in bars.values()):
        start = indices[-1]
        for index in reversed(indices[:-1]):
            if index != start - 1:
                break
            start = index
        if sessions[start].is_final(now) or sessions[start].date not in bars:
            indices = sorted(set(indices).union(range(max(0, start - CORRECTION_LOOKBACK), start)))
    last = -2
    for index in indices:
        if index != last + 1:
            groups.append([])
        groups[-1].append(sessions[index])
        last = index
    return reversed(groups)


class MarketDataService:
    def __init__(
        self, database: Path, provider: MarketProvider, clock: Callable[[], datetime] | None = None,
    ):
        self.database = database
        self.provider = provider
        self.clock = clock or (lambda: datetime.now(UTC))
        self._lock = Lock()

    def today(self) -> date:
        return self.clock().astimezone(NEW_YORK).date()

    def get_latest_price(self, symbol: str) -> MarketHistory:
        today = self.today()
        return self.get_market_history(symbol, today - timedelta(days=14), today)

    def get_market_history(
        self, symbol: str, start: date, end: date, *, force: bool = False,
    ) -> MarketHistory:
        with self._lock:
            now = self.clock()
            today = now.astimezone(NEW_YORK).date()
            sessions = [session for session in market_sessions(start, today) if session.opens <= now]
            visible = [session for session in sessions if session.date <= end]
            bars, actions, state = _read_cache(self.database, symbol, start)
            error = None
            if visible:
                for group in _fetch_groups(sessions, bars, now, force):
                    if (
                        not force and state and state["status"] == "error"
                        and now - datetime.fromisoformat(state["last_attempt_at"]) < RETRY_DELAY
                    ):
                        error = state["error_message"]
                        break
                    try:
                        batch = self.provider.fetch(symbol, group[0].date, group[-1].date)
                        received = self._save_batch(symbol, group, batch, actions, now)
                        group_error = None
                        if received != len(group):
                            group_error = f"Yahoo did not return a complete set of daily bars for {symbol}."
                        error = group_error or error
                        self._record_attempt(symbol, now, group_error, received > 0)
                    except ProviderError as exc:
                        LOGGER.warning("Market refresh failed: %s", exc)
                        error = str(exc)
                        self._record_attempt(symbol, now, error, False)
                        break
                bars, actions, state = _read_cache(self.database, symbol, start)
                if state and state["status"] == "error":
                    error = error or state["error_message"]

            missing = sum(session.date not in bars for session in visible)
            outdated = any(
                _needs_refresh(bars.get(session.date), session, now) for session in visible
            )
            result = [bars[session.date] for session in visible if session.date in bars]
            return MarketHistory(
                symbol=symbol, bars=result,
                actions=[action for day, action in sorted(actions.items()) if day <= end],
                as_of=result[-1].price_as_of if result else None,
                coverage_start=result[0].date if result else None,
                coverage_end=result[-1].date if result else None,
                last_attempt_at=state["last_attempt_at"] if state else None,
                last_success_at=state["last_success_at"] if state else None,
                missing_sessions=missing, is_stale=outdated or error is not None,
                warning=error or (f"{missing} expected trading sessions have no cached price." if missing else None),
            )

    def _save_batch(
        self, symbol: str, group: list[Session], batch: MarketBatch,
        actions: dict[date, Action], now: datetime,
    ) -> int:
        expected = {session.date: session for session in group}
        rows = {bar.date: bar for bar in batch.bars if bar.date in expected}
        updated_actions = {action.date: action for action in batch.actions if action.date in expected}
        revised = {day: action for day, action in actions.items() if day not in rows}
        revised.update(updated_actions)
        # Yahoo OHLC is split-adjusted to today's share basis. Restore each bar's
        # trading-day share basis using strictly later splits, newest gaps first.
        factors = iter(sorted(revised.items(), reverse=True))
        following = next(factors, None)
        scale = Fraction(1)
        with connect(self.database, write=True) as connection, localcontext() as context:
            context.prec = 64
            for day, price in sorted(rows.items(), reverse=True):
                while following is not None and following[0] > day:
                    action = following[1]
                    scale *= Fraction(action.split_numerator, action.split_denominator)
                    following = next(factors, None)
                session = expected[day]
                final = session.is_final(now)
                connection.execute(
                    """
                    INSERT INTO market_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, date) DO UPDATE SET
                        open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                        adj_close=excluded.adj_close, volume=excluded.volume,
                        price_as_of=excluded.price_as_of, updated_at=excluded.updated_at, is_final=excluded.is_final
                    """,
                    (symbol, day.isoformat(),
                     *(format(value * scale.numerator / scale.denominator, "f")
                       for value in (price.open, price.high, price.low, price.close)),
                     format(price.adj_close, "f") if price.adj_close is not None else None,
                     price.volume, (session.closes if final else min(now, session.closes)).isoformat(),
                     now.isoformat(), int(final)),
                )
                if day not in updated_actions:
                    connection.execute("DELETE FROM market_actions WHERE symbol = ? AND date = ?", (symbol, day.isoformat()))
            connection.executemany(
                """
                INSERT INTO market_actions VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol, date) DO UPDATE SET dividend=excluded.dividend,
                    split_numerator=excluded.split_numerator, split_denominator=excluded.split_denominator
                """,
                [(symbol, action.date.isoformat(), format(action.dividend, "f"),
                  action.split_numerator, action.split_denominator) for action in updated_actions.values()],
            )
        actions.clear()
        actions.update(revised)
        return len(rows)

    def _record_attempt(self, symbol: str, now: datetime, error: str | None, success: bool) -> None:
        with connect(self.database, write=True) as connection:
            connection.execute(
                """
                INSERT INTO market_sync_state VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,
                    last_success_at=COALESCE(excluded.last_success_at, market_sync_state.last_success_at),
                    status=excluded.status, error_message=excluded.error_message
                """,
                (symbol, now.isoformat(), now.isoformat() if success else None,
                 "error" if error else "ok", error),
            )

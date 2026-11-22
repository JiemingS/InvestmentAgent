from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.db import migrate
from app.exchange import market_sessions
from app.market import MarketDataService
from app.market_models import Action, Bar
from app.yahoo import MarketBatch, ProviderError


def day(value: str) -> date:
    return date.fromisoformat(value)


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def bar(session: date, close="50") -> Bar:
    return Bar(date=session, open=close, high=close, low=close, close=close, adj_close=close, volume=20_000)


class Provider:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.unavailable = set()
        self.missing = set()
        self.actions = {}
        self.closes = {}

    def fetch(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        if self.fail or symbol in self.unavailable:
            raise ProviderError("Yahoo temporarily unavailable.")
        return MarketBatch(
            [
                bar(session.date, self.closes.get((symbol, session.date), "50"))
                for session in market_sessions(start, end)
                if (symbol, session.date) not in self.missing
            ],
            [action for action in self.actions.get(symbol, []) if start <= action.date <= end],
        )


@pytest.fixture
def market(tmp_path):
    path = tmp_path / "market.sqlite3"
    migrate(path)
    clock = [utc("2024-01-06T18:00:00+00:00")]
    provider = Provider()
    return MarketDataService(path, provider, lambda: clock[0]), provider, clock


def test_cache_survives_restart_and_backfills_only_missing_sessions(market):
    service, provider, clock = market
    first = day("2024-01-04")
    last = day("2024-01-05")
    result = service.get_market_history("VOO", first, last)
    assert len(result.bars) == 2 and not result.is_stale
    assert provider.calls == [("VOO", first, last)]

    restarted = MarketDataService(service.database, provider, lambda: clock[0])
    assert restarted.get_market_history("VOO", first, last) == result
    earlier = day("2024-01-02")
    extended = restarted.get_market_history("VOO", earlier, day("2024-01-06"))
    assert [item.date for item in extended.bars] == [earlier, day("2024-01-03"), first, last]
    assert provider.calls == [("VOO", first, last), ("VOO", earlier, day("2024-01-03"))]
    assert restarted.get_market_history("VOO", earlier, last).missing_sessions == 0
    assert len(provider.calls) == 2


def test_early_close_holiday_weekend_and_partial_refresh(market):
    service, provider, clock = market
    july3 = day("2024-07-03")
    clock[0] = utc("2024-07-03T13:00:00+00:00")
    assert service.get_market_history("VOO", july3, july3).bars == []
    assert not provider.calls

    clock[0] = utc("2024-07-03T16:00:00+00:00")
    [partial] = service.get_market_history("VOO", july3, july3).bars
    assert not partial.is_final
    clock[0] = utc("2024-07-03T16:10:00+00:00")
    assert service.get_market_history("VOO", july3, july3).bars == [partial]
    assert len(provider.calls) == 1
    clock[0] = utc("2024-07-03T16:16:00+00:00")
    assert not service.get_market_history("VOO", july3, july3).bars[0].is_final
    clock[0] = utc("2024-07-03T18:01:00+00:00")
    [final] = service.get_market_history("VOO", july3, july3).bars
    assert final.is_final
    assert final.price_as_of == utc("2024-07-03T17:00:00+00:00")
    assert len(provider.calls) == 3

    clock[0] = utc("2024-07-06T20:00:00+00:00")
    for closed in (day("2024-07-04"), day("2024-07-06")):
        result = service.get_market_history("VOO", closed, closed)
        assert not result.bars and not result.is_stale and result.missing_sessions == 0
    assert len(provider.calls) == 3


def test_provider_failure_preserves_cached_prices_and_limits_retries(market):
    service, provider, clock = market
    start = day("2024-01-04")
    original = service.get_market_history("VOO", start, day("2024-01-05"))
    provider.fail = True
    clock[0] = utc("2024-01-08T23:00:00+00:00")
    stale = service.get_market_history("VOO", start, service.today())
    assert stale.bars == original.bars
    assert stale.is_stale and stale.warning == "Yahoo temporarily unavailable."
    assert stale.as_of == original.as_of and stale.last_success_at == original.last_success_at
    assert stale.last_attempt_at == clock[0] and stale.missing_sessions == 1
    assert service.get_market_history("VOO", start, service.today()) == stale
    assert len(provider.calls) == 2

    provider.fail = False
    clock[0] = utc("2024-01-08T23:16:00+00:00")
    fresh = service.get_market_history("VOO", start, service.today())
    assert not fresh.is_stale and fresh.warning is None
    assert fresh.coverage_end == service.today()
    assert provider.calls[-1] == ("VOO", start, service.today())
    assert service.get_market_history("VOO", start, service.today(), force=True) == fresh
    assert len(provider.calls) == 4


def test_incremental_split_reconciliation_keeps_trading_day_prices(market):
    service, provider, clock = market
    start = day("2024-01-02")
    end = day("2024-01-03")
    clock[0] = utc("2024-01-03T23:00:00+00:00")
    provider.closes = {("DEMO", start): "100", ("DEMO", end): "102"}
    before = service.get_market_history("DEMO", start, end)
    assert [item.close for item in before.bars] == [Decimal(100), Decimal(102)]

    split_day = day("2024-01-04")
    clock[0] = utc("2024-01-04T23:00:00+00:00")
    provider.closes = {("DEMO", start): "50", ("DEMO", end): "51", ("DEMO", split_day): "52"}
    provider.actions["DEMO"] = [
        Action(date=end, dividend="0.375"),
        Action(date=split_day, split_numerator=2),
    ]
    after = service.get_market_history("DEMO", start, split_day)
    assert [item.close for item in after.bars] == [Decimal(100), Decimal(102), Decimal(52)]
    assert after.bars[0].adj_close == Decimal(50)
    assert after.bars[0].volume == 20_000
    assert after.actions[0].dividend == Decimal("0.375")
    assert after.actions[1].split_numerator == 2
    assert service.get_market_history("DEMO", start, split_day) == after
    assert len(provider.calls) == 2

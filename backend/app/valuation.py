from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal, localcontext

from .exchange import market_sessions
from .market import MarketDataService
from .market_models import MarketHistory
from .portfolio import PortfolioLedger, Split, ledger_events, replay_portfolio
from .schemas import PortfolioHistory, PortfolioPoint, PortfolioValuation, Transaction


def _load_histories(
    trades: Iterable[Transaction], market: MarketDataService, end: date,
    quote_lookback: date | None = None,
) -> dict[str, MarketHistory]:
    first_dates: dict[str, date] = {}
    for trade in trades:
        first_dates[trade.symbol] = min(first_dates.get(trade.symbol, trade.trade_date), trade.trade_date)
    return {
        symbol: market.get_market_history(symbol, min(first, quote_lookback or first), end)
        for symbol, first in sorted(first_dates.items())
        if first <= end
    }


def _splits(histories: dict[str, MarketHistory]):
    for symbol, history in histories.items():
        for action in history.actions:
            if action.is_split:
                yield Split(symbol, action)


def _warnings(histories: dict[str, MarketHistory]) -> list[str]:
    return [
        f"{symbol}: {history.warning}"
        for symbol, history in histories.items() if history.warning
    ]


def value_portfolio(trades: list[Transaction], market: MarketDataService) -> PortfolioValuation:
    today = market.today()
    eligible = [trade for trade in trades if trade.trade_date <= today]
    histories = _load_histories(eligible, market, today, today - timedelta(days=14))
    ledger = replay_portfolio(eligible, _splits(histories))
    summary, positions = ledger.snapshot()
    now = market.clock()
    expected = [session for session in market_sessions(today - timedelta(days=14), today) if session.opens <= now]
    latest_session = expected[-1].date if expected else None
    summary.warnings = _warnings(histories)
    with localcontext() as context:
        context.prec = 64
        for position in positions:
            history = histories[position.symbol]
            if not history.bars:
                position.is_stale = True
                summary.warnings.append(f"No cached price is available for {position.symbol}.")
                continue
            quote = history.bars[-1]
            price = quote.close
            for action in history.actions:
                if quote.date < action.date:
                    price = price * action.split_denominator / action.split_numerator
            position.latest_price = price
            position.quote_as_of = quote.price_as_of
            position.is_stale = quote.date != latest_session or history.is_stale
            position.is_partial = not quote.is_final
            position.market_value = ledger.holdings[position.symbol].value_at(price)
            position.unrealized_pnl = position.market_value - position.remaining_cost_basis

        summary.is_stale = any(position.is_stale for position in positions)
        summary.is_partial = any(position.is_partial for position in positions)
        if all(position.market_value is not None for position in positions):
            summary.market_value = sum((position.market_value for position in positions), Decimal(0))
            summary.unrealized_pnl = summary.market_value - summary.remaining_cost_basis
            summary.quote_as_of = min((position.quote_as_of for position in positions), default=None)
    return PortfolioValuation(summary=summary, positions=positions)


def portfolio_history(
    trades: list[Transaction], market: MarketDataService, start: date, end: date,
) -> PortfolioHistory:
    eligible = [trade for trade in trades if trade.trade_date <= end]
    histories = _load_histories(eligible, market, end)
    sessions = market_sessions(start, min(end, market.today()))
    bars = {
        symbol: {bar.date: bar.close for bar in history.bars if bar.is_final}
        for symbol, history in histories.items()
    }
    ledger = PortfolioLedger()
    events = iter(ledger_events(eligible, _splits(histories)))
    event = next(events, None)
    points = []
    now = market.clock()
    for session in sessions:
        if not session.is_final(now):
            break
        while event is not None:
            event_date = event.date if isinstance(event, Split) else event.trade_date
            if event_date > session.date:
                break
            ledger.apply(event)
            event = next(events, None)
        with localcontext() as context:
            context.prec = 64
            value = Decimal(0)
            for symbol, holding in ledger.holdings.items():
                if holding.shares == 0:
                    continue
                price = bars[symbol].get(session.date)
                if price is None:
                    value = None
                    break
                value += holding.value_at(price)
        points.append(PortfolioPoint(date=session.date, market_value=value))

    return PortfolioHistory(points=points, warnings=_warnings(histories))

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

import yfinance as yf

from .market_models import Action, Bar


class ProviderError(RuntimeError):
    pass


@dataclass
class MarketBatch:
    bars: list[Bar]
    actions: list[Action]


def _decimal(value) -> Decimal | None:
    if value is None:
        return None
    result = Decimal(str(value))
    return result if result.is_finite() else None


class YahooProvider:
    def fetch(self, symbol: str, start: date, end: date) -> MarketBatch:
        ticker = yf.Ticker(symbol.replace(".", "-"))
        try:
            frame = ticker.history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=True,
                keepna=True,
                timeout=8,
            )
            if frame.empty:
                raise ProviderError(f"Yahoo returned no daily data for {symbol}.")
            metadata = ticker.history_metadata
            if metadata.get("currency") != "USD" or metadata.get("exchangeTimezoneName") != "America/New_York":
                raise ProviderError(f"{symbol} did not resolve to a supported US dollar listing.")

            bars, actions = [], []
            for index, row in frame.iterrows():
                session = index.date()
                dividend = _decimal(row.get("Dividends")) or Decimal("0")
                ratio = Fraction(_decimal(row.get("Stock Splits")) or 1).limit_denominator(100_000)
                if ratio <= 0:
                    raise ProviderError(f"Yahoo returned an invalid split ratio for {symbol}.")
                if dividend or ratio != 1:
                    actions.append(Action(
                        date=session, dividend=dividend,
                        split_numerator=ratio.numerator, split_denominator=ratio.denominator,
                    ))
                prices = [_decimal(row.get(name)) for name in ("Open", "High", "Low", "Close")]
                volume = _decimal(row.get("Volume"))
                if any(price is None or price <= 0 for price in prices) or volume is None or volume < 0:
                    continue
                bars.append(Bar(
                    date=session, open=prices[0], high=prices[1], low=prices[2], close=prices[3],
                    adj_close=_decimal(row.get("Adj Close")), volume=int(volume),
                ))
            return MarketBatch(bars, actions)
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(f"Yahoo request failed for {symbol}: {type(error).__name__}.") from error

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from .schemas import FixedDecimal


class Bar(BaseModel):
    date: date
    open: FixedDecimal
    high: FixedDecimal
    low: FixedDecimal
    close: FixedDecimal
    adj_close: FixedDecimal | None = None
    volume: int


class Action(BaseModel):
    date: date
    dividend: FixedDecimal = Decimal("0")
    split_numerator: int = 1
    split_denominator: int = 1

    @property
    def is_split(self) -> bool:
        return self.split_numerator != self.split_denominator


class CachedBar(Bar):
    price_as_of: datetime
    updated_at: datetime
    is_final: bool


class MarketHistory(BaseModel):
    symbol: str
    provider: str = "Yahoo Finance"
    bars: list[CachedBar]
    actions: list[Action]
    as_of: datetime | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    coverage_start: date | None
    coverage_end: date | None
    missing_sessions: int
    is_stale: bool
    warning: str | None = None

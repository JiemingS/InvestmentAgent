from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, PlainSerializer, StringConstraints, field_validator

CHICAGO = ZoneInfo("America/Chicago")
FixedDecimal = Annotated[
    Decimal, PlainSerializer(lambda value: format(value, "f"), when_used="json")
]
PositiveDecimal = Annotated[FixedDecimal, Field(gt=0, max_digits=18, decimal_places=8)]
NonnegativeDecimal = Annotated[FixedDecimal, Field(ge=0, max_digits=18, decimal_places=8)]
Symbol = Annotated[
    str, StringConstraints(pattern=r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,3})?$")
]


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class TransactionInput(BaseModel):
    symbol: Symbol
    account: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None
    side: Side
    trade_date: date
    quantity: PositiveDecimal
    unit_price: PositiveDecimal
    fees: NonnegativeDecimal = Decimal("0")
    currency: Literal["USD"] = "USD"

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("trade_date")
    @classmethod
    def validate_trade_date(cls, value: date) -> date:
        if value > datetime.now(CHICAGO).date():
            raise ValueError("Trade date cannot be in the future")
        return value


class Transaction(TransactionInput):
    id: int
    created_at: datetime
    updated_at: datetime


class Position(BaseModel):
    symbol: str
    shares: FixedDecimal
    remaining_cost_basis: FixedDecimal
    average_cost_per_share: FixedDecimal
    latest_price: FixedDecimal | None = None
    market_value: FixedDecimal | None = None
    unrealized_pnl: FixedDecimal | None = None
    quote_as_of: datetime | None = None
    quote_updated_at: datetime | None = None
    is_stale: bool = False
    is_partial: bool = False


class PortfolioSummary(BaseModel):
    currency: Literal["USD"] = "USD"
    cost_basis_method: Literal["weighted_average"] = "weighted_average"
    net_cash_contributed: FixedDecimal
    remaining_cost_basis: FixedDecimal
    realized_pnl: FixedDecimal
    market_value: FixedDecimal | None = None
    unrealized_pnl: FixedDecimal | None = None
    quote_as_of: datetime | None = None
    is_stale: bool = False
    is_partial: bool = False
    warnings: list[str] = Field(default_factory=list)


class PortfolioValuation(BaseModel):
    summary: PortfolioSummary
    positions: list[Position]


class PortfolioPoint(BaseModel):
    date: date
    market_value: FixedDecimal | None


class PortfolioHistory(BaseModel):
    points: list[PortfolioPoint]
    warnings: list[str]

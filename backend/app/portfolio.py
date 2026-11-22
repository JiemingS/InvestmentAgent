from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Iterable

from .market_models import Action
from .schemas import PortfolioSummary, Position, Side, Transaction

ZERO = Decimal("0")


class OversellError(ValueError):
    def __init__(self, trade: Transaction, available: Decimal):
        super().__init__(
            f"Transaction #{trade.id} would sell {trade.quantity} {trade.symbol} shares "
            f"on {trade.trade_date}, with only {available} available."
        )


@dataclass
class Holding:
    shares: Fraction = Fraction(0)
    basis: Decimal = ZERO

    def value_at(self, price: Decimal) -> Decimal:
        return price * self.shares.numerator / self.shares.denominator


@dataclass(frozen=True)
class Split:
    symbol: str
    action: Action

    @property
    def date(self) -> date:
        return self.action.date


def ledger_events(transactions: Iterable[Transaction], splits: Iterable[Split]):
    return sorted(
        [*transactions, *splits],
        key=lambda item: (item.date, 0) if isinstance(item, Split) else (item.trade_date, item.id),
    )


class PortfolioLedger:
    def __init__(self):
        self.holdings: dict[str, Holding] = {}
        self.net_cash = self.realized_pnl = ZERO

    def apply(self, event: Transaction | Split) -> None:
        holding = self.holdings.setdefault(event.symbol, Holding())
        with localcontext() as context:
            context.prec = 64
            if isinstance(event, Split):
                holding.shares *= Fraction(event.action.split_numerator, event.action.split_denominator)
                return

            quantity = Fraction(event.quantity)
            gross = event.quantity * event.unit_price
            if event.side == Side.BUY:
                cost = gross + event.fees
                holding.shares += quantity
                holding.basis += cost
                self.net_cash += cost
                return

            if quantity > holding.shares:
                raise OversellError(event, holding.value_at(Decimal(1)))
            disposed_basis = holding.basis
            if quantity != holding.shares:
                ratio = quantity / holding.shares
                disposed_basis = holding.basis * ratio.numerator / ratio.denominator
            proceeds = gross - event.fees
            self.realized_pnl += proceeds - disposed_basis
            self.net_cash -= proceeds
            holding.shares -= quantity
            holding.basis -= disposed_basis

    def snapshot(self) -> tuple[PortfolioSummary, list[Position]]:
        with localcontext() as context:
            context.prec = 64
            positions = [
                Position(
                    symbol=symbol, shares=holding.value_at(Decimal(1)), remaining_cost_basis=holding.basis,
                    average_cost_per_share=holding.basis * holding.shares.denominator / holding.shares.numerator,
                )
                for symbol, holding in sorted(self.holdings.items())
                if holding.shares > ZERO
            ]
            summary = PortfolioSummary(
                net_cash_contributed=self.net_cash,
                remaining_cost_basis=sum((item.remaining_cost_basis for item in positions), ZERO),
                realized_pnl=self.realized_pnl,
            )
        return summary, positions


def calculate_portfolio(
    transactions: Iterable[Transaction], splits: Iterable[Split] = (),
) -> tuple[PortfolioSummary, list[Position]]:
    return replay_portfolio(transactions, splits).snapshot()


def replay_portfolio(transactions: Iterable[Transaction], splits: Iterable[Split]) -> PortfolioLedger:
    ledger = PortfolioLedger()
    for event in ledger_events(transactions, splits):
        ledger.apply(event)
    return ledger

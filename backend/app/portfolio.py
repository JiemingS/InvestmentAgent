from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Iterable

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
    shares: Decimal = ZERO
    basis: Decimal = ZERO


def calculate_portfolio(
    transactions: Iterable[Transaction],
) -> tuple[PortfolioSummary, list[Position]]:
    holdings: dict[str, Holding] = {}
    net_cash = realized_pnl = ZERO

    with localcontext() as context:
        context.prec = 64
        for trade in sorted(transactions, key=lambda item: (item.trade_date, item.id)):
            holding = holdings.setdefault(trade.symbol, Holding())
            gross = trade.quantity * trade.unit_price
            if trade.side == Side.BUY:
                cost = gross + trade.fees
                holding.shares += trade.quantity
                holding.basis += cost
                net_cash += cost
                continue

            if trade.quantity > holding.shares:
                raise OversellError(trade, holding.shares)
            if trade.quantity == holding.shares:
                disposed_basis = holding.basis
            else:
                disposed_basis = holding.basis * trade.quantity / holding.shares
            proceeds = gross - trade.fees
            realized_pnl += proceeds - disposed_basis
            net_cash -= proceeds
            holding.shares -= trade.quantity
            holding.basis -= disposed_basis

        positions = [
            Position(
                symbol=symbol,
                shares=holding.shares,
                remaining_cost_basis=holding.basis,
                average_cost_per_share=holding.basis / holding.shares,
            )
            for symbol, holding in sorted(holdings.items())
            if holding.shares > ZERO
        ]
        summary = PortfolioSummary(
            net_cash_contributed=net_cash,
            remaining_cost_basis=sum((item.remaining_cost_basis for item in positions), ZERO),
            realized_pnl=realized_pnl,
        )
    return summary, positions

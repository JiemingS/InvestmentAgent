import os
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from . import transactions
from .db import migrate
from .exchange import FIRST_MARKET_DATE
from .market import MarketDataService, MarketProvider
from .market_models import MarketHistory
from .portfolio import OversellError
from .schemas import (
    PortfolioHistory, PortfolioSummary, PortfolioValuation, Position, Side,
    Symbol, Transaction, TransactionInput,
)
from .valuation import portfolio_history, value_portfolio
from .yahoo import YahooProvider

DEFAULT_DATABASE = Path(__file__).resolve().parents[2] / ".data" / "portfolio.sqlite3"


def database_path(request: Request) -> Path:
    return request.app.state.database


Database = Annotated[Path, Depends(database_path)]


def market_service(request: Request) -> MarketDataService:
    return request.app.state.market


Market = Annotated[MarketDataService, Depends(market_service)]


def _date_range(market: MarketDataService, start: date | None, end: date | None):
    end = end if end is not None else market.today()
    if not FIRST_MARKET_DATE <= end <= market.today():
        raise HTTPException(422, "End date must be between 1970-01-01 and today's US market date.")
    start = start if start is not None else max(FIRST_MARKET_DATE, end - timedelta(days=365))
    if not FIRST_MARKET_DATE <= start <= end <= market.today():
        raise HTTPException(422, "Use dates from 1970-01-01 through today's US market date, with start no later than end.")
    return start, end


def _warm_trade_symbols(
    market: MarketDataService, trades: list[Transaction], incoming: TransactionInput | None,
    previous: Transaction | None = None,
) -> None:
    symbols = {item.symbol for item in (incoming, previous) if item is not None}
    for symbol in sorted(symbols):
        records = [trade for trade in trades if trade.symbol == symbol]
        has_new_sell = incoming is not None and incoming.symbol == symbol and incoming.side == Side.SELL
        if records and (has_new_sell or any(trade.side == Side.SELL for trade in records)):
            first = min(trade.trade_date for trade in records)
            if incoming is not None and incoming.symbol == symbol:
                first = min(first, incoming.trade_date)
            market.get_market_history(symbol, first, market.today())


def create_app(database: Path | None = None, provider: MarketProvider | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        migrate(application.state.database)
        yield

    application = FastAPI(title="Personal Investment Intelligence Agent", lifespan=lifespan)
    application.state.database = database or Path(os.getenv("INVESTMENT_DB_PATH", str(DEFAULT_DATABASE)))
    application.state.market = MarketDataService(application.state.database, provider or YahooProvider())

    @application.exception_handler(OversellError)
    async def oversell_handler(_request: Request, error: OversellError):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @application.exception_handler(transactions.TransactionNotFound)
    async def not_found_handler(_request: Request, error: transactions.TransactionNotFound):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @application.get("/api/transactions")
    def list_trades(path: Database) -> list[Transaction]:
        return transactions.list_transactions(path)

    @application.post("/api/transactions", status_code=status.HTTP_201_CREATED)
    def create_trade(data: TransactionInput, path: Database, market: Market) -> Transaction:
        if data.side == Side.SELL:
            _warm_trade_symbols(market, transactions.list_transactions(path), data)
        return transactions.create_transaction(path, data)

    @application.put("/api/transactions/{transaction_id}")
    def update_trade(transaction_id: int, data: TransactionInput, path: Database, market: Market) -> Transaction:
        trades = transactions.list_transactions(path)
        previous = next((trade for trade in trades if trade.id == transaction_id), None)
        if previous is not None:
            _warm_trade_symbols(market, trades, data, previous)
        return transactions.update_transaction(path, transaction_id, data)

    @application.delete("/api/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_trade(transaction_id: int, path: Database, market: Market) -> Response:
        trades = transactions.list_transactions(path)
        previous = next((trade for trade in trades if trade.id == transaction_id), None)
        if previous is not None:
            _warm_trade_symbols(market, trades, None, previous)
        transactions.delete_transaction(path, transaction_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.get("/api/portfolio/summary")
    def portfolio_summary(path: Database, market: Market) -> PortfolioSummary:
        return value_portfolio(transactions.list_transactions(path), market).summary

    @application.get("/api/portfolio/positions")
    def portfolio_positions(path: Database, market: Market) -> list[Position]:
        return value_portfolio(transactions.list_transactions(path), market).positions

    @application.get("/api/portfolio/valuation")
    def valuation(path: Database, market: Market) -> PortfolioValuation:
        return value_portfolio(transactions.list_transactions(path), market)

    @application.get("/api/portfolio/history")
    def history(
        path: Database, market: Market, start: date | None = None, end: date | None = None,
    ) -> PortfolioHistory:
        first, last = _date_range(market, start, end)
        return portfolio_history(transactions.list_transactions(path), market, first, last)

    @application.get("/api/market/{symbol}/history")
    def price_history(
        symbol: Symbol, market: Market, start: date | None = None, end: date | None = None,
    ) -> MarketHistory:
        first, last = _date_range(market, start, end)
        return market.get_market_history(symbol, first, last)

    @application.post("/api/market/{symbol}/refresh")
    def refresh_prices(
        symbol: Symbol, market: Market, start: date | None = None, end: date | None = None,
    ) -> MarketHistory:
        first, last = _date_range(market, start, end)
        return market.get_market_history(symbol, first, last, force=True)

    return application


app = create_app()

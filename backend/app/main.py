import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from . import transactions
from .db import migrate
from .portfolio import OversellError, calculate_portfolio
from .schemas import PortfolioSummary, Position, Transaction, TransactionInput

DEFAULT_DATABASE = Path(__file__).resolve().parents[2] / ".data" / "portfolio.sqlite3"


def database_path(request: Request) -> Path:
    return request.app.state.database


Database = Annotated[Path, Depends(database_path)]


def create_app(database: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        migrate(application.state.database)
        yield

    application = FastAPI(title="Personal Investment Intelligence Agent", lifespan=lifespan)
    application.state.database = database or Path(os.getenv("INVESTMENT_DB_PATH", str(DEFAULT_DATABASE)))

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
    def create_trade(data: TransactionInput, path: Database) -> Transaction:
        return transactions.create_transaction(path, data)

    @application.put("/api/transactions/{transaction_id}")
    def update_trade(transaction_id: int, data: TransactionInput, path: Database) -> Transaction:
        return transactions.update_transaction(path, transaction_id, data)

    @application.delete("/api/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_trade(transaction_id: int, path: Database) -> Response:
        transactions.delete_transaction(path, transaction_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.get("/api/portfolio/summary")
    def portfolio_summary(path: Database) -> PortfolioSummary:
        summary, _ = calculate_portfolio(transactions.list_transactions(path))
        return summary

    @application.get("/api/portfolio/positions")
    def portfolio_positions(path: Database) -> list[Position]:
        _, positions = calculate_portfolio(transactions.list_transactions(path))
        return positions

    return application


app = create_app()

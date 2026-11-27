import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .db import connect
from .market import cached_splits
from .portfolio import Split, calculate_portfolio
from .schemas import Transaction, TransactionInput


class TransactionNotFound(LookupError):
    pass


def _ledger(connection: sqlite3.Connection) -> list[Transaction]:
    rows = connection.execute("SELECT * FROM transactions ORDER BY trade_date, id")
    return [Transaction.model_validate(dict(row)) for row in rows]


def list_transactions(path: Path, *, account: str | None = None) -> list[Transaction]:
    with connect(path) as connection:
        trades = _ledger(connection)
    # An omitted filter selects all records. An empty value selects legacy records.
    if account is None:
        return trades
    key = account.lower()
    return [trade for trade in trades if (trade.account or "").lower() == key]


def _validate_ledger(connection: sqlite3.Connection) -> None:
    calculate_portfolio(
        _ledger(connection),
        (Split(symbol, action) for symbol, action in cached_splits(connection)),
    )


def get_transaction(connection: sqlite3.Connection, transaction_id: int) -> Transaction:
    row = connection.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
    if row is None:
        raise TransactionNotFound(f"Transaction #{transaction_id} was not found.")
    return Transaction.model_validate(dict(row))


def create_transaction(path: Path, data: TransactionInput) -> Transaction:
    now = datetime.now(UTC).isoformat()
    with connect(path, write=True) as connection:
        cursor = connection.execute(
            """
            INSERT INTO transactions
                (symbol, account, side, trade_date, quantity, unit_price, fees, currency, created_at, updated_at)
            VALUES (:symbol, :account, :side, :trade_date, :quantity, :unit_price, :fees, :currency, :now, :now)
            """,
            {**data.model_dump(mode="json"), "now": now},
        )
        _validate_ledger(connection)
        return get_transaction(connection, cursor.lastrowid)


def update_transaction(path: Path, transaction_id: int, data: TransactionInput) -> Transaction:
    with connect(path, write=True) as connection:
        cursor = connection.execute(
            """
            UPDATE transactions
            SET symbol=:symbol, side=:side, trade_date=:trade_date, quantity=:quantity,
                unit_price=:unit_price, fees=:fees, currency=:currency, updated_at=:updated_at,
                account=CASE WHEN :account_provided THEN :account ELSE account END
            WHERE id=:id
            """,
            {
                **data.model_dump(mode="json"),
                "account_provided": "account" in data.model_fields_set,
                "id": transaction_id,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        if cursor.rowcount == 0:
            raise TransactionNotFound(f"Transaction #{transaction_id} was not found.")
        _validate_ledger(connection)
        return get_transaction(connection, transaction_id)


def delete_transaction(path: Path, transaction_id: int) -> None:
    with connect(path, write=True) as connection:
        cursor = connection.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        if cursor.rowcount == 0:
            raise TransactionNotFound(f"Transaction #{transaction_id} was not found.")
        _validate_ledger(connection)

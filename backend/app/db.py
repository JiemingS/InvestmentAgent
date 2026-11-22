import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MIGRATIONS = (
    (
        """
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
            trade_date TEXT NOT NULL,
            quantity TEXT NOT NULL,
            unit_price TEXT NOT NULL,
            fees TEXT NOT NULL,
            currency TEXT NOT NULL CHECK (currency = 'USD'),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX transactions_ledger_order ON transactions(trade_date, id)",
    ),
)


@contextmanager
def connect(path: Path, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        if write:
            connection.execute("BEGIN IMMEDIATE")
        yield connection
        if write:
            connection.commit()
    except BaseException:
        if write:
            connection.rollback()
        raise
    finally:
        connection.close()


def migrate(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path, write=True) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            raise RuntimeError(f"Database schema version {version} is newer than this app")
        for next_version, statements in enumerate(MIGRATIONS[version:], start=version + 1):
            for statement in statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {next_version}")

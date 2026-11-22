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
    (
        """
        CREATE TABLE market_prices (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            open TEXT NOT NULL,
            high TEXT NOT NULL,
            low TEXT NOT NULL,
            close TEXT NOT NULL,
            adj_close TEXT,
            volume INTEGER NOT NULL,
            price_as_of TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_final INTEGER NOT NULL,
            PRIMARY KEY (symbol, date)
        )
        """,
        """
        CREATE TABLE market_actions (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            dividend TEXT NOT NULL,
            split_numerator INTEGER NOT NULL,
            split_denominator INTEGER NOT NULL,
            PRIMARY KEY (symbol, date)
        )
        """,
        """
        CREATE TABLE market_sync_state (
            symbol TEXT PRIMARY KEY,
            last_attempt_at TEXT NOT NULL,
            last_success_at TEXT,
            status TEXT NOT NULL,
            error_message TEXT
        )
        """,
    ),
)


@contextmanager
def connect(path: Path, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
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


def migrate(path: Path, migrations=None) -> None:
    if migrations is None:
        migrations = MIGRATIONS
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path, write=True) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > len(migrations):
            raise RuntimeError(f"Database schema version {version} is newer than this app")
        for next_version, statements in enumerate(migrations[version:], start=version + 1):
            for statement in statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {next_version}")

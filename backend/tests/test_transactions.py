import sqlite3
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import create_app
from test_portfolio import record, trade


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "portfolio.sqlite3")) as session:
        yield session


def test_migration_and_crud_persist_across_restarts(tmp_path):
    database = tmp_path / "nested" / "portfolio.sqlite3"
    with TestClient(create_app(database)) as first:
        original = record(first, symbol=" qqqm ", account="  Roth IRA  ", quantity="0.12345678")
        assert original["symbol"] == "QQQM"
        assert original["account"] == "Roth IRA"
        assert original["quantity"] == "0.12345678"
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert connection.execute("SELECT typeof(quantity) FROM transactions").fetchone()[0] == "text"
    with TestClient(create_app(database)) as second:
        assert second.get("/api/transactions").json() == [original]
        url = f"/api/transactions/{original['id']}"
        update = second.put(url, json=trade(symbol="QQQM", quantity="0.25"))
        assert update.status_code == 200
        assert update.json()["created_at"] == original["created_at"]
        assert update.json()["account"] == "Roth IRA"
        assert Decimal(update.json()["quantity"]) == Decimal("0.25")
        update = second.put(url, json=trade(symbol="QQQM", account="Taxable", quantity="0.25"))
        assert update.status_code == 200
        assert update.json()["account"] == "Taxable"
    with TestClient(create_app(database)) as third:
        assert third.get("/api/transactions").json() == [update.json()]
        assert third.delete(url).status_code == 204
        assert third.delete(url).status_code == 404
        assert third.put(url, json=trade()).status_code == 404
    with TestClient(create_app(database)) as fourth:
        assert fourth.get("/api/transactions").json() == []


def test_upgrade_existing_version_one_database(tmp_path, monkeypatch):
    database = tmp_path / "v1.sqlite3"
    with monkeypatch.context() as develop:
        develop.setattr(db, "MIGRATIONS", db.MIGRATIONS[:1])
        db.migrate(database)
    with db.connect(database, write=True) as connection:
        connection.execute(
            """
            INSERT INTO transactions VALUES
            (1, 'VOO', 'BUY', '2024-01-02', '0.125', '99.5', '0', 'USD',
             '2024-01-02T16:00:00Z', '2024-01-02T16:00:00Z')
            """
        )
    with TestClient(create_app(database)) as upgraded:
        [preserved] = upgraded.get("/api/transactions").json()
        assert preserved["quantity"] == "0.125"
        assert preserved["account"] is None
    with db.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM market_prices").fetchone()[0] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "bad symbol"}, {"side": "HOLD"}, {"trade_date": "2024-02-30"},
        {"trade_date": "2999-01-01"}, {"quantity": "0"}, {"unit_price": "-1"},
        {"unit_price": "NaN"}, {"fees": "-0.01"}, {"quantity": "0.000000001"},
        {"quantity": "10000000000"}, {"currency": "EUR"}, {"quantity": True},
        {"account": "   "}, {"account": "a" * 81},
    ],
)
def test_invalid_transactions_return_422_and_leave_ledger_unchanged(client, changes):
    assert client.post("/api/transactions", json=trade(**changes)).status_code == 422
    assert client.get("/api/transactions").json() == []


def test_oversell_rejects_create_update_and_delete_atomically(client):
    assert client.post("/api/transactions", json=trade(side="SELL")).status_code == 409
    buy = record(client)
    sell = record(client, side="SELL", quantity="1", trade_date="2024-01-03")
    buy_url = f"/api/transactions/{buy['id']}"
    sell_url = f"/api/transactions/{sell['id']}"
    assert client.put(buy_url, json=trade(quantity="0.5")).status_code == 409
    assert client.put(buy_url, json=trade(trade_date="2024-01-04")).status_code == 409
    assert client.put(sell_url, json=trade(side="SELL", symbol="QQQM")).status_code == 409
    assert client.delete(buy_url).status_code == 409
    assert client.get("/api/transactions").json() == [buy, sell]


def test_concurrent_sells_validate_against_committed_ledger(client):
    record(client, quantity="1")

    def sell():
        return client.post("/api/transactions", json=trade(side="SELL", quantity="1")).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(sell) for _ in range(2)]
        assert sorted(future.result() for future in futures) == [201, 409]
    assert client.get("/api/portfolio/positions").json() == []

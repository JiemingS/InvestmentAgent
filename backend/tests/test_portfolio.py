from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import create_app


def trade(**changes):
    return {
        "symbol": "VOO",
        "side": "BUY",
        "trade_date": "2024-01-02",
        "quantity": "2",
        "unit_price": "100",
        "fees": "2",
        **changes,
    }


def record(client, **changes):
    response = client.post("/api/transactions", json=trade(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def test_weighted_average_fees_and_closed_position(tmp_path):
    with TestClient(create_app(tmp_path / "portfolio.sqlite3")) as client:
        record(client)
        record(client, quantity="3", unit_price="132", fees="2")
        record(client, side="SELL", quantity="1.5", unit_price="150", fees="1")
        [position] = client.get("/api/portfolio/positions").json()
        assert Decimal(position["shares"]) == Decimal("3.5")
        assert Decimal(position["average_cost_per_share"]) == Decimal("120")
        assert Decimal(position["remaining_cost_basis"]) == Decimal("420")

        summary = client.get("/api/portfolio/summary").json()
        assert summary["cost_basis_method"] == "weighted_average"
        assert Decimal(summary["realized_pnl"]) == Decimal("44")
        assert Decimal(summary["net_cash_contributed"]) == Decimal("376")
        assert summary["market_value"] is None
        assert summary["unrealized_pnl"] is None

        record(client, side="SELL", quantity="3.5", unit_price="100", fees="5")
        assert client.get("/api/portfolio/positions").json() == []
        summary = client.get("/api/portfolio/summary").json()
        assert Decimal(summary["remaining_cost_basis"]) == 0
        assert Decimal(summary["realized_pnl"]) == Decimal("-31")
        assert Decimal(summary["net_cash_contributed"]) == Decimal("31")


def test_fractional_shares_and_repeating_basis_clear_on_close(tmp_path):
    with TestClient(create_app(tmp_path / "portfolio.sqlite3")) as client:
        record(client, symbol="qqqm", quantity="0.1", unit_price="0.1", fees="0")
        record(client, symbol="QQQM", quantity="0.2", unit_price="0.1", fees="0.01")
        record(client, symbol="QQQM", side="SELL", quantity="0.1", unit_price="0.3", fees="0")
        record(client, symbol="QQQM", side="SELL", quantity="0.2", unit_price="0.3", fees="0")
        summary = client.get("/api/portfolio/summary").json()
        assert Decimal(summary["realized_pnl"]) == Decimal("0.05")
        assert client.get("/api/portfolio/positions").json() == []


def test_small_decimals_are_serialized_without_exponents(tmp_path):
    with TestClient(create_app(tmp_path / "portfolio.sqlite3")) as client:
        trade = record(client, quantity="0.00000001", unit_price="0.00000001", fees="0")
        assert trade["quantity"] == trade["unit_price"] == "0.00000001"
        summary = client.get("/api/portfolio/summary").json()
        assert summary["remaining_cost_basis"] == "0.0000000000000001"

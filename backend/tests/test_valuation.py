from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import create_app
from app.market_models import Action
from test_market import Provider, day, utc
from test_portfolio import record, trade


def test_split_sale_and_historical_portfolio_value_use_each_days_holdings(tmp_path):
    provider = Provider()
    provider.actions["VOO"] = [Action(date="2024-01-04", split_numerator=2)]
    provider.closes = {
        ("VOO", day("2024-01-02")): "50",
        ("VOO", day("2024-01-03")): "51",
        ("VOO", day("2024-01-04")): "60",
        ("VOO", day("2024-01-05")): "62",
    }
    app = create_app(tmp_path / "portfolio.sqlite3", provider)
    app.state.market.clock = lambda: utc("2024-01-06T18:00:00+00:00")
    with TestClient(app) as client:
        record(client)
        record(client, side="SELL", trade_date="2024-01-04", quantity="1", unit_price="60", fees="1")
        result = client.get("/api/portfolio/valuation").json()
        summary = result["summary"]
        [position] = result["positions"]
        assert Decimal(position["shares"]) == 3
        assert Decimal(position["remaining_cost_basis"]) == Decimal("151.5")
        assert Decimal(summary["realized_pnl"]) == Decimal("8.5")
        assert Decimal(summary["market_value"]) == Decimal("186")
        assert Decimal(summary["unrealized_pnl"]) == Decimal("34.5")
        assert summary["quote_as_of"] == "2024-01-05T21:00:00Z"
        assert position["quote_updated_at"] == "2024-01-06T18:00:00Z"

        response = client.get("/api/portfolio/history?start=2024-01-02&end=2024-01-05")
        assert response.status_code == 200
        points = response.json()["points"]
        assert [Decimal(point["market_value"]) for point in points] == [200, 204, 180, 186]
        from_after_buy = client.get("/api/portfolio/history?start=2024-01-04&end=2024-01-05")
        assert from_after_buy.json()["points"] == points[2:]

        sale = record(client, side="SELL", trade_date="2024-01-05", quantity="3", unit_price="62", fees="0")
        assert client.get("/api/portfolio/positions").json() == []
        assert client.post("/api/transactions", json=trade(side="SELL", trade_date="2024-01-05", quantity="1")).status_code == 409
        assert client.delete(f"/api/transactions/{sale['id']}").status_code == 204


def test_reverse_split_preserves_basis_and_enforces_oversell(tmp_path):
    provider = Provider()
    provider.actions["VOO"] = [Action(date="2024-01-04", split_denominator=3)]
    app = create_app(tmp_path / "portfolio.sqlite3", provider)
    app.state.market.clock = lambda: utc("2024-01-06T18:00:00+00:00")
    with TestClient(app) as client:
        record(client, quantity="3", unit_price="10", fees="0")
        assert client.post("/api/transactions", json=trade(
            side="SELL", trade_date="2024-01-04", quantity="1.1", unit_price="40", fees="0",
        )).status_code == 409
        record(client, side="SELL", trade_date="2024-01-04", quantity="1", unit_price="40", fees="0")
        summary = client.get("/api/portfolio/summary").json()
        assert Decimal(summary["realized_pnl"]) == 10
        assert Decimal(summary["remaining_cost_basis"]) == 0


def test_reciprocal_splits_allow_exactly_closing_the_position(tmp_path):
    provider = Provider()
    provider.actions["VOO"] = [
        Action(date="2024-01-03", split_denominator=3),
        Action(date="2024-01-04", split_numerator=3),
    ]
    app = create_app(tmp_path / "portfolio.sqlite3", provider)
    app.state.market.clock = lambda: utc("2024-01-06T18:00:00+00:00")
    with TestClient(app) as client:
        record(client, quantity="1", unit_price="10", fees="0")
        record(client, side="SELL", trade_date="2024-01-04", quantity="1", unit_price="11", fees="0")
        assert client.get("/api/portfolio/positions").json() == []
        assert Decimal(client.get("/api/portfolio/summary").json()["realized_pnl"]) == 1


def test_missing_quote_leaves_historical_gap_and_does_not_sum_partial_portfolio(tmp_path):
    provider = Provider()
    provider.unavailable = {"QQQM"}
    app = create_app(tmp_path / "portfolio.sqlite3", provider)
    app.state.market.clock = lambda: utc("2024-01-03T23:00:00+00:00")
    with TestClient(app) as client:
        record(client, quantity="1")
        record(client, symbol="QQQM", quantity="1")
        result = client.get("/api/portfolio/valuation").json()
        assert result["summary"]["market_value"] is None
        assert result["summary"]["unrealized_pnl"] is None
        assert result["summary"]["is_stale"]
        points = client.get("/api/portfolio/history?start=2024-01-02&end=2024-01-03").json()["points"]
        assert len(points) == 2 and all(point["market_value"] is None for point in points)

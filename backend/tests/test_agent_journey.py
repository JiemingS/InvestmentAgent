import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.tools import TransactionArgs
from test_agent import ScriptedModel, call, final, native, setup
from test_agent_web_research import Research
from test_portfolio import record


QUESTION = "Could you summarize my investment journey and offer some recommendations based on the current economic environment?"


def test_transaction_limit_only_caps_positive_integers():
    assert TransactionArgs.model_validate({"limit": 100}).limit == 12
    for limit in (True, "100", 0, -1):
        with pytest.raises(ValidationError):
            TransactionArgs.model_validate({"limit": limit})


def test_mixed_journey_preserves_full_history_and_repairs_private_search(tmp_path):
    model = ScriptedModel(
        native(call("get_transactions", limit=100)),
        native(call("web_search", query="economic outlook 98765.25")),
        native(call("web_search", query="economic outlook inflation employment monetary policy", days=14)),
        {},
        {"content": json.dumps({
            "research_answers": [{"text": "Public reporting provides context for changes in economic conditions.",
                                  "citations": ["E14"]}],
            "investment_journey": [{"text": "The recorded buys preceded a later sale.", "citations": ["E2", "E13"]}],
            "recommendations": [
                {"text": "Review how the remaining exposure fits your target allocation.", "citations": ["E1"]},
                {"text": "Move 90% of the portfolio immediately.", "citations": ["E1"]},
            ],
            "interpretations": [], "scenarios": [],
        })},
    )
    app = setup(tmp_path, model)
    app.state.financial_research = research = Research()
    with TestClient(app) as client:
        record(client, trade_date="2024-01-02", quantity="98765.25")
        for day in range(3, 15):
            record(client, trade_date=f"2024-01-{day:02}")
        record(client, trade_date="2024-02-01", side="SELL")
        result = client.post("/api/agent/chat", json={"question": QUESTION}).json()
    assert result["status"] == "partial"
    assert research.calls == [("search", "economic outlook inflation employment monetary policy", 14, False)]
    assert '"suggestions": ["economic outlook inflation employment monetary policy"]' in model.requests[2][0][-1]["content"]
    sections = {section["title"]: section["items"] for section in result["sections"]}
    assert set(sections) == {"Investment journey", "Current economic evidence", "Recommendations"}
    assert "14 transactions (13 buys, 1 sells)" in sections["Investment journey"][0]["text"]
    assert "2024-01-02 through 2024-02-01" in sections["Investment journey"][0]["text"]
    assert sections["Investment journey"][1]["citations"] == ["E2", "E13"]
    assert len(sections["Recommendations"]) == 1


def test_provider_failure_keeps_local_timeline_and_recommendations(tmp_path):
    model = ScriptedModel(
        native(call("get_transactions", symbols="VOO")),
        native(call("get_transactions"), call("web_search", query="economic outlook inflation")),
        {}, {}, final(),
    )
    app = setup(tmp_path, model)
    app.state.financial_research = Research(fail=True)
    with TestClient(app) as client:
        record(client)
        result = client.post("/api/agent/chat", json={"question": QUESTION}).json()
    assert result["status"] == "partial"
    assert "symbols" in model.requests[1][0][-1]["content"]
    assert "Use {} for all transactions" in model.requests[1][0][-1]["content"]
    assert "current economic conditions could not be verified" in " ".join(result["warnings"]).casefold()
    assert [section["title"] for section in result["sections"]] == ["Investment journey", "Recommendations"]

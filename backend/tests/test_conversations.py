import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agent.conversations import SendMessage
from app.agent.models import ToolActivity
from app.db import connect
from test_agent import NOW, ScriptedModel, final, native, call, setup
from test_portfolio import record

BASE = "/api/agent/conversations"


def create(client):
    response = client.post(BASE)
    assert response.status_code == 201
    return BASE + "/" + response.json()["id"]


def send(client, path, question, identifier=None):
    return client.post(path + "/messages", json={"id": identifier or str(uuid4()), "question": question})


def test_list_restore_and_isolate_context_using_assistant_answers(tmp_path):
    model = ScriptedModel(
        {"content": "Cobaltfern"}, {"content": "Cobaltfern again"}, {"content": "No earlier word here"},
        {"content": "Cobaltfern continues"},
    )
    with TestClient(setup(tmp_path, model)) as client:
        a, b = create(client), create(client)
        assert send(client, a, "Pick a code word.").json()["direct_answer"] == "Cobaltfern"
        assert send(client, a, "Repeat the word.").status_code == 200
        assert send(client, b, "What was our word?").status_code == 200
        assert client.get(BASE).json()[0]["id"] == b.split("/")[-1]
        assert send(client, a, "Continue.").status_code == 200
        assert client.get(BASE).json()[0]["title"] == "Pick a code word."
        assert [t["question"] for t in client.get(a).json()["turns"]] == ["Pick a code word.", "Repeat the word.", "Continue."]
        assert len(client.get(b).json()["turns"]) == 1
    assert {"role": "assistant", "content": "Cobaltfern"} in model.requests[1][0]
    assert all("Cobaltfern" not in message["content"] for message in model.requests[2][0])
    assert {"role": "assistant", "content": "Cobaltfern again"} in model.requests[3][0]


def test_preserves_answer_activity_and_synthesis_evidence_across_app_restart(tmp_path):
    idempotency = str(uuid4())
    model = ScriptedModel(native(call("get_transactions", symbols=["VOO"])), {},
                          final({"text": "The entry price comes from the local transaction.", "citations": ["E1"]}))
    with TestClient(setup(tmp_path, model)) as client:
        record(client, quantity="1")
        path = create(client)
        response = send(client, path, "Show my VOO transactions.", idempotency)
        assert response.status_code == 200
        result = response.json()
        assert result["synthesis_input"][0]["id"] == "E1"
        assert result["activity"][-1]["arguments"]["symbols"] == ["VOO"]
        assert result["activity"][-1]["source_ids"] == ["E1"]
        assert result["activity"][-1]["duration_ms"] >= 0
        assert send(client, path, "Show my VOO transactions.", idempotency).json() == result
        assert send(client, path, "Different text.", idempotency).status_code == 409
    with TestClient(setup(tmp_path, ScriptedModel())) as restarted:
        [turn] = restarted.get(path).json()["turns"]
        assert turn["result"] == result and turn["status"] == "complete"
        assert restarted.patch(path, json={"title": "Renamed"}).json()["title"] == "Renamed"
        assert restarted.delete(path).status_code == 204
        assert restarted.get(path).status_code == 404
        assert len(restarted.get("/api/transactions").json()) == 1
        with connect(restarted.app.state.conversations.path) as db:
            assert db.execute("SELECT count(*) FROM conversation_turns").fetchone()[0] == 0


def test_failure_retry_and_expired_lease_do_not_duplicate_question(tmp_path):
    app = setup(tmp_path, ScriptedModel({"content": "Retry succeeded."}))
    with TestClient(app) as client:
        path = create(client)
        key = path.split("/")[-1]
        store = app.state.conversations
        first = SendMessage(id=uuid4(), question="A persistent test.")
        _, attempt, _ = store.begin(key, first)
        store.activity(attempt, [ToolActivity(id=1, tool="get_portfolio", status="running", at=NOW)])
        assert send(client, path, "Competing question.").status_code == 409
        assert client.delete(path).status_code == 409
        with connect(store.path, write=True) as db:
            db.execute("UPDATE conversation_turns SET lease_until='2000-01-01T00:00:00Z' WHERE attempt_id=?", (attempt,))
        [interrupted] = client.get(path).json()["turns"]
        assert interrupted["status"] == "interrupted" and interrupted["activity"][0]["tool"] == "get_portfolio"
        assert send(client, path, first.question, str(first.id)).json()["direct_answer"] == "Retry succeeded."
        [retried] = client.get(path).json()["turns"]
        assert retried["status"] == "complete"
        assert retried["prior_attempts"][0]["status"] == "interrupted"


def test_generation_error_is_saved_and_retry_uses_same_id(tmp_path):
    class Failing:
        async def run(self, *_args, **_kwargs):
            raise RuntimeError("private implementation detail")

    app = setup(tmp_path, ScriptedModel({"content": "Ready."}))
    working = app.state.local_agent
    app.state.local_agent = Failing()
    with TestClient(app) as client:
        path = create(client)
        identifier = str(uuid4())
        assert send(client, path, "Please answer.", identifier).status_code == 500
        [failed] = client.get(path).json()["turns"]
        assert failed["status"] == "failed" and "private" not in failed["error"]
        app.state.local_agent = working
        assert send(client, path, "Please answer.", identifier).status_code == 200
        assert len(client.get(path).json()["turns"]) == 1


def test_cancelled_stream_persists_interrupted_status(tmp_path):
    class Interrupted:
        async def run(self, *_args, **_kwargs):
            raise asyncio.CancelledError()

    app = setup(tmp_path, ScriptedModel())
    app.state.local_agent = Interrupted()
    with TestClient(app) as client:
        path = create(client)
        response = client.post(path + "/messages?stream=true", json={"id": str(uuid4()), "question": "Please start."})
        assert response.status_code == 200 and "Generation was interrupted" in response.text
        [turn] = client.get(path).json()["turns"]
        assert turn["status"] == "interrupted" and turn["result"] is None

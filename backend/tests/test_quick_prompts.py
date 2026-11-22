from uuid import uuid4

from fastapi.testclient import TestClient

from app.agent.conversations import MIGRATIONS, SendMessage
from app.db import connect, migrate
from test_agent import ScriptedModel, call, final, native, setup
from test_conversations import create, send
from test_portfolio import record

PROMPTS = "/api/agent/quick-prompts"


def _add(client, title, prompt):
    response = client.post(PROMPTS, json={"title": title, "prompt": prompt})
    assert response.status_code == 201, response.text
    return response.json()


def test_crud_reorder_restart_and_version_one_conversation_migration(tmp_path):
    app = setup(tmp_path, ScriptedModel())
    store = app.state.conversations
    migrate(store.path, MIGRATIONS[:1])
    previous = store.create()
    store.begin(previous.id, SendMessage(id=uuid4(), question="Already stored in schema version one."))
    saved_before = store.get(previous.id)
    with TestClient(app) as client:
        assert client.get(PROMPTS).json() == []
        a = _add(client, "First", "A full prompt.")
        b = _add(client, "Second", "A multiline\nprompt.")
        c = _add(client, "Third", "Delete this entry.")
        assert [item["display_order"] for item in (a, b, c)] == [0, 1, 2]
        assert client.patch(PROMPTS + "/" + str(uuid4()), json={"title": "Missing", "prompt": "Body"}).status_code == 404
        assert client.post(PROMPTS, json={"title": " ", "prompt": "Body"}).status_code == 422
        assert client.post(PROMPTS, json={"title": "Too long", "prompt": "x" * 1601}).status_code == 422
        revised = client.patch(PROMPTS + "/" + a["id"], json={"title": "Edited", "prompt": "New full text."}).json()
        assert (revised["id"], revised["created_at"], revised["display_order"]) == (a["id"], a["created_at"], 0)
        assert revised["updated_at"] >= a["updated_at"]
        assert client.put(PROMPTS + "/order", json={"ids": [a["id"], a["id"], b["id"]]}).status_code == 409
        assert client.delete(PROMPTS + "/" + c["id"]).status_code == 204
        assert client.put(PROMPTS + "/order", json={"ids": [b["id"], a["id"], c["id"]]}).status_code == 409
        ordered = client.put(PROMPTS + "/order", json={"ids": [b["id"], a["id"]]}).json()
        assert [item["id"] for item in ordered] == [b["id"], a["id"]]
        assert store.get(previous.id) == saved_before
        with connect(store.path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    with TestClient(setup(tmp_path, ScriptedModel())) as restarted:
        restored = restarted.get(PROMPTS).json()
        assert restored == ordered
        assert [item["prompt"] for item in restored] == ["A multiline\nprompt.", "New full text."]


def test_prompt_body_is_a_normal_conversation_turn_with_tool_history(tmp_path):
    model = ScriptedModel(native(call("get_transactions", symbols=["VOO"])), {}, final())
    with TestClient(setup(tmp_path, model)) as client:
        record(client)
        saved = _add(client, "Read VOO", "Show my VOO transactions.")
        active = create(client)
        other = create(client)
        message_id = str(uuid4())
        response = send(client, active, saved["prompt"], message_id)
        assert response.status_code == 200
        assert send(client, active, saved["prompt"], message_id).json() == response.json()
        assert client.get(other).json()["turns"] == []
        [turn] = client.get(active).json()["turns"]
        assert turn["question"] == saved["prompt"] and turn["id"] == message_id
        assert turn["result"]["activity"][-1]["tool"] == "get_transactions"
        assert turn["result"]["sources"][0]["id"] == "E1"
        assert client.delete(PROMPTS + "/" + saved["id"]).status_code == 204
        assert client.get(active).json()["turns"] == [turn]

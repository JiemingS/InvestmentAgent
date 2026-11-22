from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, StringConstraints
from typing import Annotated

from ..db import connect, migrate
from .models import ChatResult, Question, ToolActivity
from .quick_prompts import QUICK_PROMPT_MIGRATION

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
LEASE = timedelta(minutes=3)
MIGRATIONS = ((
    """
    CREATE TABLE conversations (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, custom_title INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE conversation_turns (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        id TEXT NOT NULL, question TEXT NOT NULL, created_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','complete','failed','interrupted')),
        attempt_id TEXT, lease_until TEXT, activity TEXT NOT NULL DEFAULT '[]',
        result TEXT, error TEXT, prior_attempts TEXT NOT NULL DEFAULT '[]', UNIQUE(conversation_id, id)
    )
    """,
    """CREATE UNIQUE INDEX one_pending_turn ON conversation_turns(conversation_id)
       WHERE status='pending'""",
    "CREATE INDEX conversation_turn_order ON conversation_turns(conversation_id, sequence)",
), QUICK_PROMPT_MIGRATION)


class Conversation(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class Turn(BaseModel):
    id: str
    question: str
    created_at: datetime
    status: Literal["pending", "complete", "failed", "interrupted"]
    activity: list[ToolActivity]
    result: ChatResult | None = None
    error: str | None = None
    prior_attempts: list[dict] = []


class ConversationDetail(Conversation):
    turns: list[Turn]


class SendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    question: Question


class RenameConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title


class ConversationMissing(LookupError):
    pass


class ConversationConflict(ValueError):
    pass


def _now():
    return datetime.now(UTC)


def _title(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= 60 else text[:59].rstrip() + "…"


def _turn(row) -> Turn:
    values = dict(row)
    values["activity"] = json.loads(values["activity"])
    values["prior_attempts"] = json.loads(values["prior_attempts"])
    if values["result"]:
        values["result"] = json.loads(values["result"])
    return Turn.model_validate(values)


class ConversationStore:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self):
        migrate(self.path, MIGRATIONS)

    def create(self) -> Conversation:
        now = _now()
        item = Conversation(id=str(uuid4()), title="New chat", created_at=now, updated_at=now)
        with connect(self.path, write=True) as db:
            db.execute(
                "INSERT INTO conversations(id,title,created_at,updated_at) VALUES(:id,:title,:created_at,:updated_at)",
                {**item.model_dump(mode="json"), "created_at": now.isoformat(), "updated_at": now.isoformat()},
            )
        return item

    def list(self) -> list[Conversation]:
        with connect(self.path) as db:
            return [Conversation.model_validate(dict(row)) for row in db.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC, rowid DESC"
            )]

    def get(self, conversation_id: str) -> ConversationDetail:
        with connect(self.path, write=True) as db:
            self._expire(db, conversation_id)
            row = self._require(db, conversation_id)
            turns = db.execute("SELECT * FROM conversation_turns WHERE conversation_id=? ORDER BY sequence", (conversation_id,))
            return ConversationDetail(**dict(row), turns=[_turn(turn) for turn in turns])

    def rename(self, conversation_id: str, title: str) -> Conversation:
        with connect(self.path, write=True) as db:
            self._require(db, conversation_id)
            db.execute("UPDATE conversations SET title=?, custom_title=1, updated_at=? WHERE id=?",
                       (title, _now().isoformat(), conversation_id))
            return Conversation.model_validate(dict(self._require(db, conversation_id)))

    def delete(self, conversation_id: str):
        with connect(self.path, write=True) as db:
            self._expire(db, conversation_id)
            self._require(db, conversation_id)
            self._ensure_idle(db, conversation_id)
            db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))

    def begin(self, conversation_id: str, body: SendMessage) -> tuple[Turn, str | None, list[Turn]]:
        turn_id = str(body.id)
        now = _now()
        stamp = now.isoformat()
        attempt = str(uuid4())
        deadline = (now + LEASE).isoformat()
        with connect(self.path, write=True) as db:
            item = self._require(db, conversation_id)
            self._expire(db, conversation_id)
            previous = db.execute("SELECT * FROM conversation_turns WHERE conversation_id=? AND id=?",
                                  (conversation_id, turn_id)).fetchone()
            if previous and previous["question"] != body.question:
                raise ConversationConflict("This message ID already belongs to another question.")
            if previous and previous["status"] == "complete":
                return _turn(previous), None, []
            self._ensure_idle(db, conversation_id)
            if previous:
                latest = db.execute("SELECT MAX(sequence) FROM conversation_turns WHERE conversation_id=?",
                                    (conversation_id,)).fetchone()[0]
                if previous["sequence"] != latest:
                    raise ConversationConflict("Only the newest interrupted or failed turn can be retried.")
                snapshot = _turn(previous).model_dump(mode="json", exclude={"prior_attempts", "id", "question", "created_at"})
                archive = [*json.loads(previous["prior_attempts"]), snapshot]
                db.execute(
                    """UPDATE conversation_turns SET status='pending', attempt_id=?, lease_until=?,
                       result=NULL, error=NULL, activity='[]', prior_attempts=? WHERE sequence=?""",
                    (attempt, deadline, json.dumps(archive), previous["sequence"]),
                )
            else:
                db.execute(
                    """INSERT INTO conversation_turns(conversation_id,id,question,created_at,status,attempt_id,lease_until)
                       VALUES(?,?,?,?,'pending',?,?)""",
                    (conversation_id, turn_id, body.question, stamp, attempt, deadline),
                )
                if not item["custom_title"] and item["title"] == "New chat":
                    # Only the first submission should generate the title.
                    db.execute("""UPDATE conversations SET title=? WHERE id=? AND
                                  (SELECT COUNT(*) FROM conversation_turns WHERE conversation_id=?)=1""",
                               (_title(body.question), conversation_id, conversation_id))
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (stamp, conversation_id))
            row = db.execute("SELECT * FROM conversation_turns WHERE conversation_id=? AND id=?",
                             (conversation_id, turn_id)).fetchone()
            context = db.execute(
                """SELECT * FROM conversation_turns WHERE conversation_id=? AND status='complete'
                   AND sequence<? ORDER BY sequence DESC LIMIT 3""", (conversation_id, row["sequence"]),
            ).fetchall()
            return _turn(row), attempt, [_turn(prior) for prior in reversed(context)]

    def activity(self, attempt: str, events: list[ToolActivity]):
        with connect(self.path, write=True) as db:
            db.execute("UPDATE conversation_turns SET activity=? WHERE attempt_id=? AND status='pending'",
                       (json.dumps([event.model_dump(mode="json") for event in events]), attempt))

    def finish(self, conversation_id: str, attempt: str, status: str, *,
               result: ChatResult | None = None, error: str | None = None):
        with connect(self.path, write=True) as db:
            cursor = db.execute(
                """UPDATE conversation_turns SET status=?, result=?, error=?, attempt_id=NULL, lease_until=NULL
                   WHERE conversation_id=? AND attempt_id=? AND status='pending'""",
                (status, result.model_dump_json() if result else None, error, conversation_id, attempt),
            )
            if cursor.rowcount:
                db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now().isoformat(), conversation_id))

    @staticmethod
    def _require(db, conversation_id):
        row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not row:
            raise ConversationMissing("Conversation not found.")
        return row

    @staticmethod
    def _expire(db, conversation_id):
        db.execute(
            """UPDATE conversation_turns SET status='interrupted', attempt_id=NULL, lease_until=NULL,
               error='Generation was interrupted before a response was saved.'
               WHERE conversation_id=? AND status='pending' AND julianday(lease_until)<=julianday(?)""",
            (conversation_id, _now().isoformat()),
        )

    @staticmethod
    def _ensure_idle(db, conversation_id):
        if db.execute("SELECT 1 FROM conversation_turns WHERE conversation_id=? AND status='pending'",
                      (conversation_id,)).fetchone():
            raise ConversationConflict("This conversation already has a response in progress.")

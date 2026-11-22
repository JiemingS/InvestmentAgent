from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, StringConstraints

from ..db import connect
from .models import Question

QUICK_PROMPT_MIGRATION = (
    """
    CREATE TABLE quick_prompts (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        prompt TEXT NOT NULL,
        display_order INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX quick_prompts_display_order ON quick_prompts(display_order, id)",
)


class QuickPromptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    prompt: Question


class QuickPrompt(QuickPromptInput):
    id: UUID
    display_order: int
    created_at: datetime
    updated_at: datetime


class PromptOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[UUID]


class QuickPromptMissing(LookupError):
    pass


class QuickPromptOrderConflict(ValueError):
    pass


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


class QuickPromptStore:
    def __init__(self, path: Path):
        self.path = path

    def list(self) -> list[QuickPrompt]:
        with connect(self.path) as db:
            return self._list(db)

    def create(self, body: QuickPromptInput) -> QuickPrompt:
        prompt_id = str(uuid4())
        now = _timestamp()
        with connect(self.path, write=True) as db:
            display_order = db.execute("SELECT COALESCE(MAX(display_order), -1) + 1 FROM quick_prompts").fetchone()[0]
            db.execute(
                """INSERT INTO quick_prompts (id, title, prompt, display_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (prompt_id, body.title, body.prompt, display_order, now, now),
            )
            return self._get(db, prompt_id)

    def update(self, prompt_id: str, body: QuickPromptInput) -> QuickPrompt:
        with connect(self.path, write=True) as db:
            db.execute("UPDATE quick_prompts SET title=?, prompt=?, updated_at=? WHERE id=?",
                       (body.title, body.prompt, _timestamp(), prompt_id))
            return self._get(db, prompt_id)

    def delete(self, prompt_id: str) -> None:
        with connect(self.path, write=True) as db:
            if not db.execute("DELETE FROM quick_prompts WHERE id=?", (prompt_id,)).rowcount:
                raise QuickPromptMissing("Quick Prompt not found.")

    def reorder(self, order: PromptOrder) -> list[QuickPrompt]:
        with connect(self.path, write=True) as db:
            current = {prompt.id: prompt.display_order for prompt in self._list(db)}
            if len(order.ids) != len(current) or set(order.ids) != set(current):
                raise QuickPromptOrderConflict("Send each current Quick Prompt ID exactly once.")
            now = _timestamp()
            db.executemany(
                "UPDATE quick_prompts SET display_order=?, updated_at=? WHERE id=?",
                [(position, now, str(prompt_id)) for position, prompt_id in enumerate(order.ids)
                 if position != current[prompt_id]],
            )
            return self._list(db)

    @staticmethod
    def _list(db) -> list[QuickPrompt]:
        return [QuickPrompt.model_validate(dict(row)) for row in db.execute(
            "SELECT * FROM quick_prompts ORDER BY display_order, id"
        )]

    @staticmethod
    def _get(db, prompt_id: str) -> QuickPrompt:
        row = db.execute("SELECT * FROM quick_prompts WHERE id=?", (prompt_id,)).fetchone()
        if not row:
            raise QuickPromptMissing("Quick Prompt not found.")
        return QuickPrompt.model_validate(dict(row))

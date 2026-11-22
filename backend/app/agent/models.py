from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1600)]
EvidenceKind = Literal["portfolio", "market", "calendar", "news", "clock"]
EvidenceID = Annotated[str, StringConstraints(pattern=r"^E[1-9][0-9]{0,2}$")]


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Question
    previous_questions: list[Question] = Field(default_factory=list, max_length=3)


class Evidence(BaseModel):
    id: EvidenceID
    kind: EvidenceKind
    title: str
    text: str
    url: str | None = None
    observed_at: datetime | None = None
    retrieved_at: datetime
    fetched_at: datetime | None = None
    fetched_url: str | None = None
    stale: bool = False
    excerpt: str | None = None
    search_excerpt: str | None = None
    derived_from: list[EvidenceID] = Field(default_factory=list)
    fetch_error: str | None = None


class ToolActivity(BaseModel):
    id: int
    tool: str
    status: Literal["running", "ok", "warning", "error", "timeout", "rejected"]
    at: datetime
    detail: str | None = None
    arguments: dict | None = None
    duration_ms: int | None = None
    source_ids: list[EvidenceID] = Field(default_factory=list)


class ContextTurn(BaseModel):
    question: str
    answer: str = ""


class AnswerItem(BaseModel):
    text: str
    citations: list[EvidenceID] = Field(default_factory=list)


class AnswerSection(BaseModel):
    title: str
    items: list[AnswerItem]


class ChatResult(BaseModel):
    model: str
    started_at: datetime
    completed_at: datetime
    status: Literal["complete", "partial", "unavailable"]
    mode: Literal["direct", "tool", "hybrid"] | None = None
    direct_answer: str | None = None
    sections: list[AnswerSection]
    sources: list[Evidence]
    activity: list[ToolActivity]
    warnings: list[str]
    synthesis_input: list[dict] = Field(default_factory=list)


class AnalysisItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=12, max_length=720)]
    citations: list[EvidenceID] = Field(min_length=1, max_length=6)


class Synthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_answers: list[AnalysisItem] = Field(default_factory=list, max_length=4)
    interpretations: list[AnalysisItem] = Field(max_length=4)
    scenarios: list[AnalysisItem] = Field(max_length=2)
    investment_journey: list[AnalysisItem] = Field(default_factory=list, max_length=4)
    recommendations: list[AnalysisItem] = Field(default_factory=list, max_length=3)


class PublicSearchIdeas(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queries: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=130)]] = Field(max_length=4)

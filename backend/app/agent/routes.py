import asyncio
from contextlib import suppress
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from .conversations import (
    Conversation, ConversationConflict, ConversationDetail, ConversationMissing, ConversationStore,
    RenameConversation, SendMessage, Turn,
)
from .models import ChatInput, ChatResult, ContextTurn
from .orchestrator import BusyAgent
from .quick_prompt_routes import router as quick_prompt_router

router = APIRouter(prefix="/api/agent")
router.include_router(quick_prompt_router)


def _store(request: Request) -> ConversationStore:
    return request.app.state.conversations


def _invoke(operation, *args):
    try:
        return operation(*args)
    except ConversationMissing as error:
        raise HTTPException(404, str(error)) from error
    except ConversationConflict as error:
        raise HTTPException(409, str(error)) from error


def _context(turns: list[Turn]) -> list[ContextTurn]:
    remaining = 4800
    selected = []
    for turn in reversed(turns):
        if remaining < len(turn.question):
            break
        remaining -= len(turn.question)
        answer = ""
        if turn.result:
            if turn.result.mode == "direct":
                answer = turn.result.direct_answer or ""
            else:
                # Only facts formed by local adapters. Never replay external excerpts,
                # external titles or model interpretations to the tool-enabled model.
                answer = "\n".join(item.text for item in turn.result.sources
                                   if item.kind in ("portfolio", "market", "clock"))
        answer = answer[:min(900, remaining)]
        remaining -= len(answer)
        selected.append(ContextTurn(question=turn.question, answer=answer))
    return list(reversed(selected))


async def _run(request: Request, body: ChatInput, progress=None, *, history=None):
    state = request.app.state
    args = (body, state.database, state.market, state.economic_calendar, state.financial_research, progress)
    if history is not None:
        return await state.local_agent.run(*args, history=history)
    return await state.local_agent.run(*args)


def _stream(run):
    async def events():
        queue: asyncio.Queue = asyncio.Queue()

        def progress(activity):
            queue.put_nowait({"type": "activity", "activity": activity.model_dump(mode="json")})

        async def produce():
            try:
                result = await run(progress)
                queue.put_nowait({"type": "result", "result": result.model_dump(mode="json")})
            except BusyAgent as error:
                queue.put_nowait({"type": "error", "message": str(error)})
            except asyncio.CancelledError:
                queue.put_nowait({"type": "error", "message": "Generation was interrupted."})
                raise
            except Exception:
                queue.put_nowait({"type": "error", "message": "The local analysis could not be completed."})

        task = asyncio.create_task(produce())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    event = {"type": "waiting"}
                yield json.dumps(event, ensure_ascii=False) + "\n"
                if event["type"] in ("result", "error"):
                    break
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})


@router.post("/chat", response_model=ChatResult)
async def chat(request: Request, body: ChatInput, stream: bool = False):
    async def run(progress=None):
        return await _run(request, body, progress)
    if stream:
        return _stream(run)
    try:
        return await run()
    except BusyAgent as error:
        raise HTTPException(429, str(error)) from error


@router.post("/conversations", status_code=201)
def create_conversation(request: Request) -> Conversation:
    return _store(request).create()


@router.get("/conversations")
def list_conversations(request: Request) -> list[Conversation]:
    return _store(request).list()


@router.get("/conversations/{conversation_id}")
def get_conversation(request: Request, conversation_id: UUID) -> ConversationDetail:
    return _invoke(_store(request).get, str(conversation_id))


@router.patch("/conversations/{conversation_id}")
def rename_conversation(request: Request, conversation_id: UUID, body: RenameConversation) -> Conversation:
    return _invoke(_store(request).rename, str(conversation_id), body.title)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(request: Request, conversation_id: UUID) -> Response:
    _invoke(_store(request).delete, str(conversation_id))
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages", response_model=ChatResult)
async def send_message(request: Request, conversation_id: UUID, body: SendMessage, stream: bool = False):
    store = _store(request)
    key = str(conversation_id)
    turn, attempt, previous = _invoke(store.begin, key, body)
    history = _context(previous)
    chat_input = ChatInput(question=turn.question, previous_questions=[item.question for item in history])

    async def run(progress=None):
        if attempt is None:
            assert turn.result is not None
            return turn.result
        activity = []

        def capture(event):
            activity.append(event)
            store.activity(attempt, activity)
            if progress:
                progress(event)

        try:
            result = await _run(request, chat_input, capture, history=history)
        except asyncio.CancelledError:
            store.finish(key, attempt, "interrupted", error="Generation was interrupted.")
            raise
        except Exception as error:
            message = str(error) if isinstance(error, BusyAgent) else "The local analysis could not be completed."
            store.finish(key, attempt, "failed", error=message)
            raise
        store.finish(key, attempt, "failed" if result.status == "unavailable" else "complete",
                     result=result)
        return result

    if stream:
        return _stream(run)
    try:
        return await run()
    except BusyAgent as error:
        raise HTTPException(429, str(error)) from error
    except Exception as error:
        raise HTTPException(500, "The local analysis could not be completed.") from error

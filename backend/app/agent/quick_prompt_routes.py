from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from .quick_prompts import (
    PromptOrder, QuickPrompt, QuickPromptInput, QuickPromptMissing, QuickPromptOrderConflict, QuickPromptStore,
)

router = APIRouter(prefix="/quick-prompts")


def _store(request: Request) -> QuickPromptStore:
    return QuickPromptStore(request.app.state.conversations.path)


@router.get("")
def list_prompts(request: Request) -> list[QuickPrompt]:
    return _store(request).list()


@router.post("", status_code=201)
def create_prompt(request: Request, body: QuickPromptInput) -> QuickPrompt:
    return _store(request).create(body)


@router.put("/order")
def reorder_prompts(request: Request, body: PromptOrder) -> list[QuickPrompt]:
    try:
        return _store(request).reorder(body)
    except QuickPromptOrderConflict as error:
        raise HTTPException(409, str(error)) from error


@router.patch("/{prompt_id}")
def update_prompt(request: Request, prompt_id: UUID, body: QuickPromptInput) -> QuickPrompt:
    try:
        return _store(request).update(str(prompt_id), body)
    except QuickPromptMissing as error:
        raise HTTPException(404, str(error)) from error


@router.delete("/{prompt_id}", status_code=204)
def delete_prompt(request: Request, prompt_id: UUID) -> Response:
    try:
        _store(request).delete(str(prompt_id))
    except QuickPromptMissing as error:
        raise HTTPException(404, str(error)) from error
    return Response(status_code=204)

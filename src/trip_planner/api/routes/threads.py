import uuid as uuid_lib
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status

from trip_planner.api.dependencies import CurrentUser, DbSession
from trip_planner.api.planner_result import invalid_planner_outcome, to_planner_result
from trip_planner.core.pagination import decode_cursor, encode_cursor
from trip_planner.models.message import Message
from trip_planner.models.thread import Thread
from trip_planner.repositories import message_repository, thread_repository
from trip_planner.schemas.threads import (
    MessageOut,
    SendMessageRequest,
    SendMessageResponse,
    ThreadDetailResponse,
    ThreadListResponse,
    ThreadSummary,
)
from trip_planner.schemas.trips import Itinerary
from trip_planner.services.trip_planning_service import (
    PlannerContractError,
    TripPlanningService,
)

router = APIRouter(prefix="/threads", tags=["threads"])

_not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
_forbidden = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
_invalid_cursor = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor"
)

def _decode_cursor_or_400(cursor: str | None) -> tuple[datetime, uuid_lib.UUID] | None:
    """Decode an opaque cursor into its (timestamp, id) pair, raising 400 when malformed."""
    if cursor is None:
        return None

    try:
        return decode_cursor(cursor)
    except ValueError:
        raise _invalid_cursor from None

def _next_message_cursor(messages: list[Message], limit: int) -> str | None:
    """Return the next-page cursor, or None when the page isn't full."""
    if len(messages) < limit:
        return None

    last = messages[-1]

    return encode_cursor(last.created_at, last.id)

def _next_thread_cursor(threads: list[Thread], limit: int) -> str | None:
    """Return the next-page cursor, or None when the page isn't full."""
    if len(threads) < limit:
        return None

    last = threads[-1]

    return encode_cursor(last.updated_at, last.id)

def _to_thread_summary(thread: Thread) -> ThreadSummary:
    """Convert a Thread ORM instance to a ThreadSummary response schema."""
    return ThreadSummary(
        id=thread.id,
        title=thread.title,
        slug=thread.slug,
        status=thread.status,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )

def _to_message_out(message: Message) -> MessageOut:
    """Convert a Message ORM instance to a MessageOut response schema."""
    itinerary = Itinerary.model_validate(message.itinerary) if message.itinerary else None

    return MessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        itinerary=itinerary,
        created_at=message.created_at,
    )

@router.post(
    "/{thread_id}/messages",
    response_model=SendMessageResponse,
    status_code=status.HTTP_200_OK,
)
async def send_message(
    thread_id: uuid_lib.UUID,
    body: SendMessageRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> SendMessageResponse:
    """Append a follow-up message to an existing thread and return the updated result."""
    thread = await thread_repository.get_by_id(db, thread_id)

    if thread is None:
        raise _not_found

    is_owner = thread.user_id == current_user.id

    if not is_owner:
        raise _forbidden

    service = TripPlanningService(db)

    try:
        turn = await service.continue_trip(thread, body.query)
    except PlannerContractError:
        raise invalid_planner_outcome from None

    return SendMessageResponse(result=to_planner_result(turn.outcome))

@router.get("", response_model=ThreadListResponse, status_code=status.HTTP_200_OK)
async def list_threads(
    current_user: CurrentUser,
    db: DbSession,
    cursor: str | None = Query(default=None, description="Opaque cursor for the next page"),
    limit: int = Query(default=20, ge=1, le=100),
) -> ThreadListResponse:
    """List active threads for the current user, newest first, with keyset pagination."""
    decoded_cursor = _decode_cursor_or_400(cursor)
    threads = await thread_repository.list_by_user(
        db, user_id=current_user.id, cursor=decoded_cursor, limit=limit
    )

    return ThreadListResponse(
        threads=[_to_thread_summary(t) for t in threads],
        next_cursor=_next_thread_cursor(threads, limit),
    )

@router.get("/{thread_id}", response_model=ThreadDetailResponse, status_code=status.HTTP_200_OK)
async def get_thread(
    thread_id: uuid_lib.UUID,
    current_user: CurrentUser,
    db: DbSession,
    cursor: str | None = Query(default=None, description="Opaque cursor for the next page"),
    limit: int = Query(default=20, ge=1, le=100),
) -> ThreadDetailResponse:
    """Return thread metadata and a paginated page of messages (newest first)."""
    thread = await thread_repository.get_by_id(db, thread_id)

    if thread is None:
        raise _not_found

    is_owner = thread.user_id == current_user.id
    if not is_owner:
        raise _forbidden

    decoded_cursor = _decode_cursor_or_400(cursor)
    messages = await message_repository.list_by_thread(
        db, thread_id=thread.id, cursor=decoded_cursor, limit=limit
    )

    return ThreadDetailResponse(
        thread=_to_thread_summary(thread),
        messages=[_to_message_out(m) for m in messages],
        next_cursor=_next_message_cursor(messages, limit),
    )

@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: uuid_lib.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> None:
    """Soft-delete a thread and all its messages."""
    thread = await thread_repository.get_by_id(db, thread_id)

    if thread is None:
        raise _not_found

    is_owner = thread.user_id == current_user.id

    if not is_owner:
        raise _forbidden

    await message_repository.soft_delete_by_thread(db, thread_id=thread.id)
    await thread_repository.soft_delete(db, thread)

    await db.commit()

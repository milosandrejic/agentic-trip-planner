import re
import uuid as uuid_lib
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status

from trip_planner.agents.graph import plan_turn
from trip_planner.api.dependencies import CurrentUser, DbSession
from trip_planner.core.pagination import decode_cursor, encode_cursor
from trip_planner.models.message import Message
from trip_planner.models.thread import Thread, ThreadStatus
from trip_planner.repositories import message_repository, thread_repository
from trip_planner.schemas.threads import (
    ClarificationResult,
    CreateThreadRequest,
    CreateThreadResponse,
    ItineraryResult,
    MessageOut,
    SendMessageRequest,
    SendMessageResponse,
    ThreadDetailResponse,
    ThreadListResponse,
    ThreadSummary,
)
from trip_planner.schemas.trips import Itinerary

router = APIRouter(prefix="/threads", tags=["threads"])

_not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
_forbidden = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
_invalid_cursor = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor"
)

# 500 because the graph violated its own contract: it completed without producing
# either a structured itinerary or a clarification response.
_invalid_graph_outcome = HTTPException(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    detail="Graph did not produce a structured itinerary or clarification",
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

def _make_slug(text: str) -> str:
    """Build a URL-safe slug from text with a random suffix to prevent collisions."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", text[:60].lower()).strip("-")
    suffix = uuid_lib.uuid4().hex[:8]

    return f"{cleaned}-{suffix}"

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

@router.post("", response_model=CreateThreadResponse, status_code=status.HTTP_201_CREATED)
async def create_thread(
    body: CreateThreadRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CreateThreadResponse:
    """Create a new thread, invoke the planner, persist messages, and return the itinerary."""
    title = body.query[:80]
    slug = _make_slug(body.query)

    thread = await thread_repository.create_thread(
        db, user_id=current_user.id, title=title, slug=slug
    )
    await message_repository.create_message(
        db, thread_id=thread.id, role="human", content=body.query
    )
    thread.status = ThreadStatus.RUNNING
    await db.commit()

    try:
        outcome = await plan_turn(body.query, thread_id=str(thread.id))
    except Exception:
        # Any planner failure leaves the thread FAILED so clients can surface or retry it.
        thread.status = ThreadStatus.FAILED
        await db.commit()
        raise

    clarification = outcome.clarification
    itinerary = outcome.itinerary

    if clarification is not None:
        await message_repository.create_message(
            db, thread_id=thread.id, role="assistant", content=clarification.message
        )
        thread.status = ThreadStatus.READY
        await db.commit()
        return CreateThreadResponse(
            thread=_to_thread_summary(thread),
            result=ClarificationResult(clarification=clarification),
        )

    if itinerary is None:
        thread.status = ThreadStatus.FAILED
        await db.commit()
        raise _invalid_graph_outcome

    await message_repository.create_message(
        db,
        thread_id=thread.id,
        role="assistant",
        content=itinerary.summary,
        itinerary=itinerary.model_dump(),
    )
    thread.status = ThreadStatus.READY

    await db.commit()

    return CreateThreadResponse(
        thread=_to_thread_summary(thread),
        result=ItineraryResult(itinerary=itinerary),
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
    """Append a follow-up message to an existing thread and return the updated itinerary."""
    thread = await thread_repository.get_by_id(db, thread_id)

    if thread is None:
        raise _not_found

    is_owner = thread.user_id == current_user.id

    if not is_owner:
        raise _forbidden

    await message_repository.create_message(
        db, thread_id=thread.id, role="human", content=body.query
    )
    thread.status = ThreadStatus.RUNNING
    await db.commit()

    try:
        outcome = await plan_turn(body.query, thread_id=str(thread.id))
    except Exception:
        # Any planner failure leaves the thread FAILED so clients can surface or retry it.
        thread.status = ThreadStatus.FAILED
        await db.commit()
        raise

    clarification = outcome.clarification
    itinerary = outcome.itinerary

    if clarification is not None:
        await message_repository.create_message(
            db, thread_id=thread.id, role="assistant", content=clarification.message
        )
        thread.updated_at = datetime.now(timezone.utc)
        thread.status = ThreadStatus.READY
        await db.commit()
        return SendMessageResponse(result=ClarificationResult(clarification=clarification))

    if itinerary is None:
        thread.status = ThreadStatus.FAILED
        await db.commit()
        raise _invalid_graph_outcome

    await message_repository.create_message(
        db,
        thread_id=thread.id,
        role="assistant",
        content=itinerary.summary,
        itinerary=itinerary.model_dump(),
    )

    thread.updated_at = datetime.now(timezone.utc)
    thread.status = ThreadStatus.READY

    await db.commit()

    return SendMessageResponse(result=ItineraryResult(itinerary=itinerary))

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

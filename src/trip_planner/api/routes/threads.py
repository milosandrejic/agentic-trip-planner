import re
import uuid as uuid_lib
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status
from langchain_core.messages import HumanMessage

from trip_planner.agents.graph import run_planner
from trip_planner.agents.state import TripPlannerState
from trip_planner.api.dependencies import CurrentUser, DbSession
from trip_planner.models.message import Message
from trip_planner.models.thread import Thread
from trip_planner.repositories import message_repository, thread_repository
from trip_planner.schemas.threads import (
    CreateThreadRequest,
    CreateThreadResponse,
    ClarificationResult,
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
_graph_error = HTTPException(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    detail="Graph did not produce a structured itinerary or clarification",
)

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

    initial_state = TripPlannerState(
        messages=[HumanMessage(content=body.query)],
        trip_request=body.query,
        draft_itinerary="",
    )
    result = await run_planner(initial_state, thread_id=str(thread.id))

    clarification = result.get("clarification")
    itinerary = result.get("itinerary")

    await message_repository.create_message(
        db, thread_id=thread.id, role="human", content=body.query
    )

    if clarification is not None:
        await message_repository.create_message(
            db, thread_id=thread.id, role="assistant", content=clarification.message
        )
        await db.commit()
        return CreateThreadResponse(
            thread=_to_thread_summary(thread),
            result=ClarificationResult(clarification=clarification),
        )

    if itinerary is None:
        raise _graph_error

    await message_repository.create_message(
        db,
        thread_id=thread.id,
        role="assistant",
        content=itinerary.summary,
        itinerary=itinerary.model_dump(),
    )

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

    follow_up_state = TripPlannerState(
        messages=[HumanMessage(content=body.query)],
        trip_request=body.query,
        draft_itinerary="",
    )

    result = await run_planner(follow_up_state, thread_id=str(thread.id))

    clarification = result.get("clarification")
    itinerary = result.get("itinerary")

    await message_repository.create_message(
        db, thread_id=thread.id, role="human", content=body.query
    )

    if clarification is not None:
        await message_repository.create_message(
            db, thread_id=thread.id, role="assistant", content=clarification.message
        )
        thread.updated_at = datetime.now(timezone.utc)
        await db.commit()
        return SendMessageResponse(result=ClarificationResult(clarification=clarification))

    if itinerary is None:
        raise _graph_error

    await message_repository.create_message(
        db,
        thread_id=thread.id,
        role="assistant",
        content=itinerary.summary,
        itinerary=itinerary.model_dump(),
    )

    thread.updated_at = datetime.now(timezone.utc)

    await db.commit()

    return SendMessageResponse(result=ItineraryResult(itinerary=itinerary))

@router.get("", response_model=ThreadListResponse, status_code=status.HTTP_200_OK)
async def list_threads(
    current_user: CurrentUser,
    db: DbSession,
) -> ThreadListResponse:
    """List all active threads belonging to the current user, newest first."""
    threads = await thread_repository.list_by_user(db, user_id=current_user.id)

    return ThreadListResponse(threads=[_to_thread_summary(t) for t in threads])

@router.get("/{thread_id}", response_model=ThreadDetailResponse, status_code=status.HTTP_200_OK)
async def get_thread(
    thread_id: uuid_lib.UUID,
    current_user: CurrentUser,
    db: DbSession,
    before: datetime | None = Query(
        default=None, description="Cursor: fetch messages before this timestamp"
    ),
    limit: int = Query(default=20, ge=1, le=100),
) -> ThreadDetailResponse:
    """Return thread metadata and a paginated page of messages (newest first)."""
    thread = await thread_repository.get_by_id(db, thread_id)

    if thread is None:
        raise _not_found

    is_owner = thread.user_id == current_user.id
    if not is_owner:
        raise _forbidden

    messages = await message_repository.list_by_thread(
        db, thread_id=thread.id, before=before, limit=limit
    )

    return ThreadDetailResponse(
        thread=_to_thread_summary(thread),
        messages=[_to_message_out(m) for m in messages],
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

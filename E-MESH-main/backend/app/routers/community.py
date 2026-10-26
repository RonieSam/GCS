"""
Community router.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.core.ws_manager import emit_event
from app.models.message import Message
from app.models.user import User
from app.schemas.events import EventType
from app.schemas.message import CommunityMessageCreate, CommunityMessageRead
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/community", tags=["Community"])


@router.get("/messages", response_model=PaginatedResponse[CommunityMessageRead], summary="List community messages")
async def list_community_messages(
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[User, Depends(get_current_user)],
):
    # Get last 50 messages where recipient is null (public)
    query = (
        select(Message, User.username.label("sender_username"))
        .outerjoin(User, Message.sender_id == User.id)
        .where(Message.recipient_id == None)  # noqa: E711
        .order_by(Message.sent_at.desc())
        .limit(50)
    )
    result = await db.execute(query)
    rows = result.all()

    items = []
    for msg, sender_username in rows:
        items.append(
            CommunityMessageRead(
                id=msg.id,
                sender_id=msg.sender_id,
                sender_username=sender_username or "Unknown",
                content=msg.content,
                sent_at=msg.sent_at,
            )
        )
    # Reverse to return chronologically
    items.reverse()

    return PaginatedResponse(
        data=items,
        total=len(items),
        page=1,
        page_size=50,
        total_pages=1,
    )


@router.post("/messages", response_model=CommunityMessageRead, status_code=201, summary="Send community message")
async def send_community_message(
    request: Request,
    body: CommunityMessageCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
):
    msg = Message(
        sender_id=actor.id,
        recipient_id=None,
        content=body.content,
    )
    db.add(msg)
    await db.flush()

    response_msg = CommunityMessageRead(
        id=msg.id,
        sender_id=actor.id,
        sender_username=actor.username,
        content=msg.content,
        sent_at=msg.sent_at,
    )

    emit_event(
        event=EventType.COMMUNITY_MESSAGE_SENT,
        data={
            "message_id": msg.id,
            "sender_id": actor.id,
            "sender_username": actor.username,
            "content": msg.content,
            "sent_at": msg.sent_at.isoformat() if msg.sent_at else "",
        },
        target_roles=None,
        target_user_id=None,
        scope="public",
    )

    return response_msg

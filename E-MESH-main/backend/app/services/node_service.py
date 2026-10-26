"""
Node service — CRUD and status management for mesh nodes.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import NodeStatus
from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.models.node import Node
from app.models.node_link import NodeLink
from app.schemas.node import NodeCreate, NodeUpdate


async def get_node_by_id(session: AsyncSession, node_id: str) -> Optional[Node]:
    result = await session.execute(select(Node).where(Node.id == node_id))
    return result.scalar_one_or_none()


async def get_node_by_node_id(session: AsyncSession, node_id: str) -> Optional[Node]:
    result = await session.execute(select(Node).where(Node.node_id == node_id))
    return result.scalar_one_or_none()


async def list_nodes(
    session: AsyncSession,
    status: Optional[NodeStatus] = None,
    page: int = 1,
    page_size: int = 50,
) -> Tuple[List[Node], int]:
    query = select(Node)
    if status:
        query = query.where(Node.status == status)

    count_result = await session.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    query = query.offset((page - 1) * page_size).limit(page_size).order_by(Node.node_id)
    result = await session.execute(query)
    return list(result.scalars().all()), total


async def create_node(session: AsyncSession, data: NodeCreate) -> Node:
    existing = await get_node_by_node_id(session, data.node_id)
    if existing:
        raise AlreadyExistsError("Node", data.node_id)

    node = Node(
        node_id=data.node_id,
        display_name=data.display_name or data.node_id,
        is_gateway=data.is_gateway,
        status=NodeStatus.UNKNOWN,
        position_x=data.position_x,
        position_y=data.position_y,
    )
    session.add(node)
    await session.flush()
    return node


async def update_node(session: AsyncSession, node_id: str, data: NodeUpdate) -> Node:
    node = await get_node_by_id(session, node_id)
    if not node:
        raise NotFoundError("Node", node_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(node, field, value)

    await session.flush()
    return node


async def delete_node(session: AsyncSession, node_id: str) -> None:
    node = await get_node_by_id(session, node_id)
    if not node:
        raise NotFoundError("Node", node_id)
    await session.delete(node)
    await session.flush()


async def get_links_for_node(session: AsyncSession, node_db_id: str) -> List[NodeLink]:
    result = await session.execute(
        select(NodeLink).where(
            (NodeLink.source_node_id == node_db_id) | (NodeLink.target_node_id == node_db_id)
        )
    )
    return list(result.scalars().all())


async def list_all_links(session: AsyncSession) -> List[NodeLink]:
    result = await session.execute(select(NodeLink))
    return list(result.scalars().all())

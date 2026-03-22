"""Audit logger — writes immutable AuditEvent records to PostgreSQL."""

from __future__ import annotations

import logging

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.interfaces.models import AuditEvent
from app.shared.models.stock import AuditLog

logger = logging.getLogger(__name__)


async def persist_audit_events(
    session: AsyncSession,
    events: list[AuditEvent],
) -> int:
    """Batch-insert audit events into the audit_log table.  Returns count."""
    if not events:
        return 0

    rows = [
        {
            "event_id": str(e.event_id),
            "action": e.action.value,
            "order_id": str(e.order_id) if e.order_id else None,
            "ts_code": e.ts_code,
            "detail": e.detail,
            "timestamp": e.timestamp,
        }
        for e in events
    ]

    await session.execute(insert(AuditLog), rows)
    await session.commit()

    logger.info("persisted %d audit events", len(rows))
    return len(rows)

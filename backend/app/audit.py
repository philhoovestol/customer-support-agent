import json
from typing import Any

from sqlmodel import Session, desc, select

from app.database import engine
from app.models import AuditEvent


def record_audit_event(session_id: str, event_type: str, payload: dict[str, Any]) -> None:
    with Session(engine) as session:
        event = AuditEvent(
            session_id=session_id,
            event_type=event_type,
            payload_json=json.dumps(payload, default=str),
        )
        session.add(event)
        session.commit()


def list_audit_events(session_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with Session(engine) as session:
        statement = select(AuditEvent)
        if session_id:
            statement = statement.where(AuditEvent.session_id == session_id)
        statement = statement.order_by(desc(AuditEvent.created_at)).limit(limit)
        events = session.exec(statement).all()

    return [
        {
            "id": event.id,
            "session_id": event.session_id,
            "event_type": event.event_type,
            "payload": json.loads(event.payload_json),
            "created_at": event.created_at.isoformat(),
        }
        for event in events
    ]


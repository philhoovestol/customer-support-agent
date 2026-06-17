import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from typing import Any
from uuid import uuid4

from sqlmodel import Session, desc, func, select

from app.database import engine
from app.models import AuditEvent


@dataclass
class AuditTurnContext:
    turn_id: str
    turn_sequence: int
    event_sequence: int = 0


_active_turn: ContextVar[AuditTurnContext | None] = ContextVar("active_audit_turn", default=None)
_turn_sequence_lock = Lock()
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def new_turn_id() -> str:
    return f"turn-{uuid4().hex[:12]}"


def redact_audit_text(value: str) -> str:
    return EMAIL_RE.sub("[redacted-email]", value)


def _redact_audit_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_audit_text(value)
    if isinstance(value, list):
        return [_redact_audit_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_audit_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_audit_value(item) for key, item in value.items()}
    return value


def next_turn_sequence(session_id: str) -> int:
    # A session can receive concurrent requests, so allocate the ordinal under a
    # process-local lock. The event id still provides the global ordering.
    with _turn_sequence_lock, Session(engine) as session:
        statement = (
            select(func.count(AuditEvent.id))
            .where(AuditEvent.session_id == session_id)
            .where(AuditEvent.event_type == "request_received")
        )
        return int(session.exec(statement).one()) + 1


@contextmanager
def audit_turn(turn_id: str, turn_sequence: int):
    token = _active_turn.set(AuditTurnContext(turn_id=turn_id, turn_sequence=turn_sequence))
    try:
        yield
    finally:
        _active_turn.reset(token)


def record_audit_event(session_id: str, event_type: str, payload: dict[str, Any]) -> None:
    stored_payload = _redact_audit_value(payload)
    turn = _active_turn.get()
    if turn is not None:
        turn.event_sequence += 1
        stored_payload["_turn"] = {
            "turn_id": turn.turn_id,
            "turn_sequence": turn.turn_sequence,
            "event_sequence": turn.event_sequence,
        }

    with Session(engine) as session:
        event = AuditEvent(
            session_id=session_id,
            event_type=event_type,
            payload_json=json.dumps(stored_payload, default=str),
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

    serialized_events = []
    for event in events:
        payload = json.loads(event.payload_json)
        turn = payload.pop("_turn", {})
        serialized_events.append(
            {
                "id": event.id,
                "session_id": event.session_id,
                "turn_id": turn.get("turn_id"),
                "turn_sequence": turn.get("turn_sequence"),
                "sequence": turn.get("event_sequence"),
                "event_type": event.event_type,
                "payload": payload,
                "created_at": event.created_at.isoformat(),
            }
        )
    return serialized_events

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    message: str
    decision: str | None = None
    policy_result: dict[str, Any] | None = None
    audit_events: list[dict[str, Any]]


class CustomerRead(BaseModel):
    id: str
    name: str
    email: str
    loyalty_tier: str
    refund_count_last_12_months: int
    notes: str


class RefundCaseRead(BaseModel):
    id: str
    session_id: str
    customer_id: str | None
    order_id: str | None
    request_signature: str
    decision: str
    status: str
    amount: float
    requested_item_ids: list[str]
    selected_item_ids: list[str]
    reason_codes: list[str]
    policy_citations: list[str]
    customer_message: str
    created_at: str

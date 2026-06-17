from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Customer(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    email: str = Field(index=True, unique=True)
    loyalty_tier: str = "Standard"
    refund_count_last_12_months: int = 0
    notes: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Order(SQLModel, table=True):
    id: str = Field(primary_key=True)
    customer_id: str = Field(foreign_key="customer.id", index=True)
    order_date: date
    delivered_date: Optional[date] = None
    status: str = Field(default="delivered", index=True)
    subtotal: float
    tax: float = 0.0
    total: float


class OrderItem(SQLModel, table=True):
    id: str = Field(primary_key=True)
    order_id: str = Field(foreign_key="order.id", index=True)
    sku: str = Field(index=True)
    name: str
    category: str
    quantity: int = 1
    unit_price: float
    final_sale: bool = False
    opened: bool = False
    damaged: bool = False


class RefundCase(SQLModel, table=True):
    id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    customer_id: Optional[str] = Field(default=None, index=True)
    order_id: Optional[str] = Field(default=None, index=True)
    request_signature: str = Field(default="", index=True)
    decision: str = Field(index=True)
    status: str = Field(index=True)
    amount: float = 0.0
    requested_item_ids_json: str = "[]"
    selected_item_ids_json: str = "[]"
    reason_codes_json: str = "[]"
    policy_citations_json: str = "[]"
    customer_message: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class AuditEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    event_type: str = Field(index=True)
    payload_json: str
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

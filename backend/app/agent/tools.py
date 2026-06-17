import json
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from sqlmodel import Session, select

from app.database import engine
from app.models import Customer, Order, OrderItem
from app.policy import evaluate_refund_from_db


POLICY_PATH = Path(__file__).resolve().parents[1] / "data" / "refund_policy.md"


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str)


def _serialize_item(item: OrderItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "sku": item.sku,
        "name": item.name,
        "category": item.category,
        "quantity": item.quantity,
        "unit_price": item.unit_price,
        "final_sale": item.final_sale,
        "opened": item.opened,
        "damaged": item.damaged,
    }


def _serialize_order(order: Order, items: list[OrderItem]) -> dict[str, Any]:
    return {
        "id": order.id,
        "customer_id": order.customer_id,
        "order_date": order.order_date.isoformat(),
        "delivered_date": order.delivered_date.isoformat() if order.delivered_date else None,
        "status": order.status,
        "subtotal": order.subtotal,
        "tax": order.tax,
        "total": order.total,
        "items": [_serialize_item(item) for item in items],
    }


@tool
def lookup_customer(identifier: str) -> str:
    """Find a customer by customer id or email address."""
    normalized = identifier.strip().lower()
    with Session(engine) as session:
        customer = session.exec(
            select(Customer).where(
                (Customer.id == identifier.strip()) | (Customer.email == normalized)
            )
        ).first()

    if not customer:
        return _json({"type": "customer_lookup", "found": False, "identifier": identifier})

    return _json(
        {
            "type": "customer_lookup",
            "found": True,
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "email": customer.email,
                "loyalty_tier": customer.loyalty_tier,
                "refund_count_last_12_months": customer.refund_count_last_12_months,
                "notes": customer.notes,
            },
        }
    )


@tool
def list_customer_orders(customer_id: str) -> str:
    """List recent orders for a known customer id."""
    with Session(engine) as session:
        orders = session.exec(
            select(Order).where(Order.customer_id == customer_id).order_by(Order.order_date)
        ).all()
        payload = []
        for order in orders:
            items = session.exec(select(OrderItem).where(OrderItem.order_id == order.id)).all()
            payload.append(_serialize_order(order, items))

    return _json({"type": "customer_orders", "customer_id": customer_id, "orders": payload})


@tool
def get_order(order_id: str) -> str:
    """Get order details, line items, and refund-relevant item flags."""
    with Session(engine) as session:
        order = session.get(Order, order_id.strip())
        if order is None:
            return _json({"type": "order_lookup", "found": False, "order_id": order_id})
        items = session.exec(select(OrderItem).where(OrderItem.order_id == order.id)).all()

    return _json({"type": "order_lookup", "found": True, "order": _serialize_order(order, items)})


@tool
def get_refund_policy() -> str:
    """Read the current corporate refund policy."""
    return _json({"type": "refund_policy", "policy": POLICY_PATH.read_text(encoding="utf-8")})


@tool
def evaluate_refund_request(
    order_id: str,
    requested_item_ids: list[str] | None = None,
    reason: str = "",
) -> str:
    """Evaluate a refund request against the deterministic refund policy."""
    result = evaluate_refund_from_db(order_id.strip(), requested_item_ids or [], reason)
    return _json(result)


TOOLS = [
    lookup_customer,
    list_customer_orders,
    get_order,
    get_refund_policy,
    evaluate_refund_request,
]

TOOLS_BY_NAME = {tool_.name: tool_ for tool_ in TOOLS}


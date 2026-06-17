from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Literal

from sqlmodel import Session, select

from app.database import engine
from app.models import Customer, Order, OrderItem, RefundCase


Decision = Literal["approve", "deny", "escalate", "need_more_info"]

NON_REFUNDABLE_CATEGORIES = {"digital", "gift_card"}
HYGIENE_CATEGORIES = {"personal_care", "intimates"}
ITEM_NAME_STOPWORDS = {
    "arrived",
    "changed",
    "course",
    "item",
    "items",
    "order",
    "refund",
    "return",
    "want",
}
OPENED_CONDITION_DISPUTE_PATTERNS = [
    re.compile(r"\b(?:did not|didn't|didnt|never)\s+open(?:ed)?\b"),
    re.compile(r"\b(?:not|isn't|isnt|wasn't|wasnt)\s+open(?:ed)?\b"),
    re.compile(r"\b(?:unopened|sealed|unused)\b"),
]
COMPLETED_REFUND_CASE_STATUSES = {"approved"}


def _base_result(
    decision: Decision,
    reason_codes: list[str],
    customer_message: str,
    policy_citations: list[str],
    eligible_amount: float = 0.0,
    order_id: str | None = None,
    customer_id: str | None = None,
    requested_item_ids: list[str] | None = None,
    selected_item_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "policy_evaluation",
        "decision": decision,
        "reason_codes": reason_codes,
        "customer_message": customer_message,
        "policy_citations": policy_citations,
        "eligible_amount": round(eligible_amount, 2),
        "order_id": order_id,
        "customer_id": customer_id,
        "requested_item_ids": sorted(requested_item_ids or []),
        "selected_item_ids": sorted(selected_item_ids or []),
    }


def evaluate_refund(
    order: Order | None,
    items: list[OrderItem],
    requested_item_ids: list[str] | None,
    reason: str,
    customer: Customer | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    requested_item_ids = requested_item_ids or []
    reason_lower = reason.lower()

    if order is None:
        return _base_result(
            "need_more_info",
            ["ORDER_NOT_FOUND"],
            "I need a valid order number before I can evaluate a refund.",
            ["Refunds can only be evaluated against a verified order."],
            requested_item_ids=requested_item_ids,
        )

    if requested_item_ids:
        requested_set = set(requested_item_ids)
        selected_items = [
            item for item in items if item.id in requested_set or item.sku in requested_set
        ]
    elif len(items) == 1:
        selected_items = items
    else:
        return _base_result(
            "need_more_info",
            ["ITEM_DETAILS_REQUIRED"],
            (
                "I found the order, but I need the specific item from that order "
                "before I can evaluate this refund."
            ),
            ["Refund eligibility is evaluated at the item level."],
            order_id=order.id,
            customer_id=order.customer_id,
        )

    if not selected_items:
        return _base_result(
            "need_more_info",
            ["ITEM_NOT_FOUND"],
            "I found the order, but I need a valid item from that order to evaluate the refund.",
            ["Refund eligibility is evaluated at the item level."],
            order_id=order.id,
            customer_id=order.customer_id,
            requested_item_ids=requested_item_ids,
        )

    eligible_amount = sum(item.unit_price * item.quantity for item in selected_items)
    selected_item_ids = [item.id for item in selected_items]

    if order.status in {"cancelled", "refunded"}:
        return _base_result(
            "deny",
            ["ORDER_ALREADY_CLOSED"],
            "This order is already closed and is not eligible for another refund.",
            ["Cancelled or already-refunded orders cannot receive duplicate refunds."],
            eligible_amount=eligible_amount,
            order_id=order.id,
            customer_id=order.customer_id,
            requested_item_ids=requested_item_ids,
            selected_item_ids=selected_item_ids,
        )

    if order.status != "delivered" or order.delivered_date is None:
        return _base_result(
            "deny",
            ["ORDER_NOT_DELIVERED"],
            "This order has not been delivered yet, so I cannot process it as a refund.",
            ["Refunds are only available for delivered orders."],
            eligible_amount=eligible_amount,
            order_id=order.id,
            customer_id=order.customer_id,
            requested_item_ids=requested_item_ids,
            selected_item_ids=selected_item_ids,
        )

    days_since_delivery = (today - order.delivered_date).days
    if days_since_delivery > 30:
        return _base_result(
            "deny",
            ["OUTSIDE_RETURN_WINDOW"],
            "This order is outside the 30-day refund window.",
            ["Refund requests must be made within 30 days of delivery."],
            eligible_amount=eligible_amount,
            order_id=order.id,
            customer_id=order.customer_id,
            requested_item_ids=requested_item_ids,
            selected_item_ids=selected_item_ids,
        )

    final_sale_items = [item.name for item in selected_items if item.final_sale]
    if final_sale_items:
        return _base_result(
            "deny",
            ["FINAL_SALE_ITEM"],
            "I cannot refund final sale items.",
            ["Final sale items cannot be refunded, exchanged, or credited."],
            eligible_amount=eligible_amount,
            order_id=order.id,
            customer_id=order.customer_id,
            requested_item_ids=requested_item_ids,
            selected_item_ids=selected_item_ids,
        )

    disputed_hygiene_items = [
        item.name
        for item in selected_items
        if item.category in HYGIENE_CATEGORIES
        and item.opened
        and not item.damaged
        and _disputes_opened_condition(reason_lower)
    ]
    if disputed_hygiene_items:
        return _base_result(
            "escalate",
            ["CONTRADICTORY_ITEM_CONDITION"],
            (
                "This request needs human review because the item condition you "
                "provided conflicts with the order data I have."
            ),
            ["Cases with incomplete or contradictory policy data require human escalation."],
            eligible_amount=eligible_amount,
            order_id=order.id,
            customer_id=order.customer_id,
            requested_item_ids=requested_item_ids,
            selected_item_ids=selected_item_ids,
        )

    non_refundable_items = [
        item.name
        for item in selected_items
        if item.category in NON_REFUNDABLE_CATEGORIES
    ]
    if non_refundable_items:
        return _base_result(
            "deny",
            ["NON_REFUNDABLE_CATEGORY"],
            "This item category is not eligible for refunds.",
            ["Digital goods and gift cards are non-refundable once purchased."],
            eligible_amount=eligible_amount,
            order_id=order.id,
            customer_id=order.customer_id,
            requested_item_ids=requested_item_ids,
            selected_item_ids=selected_item_ids,
        )

    hygiene_items = [
        item.name
        for item in selected_items
        if item.category in HYGIENE_CATEGORIES and item.opened and not item.damaged
    ]
    if hygiene_items:
        return _base_result(
            "deny",
            ["OPENED_HYGIENE_ITEM"],
            "Opened hygiene-sensitive items cannot be refunded unless they arrived damaged or defective.",
            ["Opened personal-care and intimate items are refundable only for verified damage or defect."],
            eligible_amount=eligible_amount,
            order_id=order.id,
            customer_id=order.customer_id,
            requested_item_ids=requested_item_ids,
            selected_item_ids=selected_item_ids,
        )

    if eligible_amount > 500:
        return _base_result(
            "escalate",
            ["REFUND_OVER_500"],
            "This refund amount requires human review before it can be approved.",
            ["Refunds over $500 require human escalation."],
            eligible_amount=eligible_amount,
            order_id=order.id,
            customer_id=order.customer_id,
            requested_item_ids=requested_item_ids,
            selected_item_ids=selected_item_ids,
        )

    linked_customer = customer if customer and customer.id == order.customer_id else None
    if linked_customer and linked_customer.refund_count_last_12_months >= 3:
        refund_count = linked_customer.refund_count_last_12_months
        return _base_result(
            "escalate",
            ["HIGH_REFUND_HISTORY"],
            (
                f"This request requires human review because the customer account linked "
                f"to order {order.id} has {refund_count} refunds in the past 12 months."
            ),
            [
                "The customer account linked to the order requires human review when it "
                "has three or more refunds in the past 12 months."
            ],
            eligible_amount=eligible_amount,
            order_id=order.id,
            customer_id=order.customer_id,
            requested_item_ids=requested_item_ids,
            selected_item_ids=selected_item_ids,
        )

    if any(term in reason_lower for term in ["chargeback", "lawsuit", "legal action", "fraud"]):
        return _base_result(
            "escalate",
            ["LEGAL_OR_FRAUD_RISK"],
            "This request requires human review because it mentions a legal, fraud, or chargeback concern.",
            ["Legal, fraud, and chargeback-related cases require human escalation."],
            eligible_amount=eligible_amount,
            order_id=order.id,
            customer_id=order.customer_id,
            requested_item_ids=requested_item_ids,
            selected_item_ids=selected_item_ids,
        )

    return _base_result(
        "approve",
        ["WITHIN_POLICY"],
        "This refund is eligible under the refund policy.",
        ["Delivered, non-final-sale items may be refunded within 30 days when no escalation rule applies."],
        eligible_amount=eligible_amount,
        order_id=order.id,
        customer_id=order.customer_id,
        requested_item_ids=requested_item_ids,
        selected_item_ids=selected_item_ids,
    )


def _disputes_opened_condition(reason_lower: str) -> bool:
    return any(pattern.search(reason_lower) for pattern in OPENED_CONDITION_DISPUTE_PATTERNS)


def _infer_item_ids_from_reason(items: list[OrderItem], reason: str) -> list[str]:
    reason_lower = reason.lower()
    inferred_item_ids: list[str] = []

    for item in items:
        item_words = {
            word
            for word in re.findall(r"[a-z0-9]+", item.name.lower())
            if len(word) >= 4 and word not in ITEM_NAME_STOPWORDS
        }
        if any(re.search(rf"\b{re.escape(word)}\b", reason_lower) for word in item_words):
            inferred_item_ids.append(item.id)

    return inferred_item_ids


def evaluate_refund_from_db(
    order_id: str,
    requested_item_ids: list[str] | None,
    reason: str,
) -> dict[str, Any]:
    with Session(engine) as session:
        order = session.get(Order, order_id)
        if order is None:
            return evaluate_refund(None, [], requested_item_ids, reason)

        items = session.exec(select(OrderItem).where(OrderItem.order_id == order_id)).all()
        customer = session.get(Customer, order.customer_id)
        requested_item_ids = requested_item_ids or _infer_item_ids_from_reason(items, reason)
        result = evaluate_refund(order, items, requested_item_ids, reason, customer=customer)
        return _protect_against_duplicate_refund(session, result)


def protect_against_duplicate_refund(
    result: dict[str, Any],
    *,
    exclude_case_id: str | None = None,
) -> dict[str, Any]:
    """Recheck completed case records immediately before issuing a refund."""
    with Session(engine) as session:
        return _protect_against_duplicate_refund(
            session,
            result,
            exclude_case_id=exclude_case_id,
        )


def _protect_against_duplicate_refund(
    session: Session,
    result: dict[str, Any],
    *,
    exclude_case_id: str | None = None,
) -> dict[str, Any]:
    order_id = result.get("order_id")
    selected_item_ids = {str(item_id) for item_id in result.get("selected_item_ids", [])}
    if not order_id or not selected_item_ids:
        return result

    statement = (
        select(RefundCase)
        .where(RefundCase.order_id == order_id)
        .where(RefundCase.status.in_(COMPLETED_REFUND_CASE_STATUSES))
    )
    if exclude_case_id:
        statement = statement.where(RefundCase.id != exclude_case_id)

    refunded_item_ids: set[str] = set()
    for refund_case in session.exec(statement).all():
        try:
            case_item_ids = json.loads(refund_case.selected_item_ids_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(case_item_ids, list):
            refunded_item_ids.update(str(item_id) for item_id in case_item_ids)

    duplicate_item_ids = sorted(selected_item_ids & refunded_item_ids)
    if not duplicate_item_ids:
        return result

    item_text = ", ".join(duplicate_item_ids)
    return {
        **result,
        "decision": "deny",
        "reason_codes": ["ITEM_ALREADY_REFUNDED"],
        "customer_message": (
            f"I cannot issue another refund for {item_text} because "
            "a completed refund case already records it as refunded."
        ),
        "policy_citations": [
            "An item recorded in a completed refund case cannot be refunded again."
        ],
        "duplicate_item_ids": duplicate_item_ids,
    }

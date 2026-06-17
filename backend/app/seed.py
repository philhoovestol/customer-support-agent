import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.models import Customer, Order, OrderItem, RefundCase


DATA_PATH = Path(__file__).resolve().parent / "data" / "seed_customers.json"


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def _validate_refund_history(payload: dict[str, Any]) -> None:
    seeded_case_counts = Counter(
        case["customer_id"]
        for case in payload.get("refund_cases", [])
        if case.get("decision") == "approve" and case.get("status") == "approved"
    )
    configured_counts = {
        customer["id"]: customer.get("refund_count_last_12_months", 0)
        for customer in payload["customers"]
    }

    mismatches = {
        customer_id: {
            "refund_count_last_12_months": configured_count,
            "completed_seed_cases": seeded_case_counts[customer_id],
        }
        for customer_id, configured_count in configured_counts.items()
        if configured_count != seeded_case_counts[customer_id]
    }
    unknown_customer_ids = sorted(set(seeded_case_counts) - set(configured_counts))
    if mismatches or unknown_customer_ids:
        raise ValueError(
            "Seeded customer refund counts must match completed historical refund cases: "
            f"mismatches={mismatches}, unknown_customer_ids={unknown_customer_ids}"
        )


def seed_database(session: Session) -> None:
    existing_customer = session.exec(select(Customer).limit(1)).first()
    if existing_customer:
        return

    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    _validate_refund_history(payload)

    for customer_payload in payload["customers"]:
        orders_payload = customer_payload.pop("orders")
        customer = Customer(**customer_payload)
        session.add(customer)

        for order_payload in orders_payload:
            items_payload = order_payload.pop("items")
            order_payload["order_date"] = _parse_date(order_payload["order_date"])
            order_payload["delivered_date"] = _parse_date(order_payload.get("delivered_date"))
            order = Order(
                **order_payload,
            )
            session.add(order)

            for item_payload in items_payload:
                session.add(OrderItem(**item_payload))

    for case_payload in payload.get("refund_cases", []):
        case_data = dict(case_payload)
        case_data["requested_item_ids_json"] = json.dumps(
            case_data.pop("requested_item_ids", [])
        )
        case_data["selected_item_ids_json"] = json.dumps(
            case_data.pop("selected_item_ids", [])
        )
        case_data["reason_codes_json"] = json.dumps(case_data.pop("reason_codes", []))
        case_data["policy_citations_json"] = json.dumps(
            case_data.pop("policy_citations", [])
        )
        case_data["created_at"] = datetime.fromisoformat(case_data["created_at"])
        session.add(RefundCase(**case_data))

    session.commit()

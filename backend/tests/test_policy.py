import json
from collections import Counter
from datetime import date, timedelta

from sqlmodel import Session, SQLModel, create_engine, select

from app import policy as policy_module
from app.models import Customer, Order, OrderItem, RefundCase
from app.policy import evaluate_refund, evaluate_refund_from_db, protect_against_duplicate_refund


def make_order(
    *,
    total: float = 100.0,
    delivered_days_ago: int = 5,
    status: str = "delivered",
) -> Order:
    today = date(2026, 6, 16)
    return Order(
        id="ORD-TEST",
        customer_id="CUST-TEST",
        order_date=today - timedelta(days=delivered_days_ago + 3),
        delivered_date=today - timedelta(days=delivered_days_ago) if status == "delivered" else None,
        status=status,
        subtotal=total,
        tax=0.0,
        total=total,
    )


def make_item(
    *,
    item_id: str = "ITEM-TEST",
    unit_price: float = 100.0,
    final_sale: bool = False,
    category: str = "apparel",
    opened: bool = True,
    damaged: bool = False,
) -> OrderItem:
    return OrderItem(
        id=item_id,
        order_id="ORD-TEST",
        sku="SKU-TEST",
        name="Test Item",
        category=category,
        quantity=1,
        unit_price=unit_price,
        final_sale=final_sale,
        opened=opened,
        damaged=damaged,
    )


def test_final_sale_item_is_denied():
    result = evaluate_refund(
        make_order(),
        [make_item(final_sale=True)],
        ["ITEM-TEST"],
        "Please make an exception.",
        today=date(2026, 6, 16),
    )

    assert result["decision"] == "deny"
    assert "FINAL_SALE_ITEM" in result["reason_codes"]


def test_policy_evidence_marks_winning_and_skipped_rules():
    result = evaluate_refund(
        make_order(),
        [make_item(final_sale=True)],
        ["ITEM-TEST"],
        "Please make an exception.",
        today=date(2026, 6, 16),
    )

    checks = {check["rule"]: check for check in result["policy_checks"]}
    assert result["policy_version"] == "refund-policy-v1"
    assert result["winning_rule"] == "final_sale_exclusion"
    assert checks["verified_order"]["status"] == "passed"
    assert checks["final_sale_exclusion"]["status"] == "failed"
    assert checks["automatic_refund_limit"]["status"] == "not_applicable"
    assert checks["automatic_refund_limit"]["detail"] == "Skipped after the decisive rule."


def test_refund_over_500_is_escalated():
    result = evaluate_refund(
        make_order(total=649.0),
        [make_item(unit_price=649.0)],
        ["ITEM-TEST"],
        "It does not fit.",
        today=date(2026, 6, 16),
    )

    assert result["decision"] == "escalate"
    assert "REFUND_OVER_500" in result["reason_codes"]


def test_standard_eligible_refund_is_approved():
    result = evaluate_refund(
        make_order(total=120.0),
        [make_item(unit_price=120.0)],
        ["ITEM-TEST"],
        "It is not what I expected.",
        customer=Customer(id="CUST-TEST", name="Test User", email="test@example.com"),
        today=date(2026, 6, 16),
    )

    assert result["decision"] == "approve"
    assert result["eligible_amount"] == 120.0


def test_refund_history_uses_customer_account_linked_to_order():
    linked_customer = Customer(
        id="CUST-TEST",
        name="Linked Customer",
        email="linked@example.com",
        refund_count_last_12_months=3,
    )
    result = evaluate_refund(
        make_order(),
        [make_item()],
        ["ITEM-TEST"],
        "It is not what I expected.",
        customer=linked_customer,
        today=date(2026, 6, 16),
    )

    assert result["decision"] == "escalate"
    assert result["reason_codes"] == ["HIGH_REFUND_HISTORY"]
    assert result["customer_id"] == linked_customer.id
    assert "customer account linked to order ORD-TEST" in result["customer_message"]
    assert "3 refunds in the past 12 months" in result["customer_message"]


def test_unrelated_customer_refund_history_does_not_affect_order():
    unrelated_customer = Customer(
        id="CUST-OTHER",
        name="Unrelated Customer",
        email="unrelated@example.com",
        refund_count_last_12_months=3,
    )
    result = evaluate_refund(
        make_order(),
        [make_item()],
        ["ITEM-TEST"],
        "It is not what I expected.",
        customer=unrelated_customer,
        today=date(2026, 6, 16),
    )

    assert result["decision"] == "approve"
    assert result["reason_codes"] == ["WITHIN_POLICY"]


def test_seeded_refund_counts_match_completed_history_cases():
    with Session(policy_module.engine) as session:
        customers = session.exec(select(Customer)).all()
        completed_cases = session.exec(
            select(RefundCase).where(RefundCase.status == "approved")
        ).all()

    case_counts = Counter(case.customer_id for case in completed_cases)
    assert {
        customer.id: customer.refund_count_last_12_months for customer in customers
    } == {customer.id: case_counts[customer.id] for customer in customers}


def test_old_delivered_order_is_denied():
    result = evaluate_refund(
        make_order(total=120.0, delivered_days_ago=40),
        [make_item(unit_price=120.0)],
        ["ITEM-TEST"],
        "I changed my mind.",
        today=date(2026, 6, 16),
    )

    assert result["decision"] == "deny"
    assert "OUTSIDE_RETURN_WINDOW" in result["reason_codes"]


def test_hygiene_item_opened_condition_dispute_is_escalated():
    result = evaluate_refund(
        make_order(total=42.0),
        [make_item(unit_price=42.0, category="personal_care", opened=True, damaged=False)],
        ["ITEM-TEST"],
        "I didn't open it.",
        today=date(2026, 6, 16),
    )

    assert result["decision"] == "escalate"
    assert "CONTRADICTORY_ITEM_CONDITION" in result["reason_codes"]


def test_completed_case_registers_item_as_refunded_and_final_recheck_blocks_it(
    tmp_path, monkeypatch
):
    test_engine = create_engine(f"sqlite:///{tmp_path / 'duplicate-refund.db'}")
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(policy_module, "engine", test_engine)

    customer = Customer(id="CUST-TEST", name="Test User", email="test@example.com")
    order = make_order()
    item = make_item()
    order_id = order.id
    item_id = item.id
    waiting_case_id = "REF-WAITING"
    waiting_case = RefundCase(
        id=waiting_case_id,
        session_id="SESSION-ONE",
        customer_id=customer.id,
        order_id=order.id,
        request_signature=f"{customer.id}|{order.id}|{item.id}",
        decision="approve",
        status="awaiting_customer_confirmation",
        amount=item.unit_price,
        selected_item_ids_json=json.dumps([item.id]),
    )
    with Session(test_engine) as session:
        session.add(customer)
        session.add(order)
        session.add(item)
        session.add(waiting_case)
        session.commit()

    initial_result = evaluate_refund_from_db(order_id, [item_id], "It does not fit.")
    assert initial_result["decision"] == "approve"

    with Session(test_engine) as session:
        registered_case = session.get(RefundCase, waiting_case_id)
        assert registered_case is not None
        registered_case.status = "approved"
        session.add(registered_case)
        session.commit()

    reevaluated_result = evaluate_refund_from_db(order_id, [item_id], "Please refund it again.")
    final_recheck_result = protect_against_duplicate_refund(initial_result)

    assert reevaluated_result["decision"] == "deny"
    assert reevaluated_result["reason_codes"] == ["ITEM_ALREADY_REFUNDED"]
    assert reevaluated_result["duplicate_item_ids"] == [item_id]
    assert final_recheck_result["decision"] == "deny"
    assert final_recheck_result["duplicate_item_ids"] == [item_id]


def test_completed_case_does_not_block_an_unrelated_item_on_the_same_order(
    tmp_path, monkeypatch
):
    test_engine = create_engine(f"sqlite:///{tmp_path / 'partial-refund.db'}")
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(policy_module, "engine", test_engine)

    customer = Customer(id="CUST-TEST", name="Test User", email="test@example.com")
    order = make_order(total=150.0)
    refunded_item = make_item(item_id="ITEM-REFUNDED", unit_price=50.0)
    new_item = make_item(item_id="ITEM-NEW", unit_price=100.0)
    order_id = order.id
    new_item_id = new_item.id
    completed_case = RefundCase(
        id="REF-COMPLETED",
        session_id="SESSION-ONE",
        customer_id=customer.id,
        order_id=order.id,
        request_signature=f"{customer.id}|{order.id}|{refunded_item.id}",
        decision="approve",
        status="approved",
        amount=refunded_item.unit_price,
        selected_item_ids_json=json.dumps([refunded_item.id]),
    )
    with Session(test_engine) as session:
        session.add(customer)
        session.add(order)
        session.add(refunded_item)
        session.add(new_item)
        session.add(completed_case)
        session.commit()

    result = evaluate_refund_from_db(order_id, [new_item_id], "The other item does not fit.")

    assert result["decision"] == "approve"
    assert result["selected_item_ids"] == [new_item_id]

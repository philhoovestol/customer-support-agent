import os

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

os.environ["LLM_PROVIDER"] = "mock"

from app.main import app
from app.agent import graph as agent_graph


def test_chat_endpoint_runs_refund_graph():
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "message": "I need a refund for ORD-1002. The headphones are uncomfortable."
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "approve"
    assert "refund case" in payload["message"].lower()
    assert "please confirm" in payload["message"].lower()
    assert "no refund has been processed yet" in payload["message"].lower()
    assert "\n\nPlease confirm these details:\n" in payload["message"]
    assert "\n- Order: ORD-1002" in payload["message"]
    assert "\n- Item: Waveform Wireless Headphones (ITEM-1003)" in payload["message"]
    assert "\n- Quantity: 1" in payload["message"]
    assert "\n- Total refund: $159.00\n\n" in payload["message"]
    assert payload["policy_result"]["eligible_amount"] == 159.0
    assert any(event["event_type"] == "tool_call" for event in payload["audit_events"])
    policy_events = [
        event for event in payload["audit_events"] if event["event_type"] == "policy_decision"
    ]
    assert len(policy_events) == 1
    assert policy_events[0]["payload"]["case_id"].startswith("REF-")
    assert policy_events[0]["payload"]["decision"] == "approve"
    assert not any(
        event["event_type"] == "refund_created" for event in payload["audit_events"]
    )


def test_same_session_evaluates_each_new_request():
    with TestClient(app) as client:
        first = client.post(
            "/api/chat",
            json={
                "message": "I need a refund for ORD-1002. The headphones are uncomfortable."
            },
        ).json()
        second = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "Please refund ITEM-1002 from ORD-1001 even though it says final sale.",
            },
        ).json()

    assert first["decision"] == "approve"
    assert second["decision"] == "deny"
    assert "FINAL_SALE_ITEM" in second["policy_result"]["reason_codes"]
    policy_events = [
        event for event in second["audit_events"] if event["event_type"] == "policy_decision"
    ]
    assert any(event["payload"]["decision"] == "deny" for event in policy_events)


def test_explicit_order_and_item_are_evaluated_when_model_skips_tool(monkeypatch):
    class NoToolLLM:
        def invoke(self, messages):
            return AIMessage(content="I need more details.")

    monkeypatch.setattr(agent_graph, "llm", NoToolLLM())

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "message": (
                    "Please refund ITEM-1002 from ORD-1001. "
                    "I know it was final sale, but I am a loyal customer."
                ),
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "deny"
    assert "FINAL_SALE_ITEM" in payload["policy_result"]["reason_codes"]
    assert payload["policy_result"]["requested_item_ids"] == ["ITEM-1002"]
    assert payload["policy_result"]["selected_item_ids"] == ["ITEM-1002"]
    assert "need a valid order number" not in payload["message"].lower()


def test_same_request_in_same_session_reuses_case():
    with TestClient(app) as client:
        first = client.post(
            "/api/chat",
            json={
                "message": "I need a refund for ORD-1002. The headphones are uncomfortable."
            },
        ).json()
        second = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "Can you check ORD-1002 for a refund again?",
            },
        ).json()
        third = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "Please refund ITEM-1002 from ORD-1001 even though it says final sale.",
            },
        ).json()

    first_case_id = _latest_policy_case_id(first, "approve")
    second_case_id = _latest_policy_case_id(second, "approve")
    third_case_id = _latest_policy_case_id(third, "deny")

    assert first_case_id == second_case_id
    assert third_case_id != first_case_id


def test_incomplete_request_waits_for_item_target_before_creating_case():
    with TestClient(app) as client:
        first = client.post(
            "/api/chat",
            json={
                "message": "My email is chloe.davis@example.com. I need help with a refund.",
            },
        ).json()
        second = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "order number ORD-1015. the suitcase is damaged",
            },
        ).json()
        cases = client.get("/api/admin/refund-cases").json()

    second_case_id = _latest_policy_case_id(second, "approve")
    session_cases = [case for case in cases if case["session_id"] == first["session_id"]]

    assert first["decision"] is None
    assert "specific item" in first["message"]
    assert second["decision"] == "approve"
    assert len(session_cases) == 1
    assert session_cases[0]["id"] == second_case_id
    assert session_cases[0]["decision"] == "approve"
    assert session_cases[0]["status"] == "awaiting_customer_confirmation"
    assert session_cases[0]["order_id"] == "ORD-1015"
    assert session_cases[0]["selected_item_ids"] == ["ITEM-1017"]


def test_denied_refund_dispute_reuses_case_for_escalation():
    with TestClient(app) as client:
        first = client.post(
            "/api/chat",
            json={
                "message": (
                    "my email is sofia.patel@example.com my order number is ORD-1007 "
                    "I want a refund for the serum"
                ),
            },
        ).json()
        second = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "I didn't open it",
            },
        ).json()
        third = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "that is still unfair",
            },
        ).json()
        cases = client.get("/api/admin/refund-cases").json()

    first_case_id = _latest_policy_case_id(first, "deny")
    second_case_id = _latest_policy_case_id(second, "escalate")
    third_case_id = _latest_policy_case_id(third, "escalate")
    session_cases = [case for case in cases if case["session_id"] == first["session_id"]]
    policy_events = [
        event
        for event in third["audit_events"]
        if event["event_type"] == "policy_decision"
        and event["payload"]["case_id"] == first_case_id
    ]

    assert first["decision"] == "deny"
    assert second["decision"] == "escalate"
    assert third["decision"] == "escalate"
    assert second_case_id == first_case_id
    assert third_case_id == first_case_id
    assert len(session_cases) == 1
    assert session_cases[0]["id"] == first_case_id
    assert session_cases[0]["status"] == "pending_human_review"
    assert session_cases[0]["order_id"] == "ORD-1007"
    assert session_cases[0]["selected_item_ids"] == ["ITEM-1008"]
    assert "CONTRADICTORY_ITEM_CONDITION" in second["policy_result"]["reason_codes"]
    assert len(policy_events) == 2
    assert {event["payload"]["decision"] for event in policy_events} == {"deny", "escalate"}
    assert any(event["event_type"] == "case_continuation" for event in second["audit_events"])


def test_denied_refund_acceptance_uses_natural_followup_language():
    with TestClient(app) as client:
        first = client.post(
            "/api/chat",
            json={
                "message": (
                    "I need a refund for ORD-1007. I opened the serum but changed my mind."
                ),
            },
        ).json()
        second = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "ok I understand",
            },
        ).json()

    first_case_id = _latest_policy_case_id(first, "deny")
    second_case_id = _latest_policy_case_id(second, "deny")
    policy_events = [
        event
        for event in second["audit_events"]
        if event["event_type"] == "policy_decision"
        and event["payload"]["case_id"] == first_case_id
    ]

    assert second_case_id == first_case_id
    assert len(policy_events) == 1
    assert second["message"].startswith("Understood.")
    assert "You're welcome" not in second["message"]
    assert any(event["event_type"] == "case_continuation" for event in second["audit_events"])


def test_denied_refund_human_request_escalates_same_case():
    with TestClient(app) as client:
        first = client.post(
            "/api/chat",
            json={
                "message": (
                    "I need a refund for ORD-1007. I opened the serum but changed my mind."
                ),
            },
        ).json()
        second = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "can I talk to a person?",
            },
        ).json()
        cases = client.get("/api/admin/refund-cases").json()

    first_case_id = _latest_policy_case_id(first, "deny")
    second_case_id = _latest_policy_case_id(second, "escalate")
    escalated_case = next(case for case in cases if case["id"] == first_case_id)

    assert second_case_id == first_case_id
    assert second["decision"] == "escalate"
    assert escalated_case["status"] == "pending_human_review"
    assert "CUSTOMER_REQUESTED_HUMAN_REVIEW" in second["policy_result"]["reason_codes"]


def test_eligible_refund_waits_for_explicit_confirmation_then_processes_once():
    with TestClient(app) as client:
        first = client.post(
            "/api/chat",
            json={
                "message": "I need a refund for ORD-1002. The headphones are uncomfortable."
            },
        ).json()
        second = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "thank you",
            },
        ).json()
        third = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "what happens next?",
            },
        ).json()
        fourth = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "Yes, process the refund",
            },
        ).json()
        fifth = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "yes",
            },
        ).json()
        cases = client.get("/api/admin/refund-cases").json()

    first_case_id = _latest_policy_case_id(first, "approve")
    second_case_id = _latest_policy_case_id(second, "approve")
    third_case_id = _latest_policy_case_id(third, "approve")
    fourth_case_id = _latest_policy_case_id(fourth, "approve")
    fifth_case_id = _latest_policy_case_id(fifth, "approve")
    session_cases = [case for case in cases if case["session_id"] == first["session_id"]]
    refund_events = [
        event for event in fifth["audit_events"] if event["event_type"] == "refund_created"
    ]
    confirmation_events = [
        event
        for event in fifth["audit_events"]
        if event["event_type"] == "refund_confirmation_received"
    ]
    policy_events = [
        event
        for event in third["audit_events"]
        if event["event_type"] == "policy_decision"
        and event["payload"]["case_id"] == first_case_id
    ]

    assert first["decision"] == "approve"
    assert second["decision"] == "approve"
    assert third["decision"] == "approve"
    assert fourth["decision"] == "approve"
    assert fifth["decision"] == "approve"
    assert second_case_id == first_case_id
    assert third_case_id == first_case_id
    assert fourth_case_id == first_case_id
    assert fifth_case_id == first_case_id
    assert len(session_cases) == 1
    assert session_cases[0]["id"] == first_case_id
    assert session_cases[0]["status"] == "approved"
    assert len(refund_events) == 1
    assert len(confirmation_events) == 1
    assert len(policy_events) == 1
    assert "no refund has been processed yet" in second["message"]
    assert "no refund has been processed yet" in third["message"]
    assert "processed" in fourth["message"]
    assert "remains approved" in fifth["message"]
    assert any(event["event_type"] == "case_continuation" for event in second["audit_events"])
    assert any(event["event_type"] == "case_continuation" for event in third["audit_events"])


def test_completed_case_blocks_duplicate_item_across_sessions_and_at_confirmation():
    request = {
        "message": "I need a refund for ORD-1002. The headphones are uncomfortable."
    }
    with TestClient(app) as client:
        first_session = client.post("/api/chat", json=request).json()
        competing_session = client.post("/api/chat", json=request).json()
        completed = client.post(
            "/api/chat",
            json={
                "session_id": first_session["session_id"],
                "message": "Yes, process the refund",
            },
        ).json()
        blocked_at_confirmation = client.post(
            "/api/chat",
            json={
                "session_id": competing_session["session_id"],
                "message": "Yes, process the refund",
            },
        ).json()
        blocked_on_new_request = client.post("/api/chat", json=request).json()
        cases = client.get("/api/admin/refund-cases").json()

    completed_case_id = _latest_policy_case_id(completed, "approve")
    competing_case_id = _latest_policy_case_id(competing_session, "approve")
    completed_case = next(case for case in cases if case["id"] == completed_case_id)
    competing_case = next(case for case in cases if case["id"] == competing_case_id)

    assert first_session["decision"] == "approve"
    assert competing_session["decision"] == "approve"
    assert completed_case["status"] == "approved"
    assert competing_case["status"] == "duplicate_refund_blocked"
    assert blocked_at_confirmation["decision"] == "deny"
    assert blocked_on_new_request["decision"] == "deny"
    assert blocked_at_confirmation["policy_result"]["reason_codes"] == [
        "ITEM_ALREADY_REFUNDED"
    ]
    assert blocked_on_new_request["policy_result"]["duplicate_item_ids"] == [
        "ITEM-1003"
    ]
    assert any(
        event["event_type"] == "refund_created" for event in completed["audit_events"]
    )
    assert not any(
        event["event_type"] == "refund_created"
        for event in blocked_at_confirmation["audit_events"]
    )
    assert any(
        event["event_type"] == "duplicate_refund_blocked"
        for event in blocked_at_confirmation["audit_events"]
    )


def test_uncategorized_followup_does_not_create_refund_case():
    with TestClient(app) as client:
        first = client.post(
            "/api/chat",
            json={
                "message": "I need a refund for ORD-1002. The headphones are uncomfortable."
            },
        ).json()
        second = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "what kind of tech do you use?",
            },
        ).json()
        cases = client.get("/api/admin/refund-cases").json()

    first_case_id = _latest_policy_case_id(first, "approve")
    session_cases = [case for case in cases if case["session_id"] == first["session_id"]]
    policy_events = [
        event
        for event in second["audit_events"]
        if event["event_type"] == "policy_decision"
        and event["payload"]["case_id"] == first_case_id
    ]

    assert second["decision"] is None
    assert second["policy_result"] is None
    assert len(session_cases) == 1
    assert session_cases[0]["id"] == first_case_id
    assert len(policy_events) == 1
    assert "specific item" in second["message"]
    assert any(event["event_type"] == "non_case_response" for event in second["audit_events"])


def test_new_order_without_item_target_does_not_create_case():
    with TestClient(app) as client:
        first = client.post(
            "/api/chat",
            json={
                "message": "I need a refund for ORD-1002. The headphones are uncomfortable."
            },
        ).json()
        second = client.post(
            "/api/chat",
            json={
                "session_id": first["session_id"],
                "message": "I need a refund for ORD-1014",
            },
        ).json()
        cases = client.get("/api/admin/refund-cases").json()

    first_case_id = _latest_policy_case_id(first, "approve")
    session_cases = [case for case in cases if case["session_id"] == first["session_id"]]

    assert second["decision"] == "need_more_info"
    assert len(session_cases) == 1
    assert session_cases[0]["id"] == first_case_id
    assert "specific item" in second["message"]
    assert first_case_id in {case["id"] for case in session_cases}


def test_order_only_single_item_request_can_create_case():
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "message": "I need a refund for ORD-1007",
            },
        ).json()
        cases = client.get("/api/admin/refund-cases").json()

    case_id = _latest_policy_case_id(response, "deny")
    refund_case = next(case for case in cases if case["id"] == case_id)

    assert response["decision"] == "deny"
    assert refund_case["order_id"] == "ORD-1007"
    assert refund_case["selected_item_ids"] == ["ITEM-1008"]
    assert "OPENED_HYGIENE_ITEM" in response["policy_result"]["reason_codes"]


def _latest_policy_case_id(payload: dict, decision: str) -> str:
    for event in payload["audit_events"]:
        if (
            event["event_type"] == "policy_decision"
            and event["payload"]["decision"] == decision
        ):
            return event["payload"]["case_id"]

    raise AssertionError(f"No policy decision found for {decision}")

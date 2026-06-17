from uuid import uuid4

from langchain_core.messages import HumanMessage

from app.agent.graph import describe_request, refund_graph
from app.audit import (
    audit_turn,
    list_audit_events,
    new_turn_id,
    next_turn_sequence,
    record_audit_event,
)


class SupportAgentService:
    def run(self, message: str, session_id: str | None = None) -> dict:
        session_id = session_id or f"session-{uuid4().hex[:12]}"
        turn_id = new_turn_id()
        turn_sequence = next_turn_sequence(session_id)
        with audit_turn(turn_id, turn_sequence):
            record_audit_event(session_id, "request_received", describe_request(message))
            try:
                result = refund_graph.invoke(
                    {
                        "messages": [HumanMessage(content=message)],
                        "session_id": session_id,
                        "order_id": None,
                        "requested_item_ids": [],
                        "policy_result": None,
                        "outcome_case_id": None,
                        "case_followup": False,
                        "case_followup_intent": None,
                        "case_followup_previous_decision": None,
                        "case_followup_previous_status": None,
                        "final_response": None,
                    },
                    {"configurable": {"thread_id": session_id}},
                )
            except Exception as exc:
                record_audit_event(
                    session_id,
                    "turn_completed",
                    {"status": "error", "error_type": type(exc).__name__},
                )
                raise

            record_audit_event(
                session_id,
                "turn_completed",
                {
                    "status": "completed",
                    "decision": (result.get("policy_result") or {}).get("decision"),
                    "case_id": result.get("outcome_case_id"),
                    "customer_id": (result.get("policy_result") or {}).get("customer_id"),
                    "order_id": (result.get("policy_result") or {}).get("order_id"),
                    "response": result.get("final_response"),
                },
            )

        return {
            "session_id": session_id,
            "message": result.get("final_response")
            or "I need a bit more information before I can help with this refund.",
            "decision": (result.get("policy_result") or {}).get("decision"),
            "policy_result": result.get("policy_result"),
            "audit_events": list_audit_events(session_id=session_id, limit=80),
        }


support_agent = SupportAgentService()

from uuid import uuid4

from langchain_core.messages import HumanMessage

from app.agent.graph import refund_graph
from app.audit import list_audit_events


class SupportAgentService:
    def run(self, message: str, session_id: str | None = None) -> dict:
        session_id = session_id or f"session-{uuid4().hex[:12]}"
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

        return {
            "session_id": session_id,
            "message": result.get("final_response")
            or "I need a bit more information before I can help with this refund.",
            "decision": (result.get("policy_result") or {}).get("decision"),
            "policy_result": result.get("policy_result"),
            "audit_events": list_audit_events(session_id=session_id, limit=80),
        }


support_agent = SupportAgentService()

import json
import re
from threading import Lock
from typing import Annotated, Any, Literal, TypedDict
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy import or_
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from sqlmodel import Session, desc, select

from app.agent.llm import get_llm
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import TOOLS, TOOLS_BY_NAME
from app.audit import record_audit_event, redact_audit_text
from app.database import engine
from app.models import OrderItem, RefundCase
from app.policy import (
    REFUND_POLICY_VERSION,
    evaluate_refund_from_db,
    protect_against_duplicate_refund,
)


ORDER_RE = re.compile(r"\bORD-\d{4,}\b", re.IGNORECASE)
ITEM_RE = re.compile(r"\bITEM-\d{4,}\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
REFUND_CREATION_LOCK = Lock()
NEW_REQUEST_HINTS = (
    "another refund",
    "another order",
    "different order",
    "new order",
    "separate order",
    "separate refund",
)
REFUND_INTENT_HINTS = (
    "credit",
    "exchange",
    "refund",
    "replace",
    "return",
)
GRATITUDE_HINTS = (
    "appreciate",
    "awesome",
    "perfect",
    "thank",
    "thx",
    "you rock",
)
ACCEPTANCE_HINTS = (
    "alright",
    "fine",
    "got it",
    "i understand",
    "makes sense",
    "ok",
    "okay",
    "understand",
    "yeah",
    "yep",
    "yes",
)
REFUND_CONFIRMATION_APPROVAL_PATTERNS = (
    re.compile(r"^\s*(?:yes|yep|yeah|confirmed?|approved?)(?:\s+please)?[.!]?\s*$"),
    re.compile(r"\b(?:go ahead|please proceed|process (?:it|the refund)|issue (?:it|the refund))\b"),
    re.compile(r"\b(?:details|item details|refund details) (?:are|look) (?:correct|good)\b"),
    re.compile(r"\bi approve\b"),
)
REFUND_CONFIRMATION_REJECTION_PATTERNS = (
    re.compile(r"\b(?:no|cancel|stop)\b"),
    re.compile(r"\b(?:do not|don't|dont|not ready|not correct|not right|wrong)\b"),
)
INFORMATION_FOLLOWUP_HINTS = (
    "case",
    "confirmation",
    "details",
    "follow up",
    "follow-up",
    "how long",
    "next",
    "receipt",
    "status",
    "timeline",
    "what happens",
    "when",
)
HUMAN_REQUEST_PATTERNS = (
    re.compile(
        r"\b(?:talk|speak|chat|connect|transfer|escalate|raise|route|refer)\b.*"
        r"\b(?:human|person|representative|agent|manager|supervisor|someone)\b"
    ),
    re.compile(
        r"\b(?:human|person|representative|manager|supervisor)\b.*"
        r"\b(?:review|help|support)\b"
    ),
)
CASE_FOLLOWUP_HINTS = (
    "appeal",
    "but",
    "dispute",
    "did not",
    "didn't",
    "didnt",
    "doesn't seem right",
    "doesnt seem right",
    "exception",
    "incorrect",
    "never",
    "not ok",
    "not okay",
    "not right",
    "not true",
    "reconsider",
    "refund anyway",
    "sealed",
    "still want",
    "unfair",
    "unopened",
    "unused",
    "wrong",
)
UNSAFE_CONVERSATIONAL_REPLY_PATTERNS = (
    re.compile(r"\b(?:approv(?:e|ed|al)|den(?:y|ied)|eligib(?:le|ility))\b"),
    re.compile(
        r"\b(?:authoriz(?:e|ed|ation)|escalat(?:e|ed|ion)|exception|override|pending|"
        r"process(?:ed|ing)?|issu(?:e|ed|ing))\b"
    ),
    re.compile(r"\b(?:your|the|this)\s+(?:case|refund|request)\b"),
    re.compile(r"\bcase\s+[A-Z]{3}-[A-Z0-9]+\b", re.IGNORECASE),
    re.compile(r"\b(?:ITEM|ORD)-\d+\b", re.IGNORECASE),
    re.compile(r"\$\s*\d"),
)
SAFE_MODEL_FOLLOWUP_HINTS = {
    "gratitude": (
        "anytime",
        "glad to help",
        "happy to help",
        "my pleasure",
        "welcome",
    ),
    "acceptance": (
        "got it",
        "happy to help",
        "here if",
        "let me know",
        "reach out",
        "understood",
    ),
}


class RefundAgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    session_id: str
    customer_id: str | None
    order_id: str | None
    requested_item_ids: list[str]
    policy_result: dict[str, Any] | None
    outcome_case_id: str | None
    case_followup: bool
    case_followup_intent: str | None
    case_followup_previous_decision: str | None
    case_followup_previous_status: str | None
    final_response: str | None


llm = get_llm(TOOLS)


def describe_request(message: str) -> dict[str, Any]:
    normalized = message.strip().lower()
    order_ids = sorted({match.upper() for match in ORDER_RE.findall(message)})
    item_ids = sorted({match.upper() for match in ITEM_RE.findall(message)})
    email_present = EMAIL_RE.search(message) is not None

    if any(pattern.search(normalized) for pattern in HUMAN_REQUEST_PATTERNS):
        intent = "human_review"
    elif _is_refund_confirmation_approval(normalized):
        intent = "refund_confirmation"
    elif any(hint in normalized for hint in CASE_FOLLOWUP_HINTS):
        intent = "case_dispute"
    elif order_ids or item_ids or _looks_like_refund_intent(normalized):
        intent = "refund_request"
    elif any(hint in normalized for hint in GRATITUDE_HINTS):
        intent = "gratitude"
    elif any(hint in normalized for hint in ACCEPTANCE_HINTS):
        intent = "acceptance"
    elif any(hint in normalized for hint in INFORMATION_FOLLOWUP_HINTS):
        intent = "case_information"
    elif email_present:
        intent = "account_lookup"
    else:
        intent = "other"

    return {
        "message": redact_audit_text(message),
        "detected_intent": intent,
        "entities": {
            "order_ids": order_ids,
            "item_ids": item_ids,
            "email_present": email_present,
        },
    }


def _safe_json(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {"raw": value}
    if isinstance(loaded, dict):
        return loaded
    return {"value": loaded}


def _latest_ai_message(state: RefundAgentState) -> AIMessage:
    for message in reversed(state["messages"]):
        if isinstance(message, AIMessage):
            return message
    raise ValueError("No AI message found in graph state.")


def call_model(state: RefundAgentState) -> dict[str, Any]:
    session_id = state["session_id"]
    response = llm.invoke([SystemMessage(content=SYSTEM_PROMPT), *state["messages"]])
    tool_names = [tool_call["name"] for tool_call in (response.tool_calls or [])]
    record_audit_event(
        session_id,
        "llm_step",
        {
            "tool_calls_requested": tool_names,
            "content_preview": response.content[:300] if isinstance(response.content, str) else "",
        },
    )
    return {"messages": [response]}


def run_tools(state: RefundAgentState) -> dict[str, Any]:
    session_id = state["session_id"]
    last_message = _latest_ai_message(state)
    messages: list[ToolMessage] = []
    updates: dict[str, Any] = {}

    for tool_call in last_message.tool_calls or []:
        name = tool_call["name"]
        args = tool_call.get("args", {})
        tool_id = tool_call["id"]

        if name not in TOOLS_BY_NAME:
            result_text = json.dumps({"type": "tool_error", "error": f"Unknown tool: {name}"})
        else:
            try:
                result = TOOLS_BY_NAME[name].invoke(args)
                result_text = result if isinstance(result, str) else json.dumps(result, default=str)
            except Exception as exc:  # pragma: no cover - defensive logging path
                result_text = json.dumps({"type": "tool_error", "error": str(exc)})

        payload = _safe_json(result_text)
        record_audit_event(
            session_id,
            "tool_call",
            {"tool": name, "arguments": args, "result": payload},
        )
        messages.append(ToolMessage(content=result_text, tool_call_id=tool_id))
        updates.update(_extract_state_updates(payload))

    updates["messages"] = messages
    return updates


def _extract_state_updates(payload: dict[str, Any]) -> dict[str, Any]:
    payload_type = payload.get("type")

    if payload_type == "customer_lookup" and payload.get("found"):
        return {"customer_id": payload["customer"]["id"]}

    if payload_type == "order_lookup" and payload.get("found"):
        order = payload["order"]
        return {"order_id": order["id"], "customer_id": order["customer_id"]}

    if payload_type == "policy_evaluation":
        return {
            "policy_result": payload,
            "order_id": payload.get("order_id"),
            "customer_id": payload.get("customer_id"),
        }

    return {}


def route_after_model(state: RefundAgentState) -> Literal["tools", "policy_gate"]:
    last_message = _latest_ai_message(state)
    if last_message.tool_calls:
        return "tools"
    return "policy_gate"


def policy_gate(state: RefundAgentState) -> dict[str, Any]:
    if state.get("policy_result"):
        return {}

    continuation = _continued_case_policy_result(state)
    if continuation:
        record_audit_event(
            state["session_id"],
            "case_continuation",
            {
                "case_id": continuation["case_id"],
                "order_id": continuation["policy_result"].get("order_id"),
                "selected_item_ids": continuation["policy_result"].get("selected_item_ids", []),
                "intent": continuation["intent"],
                "reason": "customer_followup_without_new_order",
            },
        )
        return {
            "policy_result": continuation["policy_result"],
            "outcome_case_id": continuation["case_id"],
            "case_followup": True,
            "case_followup_intent": continuation["intent"],
            "case_followup_previous_decision": continuation["previous_decision"],
            "case_followup_previous_status": continuation["previous_status"],
        }

    explicit_result = _explicit_request_policy_result(state)
    if explicit_result:
        record_audit_event(
            state["session_id"],
            "policy_gate",
            {
                **explicit_result,
                "reason": "deterministic_evaluation_from_customer_ids",
            },
        )
        return {"policy_result": explicit_result}

    non_case_response = _non_case_response(state)
    record_audit_event(
        state["session_id"],
        "non_case_response",
        {
            "reason": non_case_response["reason"],
            "order_id": non_case_response.get("order_id"),
            "message": non_case_response["message"],
        },
    )
    return {"final_response": non_case_response["message"]}


def _explicit_request_policy_result(state: RefundAgentState) -> dict[str, Any] | None:
    user_text = _latest_human_text(state)
    order_match = ORDER_RE.search(user_text)
    if not order_match:
        return None

    order_id = order_match.group(0).upper()
    requested_item_ids = [match.upper() for match in ITEM_RE.findall(user_text)]
    return evaluate_refund_from_db(order_id, requested_item_ids, user_text)


def _non_case_response(state: RefundAgentState) -> dict[str, str | None]:
    user_text = _latest_human_text(state)
    order_match = ORDER_RE.search(user_text)

    if order_match:
        order_id = order_match.group(0).upper()
        return {
            "reason": "missing_item_target",
            "order_id": order_id,
            "message": (
                f"I have {order_id}. Please tell me the specific item from that "
                "order you want refunded before I open a new refund case."
            ),
        }

    if _looks_like_refund_intent(user_text):
        return {
            "reason": "missing_refund_target",
            "order_id": None,
            "message": (
                "I can help with that. Please send the order number and the "
                "specific item you want refunded before I open a new refund case."
            ),
        }

    return {
        "reason": "uncategorized",
        "order_id": None,
        "message": (
            "I can help with refund requests and case follow-ups. To start "
            "another refund, send the order number and the specific item you "
            "want reviewed."
        ),
    }


def _looks_like_refund_intent(user_text: str) -> bool:
    normalized = user_text.lower()
    return any(hint in normalized for hint in REFUND_INTENT_HINTS)


def route_after_policy(
    state: RefundAgentState,
) -> Literal["create_refund", "create_escalation", "record_denial", "compose_final"]:
    decision = (state.get("policy_result") or {}).get("decision")
    if (
        state.get("case_followup")
        and state.get("case_followup_previous_decision") == decision
    ):
        return "compose_final"
    if decision == "approve":
        return "compose_final"
    if decision == "escalate":
        return "create_escalation"
    if decision == "deny":
        return "record_denial"
    return "compose_final"


def route_after_policy_gate(
    state: RefundAgentState,
) -> Literal["record_policy_decision", "create_refund", "compose_final"]:
    result = state.get("policy_result")
    if state.get("final_response") and not result:
        return "compose_final"

    decision = (state.get("policy_result") or {}).get("decision")
    if (
        state.get("case_followup")
        and state.get("case_followup_previous_decision") == decision
    ):
        if (
            decision == "approve"
            and state.get("case_followup_previous_status") == "awaiting_customer_confirmation"
            and state.get("case_followup_intent") == "refund_confirmation"
        ):
            return "create_refund"
        return "compose_final"
    if _is_unresolved_refund_target(result):
        return "compose_final"
    return "record_policy_decision"


def record_policy_decision(state: RefundAgentState) -> dict[str, Any]:
    result = state.get("policy_result") or {}
    decision = result.get("decision", "need_more_info")
    request_signature = _request_signature(result)
    case_id = (
        state.get("outcome_case_id")
        or _find_existing_case_id(state["session_id"], result)
        or _new_case_id(decision)
    )
    status = _initial_case_status(decision)
    if (
        state.get("case_followup")
        and state.get("case_followup_previous_decision") == decision
        and state.get("case_followup_previous_status")
    ):
        status = str(state["case_followup_previous_status"])

    _upsert_case(state, case_id, status)
    record_audit_event(
        state["session_id"],
        "policy_decision",
        {
            "case_id": case_id,
            "decision": decision,
            "order_id": result.get("order_id"),
            "customer_id": result.get("customer_id"),
            "eligible_amount": result.get("eligible_amount", 0.0),
            "request_signature": request_signature,
            "requested_item_ids": result.get("requested_item_ids", []),
            "selected_item_ids": result.get("selected_item_ids", []),
            "reason_codes": result.get("reason_codes", []),
            "policy_citations": result.get("policy_citations", []),
            "policy_version": result.get("policy_version"),
            "winning_rule": result.get("winning_rule"),
            "policy_checks": result.get("policy_checks", []),
            "customer_message": result.get("customer_message", ""),
        },
    )
    return {"outcome_case_id": case_id}


def _is_unresolved_refund_target(result: dict[str, Any] | None) -> bool:
    if not result:
        return False
    return result.get("decision") == "need_more_info" and not result.get("selected_item_ids")


def create_refund(state: RefundAgentState) -> dict[str, Any]:
    result = state["policy_result"] or {}
    case_id = state.get("outcome_case_id") or _new_case_id("approve")
    with REFUND_CREATION_LOCK:
        result = protect_against_duplicate_refund(result, exclude_case_id=case_id)
        duplicate_blocked = (
            result.get("decision") == "deny"
            and "ITEM_ALREADY_REFUNDED" in result.get("reason_codes", [])
        )
        if duplicate_blocked:
            blocked_state = {**state, "policy_result": result}
            _upsert_case(blocked_state, case_id, "duplicate_refund_blocked")
        else:
            _upsert_case(state, case_id, "approved")

    amount = float(result.get("eligible_amount") or 0)

    if duplicate_blocked:
        record_audit_event(
            state["session_id"],
            "duplicate_refund_blocked",
            {
                "case_id": case_id,
                "order_id": result.get("order_id"),
                "duplicate_item_ids": result.get("duplicate_item_ids", []),
                "policy_version": result.get("policy_version"),
                "winning_rule": result.get("winning_rule"),
                "policy_checks": result.get("policy_checks", []),
            },
        )
        return {"outcome_case_id": case_id, "policy_result": result}

    record_audit_event(
        state["session_id"],
        "refund_confirmation_received",
        {
            "case_id": case_id,
            "order_id": result.get("order_id"),
            "selected_item_ids": result.get("selected_item_ids", []),
        },
    )
    record_audit_event(
        state["session_id"],
        "refund_created",
        {"case_id": case_id, "amount": amount, "order_id": result.get("order_id")},
    )
    return {"outcome_case_id": case_id}


def create_escalation(state: RefundAgentState) -> dict[str, Any]:
    case_id = state.get("outcome_case_id") or _new_case_id("escalate")
    _upsert_case(state, case_id, "pending_human_review")
    record_audit_event(
        state["session_id"],
        "escalation_created",
        {
            "case_id": case_id,
            "reason_codes": (state.get("policy_result") or {}).get("reason_codes", []),
        },
    )
    return {"outcome_case_id": case_id}


def record_denial(state: RefundAgentState) -> dict[str, Any]:
    case_id = state.get("outcome_case_id") or _new_case_id("deny")
    _upsert_case(state, case_id, "denied")
    record_audit_event(
        state["session_id"],
        "denial_recorded",
        {
            "case_id": case_id,
            "reason_codes": (state.get("policy_result") or {}).get("reason_codes", []),
        },
    )
    return {"outcome_case_id": case_id}


def _new_case_id(decision: str) -> str:
    prefixes = {
        "approve": "REF",
        "deny": "DEN",
        "escalate": "ESC",
        "need_more_info": "INF",
    }
    prefix = prefixes.get(decision, "CAS")
    return f"{prefix}-{uuid4().hex[:8].upper()}"


def _request_signature(result: dict[str, Any]) -> str:
    customer_id = result.get("customer_id") or "unknown_customer"
    order_id = result.get("order_id") or "unknown_order"
    selected_item_ids = result.get("selected_item_ids") or []
    item_key = ",".join(sorted(str(item_id) for item_id in selected_item_ids)) or "unknown_items"
    return f"{customer_id}|{order_id}|{item_key}"


def _find_existing_case_id(session_id: str, result: dict[str, Any]) -> str | None:
    request_signature = _request_signature(result)
    with Session(engine) as session:
        statement = (
            select(RefundCase)
            .where(RefundCase.session_id == session_id)
            .where(RefundCase.request_signature == request_signature)
            .order_by(desc(RefundCase.created_at))
            .limit(1)
        )
        existing_case = session.exec(statement).first()
        if existing_case and not (
            existing_case.status == "approved"
            and "ITEM_ALREADY_REFUNDED" in result.get("reason_codes", [])
        ):
            return existing_case.id

        draft_case = _find_promotable_draft_case(session, session_id, result)

    return draft_case.id if draft_case else None


def _continued_case_policy_result(state: RefundAgentState) -> dict[str, Any] | None:
    user_text = _latest_human_text(state)
    case = _latest_concrete_case(state["session_id"])
    if not case or not case.order_id:
        return None

    intent = _case_followup_intent(user_text, case)
    if intent is None:
        return None

    selected_item_ids = _case_selected_item_ids(case)
    if not selected_item_ids:
        return None

    if intent == "human_request":
        result = _human_review_result_from_case(case)
    elif case.decision in {"approve", "escalate"}:
        result = _policy_result_from_case(case)
    else:
        result = evaluate_refund_from_db(case.order_id, selected_item_ids, user_text)

    return {
        "case_id": case.id,
        "intent": intent,
        "previous_decision": case.decision,
        "previous_status": case.status,
        "policy_result": result,
    }


def _latest_human_text(state: RefundAgentState) -> str:
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _case_followup_intent(user_text: str, refund_case: RefundCase | None = None) -> str | None:
    normalized = user_text.strip().lower()
    if not normalized:
        return None
    if any(hint in normalized for hint in NEW_REQUEST_HINTS):
        return None
    if EMAIL_RE.search(normalized):
        return None
    order_match = ORDER_RE.search(normalized)
    if order_match:
        if (
            refund_case
            and refund_case.order_id == order_match.group(0).upper()
            and not ITEM_RE.search(normalized)
        ):
            return "information"
        return None
    if ITEM_RE.search(normalized):
        return None
    if (
        refund_case
        and refund_case.status == "awaiting_customer_confirmation"
        and _is_refund_confirmation_approval(normalized)
    ):
        return "refund_confirmation"
    if any(hint in normalized for hint in CASE_FOLLOWUP_HINTS):
        return "dispute"
    if any(pattern.search(normalized) for pattern in HUMAN_REQUEST_PATTERNS):
        return "human_request"
    if any(hint in normalized for hint in GRATITUDE_HINTS):
        return "gratitude"
    if any(hint in normalized for hint in ACCEPTANCE_HINTS):
        return "acceptance"
    if any(hint in normalized for hint in INFORMATION_FOLLOWUP_HINTS):
        return "information"
    return None


def _is_refund_confirmation_approval(normalized: str) -> bool:
    if any(pattern.search(normalized) for pattern in REFUND_CONFIRMATION_REJECTION_PATTERNS):
        return False
    return any(pattern.search(normalized) for pattern in REFUND_CONFIRMATION_APPROVAL_PATTERNS)


def _latest_concrete_case(session_id: str) -> RefundCase | None:
    with Session(engine) as session:
        statement = (
            select(RefundCase)
            .where(RefundCase.session_id == session_id)
            .where(RefundCase.decision.in_(["approve", "deny", "escalate"]))
            .where(RefundCase.order_id.is_not(None))
            .order_by(desc(RefundCase.created_at))
        )
        candidates = session.exec(statement).all()

    for candidate in candidates:
        if _case_selected_item_ids(candidate):
            return candidate
    return None


def _case_selected_item_ids(refund_case: RefundCase) -> list[str]:
    try:
        selected_item_ids = json.loads(refund_case.selected_item_ids_json)
    except json.JSONDecodeError:
        return []

    if not isinstance(selected_item_ids, list):
        return []
    return [str(item_id) for item_id in selected_item_ids]


def _policy_result_from_case(refund_case: RefundCase) -> dict[str, Any]:
    return {
        "type": "policy_evaluation",
        "decision": refund_case.decision,
        "reason_codes": _json_list(refund_case.reason_codes_json),
        "customer_message": refund_case.customer_message,
        "policy_citations": _json_list(refund_case.policy_citations_json),
        "eligible_amount": refund_case.amount,
        "order_id": refund_case.order_id,
        "customer_id": refund_case.customer_id,
        "requested_item_ids": _json_list(refund_case.requested_item_ids_json),
        "selected_item_ids": _case_selected_item_ids(refund_case),
    }


def _human_review_result_from_case(refund_case: RefundCase) -> dict[str, Any]:
    return {
        "type": "policy_evaluation",
        "decision": "escalate",
        "reason_codes": ["CUSTOMER_REQUESTED_HUMAN_REVIEW"],
        "customer_message": "I can route this case to a human support specialist for review.",
        "policy_citations": ["Customer-requested human review is handled on the existing case."],
        "eligible_amount": refund_case.amount,
        "order_id": refund_case.order_id,
        "customer_id": refund_case.customer_id,
        "requested_item_ids": _json_list(refund_case.requested_item_ids_json),
        "selected_item_ids": _case_selected_item_ids(refund_case),
        "policy_version": REFUND_POLICY_VERSION,
        "winning_rule": "human_review_requested",
        "policy_checks": [
            {
                "rule": "human_review_requested",
                "label": "Customer requested human review",
                "status": "failed",
                "observed_value": True,
                "expected": "No explicit human-review request",
                "reason_code": "CUSTOMER_REQUESTED_HUMAN_REVIEW",
                "citation": "Customer-requested human review is handled on the existing case.",
            }
        ],
    }


def _json_list(value: str) -> list[str]:
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded]


def _find_promotable_draft_case(
    session: Session,
    session_id: str,
    result: dict[str, Any],
) -> RefundCase | None:
    customer_id = result.get("customer_id")
    order_id = result.get("order_id")
    selected_item_ids = result.get("selected_item_ids") or []

    if not order_id or not selected_item_ids:
        return None

    statement = (
        select(RefundCase)
        .where(RefundCase.session_id == session_id)
        .where(RefundCase.status == "needs_information")
        .where(or_(RefundCase.customer_id == customer_id, RefundCase.customer_id.is_(None)))
        .order_by(desc(RefundCase.created_at))
    )
    candidates = session.exec(statement).all()

    for candidate in candidates:
        if candidate.order_id and candidate.order_id != order_id:
            continue
        if _case_has_selected_items(candidate):
            continue
        return candidate

    return None


def _case_has_selected_items(refund_case: RefundCase) -> bool:
    try:
        selected_item_ids = json.loads(refund_case.selected_item_ids_json)
    except json.JSONDecodeError:
        return True

    return bool(selected_item_ids)


def _initial_case_status(decision: str) -> str:
    statuses = {
        "approve": "awaiting_customer_confirmation",
        "deny": "policy_denied",
        "escalate": "pending_human_review",
        "need_more_info": "needs_information",
    }
    return statuses.get(decision, "policy_decided")


def _upsert_case(state: RefundAgentState, case_id: str, status: str) -> None:
    result = state["policy_result"] or {}
    requested_item_ids = result.get("requested_item_ids", [])
    selected_item_ids = result.get("selected_item_ids", [])
    with Session(engine) as session:
        case = session.get(RefundCase, case_id)
        if case is None:
            case = RefundCase(id=case_id, session_id=state["session_id"])

        case.customer_id = result.get("customer_id")
        case.order_id = result.get("order_id")
        case.request_signature = _request_signature(result)
        case.decision = result.get("decision", "unknown")
        case.status = status
        case.amount = float(result.get("eligible_amount") or 0)
        case.requested_item_ids_json = json.dumps(requested_item_ids)
        case.selected_item_ids_json = json.dumps(selected_item_ids)
        case.reason_codes_json = json.dumps(result.get("reason_codes", []))
        case.policy_citations_json = json.dumps(result.get("policy_citations", []))
        case.customer_message = result.get("customer_message", "")
        session.add(case)
        session.commit()


def compose_final(state: RefundAgentState) -> dict[str, Any]:
    result = state.get("policy_result") or {}
    if state.get("final_response") and not result:
        message = state["final_response"]
        record_audit_event(
            state["session_id"],
            "final_response",
            {"decision": None, "message": message, "case_id": None},
        )
        return {"final_response": message}

    decision = result.get("decision", "need_more_info")
    amount = float(result.get("eligible_amount") or 0)
    case_id = state.get("outcome_case_id")
    citations = result.get("policy_citations", [])
    citation_text = f" Policy basis: {citations[0]}" if citations else ""

    if (
        state.get("case_followup")
        and state.get("case_followup_previous_decision") == decision
    ):
        conversational_reply = _safe_conversational_reply(state)
        message = _compose_case_followup_message(
            decision,
            result,
            case_id,
            amount,
            state.get("case_followup_intent"),
            state.get("case_followup_previous_status"),
            conversational_reply,
        )
    elif decision == "approve":
        message = _compose_refund_confirmation_request(result, case_id, amount, citation_text)
    elif decision == "deny":
        message = f"I cannot process this refund. {result.get('customer_message')}{citation_text}"
        if case_id:
            message += f" I recorded this as case {case_id}."
    elif decision == "escalate":
        message = (
            f"This request needs human review before a decision can be made. "
            f"I escalated case {case_id}. {result.get('customer_message')}{citation_text}"
        )
    else:
        message = result.get(
            "customer_message",
            "I need a valid order number and item details before I can evaluate this refund.",
        )
        if case_id:
            message += f" I logged this as case {case_id}."

    record_audit_event(
        state["session_id"],
        "final_response",
        {"decision": decision, "message": message, "case_id": case_id},
    )
    return {"final_response": message}


def _compose_case_followup_message(
    decision: str,
    result: dict[str, Any],
    case_id: str | None,
    amount: float,
    intent: str | None,
    previous_status: str | None,
    conversational_reply: str | None = None,
) -> str:
    if intent == "refund_confirmation":
        return (
            f"Thanks for confirming. I processed the ${amount:.2f} refund "
            f"for case {case_id}."
        )

    if decision == "approve" and previous_status == "awaiting_customer_confirmation":
        return (
            f"Case {case_id} is eligible for ${amount:.2f}, but no refund has been "
            "processed yet. Please reply 'yes, process the refund' to approve the "
            "item details and authorize the refund."
        )

    if intent == "gratitude":
        return conversational_reply or (
            "You're welcome! If you need any assistance with refunds or have any other "
            "questions in the future, feel free to reach out. Have a great day!"
        )

    if intent == "acceptance":
        if conversational_reply:
            return conversational_reply
        if decision == "approve":
            return f"Got it. Case {case_id} remains approved for ${amount:.2f}."
        if decision == "escalate":
            return f"Understood. Case {case_id} remains pending human review."
        return f"Understood. I've kept this attached to case {case_id}."

    if intent == "human_request":
        return f"I've kept this attached to case {case_id}. It remains pending human review."

    if decision == "approve":
        return (
            f"Case {case_id} is approved for ${amount:.2f}. "
            "The refund has been recorded under this same case."
        )
    if decision == "escalate":
        return (
            f"Case {case_id} is pending human review. "
            f"{result.get('customer_message')}"
        )
    if decision == "deny":
        if intent == "dispute":
            return (
                f"I understand you disagree. I've kept this attached to case {case_id}. "
                f"{result.get('customer_message')}"
            )
        return (
            f"I kept this attached to case {case_id}. "
            f"{result.get('customer_message')}"
        )
    return result.get(
        "customer_message",
        "I need a valid order number and item details before I can evaluate this refund.",
    )


def _safe_conversational_reply(state: RefundAgentState) -> str | None:
    intent = state.get("case_followup_intent")
    reply_hints = SAFE_MODEL_FOLLOWUP_HINTS.get(intent or "")
    if not reply_hints:
        return None

    content = _latest_ai_message(state).content
    if not isinstance(content, str):
        return None

    reply = content.strip()
    normalized_reply = reply.lower()
    if not reply or not any(hint in normalized_reply for hint in reply_hints):
        return None
    if any(pattern.search(normalized_reply) for pattern in UNSAFE_CONVERSATIONAL_REPLY_PATTERNS):
        return None
    return reply


def _compose_refund_confirmation_request(
    result: dict[str, Any],
    case_id: str | None,
    amount: float,
    citation_text: str,
) -> str:
    order_id = result.get("order_id") or "unknown order"
    item_details = _selected_item_details(result.get("selected_item_ids", []))
    detail_lines = [f"- Order: {order_id}"]
    if item_details:
        for item in item_details:
            detail_lines.extend(
                [
                    f"- Item: {item.name} ({item.id})",
                    f"- Quantity: {item.quantity}",
                    f"- Item amount: ${item.unit_price * item.quantity:.2f}",
                ]
            )
    else:
        selected_items = ", ".join(result.get("selected_item_ids", [])) or "selected item"
        detail_lines.append(f"- Item: {selected_items}")
    detail_lines.append(f"- Total refund: ${amount:.2f}")
    details_text = "\n".join(detail_lines)

    return (
        "This request is eligible, but I need your approval before processing it.\n\n"
        f"Please confirm these details:\n{details_text}\n\n"
        "Reply 'yes, process the refund' to approve.\n"
        f"No refund has been processed yet. Refund case {case_id}.{citation_text}"
    )


def _selected_item_details(item_ids: list[str]) -> list[OrderItem]:
    if not item_ids:
        return []
    with Session(engine) as session:
        statement = select(OrderItem).where(OrderItem.id.in_(item_ids))
        items = session.exec(statement).all()
    item_order = {item_id: index for index, item_id in enumerate(item_ids)}
    return sorted(items, key=lambda item: item_order.get(item.id, len(item_order)))


def build_graph():
    graph = StateGraph(RefundAgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", run_tools)
    graph.add_node("policy_gate", policy_gate)
    graph.add_node("record_policy_decision", record_policy_decision)
    graph.add_node("create_refund", create_refund)
    graph.add_node("create_escalation", create_escalation)
    graph.add_node("record_denial", record_denial)
    graph.add_node("compose_final", compose_final)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_model)
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("policy_gate", route_after_policy_gate)
    graph.add_conditional_edges("record_policy_decision", route_after_policy)
    graph.add_edge("create_refund", "compose_final")
    graph.add_edge("create_escalation", "compose_final")
    graph.add_edge("record_denial", "compose_final")
    graph.add_edge("compose_final", END)
    return graph.compile(checkpointer=MemorySaver())


refund_graph = build_graph()

import re
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.config import settings


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
ORDER_RE = re.compile(r"\bORD-\d{4,}\b", re.IGNORECASE)
ITEM_RE = re.compile(r"\bITEM-\d{4,}\b", re.IGNORECASE)


class MockRefundLLM:
    """A deterministic local model for demos, tests, and no-key development."""

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        turn_messages = self._messages_since_latest_user(messages)
        called_tools = [
            tool_call["name"]
            for message in turn_messages
            if isinstance(message, AIMessage)
            for tool_call in (message.tool_calls or [])
        ]
        user_text = self._latest_user_text(messages)
        email = self._find(EMAIL_RE, user_text)
        order_id = self._find(ORDER_RE, user_text)
        item_ids = [match.upper() for match in ITEM_RE.findall(user_text)]

        if email and "lookup_customer" not in called_tools:
            return self._tool_call("lookup_customer", {"identifier": email})

        if order_id and "get_order" not in called_tools:
            return self._tool_call("get_order", {"order_id": order_id.upper()})

        if order_id and "evaluate_refund_request" not in called_tools:
            return self._tool_call(
                "evaluate_refund_request",
                {
                    "order_id": order_id.upper(),
                    "requested_item_ids": item_ids,
                    "reason": user_text,
                },
            )

        if email and not order_id and "list_customer_orders" not in called_tools:
            customer_id = self._customer_id_from_tool_results(messages)
            if customer_id:
                return self._tool_call("list_customer_orders", {"customer_id": customer_id})

        return AIMessage(content="I checked the available account and policy details.")

    @staticmethod
    def _latest_user_text(messages: list[BaseMessage]) -> str:
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                return str(message.content)
        return ""

    @staticmethod
    def _messages_since_latest_user(messages: list[BaseMessage]) -> list[BaseMessage]:
        for index in range(len(messages) - 1, -1, -1):
            if isinstance(messages[index], HumanMessage):
                return messages[index:]
        return messages

    @staticmethod
    def _find(pattern: re.Pattern[str], value: str) -> str | None:
        match = pattern.search(value)
        if not match:
            return None
        return match.group(0)

    @staticmethod
    def _tool_call(name: str, args: dict) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[{"name": name, "args": args, "id": f"call_{uuid4().hex}"}],
        )

    @staticmethod
    def _customer_id_from_tool_results(messages: list[BaseMessage]) -> str | None:
        for message in reversed(messages):
            content = getattr(message, "content", "")
            if not isinstance(content, str):
                continue
            match = re.search(r'"id":\s*"(CUST-\d+)"', content)
            if match:
                return match.group(1)
        return None


def get_llm(tools: list):
    if settings.llm_provider.lower() == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=settings.openai_model, temperature=0).bind_tools(tools)

    return MockRefundLLM()

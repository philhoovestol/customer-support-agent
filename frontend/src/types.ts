export type ChatRole = "customer" | "agent";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
}

export interface PolicyResult {
  decision: "approve" | "deny" | "escalate" | "need_more_info";
  reason_codes: string[];
  customer_message: string;
  policy_citations: string[];
  eligible_amount: number;
  order_id?: string | null;
  customer_id?: string | null;
  policy_version?: string;
  winning_rule?: string;
  policy_checks?: PolicyCheck[];
}

export interface PolicyCheck {
  rule: string;
  label: string;
  status: "passed" | "failed" | "not_applicable";
  observed_value: unknown;
  expected: string;
  reason_code: string;
  citation: string;
  detail?: string;
}

export interface AuditEvent {
  id: number;
  session_id: string;
  turn_id?: string | null;
  turn_sequence?: number | null;
  sequence?: number | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ChatResponse {
  session_id: string;
  message: string;
  decision: string | null;
  policy_result: PolicyResult | null;
  audit_events: AuditEvent[];
}

export interface Customer {
  id: string;
  name: string;
  email: string;
  loyalty_tier: string;
  refund_count_last_12_months: number;
  notes: string;
}

export interface RefundCase {
  id: string;
  session_id: string;
  customer_id: string | null;
  order_id: string | null;
  request_signature: string;
  decision: string;
  status: string;
  amount: number;
  requested_item_ids: string[];
  selected_item_ids: string[];
  reason_codes: string[];
  policy_citations: string[];
  customer_message: string;
  created_at: string;
}

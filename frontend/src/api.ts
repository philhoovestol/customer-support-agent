import type { AuditEvent, ChatResponse, Customer, RefundCase } from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
    ...options,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function sendChat(message: string, sessionId: string | null): Promise<ChatResponse> {
  return request<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId }),
  });
}

export function fetchCustomers(): Promise<Customer[]> {
  return request<Customer[]>("/api/customers");
}

export function fetchAdminLogs(limit = 500): Promise<AuditEvent[]> {
  return request<AuditEvent[]>(`/api/admin/logs?limit=${limit}`);
}

export function fetchSessionLogs(sessionId: string): Promise<AuditEvent[]> {
  return request<AuditEvent[]>(`/api/admin/sessions/${sessionId}/logs`);
}

export function fetchRefundCases(): Promise<RefundCase[]> {
  return request<RefundCase[]>("/api/admin/refund-cases");
}

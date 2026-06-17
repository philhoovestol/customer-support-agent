import { useEffect, useMemo, useState } from "react";

import { fetchAdminLogs, fetchRefundCases, sendChat } from "./api";
import { AdminDashboard } from "./components/AdminDashboard";
import { ChatPanel } from "./components/ChatPanel";
import type { AuditEvent, ChatMessage, PolicyResult, RefundCase } from "./types";

function makeId() {
  return crypto.randomUUID();
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [policyResult, setPolicyResult] = useState<PolicyResult | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [refundCases, setRefundCases] = useState<RefundCase[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [adminLoading, setAdminLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sortedEvents = useMemo(
    () => [...auditEvents].sort((a, b) => b.id - a.id),
    [auditEvents],
  );
  const selectedRefundCase = useMemo(
    () => refundCases.find((refundCase) => refundCase.id === selectedCaseId) ?? null,
    [refundCases, selectedCaseId],
  );

  useEffect(() => {
    void refreshAdmin();

    const refreshOnFocus = () => {
      void refreshAdmin();
    };
    window.addEventListener("focus", refreshOnFocus);

    return () => window.removeEventListener("focus", refreshOnFocus);
  }, []);

  async function refreshAdmin() {
    setAdminLoading(true);
    try {
      const [eventsResult, casesResult] = await Promise.allSettled([
        fetchAdminLogs(),
        fetchRefundCases(),
      ]);

      if (eventsResult.status === "fulfilled") {
        setAuditEvents(eventsResult.value);
      }
      if (casesResult.status === "fulfilled") {
        setRefundCases(casesResult.value);
      }

      const failedRequest = [eventsResult, casesResult].find(
        (result) => result.status === "rejected",
      );
      if (failedRequest?.status === "rejected") {
        setError(
          failedRequest.reason instanceof Error
            ? failedRequest.reason.message
            : "Could not refresh all admin data.",
        );
      }
    } finally {
      setAdminLoading(false);
    }
  }

  async function handleSend() {
    const trimmed = input.trim();
    if (!trimmed || loading) {
      return;
    }

    setError(null);
    setLoading(true);
    setInput("");
    setMessages((current) => [
      ...current,
      { id: makeId(), role: "customer", content: trimmed },
    ]);

    try {
      const response = await sendChat(trimmed, sessionId);
      setSessionId(response.session_id);
      setPolicyResult(response.policy_result);
      setMessages((current) => [
        ...current,
        { id: makeId(), role: "agent", content: response.message },
      ]);
      await refreshAdmin();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The agent could not respond.");
    } finally {
      setLoading(false);
    }
  }

  function resetSession() {
    setMessages([]);
    setInput("");
    setSessionId(null);
    setPolicyResult(null);
    setError(null);
  }

  function handleSelectCase(refundCase: RefundCase) {
    setSelectedCaseId((current) => (current === refundCase.id ? null : refundCase.id));
    setError(null);
  }

  return (
    <main className="app-shell">
      <ChatPanel
        messages={messages}
        input={input}
        sessionId={sessionId}
        policyResult={policyResult}
        loading={loading}
        error={error}
        onInputChange={setInput}
        onSend={handleSend}
        onReset={resetSession}
      />
      <AdminDashboard
        auditEvents={sortedEvents}
        refundCases={refundCases}
        selectedRefundCase={selectedRefundCase}
        loading={adminLoading}
        onSelectCase={handleSelectCase}
        onRefresh={refreshAdmin}
      />
    </main>
  );
}

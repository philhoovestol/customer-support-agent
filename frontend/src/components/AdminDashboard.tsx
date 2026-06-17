import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ClipboardList,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { AuditEvent, RefundCase } from "../types";

interface AdminDashboardProps {
  auditEvents: AuditEvent[];
  refundCases: RefundCase[];
  selectedRefundCase: RefundCase | null;
  loading: boolean;
  onSelectCase: (refundCase: RefundCase) => void;
  onRefresh: () => void;
}

export function AdminDashboard({
  auditEvents,
  refundCases,
  selectedRefundCase,
  loading,
  onSelectCase,
  onRefresh,
}: AdminDashboardProps) {
  const traceRefs = useRef<Record<number, HTMLElement | null>>({});
  const [highlightedEventId, setHighlightedEventId] = useState<number | null>(null);
  const [expandedEventIds, setExpandedEventIds] = useState<number[]>([]);
  const [activeLogDate, setActiveLogDate] = useState<string | null>(null);
  const [casesCollapsed, setCasesCollapsed] = useState(false);
  const selectedCaseId = selectedRefundCase?.id ?? null;
  const logDateGroups = useMemo(() => groupEventsByDate(auditEvents), [auditEvents]);
  const activeDateIndex = Math.max(
    0,
    logDateGroups.findIndex((group) => group.dateKey === activeLogDate),
  );
  const activeLogGroup = logDateGroups[activeDateIndex] ?? null;
  const visibleAuditEvents = activeLogGroup?.events ?? [];
  const displayDecision = useMemo(
    () => buildDisplayDecision(selectedRefundCase),
    [selectedRefundCase],
  );
  const selectedCasePolicyEvents = useMemo(() => {
    if (!selectedCaseId) {
      return [];
    }

    return auditEvents
      .filter(
        (event) =>
          event.event_type === "policy_decision" && eventContainsCaseId(event, selectedCaseId),
      )
      .sort((left, right) => right.id - left.id);
  }, [auditEvents, selectedCaseId]);
  const priorSelectedCasePolicyEvents = useMemo(
    () => selectedCasePolicyEvents.slice(1),
    [selectedCasePolicyEvents],
  );
  const firstSelectedCaseEventId = useMemo(() => {
    if (!selectedCaseId) {
      return null;
    }
    if (selectedCasePolicyEvents.length > 0) {
      return selectedCasePolicyEvents[0].id;
    }
    return auditEvents.find((event) => eventContainsCaseId(event, selectedCaseId))?.id ?? null;
  }, [auditEvents, selectedCaseId, selectedCasePolicyEvents]);
  const firstSelectedCaseEventDate = useMemo(() => {
    const event = auditEvents.find((item) => item.id === firstSelectedCaseEventId);
    return event ? dateKeyForEvent(event) : null;
  }, [auditEvents, firstSelectedCaseEventId]);

  useEffect(() => {
    if (logDateGroups.length === 0) {
      setActiveLogDate(null);
      return;
    }

    if (!activeLogDate || !logDateGroups.some((group) => group.dateKey === activeLogDate)) {
      setActiveLogDate(logDateGroups[0].dateKey);
    }
  }, [activeLogDate, logDateGroups]);

  useEffect(() => {
    if (firstSelectedCaseEventDate) {
      setActiveLogDate(firstSelectedCaseEventDate);
    }
  }, [firstSelectedCaseEventDate]);

  useEffect(() => {
    if (!firstSelectedCaseEventId) {
      return;
    }

    traceRefs.current[firstSelectedCaseEventId]?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
    setHighlightedEventId(firstSelectedCaseEventId);

    const timeoutId = window.setTimeout(() => setHighlightedEventId(null), 1800);
    return () => window.clearTimeout(timeoutId);
  }, [activeLogDate, firstSelectedCaseEventId]);

  function changeDatePage(direction: -1 | 1) {
    const nextGroup = logDateGroups[activeDateIndex + direction];
    if (nextGroup) {
      setActiveLogDate(nextGroup.dateKey);
    }
  }

  function toggleEvent(eventId: number) {
    setExpandedEventIds((current) =>
      current.includes(eventId)
        ? current.filter((id) => id !== eventId)
        : [...current, eventId],
    );
  }

  return (
    <aside className="workspace-panel admin-panel">
      <header className="panel-header compact">
        <div>
          <p className="eyebrow">Admin Console</p>
          <h2>Agent Trace</h2>
        </div>
        <button
          aria-label="Reload logs and cases"
          className="icon-button"
          type="button"
          onClick={onRefresh}
          title="Reload logs and cases"
        >
          <RefreshCw className={loading ? "spin" : ""} size={18} />
        </button>
      </header>

      <div className={`admin-body ${casesCollapsed ? "cases-collapsed" : ""}`}>
        <section className={`cases-rail ${casesCollapsed ? "collapsed" : ""}`}>
          <div className="section-title cases-title">
            <button
              aria-label={
                casesCollapsed
                  ? "Expand refund cases and policy decision"
                  : "Collapse refund cases and policy decision"
              }
              className="rail-toggle"
              type="button"
              onClick={() => setCasesCollapsed((current) => !current)}
              title={
                casesCollapsed
                  ? "Expand refund cases and policy decision"
                  : "Collapse refund cases and policy decision"
              }
            >
              <ClipboardList size={17} />
              {!casesCollapsed ? <h3>Refund Cases</h3> : null}
              {casesCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
            </button>
          </div>
          {!casesCollapsed ? (
            <>
              <div className="case-list">
                {refundCases.map((refundCase) => (
                  <button
                    aria-pressed={refundCase.id === selectedCaseId}
                    className={`case-row ${refundCase.id === selectedCaseId ? "selected" : ""}`}
                    key={refundCase.id}
                    type="button"
                    onClick={() => onSelectCase(refundCase)}
                  >
                    <div>
                      <strong>{refundCase.id}</strong>
                      <span>{refundCase.order_id ?? "no order"}</span>
                    </div>
                    <span className={`case-status ${refundCase.decision}`}>
                      {refundCase.status}
                    </span>
                  </button>
                ))}
                {refundCases.length === 0 ? <p className="muted">No cases yet.</p> : null}
              </div>

              <section className="decision-panel">
                <div className="section-title">
                  <ShieldCheck size={17} />
                  <h3>Policy Decision</h3>
                </div>
                {displayDecision ? (
                  <div className="decision-details">
                    <div className={`decision-tile ${displayDecision.decision}`}>
                      <span>{displayDecision.decision.replaceAll("_", " ")}</span>
                      <strong>${displayDecision.amount.toFixed(2)}</strong>
                    </div>
                    <div className="decision-meta">
                      {displayDecision.meta.map((item) => (
                        <div key={item.label}>
                          <span>{item.label}</span>
                          <strong>{item.value}</strong>
                        </div>
                      ))}
                    </div>
                    <p>{displayDecision.message}</p>
                    <div className="tag-row">
                      {displayDecision.reasonCodes.map((code) => (
                        <span className="tag" key={code}>
                          {code}
                        </span>
                      ))}
                    </div>
                    {displayDecision.citations.length > 0 ? (
                      <div className="citation-list">
                        {displayDecision.citations.map((citation) => (
                          <p key={citation}>{citation}</p>
                        ))}
                      </div>
                    ) : null}
                    {selectedRefundCase && priorSelectedCasePolicyEvents.length > 0 ? (
                      <div className="policy-check-list">
                        <div className="policy-check-heading">
                          <strong>Prior policy checks</strong>
                          <span>{priorSelectedCasePolicyEvents.length}</span>
                        </div>
                        {priorSelectedCasePolicyEvents.map((event) => {
                          const check = policyCheckForEvent(event);

                          return (
                            <article className="policy-check-row" key={event.id}>
                              <div>
                                <strong>{check.decision.replaceAll("_", " ")}</strong>
                                <time>{new Date(event.created_at).toLocaleTimeString()}</time>
                              </div>
                              <p>{check.message}</p>
                              <div className="tag-row">
                                {check.reasonCodes.map((code) => (
                                  <span className="tag" key={`${event.id}-${code}`}>
                                    {code}
                                  </span>
                                ))}
                              </div>
                            </article>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <p className="muted">Select a case to view its policy decisions.</p>
                )}
              </section>
            </>
          ) : null}
        </section>

        <div className="admin-content">
          <section className="trace-panel">
            <div className="section-title">
              <ClipboardList size={17} />
              <h3>Reasoning Logs</h3>
            </div>
            <div className="log-pager">
              <button
                className="pager-button"
                type="button"
                disabled={activeDateIndex >= logDateGroups.length - 1}
                onClick={() => changeDatePage(1)}
                title="Older log date"
              >
                <ChevronLeft size={16} />
              </button>
              <div>
                <strong>{activeLogGroup?.label ?? "No logs"}</strong>
                <span>
                  {activeLogGroup
                    ? `${activeLogGroup.events.length} log${activeLogGroup.events.length === 1 ? "" : "s"}`
                    : "0 logs"}
                </span>
              </div>
              <button
                className="pager-button"
                type="button"
                disabled={activeDateIndex <= 0}
                onClick={() => changeDatePage(-1)}
                title="Newer log date"
              >
                <ChevronRight size={16} />
              </button>
            </div>
            <div className="trace-list">
              {visibleAuditEvents.map((event) => {
                const isExpanded = expandedEventIds.includes(event.id);

                return (
                <article
                  className={`trace-row ${
                    event.id === highlightedEventId ? "trace-row-highlight" : ""
                  } ${event.id === firstSelectedCaseEventId ? "trace-row-case-match" : ""}`}
                  key={event.id}
                  ref={(element) => {
                    traceRefs.current[event.id] = element;
                  }}
                >
                  <button className="trace-summary" type="button" onClick={() => toggleEvent(event.id)}>
                    <span className="trace-type">{event.event_type.replaceAll("_", " ")}</span>
                    <span className="trace-session">{event.session_id}</span>
                    <time>{new Date(event.created_at).toLocaleTimeString()}</time>
                    {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </button>
                  {isExpanded ? <pre>{JSON.stringify(event.payload, null, 2)}</pre> : null}
                </article>
              );
              })}
              {visibleAuditEvents.length === 0 ? <p className="muted">No logs yet.</p> : null}
            </div>
          </section>
        </div>
      </div>
    </aside>
  );
}

function buildDisplayDecision(selectedRefundCase: RefundCase | null) {
  if (selectedRefundCase) {
    return {
      decision: selectedRefundCase.decision,
      amount: selectedRefundCase.amount,
      message: selectedRefundCase.customer_message,
      reasonCodes: selectedRefundCase.reason_codes,
      citations: selectedRefundCase.policy_citations,
      meta: [
        { label: "Case", value: selectedRefundCase.id },
        { label: "Status", value: selectedRefundCase.status.replaceAll("_", " ") },
        { label: "Order", value: selectedRefundCase.order_id ?? "none" },
        { label: "Customer", value: selectedRefundCase.customer_id ?? "none" },
      ],
    };
  }

  return null;
}

function eventContainsCaseId(event: AuditEvent, caseId: string): boolean {
  return containsValue(event.payload, caseId);
}

function policyCheckForEvent(event: AuditEvent) {
  return {
    decision: getTextPayloadValue(event.payload, "decision", "unknown"),
    message: getTextPayloadValue(event.payload, "customer_message", "Policy decision recorded."),
    reasonCodes: getStringArrayPayloadValue(event.payload, "reason_codes"),
  };
}

function getTextPayloadValue(
  payload: Record<string, unknown>,
  key: string,
  fallback: string,
): string {
  const value = payload[key];
  return typeof value === "string" ? value : fallback;
}

function getStringArrayPayloadValue(payload: Record<string, unknown>, key: string): string[] {
  const value = payload[key];
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter((item): item is string => typeof item === "string");
}

function groupEventsByDate(events: AuditEvent[]) {
  const groups = events.reduce<Record<string, AuditEvent[]>>((accumulator, event) => {
    const dateKey = dateKeyForEvent(event);
    accumulator[dateKey] = [...(accumulator[dateKey] ?? []), event];
    return accumulator;
  }, {});

  return Object.entries(groups)
    .sort(([left], [right]) => right.localeCompare(left))
    .map(([dateKey, groupEvents]) => ({
      dateKey,
      label: new Date(`${dateKey}T12:00:00`).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      }),
      events: groupEvents.sort((left, right) => right.id - left.id),
    }));
}

function dateKeyForEvent(event: AuditEvent): string {
  return event.created_at.slice(0, 10);
}

function containsValue(value: unknown, needle: string): boolean {
  if (value === needle) {
    return true;
  }

  if (Array.isArray(value)) {
    return value.some((item) => containsValue(item, needle));
  }

  if (value && typeof value === "object") {
    return Object.values(value).some((item) => containsValue(item, needle));
  }

  return false;
}

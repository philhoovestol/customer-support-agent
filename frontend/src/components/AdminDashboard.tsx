import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ClipboardList,
  Filter,
  RefreshCw,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { AuditEvent, PolicyCheck, RefundCase } from "../types";

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
  const [expandedEventIds, setExpandedEventIds] = useState<number[]>([]);
  const [activeLogDate, setActiveLogDate] = useState<string | null>(null);
  const [casesCollapsed, setCasesCollapsed] = useState(false);
  const [searchFilter, setSearchFilter] = useState("");
  const [turnFilter, setTurnFilter] = useState("");
  const [caseFilter, setCaseFilter] = useState("");
  const [sessionFilter, setSessionFilter] = useState("");
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const selectedCaseId = selectedRefundCase?.id ?? null;
  const casesByTurn = useMemo(
    () => buildCasesByTurn(auditEvents, refundCases),
    [auditEvents, refundCases],
  );
  const selectedCaseTurnIds = useMemo(() => {
    if (!selectedCaseId) {
      return new Set<string>();
    }
    return new Set(
      [...casesByTurn.entries()]
        .filter(([, cases]) => cases.some((refundCase) => refundCase.id === selectedCaseId))
        .map(([turnId]) => turnId),
    );
  }, [casesByTurn, selectedCaseId]);
  const sessionOptions = useMemo(
    () => [...new Set(auditEvents.map((event) => event.session_id))].sort(),
    [auditEvents],
  );
  const eventTypeOptions = useMemo(
    () => [...new Set(auditEvents.map((event) => event.event_type))].sort(),
    [auditEvents],
  );
  const turnOptions = useMemo(() => {
    const turns = new Map<string, AuditEvent>();
    for (const event of [...auditEvents].sort((left, right) => right.id - left.id)) {
      if (event.turn_id && !turns.has(event.turn_id)) {
        turns.set(event.turn_id, event);
      }
    }
    return [...turns.entries()].map(([turnId, event]) => ({
      turnId,
      label: `Turn ${event.turn_sequence ?? "?"} | ${event.session_id}`,
    }));
  }, [auditEvents]);
  const filteredAuditEvents = useMemo(() => {
    const search = searchFilter.trim().toLowerCase();
    return auditEvents.filter((event) => {
      const linkedCases = event.turn_id ? (casesByTurn.get(event.turn_id) ?? []) : [];
      if (turnFilter && event.turn_id !== turnFilter) {
        return false;
      }
      if (caseFilter && !linkedCases.some((refundCase) => refundCase.id === caseFilter)) {
        return false;
      }
      if (sessionFilter && event.session_id !== sessionFilter) {
        return false;
      }
      if (eventTypeFilter && event.event_type !== eventTypeFilter) {
        return false;
      }
      if (!search) {
        return true;
      }

      const searchable = JSON.stringify({
        event_type: event.event_type,
        session_id: event.session_id,
        turn_id: event.turn_id,
        turn_sequence: event.turn_sequence,
        sequence: event.sequence,
        cases: linkedCases,
        payload: event.payload,
      }).toLowerCase();
      return searchable.includes(search);
    });
  }, [
    auditEvents,
    caseFilter,
    casesByTurn,
    eventTypeFilter,
    searchFilter,
    sessionFilter,
    turnFilter,
  ]);
  const logDateGroups = useMemo(
    () => groupEventsByDate(filteredAuditEvents),
    [filteredAuditEvents],
  );
  const activeDateIndex = Math.max(
    0,
    logDateGroups.findIndex((group) => group.dateKey === activeLogDate),
  );
  const activeLogGroup = logDateGroups[activeDateIndex] ?? null;
  const visibleAuditEvents = activeLogGroup?.events ?? [];
  const hasActiveFilters = Boolean(
    searchFilter || turnFilter || caseFilter || sessionFilter || eventTypeFilter,
  );
  const selectedCaseEvidenceEvents = useMemo(() => {
    if (!selectedCaseId) {
      return [];
    }

    const seenTurns = new Set<string>();
    return auditEvents
      .filter(
        (event) =>
          eventContainsCaseId(event, selectedCaseId) &&
          getPolicyChecks(event.payload).length > 0,
      )
      .sort((left, right) => right.id - left.id)
      .filter((event) => {
        const key = event.turn_id ?? `event-${event.id}`;
        if (seenTurns.has(key)) {
          return false;
        }
        seenTurns.add(key);
        return true;
      });
  }, [auditEvents, selectedCaseId]);
  useEffect(() => {
    if (!selectedCaseId) {
      return;
    }
    setSearchFilter("");
    setTurnFilter("");
    setCaseFilter("");
    setSessionFilter("");
    setEventTypeFilter("");
  }, [selectedCaseId]);

  useEffect(() => {
    if (logDateGroups.length === 0) {
      setActiveLogDate(null);
      return;
    }

    if (!activeLogDate || !logDateGroups.some((group) => group.dateKey === activeLogDate)) {
      setActiveLogDate(logDateGroups[0].dateKey);
    }
  }, [activeLogDate, logDateGroups]);

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

  function clearTraceFilters() {
    setSearchFilter("");
    setTurnFilter("");
    setCaseFilter("");
    setSessionFilter("");
    setEventTypeFilter("");
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
                  <h3>Case Decisions</h3>
                </div>
                {selectedRefundCase ? (
                  <div className="case-decisions">
                    <div className="case-decision-summary">
                      <div>
                        <strong>{selectedRefundCase.id}</strong>
                        <span>
                          {selectedRefundCase.order_id ?? "no order"} | {selectedRefundCase.customer_id ?? "no customer"}
                        </span>
                      </div>
                      <span className={`case-status ${selectedRefundCase.decision}`}>
                        {selectedRefundCase.status.replaceAll("_", " ")}
                      </span>
                    </div>
                    <div className="case-decision-list">
                      {selectedCaseEvidenceEvents.map((event, index) => {
                        const decision = policyDecisionForEvent(
                          event,
                          index === 0 ? selectedRefundCase : null,
                        );

                        return (
                          <article className="case-decision-row" key={event.id}>
                            <div className="case-decision-heading">
                              <span className={`decision-badge ${decision.decision}`}>
                                {decision.decision.replaceAll("_", " ")}
                              </span>
                              <time>
                                Turn {event.turn_sequence ?? "?"} | {new Date(event.created_at).toLocaleTimeString()}
                              </time>
                            </div>
                            {decision.message ? <p>{decision.message}</p> : null}
                            {decision.reasonCodes.length > 0 ? (
                              <div className="tag-row">
                                {decision.reasonCodes.map((code) => (
                                  <span className="tag" key={`${event.id}-${code}`}>
                                    {code}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                            <PolicyEvidenceDisclosure event={event} />
                          </article>
                        );
                      })}
                      {selectedCaseEvidenceEvents.length === 0 ? (
                        <p className="muted">No policy decisions recorded for this case.</p>
                      ) : null}
                    </div>
                  </div>
                ) : (
                  <p className="muted">Select a case to view its decisions.</p>
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
                    ? `${activeLogGroup.events.length} technical traces`
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
            <section className="trace-filters" aria-label="Reasoning log filters">
              <div className="trace-filter-heading">
                <div>
                  <Filter size={14} />
                  <strong>Filters</strong>
                  <span>
                    {filteredAuditEvents.length} of {auditEvents.length}
                  </span>
                </div>
                <button
                  type="button"
                  disabled={!hasActiveFilters}
                  onClick={clearTraceFilters}
                  title="Clear reasoning log filters"
                >
                  <X size={13} />
                  Clear
                </button>
              </div>
              <div className="trace-filter-grid">
                <label className="trace-search-filter">
                  <span>Search</span>
                  <div>
                    <Search size={14} />
                    <input
                      type="search"
                      value={searchFilter}
                      placeholder="Payload, ID, status..."
                      onChange={(event) => setSearchFilter(event.target.value)}
                    />
                  </div>
                </label>
                <label>
                  <span>Turn</span>
                  <select value={turnFilter} onChange={(event) => setTurnFilter(event.target.value)}>
                    <option value="">Any turn</option>
                    {turnOptions.map((turn) => (
                      <option key={turn.turnId} value={turn.turnId}>
                        {turn.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Case</span>
                  <select value={caseFilter} onChange={(event) => setCaseFilter(event.target.value)}>
                    <option value="">Any case</option>
                    {refundCases.map((refundCase) => (
                      <option key={refundCase.id} value={refundCase.id}>
                        {refundCase.id} | {refundCase.decision.replaceAll("_", " ")}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Session</span>
                  <select
                    value={sessionFilter}
                    onChange={(event) => setSessionFilter(event.target.value)}
                  >
                    <option value="">Any session</option>
                    {sessionOptions.map((sessionId) => (
                      <option key={sessionId} value={sessionId}>
                        {sessionId}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Event</span>
                  <select
                    value={eventTypeFilter}
                    onChange={(event) => setEventTypeFilter(event.target.value)}
                  >
                    <option value="">Any event</option>
                    {eventTypeOptions.map((eventType) => (
                      <option key={eventType} value={eventType}>
                        {eventType.replaceAll("_", " ")}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </section>
            <div className="trace-list">
              {visibleAuditEvents.map((event) => renderTechnicalEvent(event))}
              {visibleAuditEvents.length === 0 ? (
                <p className="muted">
                  {hasActiveFilters ? "No traces match these filters." : "No logs yet."}
                </p>
              ) : null}
            </div>
          </section>
        </div>
      </div>
    </aside>
  );

  function renderTechnicalEvent(event: AuditEvent) {
    const isExpanded = expandedEventIds.includes(event.id);
    const linkedCases = event.turn_id ? (casesByTurn.get(event.turn_id) ?? []) : [];
    const isSelectedCaseTrace = Boolean(
      event.turn_id && selectedCaseTurnIds.has(event.turn_id),
    );

    return (
      <article
        className={`trace-row ${isSelectedCaseTrace ? "trace-row-case-match" : ""}`}
        key={event.id}
      >
        <button className="trace-summary" type="button" onClick={() => toggleEvent(event.id)}>
          <span className="trace-type">{event.event_type.replaceAll("_", " ")}</span>
          <span className="trace-session">
            Turn {event.turn_sequence ?? "?"} / Step {event.sequence ?? "?"}
          </span>
          <time>{new Date(event.created_at).toLocaleTimeString()}</time>
          {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {isExpanded ? (
          <div className="trace-expanded">
            <div className="trace-context-grid">
              <div>
                <span>Turn</span>
                <strong>{event.turn_sequence ?? "unknown"}</strong>
              </div>
              <div>
                <span>Step</span>
                <strong>{event.sequence ?? "unknown"}</strong>
              </div>
              <div>
                <span>Turn ID</span>
                <strong>{event.turn_id ?? "unknown"}</strong>
              </div>
              <div>
                <span>Session</span>
                <strong>{event.session_id}</strong>
              </div>
            </div>
            <div className="trace-case-context">
              <strong>Linked cases</strong>
              {linkedCases.length > 0 ? (
                linkedCases.map((refundCase) => (
                  <div className="trace-case-row" key={refundCase.id}>
                    <div>
                      <strong>{refundCase.id}</strong>
                      <span>{refundCase.order_id ?? "no order"}</span>
                    </div>
                    <div>
                      <span className={`case-status ${refundCase.decision}`}>
                        {refundCase.decision.replaceAll("_", " ")}
                      </span>
                      <span>{refundCase.status.replaceAll("_", " ")}</span>
                    </div>
                  </div>
                ))
              ) : (
                <p>No case linked to this turn.</p>
              )}
            </div>
            <pre>{JSON.stringify(event.payload, null, 2)}</pre>
          </div>
        ) : null}
      </article>
    );
  }
}

interface PolicyEvidenceDisclosureProps {
  event: AuditEvent;
}

function PolicyEvidenceDisclosure({ event }: PolicyEvidenceDisclosureProps) {
  const checks = getPolicyChecks(event.payload);
  const winningRule = getTextPayloadValue(event.payload, "winning_rule", "");
  const policyVersion = getTextPayloadValue(event.payload, "policy_version", "unversioned");

  if (checks.length === 0) {
    return null;
  }

  return (
    <details className="policy-evidence-disclosure">
      <summary>
        <span>
          <strong>Evidence</strong>
          <small>
            {policyVersion} | Turn {event.turn_sequence ?? "?"}
          </small>
        </span>
        <span>
          {checks.length} items
          <ChevronDown size={14} />
        </span>
      </summary>
      <section className="policy-matrix">
        <div className="policy-matrix-list">
          {checks.map((check) => (
            <div
              className={`policy-matrix-row ${check.status} ${
                check.rule === winningRule ? "decisive" : ""
              }`}
              key={check.rule}
            >
              <span className="policy-status">{policyStatusLabel(check.status)}</span>
              <div>
                <strong>{check.label}</strong>
                <p>Observed: {formatObservedValue(check.observed_value)}</p>
                <p>Expected: {check.expected}</p>
              </div>
              {check.rule === winningRule ? (
                <span className="winning-rule">Decisive</span>
              ) : null}
            </div>
          ))}
        </div>
      </section>
    </details>
  );
}

function eventContainsCaseId(event: AuditEvent, caseId: string): boolean {
  return containsValue(event.payload, caseId);
}

function policyDecisionForEvent(event: AuditEvent, fallbackCase: RefundCase | null) {
  const reasonCodes = getStringArrayPayloadValue(event.payload, "reason_codes");
  return {
    decision: getTextPayloadValue(event.payload, "decision", fallbackCase?.decision ?? "unknown"),
    message: getTextPayloadValue(
      event.payload,
      "customer_message",
      fallbackCase?.customer_message ?? "",
    ),
    reasonCodes: reasonCodes.length > 0 ? reasonCodes : (fallbackCase?.reason_codes ?? []),
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

function getPolicyChecks(payload: Record<string, unknown>): PolicyCheck[] {
  const value = payload.policy_checks;
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter((item): item is PolicyCheck => {
    if (!item || typeof item !== "object") {
      return false;
    }
    const check = item as Record<string, unknown>;
    return (
      typeof check.rule === "string" &&
      typeof check.label === "string" &&
      ["passed", "failed", "not_applicable"].includes(String(check.status)) &&
      typeof check.expected === "string" &&
      typeof check.reason_code === "string" &&
      typeof check.citation === "string"
    );
  });
}

function policyStatusLabel(status: PolicyCheck["status"]): string {
  if (status === "not_applicable") {
    return "N/A";
  }
  return status === "passed" ? "Pass" : "Fail";
}

function formatObservedValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "none";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

interface AuditTurn {
  turnId: string;
  sessionId: string;
  turnSequence: number;
  firstEventId: number;
  events: AuditEvent[];
}

function buildCasesByTurn(
  events: AuditEvent[],
  refundCases: RefundCase[],
): Map<string, RefundCase[]> {
  const turns = new Map<string, AuditTurn>();
  for (const event of events) {
    if (!event.turn_id) {
      continue;
    }

    const existing = turns.get(event.turn_id);
    if (existing) {
      existing.events.push(event);
      existing.firstEventId = Math.min(existing.firstEventId, event.id);
      continue;
    }

    turns.set(event.turn_id, {
      turnId: event.turn_id,
      sessionId: event.session_id,
      turnSequence: event.turn_sequence ?? Number.MAX_SAFE_INTEGER,
      firstEventId: event.id,
      events: [event],
    });
  }

  const directCasesByTurn = new Map<string, RefundCase[]>();
  const result = new Map<string, RefundCase[]>();
  for (const turn of turns.values()) {
    const directCases = refundCases.filter((refundCase) =>
      turn.events.some((event) => eventContainsCaseId(event, refundCase.id)),
    );
    directCasesByTurn.set(turn.turnId, directCases);
    result.set(turn.turnId, [...directCases]);
  }

  const turnsBySession = new Map<string, AuditTurn[]>();
  for (const turn of turns.values()) {
    turnsBySession.set(turn.sessionId, [
      ...(turnsBySession.get(turn.sessionId) ?? []),
      turn,
    ]);
  }

  for (const sessionTurns of turnsBySession.values()) {
    sessionTurns.sort(
      (left, right) =>
        left.turnSequence - right.turnSequence || left.firstEventId - right.firstEventId,
    );

    for (const refundCase of refundCases) {
      if (refundCase.session_id !== sessionTurns[0]?.sessionId) {
        continue;
      }

      const anchorIndexes = sessionTurns
        .map((turn, index) =>
          (directCasesByTurn.get(turn.turnId) ?? []).some(
            (directCase) => directCase.id === refundCase.id,
          )
            ? index
            : -1,
        )
        .filter((index) => index >= 0);

      for (let anchor = 0; anchor < anchorIndexes.length - 1; anchor += 1) {
        const start = anchorIndexes[anchor];
        const end = anchorIndexes[anchor + 1];
        const gapHasDifferentCase = sessionTurns
          .slice(start + 1, end)
          .some((turn) =>
            (directCasesByTurn.get(turn.turnId) ?? []).some(
              (directCase) => directCase.id !== refundCase.id,
            ),
          );
        if (gapHasDifferentCase) {
          continue;
        }

        for (const turn of sessionTurns.slice(start + 1, end)) {
          if ((directCasesByTurn.get(turn.turnId) ?? []).length > 0) {
            continue;
          }
          result.set(turn.turnId, [...(result.get(turn.turnId) ?? []), refundCase]);
        }
      }
    }
  }

  return result;
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

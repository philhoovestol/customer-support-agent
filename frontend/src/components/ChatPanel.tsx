import { Loader2, RefreshCcw, Send } from "lucide-react";
import type { FormEvent, KeyboardEvent } from "react";

import type { ChatMessage, PolicyResult } from "../types";

interface ChatPanelProps {
  messages: ChatMessage[];
  input: string;
  sessionId: string | null;
  policyResult: PolicyResult | null;
  loading: boolean;
  error: string | null;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onReset: () => void;
}

export function ChatPanel({
  messages,
  input,
  sessionId,
  policyResult,
  loading,
  error,
  onInputChange,
  onSend,
  onReset,
}: ChatPanelProps) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSend();
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }

    event.preventDefault();

    if (!loading && input.trim()) {
      onSend();
    }
  }

  return (
    <section className="workspace-panel chat-panel">
      <header className="panel-header">
        <div>
          <p className="eyebrow">Customer Console</p>
        </div>
        <button className="icon-button" type="button" onClick={onReset} title="New session">
          <RefreshCcw size={18} />
        </button>
      </header>

      <div className="session-strip">
        <span>{sessionId ?? "new session"}</span>
        {policyResult ? <DecisionBadge decision={policyResult.decision} /> : null}
      </div>

      <div className="chat-scroll">
        {messages.map((message) => (
          <article className={`message ${message.role}`} key={message.id}>
            <span>{message.role === "customer" ? "Customer" : "Agent"}</span>
            <p>{message.content}</p>
          </article>
        ))}
        {messages.length === 0 ? (
          <div className="empty-chat">
            <p>Start with an order number such as ORD-1002.</p>
          </div>
        ) : null}
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      <form className="composer" onSubmit={submit}>
        <textarea
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
          onKeyDown={handleComposerKeyDown}
          placeholder="Customer refund message"
          rows={3}
        />
        <button className="send-button" type="submit" disabled={loading || !input.trim()} title="Send">
          {loading ? <Loader2 className="spin" size={18} /> : <Send size={18} />}
          <span>Send</span>
        </button>
      </form>
    </section>
  );
}

function DecisionBadge({ decision }: { decision: string }) {
  return <span className={`decision-badge ${decision}`}>{decision.replaceAll("_", " ")}</span>;
}

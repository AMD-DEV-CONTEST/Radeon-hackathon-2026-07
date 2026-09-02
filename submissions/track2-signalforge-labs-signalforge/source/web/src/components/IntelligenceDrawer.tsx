import { useEffect, useRef, useState } from "react";
import { getIntelligence, getProtectedIntelligence, purgeProtectedIntelligence } from "../api";
import type {
  EngineCallAudit,
  IntelligenceRecord,
  LifecycleAudit,
  ModelCallAudit,
  ProtectedIntelligenceRecord,
  RetrievalAudit
} from "../types";
import { CheckIcon, CloseIcon, ShieldIcon } from "./Icons";

type InspectorTab = "pipeline" | "trace" | "evidence" | "engines" | "prompts";

type Props = {
  runID: string;
  traceID?: string;
  open: boolean;
  protectedCapture: boolean;
  onClose: () => void;
};

export function IntelligenceDrawer({ runID, traceID, open, protectedCapture, onClose }: Props) {
  const [record, setRecord] = useState<IntelligenceRecord | null>(null);
  const [protectedRecord, setProtectedRecord] = useState<ProtectedIntelligenceRecord | null>(null);
  const [tab, setTab] = useState<InspectorTab>("pipeline");
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "denied" | "error" | "purged">("idle");
  const closeButton = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (open && !wasOpen.current) {
      returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      closeButton.current?.focus();
    } else if (!open && wasOpen.current) {
      returnFocus.current?.focus();
    }
    wasOpen.current = open;
  }, [open]);

  useEffect(() => {
    if (!open) {
      setProtectedRecord(null);
      setToken("");
      return;
    }
    let active = true;
    setStatus("loading");
    setRecord(null);
    setProtectedRecord(null);
    setToken("");
    getIntelligence(runID).then((next) => {
      if (!active) return;
      if (!sameIdentity(next, runID, traceID)) {
        setStatus("error");
        return;
      }
      setRecord(next);
      setStatus("ready");
    }).catch(() => {
      if (active) setStatus("error");
    });
    return () => { active = false; };
  }, [open, runID, traceID]);

  async function unlock() {
    if (!token.trim()) return;
    setStatus("loading");
    try {
      setProtectedRecord(await getProtectedIntelligence(runID, token));
      setStatus("ready");
    } catch {
      setProtectedRecord(null);
      setStatus("denied");
    }
  }

  async function purge() {
    try {
      await purgeProtectedIntelligence(runID, token);
      setProtectedRecord(null);
      setToken("");
      const next = await getIntelligence(runID);
      if (!sameIdentity(next, runID, traceID)) throw new Error("lineage identity mismatch");
      setRecord(next);
      setStatus("purged");
    } catch {
      setStatus("denied");
    }
  }

  return (
    <>
      <button className={`drawer-scrim intelligence-scrim ${open ? "is-open" : ""}`} onClick={onClose} aria-label="Dismiss intelligence overlay" tabIndex={open ? 0 : -1} />
      <aside className={`intelligence-drawer ${open ? "is-open" : ""}`} role="dialog" aria-modal="true" aria-labelledby="intelligence-title" aria-hidden={!open} inert={!open}>
        <header>
          <div>
            <span className="eyebrow">Radeon Mission Control</span>
            <h2 id="intelligence-title">Intelligence lineage.</h2>
            <p>Every agent, source, engine, and release decision tied to one run.</p>
          </div>
          <button ref={closeButton} className="icon-button" onClick={onClose} aria-label="Close intelligence inspector"><CloseIcon /></button>
        </header>

        <div className="intelligence-tabs" role="tablist" aria-label="Intelligence views">
          {(["pipeline", "trace", "evidence", "engines", "prompts"] as InspectorTab[]).map((item) => (
            <button key={item} role="tab" aria-selected={tab === item} onClick={() => setTab(item)}>{item}</button>
          ))}
        </div>

        <div className="intelligence-body">
          {status === "loading" && !record && <InspectorState title="Loading lineage" detail="Reading the privacy-safe execution record." />}
          {status === "error" && <InspectorState title="Lineage unavailable" detail="The answer remains available; observability failed independently." />}
          {record && <RunHeader record={record} />}
          {record && tab === "pipeline" && <Pipeline record={record} />}
          {record && tab === "trace" && <TraceTimeline record={record} />}
          {record && tab === "evidence" && <Retrievals items={record.retrievals} />}
          {record && tab === "engines" && <Engines items={record.engine_calls} />}
          {record && tab === "prompts" && (
            <ProtectedPanel
              record={record}
              protectedRecord={protectedRecord}
              protectedCapture={protectedCapture}
              operatorToken={token}
              status={status}
              onToken={setToken}
              onUnlock={() => void unlock()}
              onPurge={() => void purge()}
            />
          )}
        </div>

        <footer>
          <ShieldIcon />
          <span>Telemetry excludes prompt bodies, answers, credentials, private memory, and raw financial values by default.</span>
        </footer>
      </aside>
    </>
  );
}

function sameIdentity(record: IntelligenceRecord, runID: string, traceID?: string): boolean {
  return record.run_id === runID && (!traceID || record.trace_id === traceID);
}

function TraceTimeline({ record }: { record: IntelligenceRecord }) {
  const timeline = record.timeline ?? [];
  if (timeline.length === 0) {
    return <InspectorState title="No correlated lifecycle trace" detail="This historical record predates the bounded orchestration timeline." />;
  }
  return (
    <section className="judge-trace" aria-label="Judge-facing correlated execution trace">
      <header>
        <div>
          <span className="eyebrow">Same journey · bounded operational facts</span>
          <h3>Conversation-to-trace timeline</h3>
        </div>
        <code>{shortID(record.trace_id)}</code>
      </header>
      <ol>
        {timeline.map((event) => <TraceEvent key={`${event.sequence}-${event.event_type}-${event.step_id ?? "run"}`} event={event} />)}
      </ol>
    </section>
  );
}

function TraceEvent({ event }: { event: LifecycleAudit }) {
  const statusClass = event.status.replaceAll("_", "-");
  const counts = [
    event.specialist_count ? `${event.specialist_count} specialists` : "",
    event.concurrency_limit ? `limit ${event.concurrency_limit}` : "",
    event.succeeded_count ? `${event.succeeded_count} passed` : "",
    event.failed_count ? `${event.failed_count} failed` : "",
    event.observed_concurrency ? `concurrency ${event.observed_concurrency}` : ""
  ].filter(Boolean);
  return (
    <li className={`trace-event status-${statusClass}`}>
      <span className="trace-sequence">{String(event.sequence).padStart(2, "0")}</span>
      <div>
        <span className="eyebrow">
          {humanize(event.event_type)}
          {event.wave ? ` · wave ${event.wave}` : ""}
        </span>
        <strong>{humanize(event.step_id ?? "run")}</strong>
        <small>
          {event.role_id ? humanize(event.role_id) : "Runtime authority"}
          {event.route ? ` · ${humanize(event.route)}` : ""}
          {counts.length > 0 ? ` · ${counts.join(" · ")}` : ""}
        </small>
      </div>
      <span className="trace-status">{humanize(event.status)}</span>
      <time dateTime={event.at}>{formatDateTime(event.at)}</time>
    </li>
  );
}

function RunHeader({ record }: { record: IntelligenceRecord }) {
  return (
    <section className="intelligence-run">
      <div><span>Run</span><code>{shortID(record.run_id)}</code></div>
      <div><span>Trace</span><code>{shortID(record.trace_id)}</code></div>
      <div><span>Route</span><strong>{routeSummary(record)}</strong></div>
      <div><span>Capture</span><strong className={`capture-state ${record.capture.status}`}>{record.capture.status}</strong></div>
    </section>
  );
}

function Pipeline({ record }: { record: IntelligenceRecord }) {
  const modelCalls = record.model_calls ?? [];
  const retrievals = record.retrievals ?? [];
  const engineCalls = record.engine_calls ?? [];
  if (modelCalls.length === 0 && retrievals.length === 0 && engineCalls.length === 0) {
    return <InspectorState title="No model calls in this replay" detail="Fixture mode still exposes deterministic retrieval, engine, and release lineage when present." />;
  }
  const modelTokens = modelCalls.reduce((sum, call) => sum + call.input_tokens + call.output_tokens, 0);
  return (
    <>
      <section className="lineage-stats">
        <Stat value={modelCalls.length} label="Model calls" />
        <Stat value={retrievals.length} label="Context packets" />
        <Stat value={engineCalls.length} label="Engine receipts" />
        <Stat value={modelTokens} label="Observed tokens" />
      </section>
      <div className="pipeline-list">
        {modelCalls.map((call, index) => <ModelCall key={call.model_call_id} call={call} index={index} />)}
        {record.release && (
          <article className="pipeline-card release">
            <div className="pipeline-index"><CheckIcon /></div>
            <div className="pipeline-main"><span className="eyebrow">Release authority</span><strong>{humanize(record.release.status)}</strong><small>{record.release.evidence_refs?.length ?? 0} evidence · {record.release.receipt_refs?.length ?? 0} receipts · {record.release.claim_refs?.length ?? 0} answer-used claims</small></div>
          </article>
        )}
      </div>
    </>
  );
}

function ModelCall({ call, index }: { call: ModelCallAudit; index: number }) {
  return (
    <article className="pipeline-card">
      <div className="pipeline-index">{String(index + 1).padStart(2, "0")}</div>
      <div className="pipeline-main">
        <span className="eyebrow">{humanize(call.role_class)} · {humanize(call.route)}</span>
        <strong>{humanize(call.role_id)}</strong>
        <small>{call.model_id} · {formatDuration(call.duration_ms)} · TTFT {formatDuration(call.ttft_ms)}</small>
      </div>
      <div className="token-pair"><span>{call.input_tokens}<small>in</small></span><span>{call.output_tokens}<small>out</small></span></div>
      <details>
        <summary>Contract hashes</summary>
        <code>prompt {shortID(call.request_payload_sha256)}</code>
        <code>system {shortID(call.system_prompt_sha256)}</code>
        {call.response_payload_sha256 && <code>output {shortID(call.response_payload_sha256)}</code>}
      </details>
    </article>
  );
}

function Retrievals({ items }: { items: RetrievalAudit[] | null | undefined }) {
  const safeItems = items ?? [];
  if (safeItems.length === 0) return <InspectorState title="No retrieval records" detail="This run did not compile a governed context packet." />;
  return <div className="audit-grid">{safeItems.map((item) => (
    <article className="audit-card" key={item.retrieval_id}>
      <span className="audit-status">{humanize(item.status)}</span>
      <h3>{humanize(item.role_id)}</h3>
      <p>{humanize(item.method)} · {item.estimated_tokens} estimated tokens</p>
      <AuditPair label="Context packet" value={item.context_packet_id} />
      <AuditList label="Evidence" items={item.evidence_ids} />
      {(item.evidence_sources?.length ?? 0) > 0 && (
        <details className="source-lineage">
          <summary>Source lineage · {item.evidence_sources?.length}</summary>
          {item.evidence_sources?.map((source) => (
            <div key={source.evidence_id}>
              <strong>{humanize(source.source_type)}</strong>
              <code>{source.locator}</code>
              {source.document_section && <small>{source.document_section}</small>}
              <small>{shortID(source.content_sha256)} · {formatDateTime(source.as_of)}</small>
            </div>
          ))}
        </details>
      )}
      <AuditList label="Documents" items={item.document_ids ?? []} />
      <AuditList label="Graph traversals" items={item.graph_traversal_ids ?? []} />
      {(item.dropped_ids?.length ?? 0) > 0 && <AuditList label="Rejected" items={item.dropped_ids ?? []} />}
    </article>
  ))}</div>;
}

function Engines({ items }: { items: EngineCallAudit[] | null | undefined }) {
  const safeItems = items ?? [];
  if (safeItems.length === 0) return <InspectorState title="No deterministic receipts" detail="No financial engine was required for this journey." />;
  return <div className="audit-grid">{safeItems.map((item) => (
    <article className="audit-card engine-audit-card" key={item.engine_call_id}>
      <span className="audit-status"><CheckIcon /> {item.invariants_passed}/{item.invariants_total} invariants</span>
      <h3>{humanize(item.operation_id)}</h3>
      <p>{item.engine_id} {item.engine_version} · formula {item.formula_version}</p>
      <AuditPair label="Receipt" value={shortID(item.receipt_id)} />
      <AuditPair label="Receipt hash" value={shortID(item.receipt_sha256)} />
      <AuditList label="Inputs" items={item.input_refs} />
      <AuditList label="Outputs" items={item.output_refs} />
      <AuditList label="Evidence" items={item.evidence_refs ?? []} />
    </article>
  ))}</div>;
}

function ProtectedPanel({ record, protectedRecord, protectedCapture, operatorToken, status, onToken, onUnlock, onPurge }: {
  record: IntelligenceRecord;
  protectedRecord: ProtectedIntelligenceRecord | null;
  protectedCapture: boolean;
  operatorToken: string;
  status: string;
  onToken: (value: string) => void;
  onUnlock: () => void;
  onPurge: () => void;
}) {
  if (!protectedCapture || !record.capture.enabled) {
    return <InspectorState title="Protected capture is off" detail="This is the default. Enable it explicitly with a file-mounted operator token for a short diagnostic session." />;
  }
  if (!record.capture.available) {
    return <InspectorState title={`Protected capture ${record.capture.status}`} detail="Metadata and hashes remain available; body artifacts cannot be recovered." />;
  }
  if (!protectedRecord) {
    return (
      <section className="audit-unlock">
        <ShieldIcon />
        <span className="eyebrow">Local operator authorization</span>
        <h3>Unlock sanitized model I/O.</h3>
        <p>The token remains only in this component's memory. It is never stored in the browser or emitted to telemetry.</p>
        <form onSubmit={(event) => { event.preventDefault(); onUnlock(); }}>
          <input type="password" value={operatorToken} onChange={(event) => onToken(event.target.value)} autoComplete="off" placeholder="Ephemeral audit token" aria-label="Protected audit token" />
          <button disabled={!operatorToken.trim() || status === "loading"}>Unlock</button>
        </form>
        {status === "denied" && <p className="audit-denied" role="alert">Authorization failed or the capture expired.</p>}
        <small>Expires {formatDateTime(record.capture.expires_at)}</small>
      </section>
    );
  }
  return (
    <section className="protected-record">
      <header><div><span className="eyebrow">Authorized diagnostic view</span><h3>Sanitized inputs and outputs</h3></div><button onClick={onPurge}>Purge now</button></header>
      <div className="protected-question"><span>Interpreted request</span><pre>{protectedRecord.question}</pre></div>
      {(protectedRecord.model_calls ?? []).map((call) => (
        <details className="protected-call" key={call.model_call_id}>
          <summary>{call.parameters.model}<span>{call.parameters.max_tokens} token budget</span></summary>
          {call.messages.map((message, index) => <div key={`${message.role}-${index}`}><span>{message.role}</span><pre>{message.content}</pre></div>)}
          {call.raw_output && <div><span>Structured model output</span><pre>{call.raw_output}</pre></div>}
        </details>
      ))}
      {(protectedRecord.model_calls?.length ?? 0) === 0 && <InspectorState title="No model bodies in this run" detail="The protected request remains available, but fixture replay made no model call." />}
      <small>Automatic expiry: {formatDateTime(protectedRecord.expires_at)}</small>
    </section>
  );
}

function InspectorState({ title, detail }: { title: string; detail: string }) {
  return <section className="inspector-state"><span className="forge-loader"><i /><i /><i /></span><strong>{title}</strong><p>{detail}</p></section>;
}

function Stat({ value, label }: { value: number; label: string }) {
  return <div><strong>{value.toLocaleString("en-US")}</strong><span>{label}</span></div>;
}

function AuditPair({ label, value }: { label: string; value: string }) {
  return <div className="audit-pair"><span>{label}</span><code>{value}</code></div>;
}

function AuditList({ label, items }: { label: string; items: string[] | null | undefined }) {
  const safeItems = items ?? [];
  if (safeItems.length === 0) return null;
  return <div className="audit-list"><span>{label}</span><div>{safeItems.map((item) => <code key={item}>{shortID(item)}</code>)}</div></div>;
}

function routeSummary(record: IntelligenceRecord) {
  const routes = new Set((record.model_calls ?? []).map((call) => call.route));
  if (routes.size === 0) return "deterministic / fixture";
  return Array.from(routes).map(humanize).join(" + ");
}

function humanize(value: string) {
  return value.replace(/[._:/-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function shortID(value: string) {
  if (value.length <= 24) return value;
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}

function formatDuration(value: number) {
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

function formatDateTime(value?: string) {
  if (!value) return "not retained";
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

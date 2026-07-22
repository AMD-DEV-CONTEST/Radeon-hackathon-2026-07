import { useDeferredValue, useState } from "react";
import type { CalculationCard, EvidenceCard, Projection } from "../types";
import { CheckIcon, CloseIcon, DocumentIcon, ReceiptIcon, ShieldIcon } from "./Icons";

type Props = {
  projection: Projection;
  open: boolean;
  tab: "evidence" | "calculations";
  refs: string[];
  onTab: (tab: Props["tab"]) => void;
  onClose: () => void;
};

export function ProofDrawer({ projection, open, tab, refs, onTab, onClose }: Props) {
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.toLowerCase());
  const evidence = projection.evidence.filter((item) =>
    (refs.length === 0 || refs.includes(item.evidence_id)) && searchableEvidence(item).includes(deferredQuery)
  );
  const calculations = projection.calculations.filter((item) =>
    (refs.length === 0 || refs.includes(item.receipt_id)) && searchableCalculation(item).includes(deferredQuery)
  );
  return (
    <>
      <button className={`drawer-scrim ${open ? "is-open" : ""}`} onClick={onClose} aria-label="Close proof drawer" tabIndex={open ? 0 : -1} />
      <aside className={`proof-drawer ${open ? "is-open" : ""}`} aria-label="Evidence and calculation proof" aria-hidden={!open} inert={!open}>
        <header>
          <div><span className="eyebrow">Proof layer</span><h2>Inspect the work.</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Close proof drawer"><CloseIcon /></button>
        </header>
        <div className="proof-tabs" role="tablist">
          <button role="tab" aria-selected={tab === "evidence"} onClick={() => onTab("evidence")}><DocumentIcon /> Evidence <span>{evidence.length}</span></button>
          <button role="tab" aria-selected={tab === "calculations"} onClick={() => onTab("calculations")}><ReceiptIcon /> Receipts <span>{calculations.length}</span></button>
        </div>
        <label className="proof-search"><span className="sr-only">Search proof items</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter this proof set" /></label>
        <div className="proof-list">
          {tab === "evidence" ? evidence.map((item) => <EvidenceItem key={item.evidence_id} item={item} />) : calculations.map((item) => <CalculationItem key={item.receipt_id} item={item} />)}
          {((tab === "evidence" && evidence.length === 0) || (tab === "calculations" && calculations.length === 0)) && <p className="empty-proof">No proof items match this filter.</p>}
        </div>
        <footer><ShieldIcon /><span>Only answer-used evidence and successful receipts cross this boundary.</span></footer>
      </aside>
    </>
  );
}

function EvidenceItem({ item }: { item: EvidenceCard }) {
  return (
    <details className="proof-card">
      <summary><span className="proof-kind">{humanize(item.source_type)}</span><strong>{humanize(item.evidence_id)}</strong><small>{item.used_in_sections.map(humanize).join(" / ")}</small></summary>
      <div className="proof-details">
        <div className="proof-pair"><span>Locator</span>{isURL(item.locator) ? <a href={item.locator} target="_blank" rel="noreferrer">Open primary source</a> : <code>{item.locator}</code>}</div>
        {item.document_section && <Pair label="Section" value={item.document_section} />}
        <Pair label="As of" value={formatDate(item.as_of)} />
        <Pair label="Content hash" value={shortHash(item.content_sha256)} mono />
      </div>
    </details>
  );
}

function CalculationItem({ item }: { item: CalculationCard }) {
  return (
    <details className="proof-card receipt-card">
      <summary><span className="proof-kind success"><CheckIcon /> Verified</span><strong>{humanize(item.operation_id)}</strong><small>{item.engine_id} engine · formula {item.formula_version}</small></summary>
      <div className="receipt-outputs">
        {item.outputs.map((output) => <div key={output.output_id}><span>{humanize(output.output_id)}</span><strong>{formatQuantity(output.quantity.value, output.quantity.unit)}</strong></div>)}
      </div>
      <div className="proof-details">
        <Pair label="Receipt" value={shortHash(item.receipt_sha256)} mono />
        <Pair label="Source as of" value={formatDate(item.source_as_of)} />
        <Pair label="Invariants" value={`${item.invariant_results.filter((check) => check.passed).length}/${item.invariant_results.length} passed`} />
      </div>
    </details>
  );
}

function Pair({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="proof-pair"><span>{label}</span><code className={mono ? "mono" : ""}>{value}</code></div>;
}

function formatQuantity(value: string, unit: string) {
  const [integer, decimal = ""] = value.split(".");
  const signed = integer.startsWith("-") ? integer.slice(1) : integer;
  const grouped = signed.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const exact = `${integer.startsWith("-") ? "-" : ""}${grouped}${decimal ? `.${decimal.slice(0, 4).replace(/0+$/, "")}` : ""}`.replace(/\.$/, "");
  const units: Record<string, string> = { ratio: "x", percent: "%", USD: " USD", usd: " USD" };
  return exact + (units[unit] ?? ` ${unit}`);
}

function humanize(value: string) {
  return value.replace(/[._:-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(value));
}

function shortHash(value: string) {
  return `${value.slice(0, 12)}...${value.slice(-8)}`;
}

function searchableEvidence(item: EvidenceCard) {
  return `${item.evidence_id} ${item.source_type} ${item.locator} ${item.document_section ?? ""}`.toLowerCase();
}

function searchableCalculation(item: CalculationCard) {
  return `${item.receipt_id} ${item.operation_id} ${item.engine_id} ${item.outputs.map((output) => output.output_id).join(" ")}`.toLowerCase();
}

function isURL(value: string) {
  return value.startsWith("https://") || value.startsWith("http://");
}

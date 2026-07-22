import { useEffect, useState } from "react";
import { caseExportURL, deleteCase, getCase, listCases } from "../api";
import { displayCaseTitle } from "../format";
import type { CaseSummary, Projection, RetentionView } from "../types";
import { ArrowIcon, ShieldIcon } from "./Icons";

type Props = {
  available: boolean;
  retain: boolean;
  retention?: RetentionView;
  open: boolean;
  onRetain: (value: boolean) => void;
  onOpen: () => void;
  onClose: () => void;
  onLoad: (projection: Projection) => void;
};

export function MemoryControls({ available, retain, retention, open, onRetain, onOpen, onClose, onLoad }: Props) {
  return (
    <>
      <section className="memory-controls" aria-label="Local case memory">
        <label className={!available ? "is-disabled" : ""}>
          <input type="checkbox" checked={retain} disabled={!available} onChange={(event) => onRetain(event.target.checked)} />
          <span><strong>Save this case locally</strong><small>Off by default. Stores the released audit snapshot, never private model traces.</small></span>
        </label>
        <div className={`retention-state status-${retention?.status ?? "not_requested"}`}>
          <ShieldIcon />
          <span>{retentionLabel(available, retention)}</span>
        </div>
        <button className="library-button" aria-label="Open saved cases" disabled={!available} onClick={onOpen}>Case library <ArrowIcon /></button>
      </section>
      <CaseLibrary open={open} onClose={onClose} onLoad={onLoad} />
    </>
  );
}

function CaseLibrary({ open, onClose, onLoad }: Pick<Props, "open" | "onClose" | "onLoad">) {
  const [items, setItems] = useState<CaseSummary[]>([]);
  const [failure, setFailure] = useState("");
  const [pendingDelete, setPendingDelete] = useState("");

  useEffect(() => {
    if (!open) return;
    setFailure("");
    void listCases().then(setItems).catch(() => setFailure("The local case index is temporarily unavailable."));
  }, [open]);

  async function inspect(caseID: string) {
    try {
      const stored = await getCase(caseID);
      onLoad(stored.case);
      onClose();
    } catch {
      setFailure("This case could not be verified and was not opened.");
    }
  }

  async function remove(caseID: string) {
    if (pendingDelete !== caseID) {
      setPendingDelete(caseID);
      return;
    }
    try {
      await deleteCase(caseID);
      setItems((current) => current.filter((item) => item.case_id !== caseID));
      setPendingDelete("");
    } catch {
      setFailure("The case could not be deleted safely.");
    }
  }

  return (
    <>
      <button className={`library-scrim ${open ? "is-open" : ""}`} aria-label="Close case library" tabIndex={open ? 0 : -1} onClick={onClose} />
      <aside className={`case-library ${open ? "is-open" : ""}`} aria-hidden={!open} inert={!open}>
        <header><div><span className="eyebrow">Private local retention</span><h2>Research case library</h2></div><button className="icon-button" onClick={onClose} aria-label="Close case library">×</button></header>
        <div className="library-principle"><ShieldIcon /><p><strong>Published snapshots, not model memory.</strong> Every case is hash-verified on read. Future calculations still resolve from canonical evidence and receipts.</p></div>
        {failure && <p className="library-failure" role="alert">{failure}</p>}
        <div className="library-list">
          {items.length === 0 && !failure && <p className="empty-proof">No cases have been saved on this device.</p>}
          {items.map((item) => <article key={item.case_id}>
            <span className="eyebrow">{new Date(item.saved_at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}</span>
            <h3>{displayCaseTitle(item.title)}</h3>
            <p>{item.evidence_items} evidence references · {item.calculation_receipts} deterministic receipts</p>
            <code>{item.projection_sha256.slice(0, 16)}…</code>
            <div>
              <button onClick={() => void inspect(item.case_id)}>Inspect</button>
              <a href={caseExportURL(item.case_id)} download>Export</a>
              <button className={pendingDelete === item.case_id ? "confirm-delete" : ""} onClick={() => void remove(item.case_id)}>{pendingDelete === item.case_id ? "Confirm delete" : "Delete"}</button>
            </div>
          </article>)}
        </div>
      </aside>
    </>
  );
}

function retentionLabel(available: boolean, retention?: RetentionView): string {
  if (!available) return "Durable memory disabled for this runtime";
  if (!retention || retention.status === "not_requested") return "Ephemeral session · nothing retained";
  if (retention.status === "pending") return "Local save pending";
  if (retention.status === "saved") return "Audit snapshot saved locally";
  return "Analysis completed · local save did not succeed";
}

import { Download, FileArchive, FileDown, LockKeyhole } from "lucide-react";
import { useState } from "react";

import { Button } from "../../components/ui/Button";
import {
  businessDownloadUrl,
  downloadArtifact,
  evidenceDownloadUrl,
} from "../../lib/api";
import type { Approval, Revision } from "../../lib/types";

interface ExportPanelProps {
  revision: Revision;
  approval?: Approval;
  onBusinessExported: () => Promise<void>;
}

export function ExportPanel({ revision, approval, onBusinessExported }: ExportPanelProps) {
  const [active, setActive] = useState<"business" | "evidence">();
  const [error, setError] = useState<string>();
  const directExport = revision.status === "exportable";
  const approvedExport =
    revision.status === "approved" && approval?.status === "approved" && !approval.consumed;
  const businessEnabled = directExport || approvedExport;
  const evidenceEnabled = directExport || revision.status === "approved";

  async function run(kind: "business" | "evidence") {
    setActive(kind);
    setError(undefined);
    try {
      const url =
        kind === "business"
          ? businessDownloadUrl(revision.id, approvedExport ? approval?.id : undefined)
          : evidenceDownloadUrl(revision.id);
      await downloadArtifact(url);
      if (kind === "business") await onBusinessExported();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The local export failed.");
    } finally {
      setActive(undefined);
    }
  }

  return (
    <section className="operation-panel export-panel" aria-labelledby="export-title">
      <header className="operation-panel__heading">
        <span className="operation-panel__icon" aria-hidden="true"><FileDown size={17} /></span>
        <div>
          <h3 id="export-title">Export</h3>
          <p>Business output and audit evidence stay separate</p>
        </div>
      </header>

      {!businessEnabled && !evidenceEnabled ? (
        <p className="operation-message">
          <LockKeyhole size={15} aria-hidden="true" /> Downloads remain locked in this state.
        </p>
      ) : null}
      {approvedExport ? (
        <p className="operation-message operation-message--warning">
          <LockKeyhole size={15} aria-hidden="true" /> Business output uses this approval once.
        </p>
      ) : null}
      {error ? <p className="operation-error" role="alert">{error}</p> : null}

      <div className="operation-panel__actions">
        <Button
          disabled={!businessEnabled || Boolean(active)}
          icon={<Download size={15} aria-hidden="true" />}
          onClick={() => void run("business")}
          variant="primary"
        >
          {active === "business" ? "Preparing" : "Business output"}
        </Button>
        <Button
          disabled={!evidenceEnabled || Boolean(active)}
          icon={<FileArchive size={15} aria-hidden="true" />}
          onClick={() => void run("evidence")}
        >
          {active === "evidence" ? "Preparing" : "Evidence package"}
        </Button>
      </div>
    </section>
  );
}

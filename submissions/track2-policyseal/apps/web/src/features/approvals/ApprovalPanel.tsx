import { Clock3, ShieldCheck, ShieldX, UserCheck, UserRound } from "lucide-react";

import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import type { Approval, DemoRole, DisclosureTask, Revision } from "../../lib/types";
import { formatDate, titleCase } from "../../lib/utils";

interface ApprovalPanelProps {
  task: DisclosureTask;
  revision: Revision;
  role: DemoRole;
  approval?: Approval;
  busy?: boolean;
  error?: string;
  onRequest: () => Promise<void>;
  onResolve: (operation: "approve" | "reject") => Promise<void>;
}

function approvalTone(approval: Approval): "success" | "warning" | "danger" | "neutral" {
  if (approval.status === "approved" || approval.status === "consumed") return "success";
  if (approval.status === "pending") return "warning";
  if (approval.status === "rejected" || approval.status === "expired") return "danger";
  return "neutral";
}

export function ApprovalPanel({
  task,
  revision,
  role,
  approval,
  busy = false,
  error,
  onRequest,
  onResolve,
}: ApprovalPanelProps) {
  const pending = approval?.status === "pending";
  const requester = role === "requester";
  const blocked = revision.status === "blocked";

  return (
    <section className="operation-panel approval-panel" aria-labelledby="approval-title">
      <header className="operation-panel__heading">
        <span className="operation-panel__icon" aria-hidden="true"><UserCheck size={17} /></span>
        <div>
          <h3 id="approval-title">Approval</h3>
          <p>Exact revision binding / separate reviewer</p>
        </div>
        {approval ? <Badge tone={approvalTone(approval)}>{titleCase(approval.status)}</Badge> : null}
      </header>

      {blocked ? (
        <p className="operation-message operation-message--danger">
          <ShieldX size={15} aria-hidden="true" /> Policy Block cannot enter approval.
        </p>
      ) : approval ? (
        <dl className="approval-facts">
          <div><dt>Binding</dt><dd>{approval.binding_sha256.slice(0, 16)}...</dd></div>
          <div><dt>Requester</dt><dd>{approval.requester_id}</dd></div>
          <div><dt>Expires</dt><dd>{formatDate(approval.expires_at)}</dd></div>
        </dl>
      ) : revision.status === "awaiting_approval" ? (
        <p className="operation-message">
          <Clock3 size={15} aria-hidden="true" /> The output is held until a request is reviewed.
        </p>
      ) : (
        <p className="operation-message operation-message--success">
          <ShieldCheck size={15} aria-hidden="true" /> No reviewer approval is required for this revision.
        </p>
      )}

      {error ? <p className="operation-error" role="alert">{error}</p> : null}

      <div className="operation-panel__actions">
        {revision.status === "awaiting_approval" && !approval && requester ? (
          <Button
            disabled={busy}
            icon={<UserRound size={15} aria-hidden="true" />}
            onClick={() => void onRequest()}
            variant="primary"
          >
            {busy ? "Requesting" : "Request approval"}
          </Button>
        ) : null}
        {revision.status === "awaiting_approval" && !approval && !requester ? (
          <span className="operation-hint">Waiting for {task.requester_id} to submit.</span>
        ) : null}
        {pending && requester ? (
          <span className="operation-hint">Self-approval unavailable. Switch to the synthetic reviewer.</span>
        ) : null}
        {pending && !requester ? (
          <>
            <Button disabled={busy} onClick={() => void onResolve("reject")} variant="danger">
              Reject
            </Button>
            <Button
              disabled={busy}
              icon={<ShieldCheck size={15} aria-hidden="true" />}
              onClick={() => void onResolve("approve")}
              variant="primary"
            >
              {busy ? "Resolving" : "Approve exact revision"}
            </Button>
          </>
        ) : null}
      </div>
    </section>
  );
}

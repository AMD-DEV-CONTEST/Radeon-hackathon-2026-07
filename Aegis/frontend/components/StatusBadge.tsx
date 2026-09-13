const STATUS_LABELS: Record<string, string> = {
  triggered: "Triggered",
  investigating: "Investigating",
  root_cause_identified: "Root cause found",
  remediation_pending_approval: "Awaiting approval",
  remediating: "Remediating",
  resolved: "Resolved",
  failed: "Failed",
};

export function StatusBadge({ status }: { status: string }) {
  return <span className="status-badge">{STATUS_LABELS[status] ?? status}</span>;
}

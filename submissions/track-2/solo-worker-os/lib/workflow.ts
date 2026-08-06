export interface WorkflowCheck {
  label: string;
  key: string;
}

export interface WorkflowStage {
  key: string;
  label: string;
  color: string;
  checks: WorkflowCheck[];
}

export const WORKFLOW_STAGES: WorkflowStage[] = [
  {
    key: 'kickoff',
    label: 'Kickoff',
    color: 'amber',
    checks: [
      { key: 'brief_received',   label: 'Brief / requirements received' },
      { key: 'timeline_agreed',  label: 'Timeline & milestones agreed' },
      { key: 'deposit_invoiced', label: 'Deposit invoice sent' },
    ],
  },
  {
    key: 'in_progress',
    label: 'In Progress',
    color: 'blue',
    checks: [
      { key: 'work_started',     label: 'Work started' },
      { key: 'draft_complete',   label: 'First draft / version complete' },
      { key: 'internal_review',  label: 'Internal review done' },
    ],
  },
  {
    key: 'review',
    label: 'Client Review',
    color: 'violet',
    checks: [
      { key: 'sent_to_client',    label: 'Draft sent to client' },
      { key: 'feedback_received', label: 'Client feedback received' },
      { key: 'revisions_applied', label: 'Revisions applied' },
    ],
  },
  {
    key: 'delivery',
    label: 'Delivery',
    color: 'teal',
    checks: [
      { key: 'final_sent',   label: 'Final deliverables sent' },
      { key: 'signoff',      label: 'Client sign-off received' },
      { key: 'assets_filed', label: 'Project assets filed / archived' },
    ],
  },
  {
    key: 'invoiced',
    label: 'Invoice',
    color: 'orange',
    checks: [
      { key: 'invoice_sent',      label: 'Final invoice sent' },
      { key: 'payment_terms_set', label: 'Payment terms confirmed' },
    ],
  },
  {
    key: 'paid',
    label: 'Paid',
    color: 'emerald',
    checks: [
      { key: 'payment_received', label: 'Payment received' },
      { key: 'receipt_sent',     label: 'Receipt / thank-you sent' },
    ],
  },
];

export const STAGE_ORDER = WORKFLOW_STAGES.map((s) => s.key);

export function getStageIndex(stageKey: string): number {
  return STAGE_ORDER.indexOf(stageKey);
}

/** Checks map: { [stage_check_key]: boolean } */
export type ChecksMap = Record<string, boolean>;

/** Checks for the current stage are all complete → ready to advance */
export function isStageComplete(stageKey: string, checks: ChecksMap): boolean {
  const stage = WORKFLOW_STAGES.find((s) => s.key === stageKey);
  if (!stage) return false;
  return stage.checks.every((c) => checks[`${stageKey}:${c.key}`]);
}

/** Return the next stage key, or null if already at the end */
export function nextStage(stageKey: string): string | null {
  const idx = getStageIndex(stageKey);
  if (idx < 0 || idx >= STAGE_ORDER.length - 1) return null;
  return STAGE_ORDER[idx + 1];
}

export const STAGE_COLOR_CLASSES: Record<string, { bg: string; text: string; ring: string; dot: string }> = {
  amber:   { bg: 'bg-amber-400/10',   text: 'text-amber-300',   ring: 'ring-amber-400/25',   dot: 'bg-amber-400' },
  blue:    { bg: 'bg-blue-400/10',    text: 'text-blue-300',    ring: 'ring-blue-400/25',    dot: 'bg-blue-400' },
  violet:  { bg: 'bg-violet-400/10',  text: 'text-violet-300',  ring: 'ring-violet-400/25',  dot: 'bg-violet-400' },
  teal:    { bg: 'bg-teal-400/10',    text: 'text-teal-300',    ring: 'ring-teal-400/25',    dot: 'bg-teal-400' },
  orange:  { bg: 'bg-orange-400/10',  text: 'text-orange-300',  ring: 'ring-orange-400/25',  dot: 'bg-orange-400' },
  emerald: { bg: 'bg-emerald-400/10', text: 'text-emerald-300', ring: 'ring-emerald-400/25', dot: 'bg-emerald-400' },
};

/** User-facing English labels + tone mapping for contract enums. */
import type { Tone } from './primitives';
import type {
  MilestoneStateValue,
  RouteEligibility,
  RouteType,
} from '../contracts/types';

export const MILESTONE_STATE_LABEL: Record<MilestoneStateValue, string> = {
  NOT_STARTED: 'Not started',
  IN_PROGRESS: 'In progress',
  NEEDS_INPUT: 'Needs input',
  REVIEW_READY: 'Ready to review',
  CONFIRMED: 'Confirmed',
  COMPLETE_WITH_GAPS: 'Complete with gaps',
  INVALIDATED: 'Invalidated',
  FAILED: 'Failed',
};

export const MILESTONE_STATE_TONE: Record<MilestoneStateValue, Tone> = {
  NOT_STARTED: 'muted',
  IN_PROGRESS: 'info',
  NEEDS_INPUT: 'warn',
  REVIEW_READY: 'info',
  CONFIRMED: 'ok',
  COMPLETE_WITH_GAPS: 'warn',
  INVALIDATED: 'danger',
  FAILED: 'danger',
};

export const ROUTE_LABEL: Record<RouteType, string> = {
  PRIVATE_SELF: 'Private',
  BEGINNER: 'Beginner',
  PEER: 'Peer',
  CUSTOMER_EVALUATOR: 'Customer / evaluator',
  PUBLIC: 'Public',
};

export const ROUTE_ELIGIBILITY_LABEL: Record<RouteEligibility | 'UNKNOWN', string> = {
  ELIGIBLE: 'Eligible',
  INELIGIBLE: 'Ineligible',
  ELIGIBLE_AFTER_PRIVACY_APPROVAL: 'Eligible after privacy approval',
  BLOCKED: 'Blocked',
  UNKNOWN: 'Unknown',
};

export const ROUTE_ELIGIBILITY_TONE: Record<RouteEligibility | 'UNKNOWN', Tone> = {
  ELIGIBLE: 'ok',
  INELIGIBLE: 'muted',
  ELIGIBLE_AFTER_PRIVACY_APPROVAL: 'warn',
  BLOCKED: 'danger',
  UNKNOWN: 'muted',
};

import type {
  DetailAccess,
  RelationConfirmation,
  RelationGate,
} from '../viewmodel/relationView';

export const RELATION_GATE_LABEL: Record<RelationGate, string> = {
  NO_TRACE: 'No search yet',
  LOCKED: 'Not ready — locked',
  READY: 'Ready',
  INVALIDATED: 'Invalidated',
};

export const RELATION_GATE_TONE: Record<RelationGate, Tone> = {
  NO_TRACE: 'muted',
  LOCKED: 'muted',
  READY: 'ok',
  INVALIDATED: 'danger',
};

export const RELATION_CONFIRMATION_LABEL: Record<RelationConfirmation, string> = {
  PENDING: 'Pending',
  CONFIRMED: 'Confirmed',
  DECLINED: 'Declined',
};

export const RELATION_CONFIRMATION_TONE: Record<RelationConfirmation, Tone> = {
  PENDING: 'warn',
  CONFIRMED: 'ok',
  DECLINED: 'muted',
};

export const DETAIL_ACCESS_LABEL: Record<DetailAccess, string> = {
  DENIED_UNTIL_CONFIRMED: 'Details locked until confirmation',
  AVAILABLE: 'Details available',
  DECLINED: 'Details closed after decline',
};

export const DETAIL_ACCESS_TONE: Record<DetailAccess, Tone> = {
  DENIED_UNTIL_CONFIRMED: 'warn',
  AVAILABLE: 'ok',
  DECLINED: 'muted',
};

const TERMINAL_TONE: Record<string, Tone> = {
  SUCCEEDED: 'ok',
  NEEDS_USER_INPUT: 'info',
  PAUSED: 'info',
  CANCELLED: 'muted',
  TIMED_OUT: 'warn',
  MODEL_UNAVAILABLE: 'danger',
  MODEL_OOM: 'danger',
  INVALID_MODEL_OUTPUT: 'danger',
  STORAGE_ERROR: 'danger',
  POLICY_BLOCKED: 'warn',
  DELETION_FAILED: 'danger',
  INTERNAL_ERROR: 'danger',
};

export function terminalTone(state: string): Tone {
  return TERMINAL_TONE[state] ?? 'warn';
}

export function healthTone(status: 'ok' | 'degraded' | 'unavailable'): Tone {
  if (status === 'ok') return 'ok';
  if (status === 'degraded') return 'warn';
  return 'danger';
}

/** Format an ISO timestamp for display; falls back to the raw string. */
export function formatTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace('T', ' ').replace('.000Z', 'Z');
}

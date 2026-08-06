/** User-facing Chinese labels + tone mapping for contract enums. */
import type { Tone } from './primitives';
import type {
  MilestoneStateValue,
  RouteEligibility,
  RouteType,
} from '../contracts/types';

export const MILESTONE_STATE_LABEL: Record<MilestoneStateValue, string> = {
  NOT_STARTED: '未开始',
  IN_PROGRESS: '进行中',
  NEEDS_INPUT: '待补充',
  REVIEW_READY: '待确认',
  CONFIRMED: '已确认',
  COMPLETE_WITH_GAPS: '带缺口完成',
  INVALIDATED: '已失效',
  FAILED: '失败',
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
  PRIVATE_SELF: '仅自己',
  BEGINNER: '新手',
  PEER: '同行',
  CUSTOMER_EVALUATOR: '客户/评审',
  PUBLIC: '公开',
};

export const ROUTE_ELIGIBILITY_LABEL: Record<RouteEligibility | 'UNKNOWN', string> = {
  ELIGIBLE: '可用',
  INELIGIBLE: '不适用',
  ELIGIBLE_AFTER_PRIVACY_APPROVAL: '隐私审批后可用',
  BLOCKED: '受阻',
  UNKNOWN: '未知',
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
  NO_TRACE: '无检索轨迹',
  LOCKED: '未就绪（已锁定）',
  READY: '已就绪',
  INVALIDATED: '已失效',
};

export const RELATION_GATE_TONE: Record<RelationGate, Tone> = {
  NO_TRACE: 'muted',
  LOCKED: 'muted',
  READY: 'ok',
  INVALIDATED: 'danger',
};

export const RELATION_CONFIRMATION_LABEL: Record<RelationConfirmation, string> = {
  PENDING: '待确认',
  CONFIRMED: '已确认',
  DECLINED: '已拒绝',
};

export const RELATION_CONFIRMATION_TONE: Record<RelationConfirmation, Tone> = {
  PENDING: 'warn',
  CONFIRMED: 'ok',
  DECLINED: 'muted',
};

export const DETAIL_ACCESS_LABEL: Record<DetailAccess, string> = {
  DENIED_UNTIL_CONFIRMED: '详细证据：需先确认关系',
  AVAILABLE: '详细证据：已解锁',
  DECLINED: '详细证据：已随拒绝关闭',
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

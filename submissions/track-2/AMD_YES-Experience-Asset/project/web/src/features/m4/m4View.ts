import type {
  InsightStatementV1,
  M4EvidenceStatementV1,
  M4FailureV1,
  M4WorkspaceV1,
} from './types';

/**
 * The eight states the workspace can be in.
 *
 * Five of them are the artifact's own `state` and are read straight from it.
 * The other three describe the workspace when there is no artifact yet, so
 * they can only come from the run: a map that has never been generated, one
 * being generated now, and one whose generation stopped. Inventing a local
 * state machine on top would let the UI claim a stage the backend never
 * reported.
 */
export type M4ViewState =
  | 'NOT_STARTED'
  | 'IN_PROGRESS'
  | 'NEEDS_INPUT'
  | 'REVIEW_READY'
  | 'CONFIRMED'
  | 'COMPLETE_WITH_GAPS'
  | 'INVALIDATED'
  | 'FAILED';

export interface M4View {
  state: M4ViewState;
  /**
   * Kept separately from `state` so a failed regeneration over an invalidated
   * map stays visible. Collapsing the two would force a choice between showing
   * the user why the map is stale and showing them why the rebuild stopped.
   */
  failure: M4FailureV1 | null;
  progressMessage: string;
  visibleGaps: InsightStatementV1[];
  evidenceById: Map<string, M4EvidenceStatementV1>;
  canCreate: boolean;
  canEdit: boolean;
  canRegenerate: boolean;
}

const RUNNING_STATES = new Set(['QUEUED', 'RUNNING', 'WAITING_FOR_USER']);

export function deriveM4View(workspace: M4WorkspaceV1): M4View {
  const { map, run_status: run } = workspace;
  const failure = run?.failure ?? null;
  const evidenceById = new Map(
    workspace.evidence_statements.map((statement) => [statement.statement_id, statement]),
  );
  const visibleGaps = (map?.entries ?? [])
    .flatMap((entry) => entry.statements)
    .filter((statement) => statement.is_visible_gap);

  let state: M4ViewState;
  if (map) {
    state = map.state;
  } else if (failure) {
    state = 'FAILED';
  } else if (run && RUNNING_STATES.has(run.state)) {
    state = 'IN_PROGRESS';
  } else {
    state = 'NOT_STARTED';
  }

  return {
    state,
    failure,
    progressMessage: run?.progress?.message ?? '',
    visibleGaps,
    evidenceById,
    canCreate: map === null,
    canEdit: map !== null && map.state !== 'INVALIDATED',
    canRegenerate: map?.state === 'INVALIDATED',
  };
}

export const STATE_LABELS: Record<M4ViewState, string> = {
  NOT_STARTED: '尚未生成',
  IN_PROGRESS: '生成中',
  NEEDS_INPUT: '有可见缺口，待补充',
  REVIEW_READY: '待审阅',
  CONFIRMED: '已确认',
  COMPLETE_WITH_GAPS: '带缺口接受',
  INVALIDATED: '已失效',
  FAILED: '生成已终止',
};

export const STATE_TONES: Record<M4ViewState, 'neutral' | 'ok' | 'warn' | 'danger' | 'info'> = {
  NOT_STARTED: 'neutral',
  IN_PROGRESS: 'info',
  NEEDS_INPUT: 'warn',
  REVIEW_READY: 'info',
  CONFIRMED: 'ok',
  COMPLETE_WITH_GAPS: 'warn',
  INVALIDATED: 'danger',
  FAILED: 'danger',
};

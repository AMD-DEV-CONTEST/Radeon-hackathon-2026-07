/**
 * Pure derivation from a contract `StatusSnapshot` to a render-ready view model.
 *
 * Every derived value is traceable to a contract field. In particular:
 *  - progress `percent` is shown only with the public milestone basis supplied
 *    by E1-A; internal units are never promoted to user-visible progress. ETA is
 *    shown only when the backend supplies both value and basis (AC-17).
 *  - confirmed / unresolved counts come from statement + question state, not from
 *    visual guesses (AC-17).
 *  - stale/invalidation is derived from real invalidation markers (AC-15).
 */
import {
  ALL_MILESTONES,
  ALL_ROUTES,
  type ExperienceAssetV1,
  type Milestone,
  type MilestoneStateValue,
  type RouteEligibility,
  type RouteType,
} from '../contracts/types';
import type { ActiveRun, StatusSnapshot } from '../data/provider';
import { deriveRelationDiscovery, type RelationDiscoveryView } from './relationView';

export interface HealthView {
  available: boolean;
  status: 'ok' | 'degraded' | 'unavailable';
  appVersion: string | null;
  database: string | null;
  modelEndpoint: string | null;
  modelProfile: string | null;
  gpuViability: string | null;
  inferenceMode: string | null;
  checkedAt: string | null;
  error: string | null;
}

export interface MilestoneView {
  milestone: Milestone;
  state: MilestoneStateValue;
  isConfirmed: boolean;
  isInvalidated: boolean;
  isCurrent: boolean;
}

export interface CountsView {
  totalStatements: number;
  confirmedStatements: number;
  unresolvedStatements: number;
  openQuestions: number;
}

export interface RouteView {
  route: RouteType;
  eligibility: RouteEligibility | 'UNKNOWN';
  explanation: string | null;
}

export interface StaleView {
  isStale: boolean;
  reasons: string[];
}

export interface ProgressRunView {
  kind: 'progress';
  runId: string;
  stage: string;
  state: string;
  percent: number | null;
  percentBasis: string | null;
  milestonesDone: number | null;
  milestonesTotal: number | null;
  etaSeconds: number | null;
  etaBasis: string | null;
  message: string;
  occurredAt: string;
  workPlanStepCount: number;
  retrievalScope: string;
  latestPolicyOutcome: string | null;
  latestToolExecutionStatus: string | null;
  verificationOutcome: string | null;
}

export interface TerminalRunView {
  kind: 'terminal';
  runId: string;
  state: string;
  isSuccess: boolean;
  isSafeStop: boolean;
  retryable: boolean;
  safeMessage: string;
  recoveryAction: string;
  lastDurableVersionId: string | null;
  internalErrorClass: string | null;
  elapsedMs: number;
  modelCallCount: number;
  finishedAt: string;
}

export type RunView = ProgressRunView | TerminalRunView | null;

export interface VersionView {
  present: boolean;
  availability: StatusSnapshot['assetAvailability'];
  assetId: string | null;
  versionId: string | null;
  parentVersionId: string | null;
  updatedAt: string | null;
  changeKind: string | null;
  changeReason: string | null;
  lifecycle: string | null;
  currentMilestone: Milestone | null;
}

export interface StatusView {
  source: 'mock' | 'live';
  scenario: string | null;
  fetchedAt: string;
  health: HealthView;
  version: VersionView;
  milestones: MilestoneView[];
  counts: CountsView | null;
  routes: RouteView[];
  stale: StaleView;
  run: RunView;
  relation: RelationDiscoveryView;
  terminalStates: readonly string[] | null;
}

const SAFE_STOP_STATES = new Set(['PAUSED', 'CANCELLED', 'NEEDS_USER_INPUT']);

function deriveHealth(snapshot: StatusSnapshot): HealthView {
  const { health } = snapshot;
  if (!health) {
    return {
      available: false,
      status: 'unavailable',
      appVersion: null,
      database: null,
      modelEndpoint: null,
      modelProfile: null,
      gpuViability: null,
      inferenceMode: null,
      checkedAt: null,
      error: snapshot.healthError,
    };
  }
  return {
    available: true,
    status: health.status,
    appVersion: health.app_version,
    database: health.database,
    modelEndpoint: health.model_endpoint,
    modelProfile: health.model_profile,
    gpuViability: health.gpu_viability,
    inferenceMode: health.inference_mode ?? 'local_only',
    checkedAt: health.checked_at,
    error: null,
  };
}

function deriveVersion(snapshot: StatusSnapshot): VersionView {
  const asset = snapshot.asset;
  if (!asset) {
    return {
      present: false,
      availability: snapshot.assetAvailability,
      assetId: null,
      versionId: null,
      parentVersionId: null,
      updatedAt: null,
      changeKind: null,
      changeReason: null,
      lifecycle: null,
      currentMilestone: null,
    };
  }
  return {
    present: true,
    availability: 'present',
    assetId: asset.asset_id,
    versionId: asset.version_id,
    parentVersionId: asset.lineage?.parent_version_id ?? null,
    updatedAt: asset.updated_at,
    changeKind: asset.lineage?.change_kind ?? null,
    changeReason: asset.lineage?.change_reason ?? null,
    lifecycle: asset.lifecycle ?? null,
    currentMilestone: asset.current_milestone ?? null,
  };
}

function deriveMilestones(asset: ExperienceAssetV1 | null): MilestoneView[] {
  if (!asset) return [];
  return ALL_MILESTONES.map((milestone) => {
    const state: MilestoneStateValue = asset.milestone_states[milestone] ?? 'NOT_STARTED';
    return {
      milestone,
      state,
      isConfirmed: state === 'CONFIRMED' || state === 'COMPLETE_WITH_GAPS',
      isInvalidated: state === 'INVALIDATED',
      isCurrent: asset.current_milestone === milestone,
    };
  });
}

function deriveCounts(asset: ExperienceAssetV1 | null): CountsView | null {
  if (!asset) return null;
  const statements = asset.statements ?? [];
  const questions = asset.unresolved_questions ?? [];
  return {
    totalStatements: statements.length,
    confirmedStatements: statements.filter((s) => s.confirmation === 'CONFIRMED').length,
    unresolvedStatements: statements.filter((s) => s.status === 'UNRESOLVED').length,
    openQuestions: questions.filter((q) => (q.state ?? 'OPEN') === 'OPEN').length,
  };
}

function deriveRoutes(asset: ExperienceAssetV1 | null): RouteView[] {
  if (!asset) return [];
  const byRoute = new Map(asset.route_decisions.map((d) => [d.route, d]));
  return ALL_ROUTES.map((route) => {
    const decision = byRoute.get(route);
    return {
      route,
      eligibility: decision?.eligibility ?? 'UNKNOWN',
      explanation: decision?.explanation ?? null,
    };
  });
}

function deriveStale(asset: ExperienceAssetV1 | null): StaleView {
  if (!asset) return { isStale: false, reasons: [] };
  const reasons: string[] = [];

  const invalidatedMilestones = ALL_MILESTONES.filter(
    (m) => asset.milestone_states[m] === 'INVALIDATED',
  );
  if (invalidatedMilestones.length > 0) {
    reasons.push(`里程碑 ${invalidatedMilestones.join('、')} 已因修正失效，需重新生成。`);
  }

  const invalidatedArtifacts = (asset.milestone_artifacts ?? []).filter(
    (a) => a.invalidated_by_version_id != null,
  );
  if (invalidatedArtifacts.length > 0) {
    reasons.push(`${invalidatedArtifacts.length} 个里程碑产物被更新的版本作废。`);
  }

  const supersededExports = (asset.exports ?? []).filter((e) => e.state === 'SUPERSEDED');
  if (supersededExports.length > 0) {
    reasons.push(`${supersededExports.length} 个导出结果已被更高版本取代。`);
  }

  return { isStale: reasons.length > 0, reasons };
}

function deriveRun(activeRun: ActiveRun | null): RunView {
  if (!activeRun) return null;
  if (activeRun.kind === 'progress') {
    const e = activeRun.event;
    const state = activeRun.state;
    const publicPercent =
      e.percent != null && e.percent_basis != null ? e.percent : null;
    return {
      kind: 'progress',
      runId: e.run_id,
      stage: e.stage,
      state: e.state,
      percent: publicPercent,
      percentBasis: publicPercent === null ? null : (e.percent_basis ?? null),
      milestonesDone: e.milestones_done ?? null,
      milestonesTotal: e.milestones_total ?? null,
      etaSeconds: e.eta_seconds != null && e.eta_basis != null ? e.eta_seconds : null,
      etaBasis: e.eta_seconds != null && e.eta_basis != null ? e.eta_basis : null,
      message: e.message,
      occurredAt: e.occurred_at,
      workPlanStepCount: state.work_plan.steps.length,
      retrievalScope: state.retrieval_scope,
      latestPolicyOutcome: state.policy_decisions?.at(-1)?.outcome ?? null,
      latestToolExecutionStatus: state.tool_executions?.at(-1)?.status ?? null,
      verificationOutcome: state.verification_report?.outcome ?? null,
    };
  }
  const r = activeRun.result;
  return {
    kind: 'terminal',
    runId: r.run_id,
    state: r.state,
    isSuccess: r.state === 'SUCCEEDED',
    isSafeStop: SAFE_STOP_STATES.has(r.state),
    retryable: r.retryable,
    safeMessage: r.safe_user_message,
    recoveryAction: r.recovery_action,
    lastDurableVersionId: r.last_durable_version_id ?? null,
    internalErrorClass: r.internal_error_class ?? null,
    elapsedMs: r.elapsed_ms,
    modelCallCount: r.model_call_count,
    finishedAt: r.finished_at,
  };
}

export function deriveStatusView(snapshot: StatusSnapshot): StatusView {
  return {
    source: snapshot.source,
    scenario: snapshot.scenario,
    fetchedAt: snapshot.fetchedAt,
    health: deriveHealth(snapshot),
    version: deriveVersion(snapshot),
    milestones: deriveMilestones(snapshot.asset),
    counts: deriveCounts(snapshot.asset),
    routes: deriveRoutes(snapshot.asset),
    stale: deriveStale(snapshot.asset),
    run: deriveRun(snapshot.activeRun),
    relation: deriveRelationDiscovery(
      snapshot.asset,
      snapshot.relationWorkspace,
      snapshot.retrievalTrace,
    ),
    terminalStates: snapshot.terminalStates,
  };
}

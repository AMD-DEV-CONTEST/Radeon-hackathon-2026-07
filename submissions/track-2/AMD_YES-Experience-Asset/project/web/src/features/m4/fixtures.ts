import confirmedMap from '../../../../contracts/examples/e5/instance/m4-insight-boundary-map.json';
import type {
  InsightBoundaryMapV1,
  InsightStatementV1,
  M4EvidenceStatementV1,
  M4WorkspaceV1,
} from './types';

/**
 * Every scenario derives from the frozen contract instance rather than being
 * written by hand. A hand-written fixture drifts from the contract silently:
 * the component tests keep passing against a shape the backend stopped
 * producing, and the mismatch appears only in the browser.
 */
function validatedMap(value: unknown): InsightBoundaryMapV1 {
  if (!value || typeof value !== 'object') throw new Error('Invalid M4 map fixture');
  const map = value as Record<string, unknown>;
  if (typeof map.artifact_id !== 'string' || !Array.isArray(map.entries)) {
    throw new Error('Invalid M4 map fixture');
  }
  return value as InsightBoundaryMapV1;
}

const confirmed = validatedMap(confirmedMap);

const evidenceStatements: M4EvidenceStatementV1[] = confirmed.dependency_statement_ids.map(
  (statement_id, index) => ({
    statement_id,
    text: `原始证据 ${index + 1}：试坐后腰部支撑不足。`,
    status: 'SOURCE_FACT',
    source_refs: ['粘贴文本 #1'],
  }),
);

function workspaceWith(
  map: InsightBoundaryMapV1 | null,
  options: Partial<M4WorkspaceV1> = {},
): M4WorkspaceV1 {
  return {
    schema_version: '1.0.0',
    asset_id: confirmed.asset_id,
    canonical_version_id: confirmed.base_canonical_version_id,
    canonical_content_hash: 'a'.repeat(64),
    map,
    evidence_statements: map ? evidenceStatements : [],
    run_status: null,
    ...options,
  };
}

function withStatement(
  map: InsightBoundaryMapV1,
  role: InsightStatementV1['role'],
  update: Partial<InsightStatementV1>,
): InsightBoundaryMapV1 {
  return {
    ...map,
    entries: map.entries.map((entry) => ({
      ...entry,
      statements: entry.statements.map((statement) =>
        statement.role === role ? { ...statement, ...update } : statement,
      ),
    })),
  };
}

const withGap = withStatement(
  { ...confirmed, state: 'NEEDS_INPUT' },
  'COUNTEREXAMPLE',
  {
    is_visible_gap: true,
    gap_reason: '来源里没有出现反例。',
    status: 'UNRESOLVED',
    source_statement_ids: [],
    source_decision_ids: [],
  },
);

const invalidated: InsightBoundaryMapV1 = {
  ...confirmed,
  state: 'INVALIDATED',
  invalidated_by_m3_artifact_id: '0f2f5a58-3a49-4f57-8f28-6b1c0a2b8f11',
  invalidated_by_canonical_version_id: '4c5b7f1e-1c2a-4f0a-9d3b-2e6f7a8b9c01',
  invalidation_reason: 'M3 correction changed dependencies used by this insight map: decision:…',
  affected_insight_ids: confirmed.entries.map((entry) => entry.insight_id),
  reusable_insight_ids: [],
};

export const M4_SCENARIOS: Record<string, M4WorkspaceV1> = {
  not_started: workspaceWith(null),
  in_progress: workspaceWith(null, {
    run_status: {
      schema_version: '1.0.0',
      run_id: '2f1d4a1e-9c1a-4b7f-8a3d-71a2c4e5b6d7',
      asset_id: confirmed.asset_id,
      state: 'RUNNING',
      progress: {
        schema_version: '1.0.0',
        run_id: '2f1d4a1e-9c1a-4b7f-8a3d-71a2c4e5b6d7',
        asset_id: confirmed.asset_id,
        sequence: 0,
        stage: 'PLAN_INSIGHTS',
        state: 'RUNNING',
        message: '正在从已接受的决策账本推导教训。',
        occurred_at: confirmed.updated_at,
      },
      failure: null,
    },
  }),
  needs_input: workspaceWith(withGap),
  review_ready: workspaceWith({ ...confirmed, state: 'REVIEW_READY' }),
  confirmed: workspaceWith(confirmed),
  complete_with_gaps: workspaceWith({ ...withGap, state: 'COMPLETE_WITH_GAPS' }),
  invalidated: workspaceWith(invalidated),
  failed: workspaceWith(null, {
    run_status: {
      schema_version: '1.0.0',
      run_id: '8b3c1f22-5d6e-4a09-9f11-3c4d5e6f7a80',
      asset_id: confirmed.asset_id,
      state: 'TERMINAL',
      progress: null,
      failure: {
        schema_version: '1.0.0',
        run_id: '8b3c1f22-5d6e-4a09-9f11-3c4d5e6f7a80',
        asset_id: confirmed.asset_id,
        failure_code: 'MODEL_UNAVAILABLE',
        terminal_state: 'MODEL_UNAVAILABLE',
        retryable: true,
        safe_user_message: '本地推理服务不可用，未保存任何洞察。',
        last_durable_artifact_id: null,
        occurred_at: confirmed.updated_at,
      },
    },
  }),
};

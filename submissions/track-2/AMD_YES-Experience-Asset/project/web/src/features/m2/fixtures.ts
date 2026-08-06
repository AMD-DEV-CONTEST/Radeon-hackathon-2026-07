import type { CriticalMomentEntryV1, CriticalMomentMapV1 } from './types';

const IDS = {
  artifact: '00000000-0000-4000-8000-000000000701',
  asset: '00000000-0000-4000-8000-000000000702',
  m1Version: '00000000-0000-4000-8000-000000000703',
  run: '00000000-0000-4000-8000-000000000704',
  statementA: '00000000-0000-4000-8000-000000000705',
  statementB: '00000000-0000-4000-8000-000000000706',
  newM1Version: '00000000-0000-4000-8000-000000000707',
};

function entry(
  displayOrder: number,
  temporal:
    | { temporal_status: 'KNOWN'; time_label: string; conflict_statement_ids: []; unresolved_reason: null }
    | { temporal_status: 'MISSING'; time_label: null; conflict_statement_ids: []; unresolved_reason: string }
    | {
        temporal_status: 'CONFLICTING';
        time_label: null;
        conflict_statement_ids: [string, string, ...string[]];
        unresolved_reason: string;
      },
  sourceStatementIds: string[] = displayOrder === 0 ? [IDS.statementA] : [IDS.statementB],
): CriticalMomentEntryV1 {
  const changeStatementIds = displayOrder === 0 ? [] : [IDS.statementB];
  const cueStatementIds = displayOrder === 0 ? [IDS.statementA] : [];
  const surpriseStatementIds = displayOrder === 0 ? [] : [IDS.statementB];
  return {
    moment_id: `00000000-0000-4000-8000-00000000071${displayOrder}`,
    display_order: displayOrder,
    title: displayOrder === 0 ? '开始试用网面椅' : '更换为软垫人体工学椅',
    description:
      displayOrder === 0
        ? '来源陈述记录了透气性与长时间坐姿不适。'
        : '没想到退换窗口仍然有效，用户于是更换了选择。',
    criticality_status: 'AGENT_PROPOSED',
    criticality_reason: '该事件改变了用户接下来的行动。',
    source_statement_ids: sourceStatementIds,
    cue_statement_ids: cueStatementIds,
    change_statement_ids: changeStatementIds,
    surprise_statement_ids: surpriseStatementIds,
    ...temporal,
  };
}

const known = (timeLabel: string) => ({
  temporal_status: 'KNOWN' as const,
  time_label: timeLabel,
  conflict_statement_ids: [] as [],
  unresolved_reason: null,
});

const base: CriticalMomentMapV1 = {
  schema_version: '0.1.0',
  artifact_id: IDS.artifact,
  asset_id: IDS.asset,
  base_m1_version_id: IDS.m1Version,
  generated_by_run_id: IDS.run,
  state: 'REVIEW_READY',
  order_basis: 'NARRATIVE_SEQUENCE',
  moments: [entry(0, known('约两周试用期')), entry(1, known('随后约两周'))],
  dependency_statement_ids: [IDS.statementA, IDS.statementB],
  unresolved_question_ids: [],
  created_at: '2026-07-28T04:30:00Z',
  updated_at: '2026-07-28T04:30:00Z',
  invalidated_by_m1_version_id: null,
  invalidation_reason: null,
};

export const M2_SCENARIOS: Record<string, CriticalMomentMapV1> = {
  complete: base,
  incomplete: {
    ...base,
    state: 'NEEDS_INPUT',
    moments: [
      entry(0, {
        temporal_status: 'MISSING',
        time_label: null,
        conflict_statement_ids: [],
        unresolved_reason: '来源没有说明具体发生时间。',
      }),
    ],
    unresolved_question_ids: ['00000000-0000-4000-8000-000000000720'],
  },
  conflicting: {
    ...base,
    state: 'NEEDS_INPUT',
    moments: [
      entry(0, {
        temporal_status: 'CONFLICTING',
        time_label: null,
        conflict_statement_ids: [IDS.statementA, IDS.statementB],
        unresolved_reason: '来源同时写了“当天退回”和“试用两周”，需要用户确认。',
      }, [IDS.statementA, IDS.statementB]),
    ],
  },
  correction_invalidation: {
    ...base,
    state: 'INVALIDATED',
    updated_at: '2026-07-28T04:31:00Z',
    invalidated_by_m1_version_id: IDS.newM1Version,
    invalidation_reason:
      'M1 correction changed statements used by this Critical Moment Map: ' + IDS.statementA,
  },
};

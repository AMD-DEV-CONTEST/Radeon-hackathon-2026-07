import { Badge, Mono, Panel } from '../../components/primitives';
import type { CriticalMomentMapV1, TemporalStatus } from './types';

const TEMPORAL_LABELS: Record<TemporalStatus, string> = {
  KNOWN: '时间有来源',
  MISSING: '时间待确认',
  CONFLICTING: '来源冲突',
};

const CRITICALITY_LABELS = {
  AGENT_PROPOSED: 'Agent 提议，待用户决定',
  UNRESOLVED: '用户标记为待确认',
  USER_CONFIRMED: '用户已确认',
} as const;

function temporalTone(status: TemporalStatus): 'ok' | 'warn' | 'danger' {
  if (status === 'KNOWN') return 'ok';
  return status === 'MISSING' ? 'warn' : 'danger';
}

export function CriticalMomentMap({ artifact }: { artifact: CriticalMomentMapV1 }) {
  return (
    <Panel
      title="Critical Moment Map"
      testId="m2-critical-moment-map"
      actions={<Badge tone={artifact.state === 'INVALIDATED' ? 'danger' : 'info'}>{artifact.state}</Badge>}
    >
      <p>
        绑定 M1 版本：<Mono>{artifact.base_m1_version_id}</Mono>
      </p>

      {artifact.state === 'INVALIDATED' ? (
        <div role="alert" data-testid="m2-invalidated">
          <strong>该时间线已失效。</strong> {artifact.invalidation_reason}
        </div>
      ) : null}

      {artifact.moments.length === 0 ? (
        <p data-testid="m2-empty">当前证据尚不足以形成关键时刻。</p>
      ) : (
        <ol data-testid="m2-moment-list">
          {artifact.moments.map((moment) => (
            <li key={moment.moment_id} data-testid={`m2-moment-${moment.display_order}`}>
              <div>
                <strong>{moment.title}</strong>{' '}
                <Badge tone={temporalTone(moment.temporal_status)}>
                  {TEMPORAL_LABELS[moment.temporal_status]}
                </Badge>
              </div>
              <p>{moment.description}</p>
              <p data-testid="m2-criticality">
                关键性：{CRITICALITY_LABELS[moment.criticality_status]}
              </p>
              <p data-testid={`m2-evidence-roles-${moment.display_order}`}>
                证据角色：{' '}
                <Badge tone="info">线索 {moment.cue_statement_ids.length}</Badge>{' '}
                <Badge tone="info">变化/转折 {moment.change_statement_ids.length}</Badge>{' '}
                <Badge tone="info">意外 {moment.surprise_statement_ids.length}</Badge>{' '}
                <Badge tone={moment.conflict_statement_ids.length ? 'danger' : 'info'}>
                  冲突 {moment.conflict_statement_ids.length}
                </Badge>
              </p>
              {moment.time_label ? <p data-testid="m2-time-label">{moment.time_label}</p> : null}
              {moment.unresolved_reason ? (
                <p data-testid="m2-unresolved-reason">{moment.unresolved_reason}</p>
              ) : null}
              <small>来源陈述：{moment.source_statement_ids.length}</small>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

import { Badge, Mono, Panel } from '../../components/primitives';
import type { CriticalMomentMapV1, TemporalStatus } from './types';

const TEMPORAL_LABELS: Record<TemporalStatus, string> = {
  KNOWN: 'Time supported by evidence',
  MISSING: 'Time needs confirmation',
  CONFLICTING: 'Conflicting sources',
};

const CRITICALITY_LABELS = {
  AGENT_PROPOSED: 'Agent suggestion — awaiting your decision',
  UNRESOLVED: 'Marked for later confirmation',
  USER_CONFIRMED: 'Confirmed by you',
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
        Based on M1 version: <Mono>{artifact.base_m1_version_id}</Mono>
      </p>

      {artifact.state === 'INVALIDATED' ? (
        <div role="alert" data-testid="m2-invalidated">
          <strong>This timeline is out of date.</strong> {artifact.invalidation_reason}
        </div>
      ) : null}

      {artifact.moments.length === 0 ? (
        <p data-testid="m2-empty">There is not enough evidence to identify a critical moment yet.</p>
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
                Significance: {CRITICALITY_LABELS[moment.criticality_status]}
              </p>
              <p data-testid={`m2-evidence-roles-${moment.display_order}`}>
                Evidence roles:{' '}
                <Badge tone="info">Cues {moment.cue_statement_ids.length}</Badge>{' '}
                <Badge tone="info">Changes {moment.change_statement_ids.length}</Badge>{' '}
                <Badge tone="info">Surprises {moment.surprise_statement_ids.length}</Badge>{' '}
                <Badge tone={moment.conflict_statement_ids.length ? 'danger' : 'info'}>
                  Conflicts {moment.conflict_statement_ids.length}
                </Badge>
              </p>
              {moment.time_label ? <p data-testid="m2-time-label">{moment.time_label}</p> : null}
              {moment.unresolved_reason ? (
                <p data-testid="m2-unresolved-reason">{moment.unresolved_reason}</p>
              ) : null}
              <small>Source statements: {moment.source_statement_ids.length}</small>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

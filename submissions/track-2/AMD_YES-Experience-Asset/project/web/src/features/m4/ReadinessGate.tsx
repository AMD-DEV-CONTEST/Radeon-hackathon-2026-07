import { Badge, Mono, Panel } from '../../components/primitives';
import type { M4View } from './m4View';
import { ACCEPTABLE_STATES, type DiscoveryLock, type KnowledgeCardReadinessV1 } from './readiness';

const MILESTONE_LABELS: Record<string, string> = {
  CONFIRMED: 'Confirmed',
  COMPLETE_WITH_GAPS: 'Accepted with gaps',
};

export function ReadinessGate({
  view,
  readiness,
  lock,
  busy = false,
  error = '',
  onAccept,
}: {
  view: M4View;
  readiness: KnowledgeCardReadinessV1 | null;
  lock: DiscoveryLock | null;
  busy?: boolean;
  error?: string;
  onAccept?: (action: 'CONFIRM' | 'ACCEPT_WITH_GAPS') => void;
}) {
  const acceptable = ACCEPTABLE_STATES.includes(view.state);
  const hasGaps = view.visibleGaps.length > 0;

  return (
    <Panel
      title="Knowledge Card readiness"
      testId="m4-readiness-gate"
      actions={
        <Badge
          tone={readiness ? 'ok' : 'warn'}
          testId="m4-readiness-badge"
        >
          {readiness ? MILESTONE_LABELS[readiness.milestone_state] : 'Not accepted'}
        </Badge>
      }
    >
      {readiness ? (
        <div data-testid="m4-readiness-bindings">
          <p>
            Version: <Mono>{readiness.version_id}</Mono>
          </p>
          <p>
            Card hash: <Mono>{readiness.knowledge_card_hash}</Mono>
          </p>
          {readiness.accepted_gap_statement_ids.length ? (
            <p>
              Accepted with {readiness.accepted_gap_statement_ids.length} visible gaps.
            </p>
          ) : null}
        </div>
      ) : (
        <p data-testid="m4-readiness-absent">
          This card has not been accepted. Readiness only comes from your explicit acceptance.
        </p>
      )}

      {acceptable && onAccept ? (
        <div className="row">
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy || hasGaps}
            onClick={() => onAccept('CONFIRM')}
          >
            Confirm this card
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy || !hasGaps}
            onClick={() => onAccept('ACCEPT_WITH_GAPS')}
          >
            Accept with gaps ({view.visibleGaps.length})
          </button>
        </div>
      ) : null}

      {error ? (
        <div className="notice notice--danger" role="alert" data-testid="m4-readiness-error">
          {error}
        </div>
      ) : null}

      {/* The lock and its reason are the backend's, never recomputed here: a
          locally derived lock would disagree with the server the moment the
          card changes in another tab, and the user would be offered an action
          that fails when clicked. */}
      <div data-testid="m4-discovery-lock" data-locked={lock?.locked ? 'true' : 'false'}>
        <strong>Find related experiences</strong>{' '}
        {lock === null ? (
          <Badge tone="muted">Not loaded</Badge>
        ) : lock.locked ? (
          <Badge tone="warn" testId="m4-discovery-locked">
            Locked{lock.outcome ? ` (${lock.outcome})` : ''}
          </Badge>
        ) : (
          <Badge tone="ok" testId="m4-discovery-available">
            Available
          </Badge>
        )}
        {lock?.locked && lock.reason ? (
          <p data-testid="m4-discovery-lock-reason">{lock.reason}</p>
        ) : null}
      </div>
    </Panel>
  );
}

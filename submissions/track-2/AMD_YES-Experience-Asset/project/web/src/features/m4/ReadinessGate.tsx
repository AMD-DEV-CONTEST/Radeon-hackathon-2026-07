import { Badge, Mono, Panel } from '../../components/primitives';
import type { M4View } from './m4View';
import { ACCEPTABLE_STATES, type DiscoveryLock, type KnowledgeCardReadinessV1 } from './readiness';

const MILESTONE_LABELS: Record<string, string> = {
  CONFIRMED: '已确认',
  COMPLETE_WITH_GAPS: '带缺口接受',
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
      title="Knowledge Card 就绪"
      testId="m4-readiness-gate"
      actions={
        <Badge
          tone={readiness ? 'ok' : 'warn'}
          testId="m4-readiness-badge"
        >
          {readiness ? MILESTONE_LABELS[readiness.milestone_state] : '尚未接受'}
        </Badge>
      }
    >
      {readiness ? (
        <div data-testid="m4-readiness-bindings">
          <p>
            绑定版本：<Mono>{readiness.version_id}</Mono>
          </p>
          <p>
            卡片哈希：<Mono>{readiness.knowledge_card_hash}</Mono>
          </p>
          {readiness.accepted_gap_statement_ids.length ? (
            <p>
              接受时留下 {readiness.accepted_gap_statement_ids.length} 处缺口。
            </p>
          ) : null}
        </div>
      ) : (
        <p data-testid="m4-readiness-absent">
          这张卡还没有被接受。接受是唯一的就绪来源——系统不会因为「没有未解问题」就替你认定它完成了。
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
            确认这张卡
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy || !hasGaps}
            onClick={() => onAccept('ACCEPT_WITH_GAPS')}
          >
            带缺口接受（{view.visibleGaps.length}）
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
        <strong>查找相关经历</strong>{' '}
        {lock === null ? (
          <Badge tone="muted">尚未读取</Badge>
        ) : lock.locked ? (
          <Badge tone="warn" testId="m4-discovery-locked">
            已锁定{lock.outcome ? `（${lock.outcome}）` : ''}
          </Badge>
        ) : (
          <Badge tone="ok" testId="m4-discovery-available">
            可用
          </Badge>
        )}
        {lock?.locked && lock.reason ? (
          <p data-testid="m4-discovery-lock-reason">{lock.reason}</p>
        ) : null}
      </div>
    </Panel>
  );
}

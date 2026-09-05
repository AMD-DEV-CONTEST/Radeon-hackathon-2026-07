import {Badge, Mono, Panel, type Tone} from '../../components/primitives';
import {
  FAILURE_LABELS,
  RELATION_TYPE_LABELS,
  STATE_LABELS,
  type DiscoveryView,
} from './discoveryView';

const STATE_TONES: Record<DiscoveryView['state'], Tone> = {
  LOCKED: 'muted',
  IDLE: 'neutral',
  RUNNING: 'info',
  CANDIDATE: 'ok',
  NO_MATCH: 'neutral',
  TECHNICAL_FAILURE: 'danger',
  STALE: 'warn',
};

export function DiscoveryPanel({
  view,
  busy = false,
  error = '',
  onSearch,
  onDecide,
}: {
  view: DiscoveryView;
  busy?: boolean;
  error?: string;
  onSearch?: () => void;
  onDecide?: (action: 'CONFIRM' | 'DECLINE') => void;
}) {
  const {candidate} = view;

  return (
    <Panel
      title="相关经历"
      testId="relation-discovery"
      actions={
        <Badge tone={STATE_TONES[view.state]} testId="relation-state">
          {STATE_LABELS[view.state]}
        </Badge>
      }
    >
      <div data-testid="relation-outcome" data-state={view.state}>
        {view.state === 'RUNNING' ? (
          <p>正在与其他已就绪的经历比较，只比较摘要，不读取历史细节。</p>
        ) : null}

        {view.state === 'NO_MATCH' ? (
          // A finished search, not an error. Presenting abstention as a failure
          // would train the user to retry until something appears.
          <p data-testid="relation-no-match">
            已经比较过，没有找到可辩护的关系。这是一次完成的查找，不是失败。
          </p>
        ) : null}

        {view.state === 'TECHNICAL_FAILURE' ? (
          <div role="alert" data-testid="relation-failure" className="notice notice--danger">
            <strong>{view.failureClass ? FAILURE_LABELS[view.failureClass] : '查找中断'}</strong>
            {/* Kept visibly distinct from no-match: an outage says nothing about
                whether a relation exists, and reading it as "none found" would
                make a five-minute failure look like a conclusion. */}
            <p>
              这次查找没有得出结论，与「没有找到关系」不同。
              {view.retryable ? '可以重试。' : '重试不会改变结果。'}
            </p>
          </div>
        ) : null}

        {view.state === 'LOCKED' ? (
          <p data-testid="relation-locked">先接受这张卡，才能与其他经历比较。</p>
        ) : null}

        {view.state === 'IDLE' ? (
          <p data-testid="relation-idle">还没有查找过。查找由你显式发起，不会自动进行。</p>
        ) : null}

        {view.stale ? (
          // Named as a change to an asset, not as a generic error. The user
          // reasoned about the earlier answer; if the screen does not say what
          // moved, a silently different result later reads as the system having
          // been wrong the first time.
          <div role="status" data-testid="relation-stale" className="notice notice--warn">
            <strong>其中一个资产已变更</strong>
            <p>
              这条比较所依据的内容已经不在了，因此结论与访问权限都已撤销。
              系统不会自动重跑：那会在你没有选择的时刻，用另一个答案替换你已经推敲过的那个。
              先让卡片重新就绪，再由你发起一次新的查找。
            </p>
          </div>
        ) : null}
      </div>

      {candidate ? (
        <div data-testid="relation-candidate">
          <h3>
            {candidate.title}{' '}
            <Badge tone="info" testId="relation-type">
              {RELATION_TYPE_LABELS[candidate.relation_type] ?? candidate.relation_type}
            </Badge>
          </h3>
          <p>{candidate.summary}</p>
          <div data-testid="relation-mappings">
            <strong>角色映射</strong>
            <ul>
              {candidate.node_mappings.map((mapping) => (
                <li key={`${mapping.current_node_id}:${mapping.historical_node_id}`}>
                  <Mono>{mapping.current_role ?? '根节点'}</Mono> ↔{' '}
                  <Mono>{mapping.historical_role ?? '根节点'}</Mono>
                </li>
              ))}
            </ul>
          </div>
          <div data-testid="relation-boundary">
            <strong>迁移边界</strong>
            <ul>
              {candidate.current_boundary_node_ids.map((nodeId) => (
                <li key={nodeId}>
                  <Mono>{nodeId}</Mono>
                </li>
              ))}
            </ul>
          </div>
          <div data-testid="relation-provenance">
            <strong>双边溯源</strong>
            <ul>
              {candidate.provenance.map((entry) => (
                <li key={`${entry.side}:${entry.node_id}`}>
                  {entry.side}：<Mono>{entry.node_id}</Mono>（{entry.statement_ids.length} 条陈述）
                </li>
              ))}
            </ul>
          </div>
          {/* The candidate view carries no historical detail on purpose: showing
              it here would make the confirmation decision moot, because the user
              would already have read what they are deciding whether to read. */}
          <p data-testid="relation-detail-withheld">
            确认之前不显示历史细节。确认本身就是你同意查看那段历史的动作。
          </p>

          {/* Decided states come from the backend record. Filtering the card out
              locally would hide it while leaving the permission behind it in
              place, so the screen would disagree with what the system allows. */}
          <div data-testid="relation-decision" data-decision={view.decision}>
            {view.decision === 'CONFIRMED' && view.canReadDetail ? (
              <p data-testid="relation-confirmed">
                已确认。这条确认只解锁这一个历史资产，不是你的整个档案。
              </p>
            ) : null}
            {view.decision === 'CONFIRMED' && !view.canReadDetail ? (
              // The confirmation happened and stays on the record; what ended
              // is the access it granted. Showing it as never confirmed would
              // misreport the user's own decision back to them.
              <p data-testid="relation-detail-revoked">
                这条确认仍在记录中，但它授予的历史细节访问已被撤销，因为被绑定的内容已变更。
              </p>
            ) : null}
            {view.decision === 'DECLINED' ? (
              <p data-testid="relation-declined">
                已拒绝。这个答复是持久的，下次载入不会再问一遍。
              </p>
            ) : null}
            {view.canDecide && onDecide ? (
              <div className="row">
                <button
                  type="button"
                  className="btn btn--primary"
                  data-testid="relation-confirm"
                  disabled={busy}
                  onClick={() => onDecide('CONFIRM')}
                >
                  确认这条关系
                </button>
                <button
                  type="button"
                  className="btn"
                  data-testid="relation-decline"
                  disabled={busy}
                  onClick={() => onDecide('DECLINE')}
                >
                  拒绝
                </button>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {error ? (
        <div className="notice notice--danger" role="alert" data-testid="relation-error">
          {error}
        </div>
      ) : null}

      <button
        type="button"
        className="btn btn--primary"
        data-testid="relation-search"
        disabled={busy || !view.canSearch || !onSearch}
        onClick={() => onSearch?.()}
      >
        {view.state === 'TECHNICAL_FAILURE' ? '重试查找' : '查找相关经历'}
      </button>
    </Panel>
  );
}

import type { StatusView } from '../viewmodel/statusView';
import { Badge, Mono } from '../components/primitives';
import './shell.css';

/**
 * A always-visible summary of who is serving the model and what was last
 * persisted, so those facts stay on screen while the user works inside a
 * milestone instead of living only in the status view.
 *
 * Everything here is read from the status view model. Nothing is derived,
 * defaulted or inferred: a field the backend did not supply renders as an
 * explicit unavailable marker.
 */
export function GlobalStatus({ view }: { view: StatusView | null }) {
  if (!view) {
    return (
      <div className="shell__status" data-testid="shell-status">
        <span className="shell__status-item shell__status-item--muted">状态读取中</span>
      </div>
    );
  }

  const { health, version, source, stale } = view;
  const shortId = (value: string | null) => (value ? `${value.slice(0, 8)}…` : null);

  return (
    <div className="shell__status" data-testid="shell-status">
      {stale.isStale ? (
        <Badge tone="warn" testId="shell-status-stale">
          内容已失效{stale.reasons.length > 0 ? `：${stale.reasons[0]}` : ''}
        </Badge>
      ) : null}

      <span className="shell__status-item">
        <span className="shell__status-key">模型</span>
        {health.modelProfile ? (
          <Mono>{health.modelProfile}</Mono>
        ) : (
          <span className="shell__status-absent">未提供</span>
        )}
      </span>

      {health.inferenceMode ? (
        <Badge tone="info" testId="shell-status-inference">
          {health.inferenceMode}
        </Badge>
      ) : null}

      {health.gpuViability ? (
        <span className="shell__status-item">
          <span className="shell__status-key">GPU</span>
          <Mono>{health.gpuViability}</Mono>
        </span>
      ) : null}

      <span className="shell__status-spacer" />

      <span className="shell__status-item">
        <span className="shell__status-key">版本</span>
        {shortId(version.versionId) ? (
          <Mono>{shortId(version.versionId)}</Mono>
        ) : (
          <span className="shell__status-absent">尚无</span>
        )}
      </span>

      <span className="shell__status-item">
        <span className="shell__status-key">最近保存</span>
        {version.updatedAt ? (
          <Mono>{version.updatedAt}</Mono>
        ) : (
          <span className="shell__status-absent">尚无</span>
        )}
      </span>

      <Badge tone={source === 'live' ? 'ok' : 'muted'} testId="shell-status-source">
        {source}
      </Badge>
    </div>
  );
}

import type { StaleView } from '../viewmodel/statusView';

export function StaleNotice({ stale }: { stale: StaleView }) {
  if (!stale.isStale) {
    return (
      <p className="notice notice--ok" data-testid="stale-none">
        无失效内容：所有里程碑产物均对应当前版本。
      </p>
    );
  }
  return (
    <div className="notice notice--warn" data-testid="stale-notice" role="alert">
      <strong>存在失效/过期内容</strong>
      <ul>
        {stale.reasons.map((reason, i) => (
          <li key={i} data-testid="stale-reason">
            {reason}
          </li>
        ))}
      </ul>
    </div>
  );
}

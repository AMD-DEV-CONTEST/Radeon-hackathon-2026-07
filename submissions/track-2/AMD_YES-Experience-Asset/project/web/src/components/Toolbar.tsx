import type { ResolvedConfig } from '../data/config';
import { Badge } from './primitives';

/**
 * Shows the active data source and offers a mock/live switch plus refresh.
 * Switching source or scenario navigates with a query param so the reload picks
 * a different checked-in fixture or the live backend — it never mutates state.
 */
export function Toolbar({
  config,
  onRefresh,
  isRefreshing,
  fetchedAt,
}: {
  config: ResolvedConfig;
  onRefresh: () => void;
  isRefreshing: boolean;
  fetchedAt: string | null;
}) {
  const setParam = (key: string, value: string) => {
    const url = new URL(window.location.href);
    url.searchParams.set(key, value);
    window.location.assign(url.toString());
  };

  return (
    <div className="toolbar" data-testid="toolbar">
      <div className="toolbar__group">
        <span className="toolbar__label">数据源</span>
        <div className="segmented" role="group" aria-label="数据源">
          <button
            type="button"
            className={`seg${config.source === 'mock' ? ' seg--on' : ''}`}
            aria-pressed={config.source === 'mock'}
            onClick={() => setParam('source', 'mock')}
            data-testid="source-mock"
          >
            Mock
          </button>
          <button
            type="button"
            className={`seg${config.source === 'live' ? ' seg--on' : ''}`}
            aria-pressed={config.source === 'live'}
            onClick={() => setParam('source', 'live')}
            data-testid="source-live"
          >
            Live
          </button>
        </div>
        <Badge tone={config.source === 'live' ? 'info' : 'neutral'} testId="active-source">
          {config.source === 'live'
            ? `Live · ${config.apiBaseUrl || 'same-origin /api'}`
            : `Mock · ${config.scenario}`}
        </Badge>
      </div>
      <div className="toolbar__group">
        <span className="toolbar__fetched" data-testid="fetched-at">
          {fetchedAt ? `更新于 ${fetchedAt}` : ''}
        </span>
        <button
          type="button"
          className="btn"
          onClick={onRefresh}
          disabled={isRefreshing}
          data-testid="refresh"
        >
          {isRefreshing ? '刷新中…' : '刷新'}
        </button>
      </div>
    </div>
  );
}

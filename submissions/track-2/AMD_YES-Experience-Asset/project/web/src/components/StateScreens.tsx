import type { AssetAvailability } from '../data/provider';

export function LoadingScreen() {
  return (
    <div className="screen" data-testid="loading-screen" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <p>正在读取状态…</p>
    </div>
  );
}

export function ErrorScreen({
  message,
  retryable,
  onRetry,
}: {
  message: string;
  retryable: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="screen screen--error" data-testid="error-screen" role="alert">
      <h2>无法加载状态</h2>
      <p className="screen__message" data-testid="error-message">
        {message}
      </p>
      {retryable ? (
        <button type="button" className="btn btn--primary" onClick={onRetry} data-testid="error-retry">
          重试
        </button>
      ) : (
        <p className="hint">该错误不可自动重试，请检查后端与配置。</p>
      )}
    </div>
  );
}

export function EmptyAssetScreen({ availability }: { availability: AssetAvailability }) {
  const isNotServed = availability === 'not_served';
  return (
    <div className="screen screen--empty" data-testid="empty-screen">
      <h2>{isNotServed ? '后端尚未提供资产状态' : '还没有经验资产'}</h2>
      <p data-testid="empty-message">
        {isNotServed
          ? '当前本地后端仅提供健康与终态契约端点（E1-A）。资产、进度与运行状态的实时端点将在后续里程碑接入；界面不会为此编造内容。'
          : '后端可用，但尚未创建任何经验资产。创建后，这里会显示版本、里程碑与运行状态。'}
      </p>
    </div>
  );
}

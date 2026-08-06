import './shell.css';

/**
 * A visible in-flight state for local backend operations.
 *
 * This deliberately shows no percentage, duration estimate, or claim that a
 * particular operation invokes the model. The caller names the operation; the
 * shared note only says that the local service has not returned yet.
 */
export function Working({
  label,
  testId = 'shell-working',
}: {
  label: string;
  testId?: string;
}) {
  return (
    <div className="shell__working" role="status" aria-live="polite" data-testid={testId}>
      <span className="shell__working-pulse" aria-hidden="true" />
      <span>
        {label}
        <span className="shell__working-note">
          正在等待本地服务返回真实结果；收到后界面会更新。
        </span>
      </span>
    </div>
  );
}

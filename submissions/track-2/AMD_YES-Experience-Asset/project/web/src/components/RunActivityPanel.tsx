import type { RunView } from '../viewmodel/statusView';
import { Badge, Field, Mono, Panel } from './primitives';
import { formatTime, terminalTone } from './labels';

export function RunActivityPanel({ run }: { run: RunView }) {
  if (!run) {
    return (
      <Panel title="当前运行" testId="run-panel">
        <p className="notice notice--muted" data-testid="run-idle">
          当前没有正在进行的运行。
        </p>
      </Panel>
    );
  }

  if (run.kind === 'progress') {
    return (
      <Panel title="当前运行" testId="run-panel">
        <div className="row">
          <Badge tone="info" testId="run-state">
            {run.state}
          </Badge>
          <span className="run__stage">{run.stage}</span>
        </div>
        {run.percent !== null && run.percentBasis !== null ? (
          <>
            <div
              className="progress"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={run.percent}
              data-testid="run-progress"
            >
              <div className="progress__bar" style={{ width: `${run.percent}%` }} />
            </div>
            <p className="progress__label" data-testid="run-progress-label">
              {run.percent}%（{run.milestonesDone ?? '—'}/{run.milestonesTotal ?? '—'} 公开里程碑 ·{' '}
              {run.percentBasis}）
            </p>
          </>
        ) : (
          <p className="notice notice--muted" data-testid="run-progress-indeterminate">
            后端尚未提供有公开依据的百分比进度。
          </p>
        )}
        <p className="run__message" data-testid="run-message">
          {run.message}
        </p>
        <div className="fields">
          <Field label="运行 ID">
            <Mono>{run.runId}</Mono>
          </Field>
          <Field label="事件时间">{formatTime(run.occurredAt)}</Field>
          <Field label="工作计划">{run.workPlanStepCount} 个规范步骤</Field>
          <Field label="检索范围">
            <Mono>{run.retrievalScope}</Mono>
          </Field>
          <Field label="策略决策">
            <Mono>{run.latestPolicyOutcome ?? '尚未记录'}</Mono>
          </Field>
          <Field label="工具执行">
            <Mono>{run.latestToolExecutionStatus ?? '尚未执行'}</Mono>
          </Field>
          <Field label="验证结果">
            <Mono>{run.verificationOutcome ?? '尚未验证'}</Mono>
          </Field>
          <Field label="ETA" testId="run-eta">
            {run.etaSeconds !== null && run.etaBasis !== null
              ? `${run.etaSeconds} 秒 · ${run.etaBasis}`
              : '后端尚无有依据的估算'}
          </Field>
        </div>
        <p className="hint">百分比只使用公开里程碑依据；内部工作单元不会显示为用户进度。</p>
      </Panel>
    );
  }

  // terminal
  return (
    <Panel title="当前运行" testId="run-panel">
      <div className="row">
        <Badge tone={terminalTone(run.state)} testId="run-terminal-state">
          {run.state}
        </Badge>
        {run.isSafeStop ? (
          <Badge tone="info" testId="run-safe-stop">
            安全停止
          </Badge>
        ) : null}
        {run.retryable ? (
          <Badge tone="neutral" testId="run-retryable">
            可重试
          </Badge>
        ) : (
          <Badge tone="muted">不可重试</Badge>
        )}
      </div>
      <p
        className={`notice ${run.isSuccess ? 'notice--ok' : run.isSafeStop ? 'notice--info' : 'notice--danger'}`}
        data-testid="run-safe-message"
      >
        {run.safeMessage}
      </p>
      <div className="fields">
        <Field label="恢复动作" testId="run-recovery">
          {run.recoveryAction}
        </Field>
        <Field label="最后有效版本">
          <Mono>{run.lastDurableVersionId ?? '—'}</Mono>
        </Field>
        {run.internalErrorClass ? (
          <Field label="错误类别">
            <Mono>{run.internalErrorClass}</Mono>
          </Field>
        ) : null}
        <Field label="用时">{run.elapsedMs} ms</Field>
        <Field label="模型调用次数">{run.modelCallCount}</Field>
        <Field label="结束时间">{formatTime(run.finishedAt)}</Field>
      </div>
    </Panel>
  );
}

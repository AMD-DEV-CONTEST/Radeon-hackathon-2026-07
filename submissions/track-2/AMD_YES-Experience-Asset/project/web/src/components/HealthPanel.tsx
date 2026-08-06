import type { HealthView } from '../viewmodel/statusView';
import { Badge, Field, Mono, Panel } from './primitives';
import { formatTime, healthTone } from './labels';

export function HealthPanel({ health }: { health: HealthView }) {
  return (
    <Panel title="服务健康" testId="health-panel">
      <div className="row">
        <Badge tone={healthTone(health.status)} testId="health-status">
          {health.status === 'ok'
            ? '正常'
            : health.status === 'degraded'
              ? '降级'
              : '不可用'}
        </Badge>
        {health.inferenceMode ? (
          <Badge tone="info" testId="health-inference-mode">
            {health.inferenceMode}
          </Badge>
        ) : null}
      </div>
      {health.available ? (
        <div className="fields">
          <Field label="应用版本">
            <Mono>{health.appVersion}</Mono>
          </Field>
          <Field label="数据库" testId="health-database">
            {health.database}
          </Field>
          <Field label="模型端点">
            <Mono>{health.modelEndpoint}</Mono>
          </Field>
          <Field label="模型 Profile">
            <Mono>{health.modelProfile}</Mono>
          </Field>
          <Field label="GPU 可用性" testId="health-gpu">
            {health.gpuViability}
          </Field>
          <Field label="检查时间">{formatTime(health.checkedAt)}</Field>
        </div>
      ) : (
        <p className="notice notice--danger" data-testid="health-error">
          无法读取健康状态：{health.error ?? '未知错误'}
        </p>
      )}
    </Panel>
  );
}

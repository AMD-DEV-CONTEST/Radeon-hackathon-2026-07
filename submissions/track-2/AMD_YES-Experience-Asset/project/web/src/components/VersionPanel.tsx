import type { VersionView } from '../viewmodel/statusView';
import { Badge, Field, Mono, Panel } from './primitives';
import { formatTime } from './labels';

export function VersionPanel({ version }: { version: VersionView }) {
  return (
    <Panel title="版本与自动保存" testId="version-panel">
      <div className="fields">
        <Field label="资产 ID">
          <Mono>{version.assetId}</Mono>
        </Field>
        <Field label="当前版本" testId="version-current">
          <Mono>{version.versionId}</Mono>
        </Field>
        <Field label="父版本">
          <Mono>{version.parentVersionId ?? '（首个版本）'}</Mono>
        </Field>
        <Field label="生命周期">
          <Badge tone={version.lifecycle === 'PAUSED' ? 'info' : 'neutral'}>
            {version.lifecycle ?? '—'}
          </Badge>
        </Field>
        <Field label="最近保存" testId="version-updated">
          {formatTime(version.updatedAt)}
        </Field>
        <Field label="变更类型">{version.changeKind ?? '—'}</Field>
      </div>
      {version.changeReason ? (
        <p className="notice notice--info" data-testid="version-change-reason">
          最近一次保存：{version.changeReason}
        </p>
      ) : null}
      <p className="hint">
        自动保存含义：每个被接受的变更都会提交为一个新的不可变版本；界面只反映已提交的持久状态。
      </p>
    </Panel>
  );
}

import { useState } from 'react';
import { ROUTE_ELIGIBILITY_LABEL, ROUTE_ELIGIBILITY_TONE, ROUTE_LABEL } from '../../components/labels';
import { Badge, Mono, Panel } from '../../components/primitives';
import type { M5ApprovalAction, M5PrivacyAction, M5WorkspaceView } from './types';

type Props = {
  workspace: M5WorkspaceView;
  onResolveFinding: (findingId: string, action: M5PrivacyAction) => void;
  onApprove: (binding: M5ApprovalAction) => void;
  onCanonicalEdit?: () => void;
};

const CONTENT_CHANGE_ACTIONS = new Set<M5PrivacyAction>(['GENERALIZE', 'REMOVE']);

function severityTone(severity: M5WorkspaceView['findings'][number]['severity']) {
  if (severity === 'CRITICAL' || severity === 'HIGH') return 'danger' as const;
  if (severity === 'MEDIUM') return 'warn' as const;
  return 'info' as const;
}

export function M5ReviewPanel({
  workspace,
  onResolveFinding,
  onApprove,
  onCanonicalEdit = () => {},
}: Props) {
  const [pendingChange, setPendingChange] = useState<{
    findingId: string;
    action: M5PrivacyAction;
  } | null>(null);

  const resolve = (findingId: string, action: M5PrivacyAction) => {
    if (CONTENT_CHANGE_ACTIONS.has(action)) {
      setPendingChange({findingId, action});
      return;
    }
    onResolveFinding(findingId, action);
  };

  const confirmContentChange = () => {
    if (!pendingChange) return;
    setPendingChange(null);
    onCanonicalEdit();
  };

  const approval = workspace.approval;
  const privateRoute = approval.route === 'PRIVATE_SELF';
  const hasOpenFinding = workspace.findings.some(finding => finding.resolution === 'OPEN');
  const canApprove =
    !privateRoute
    && approval.state === 'READY'
    && workspace.privacy_review_state === 'COMPLETE'
    && !hasOpenFinding
    && Boolean(approval.route_draft_id)
    && Boolean(approval.privacy_review_hash);

  return (
    <section data-testid="m5-review-panel">
      <Panel title="M5 Route Readiness Matrix" testId="m5-route-matrix">
        <div className="row">
          <Badge tone="info">版本 {workspace.version_id}</Badge>
          <Badge tone={workspace.autosave_state === 'save_failed' ? 'danger' : 'ok'}>
            {workspace.autosave_state}
          </Badge>
          <Badge tone={workspace.terminal_state ? 'muted' : 'info'}>
            {workspace.terminal_state ?? '运行中'}
          </Badge>
        </div>
        <ul className="routes">
          {workspace.decisions.map(decision => (
            <li className="route" key={decision.route} data-testid={`m5-route-${decision.route}`}>
              <div className="route__head">
                <span className="route__name">{ROUTE_LABEL[decision.route]}</span>
                <Badge tone={ROUTE_ELIGIBILITY_TONE[decision.eligibility]}>
                  {ROUTE_ELIGIBILITY_LABEL[decision.eligibility]}
                </Badge>
              </div>
              <p className="route__why">{decision.explanation}</p>
              {decision.reason_codes?.length ? (
                <p className="route__why">原因：{decision.reason_codes.join(', ')}</p>
              ) : null}
              <div
                className="route__why"
                data-testid={`m5-route-${decision.route}-evidence`}
              >
                <p>
                  支持证据：
                  {decision.supporting_statement_ids?.length
                    ? <Mono>{decision.supporting_statement_ids.join(', ')}</Mono>
                    : '无'}
                </p>
                <p>
                  缺失证据：
                  {decision.missing_statement_ids?.length
                    ? <Mono>{decision.missing_statement_ids.join(', ')}</Mono>
                    : '无'}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="隐私与表述风险" testId="m5-privacy-review">
        <div className="notice notice--warn">
          自动检测只用于辅助检查，不能保证发现全部隐私或表述风险。
        </div>
        {workspace.privacy_review_state === 'FAILED' ? (
          <div className="notice notice--danger" role="alert">
            隐私检查失败：{workspace.privacy_failure_code ?? 'UNKNOWN'}。外部批准保持阻断。
          </div>
        ) : null}
        {workspace.findings.length === 0 ? (
          <div className="notice notice--muted">当前检查没有返回风险项，仍需用户最终复核。</div>
        ) : (
          <ul className="routes">
            {workspace.findings.map(finding => (
              <li className="route" key={finding.finding_id}>
                <div className="route__head">
                  <span className="route__name">{finding.category}</span>
                  <Badge tone={severityTone(finding.severity)}>{finding.severity}</Badge>
                </div>
                <p className="route__why">{finding.explanation}</p>
                <p className="route__why">
                  影响引用：<Mono>{finding.affected_reference_ids.join(', ')}</Mono>
                </p>
                <div className="row">
                  {finding.allowed_actions.map(action => (
                    <button
                      className="btn btn--sm"
                      disabled={finding.resolution !== 'OPEN'}
                      key={action}
                      onClick={() => resolve(finding.finding_id, action)}
                    >
                      {action}
                    </button>
                  ))}
                  <Badge tone={finding.resolution === 'OPEN' ? 'warn' : 'ok'}>
                    {finding.resolution}
                  </Badge>
                </div>
              </li>
            ))}
          </ul>
        )}
        {pendingChange ? (
          <div className="notice notice--danger" role="dialog" aria-label="确认内容修改">
            <p>
              {pendingChange.action} 需要你先对受影响的 canonical 内容做明确编辑。
              未创建新版本前，系统不会把该风险标记为已解决。
            </p>
            <div className="row">
              <button className="btn btn--primary" onClick={confirmContentChange}>
                去 M1 创建新版本
              </button>
              <button className="btn" onClick={() => setPendingChange(null)}>取消</button>
            </div>
          </div>
        ) : null}
      </Panel>

      <Panel title="外部分享批准" testId="m5-approval">
        <div className="fields">
          <div className="field"><span className="field__label">路线</span><span>{ROUTE_LABEL[approval.route]}</span></div>
          <div className="field"><span className="field__label">语言</span><span>{approval.language}</span></div>
          <div className="field"><span className="field__label">版本</span><Mono>{approval.version_id}</Mono></div>
          <div className="field"><span className="field__label">状态</span><Badge tone={approval.state === 'READY' || approval.state === 'APPROVED' ? 'ok' : 'warn'}>{approval.state}</Badge></div>
        </div>
        {approval.stale_reason ? (
          <div className="notice notice--danger">旧批准不可用：{approval.stale_reason}</div>
        ) : null}
        <p className="route__why">预览、生成和私人下载都不会产生外部分享批准。</p>
        {privateRoute ? (
          <div className="notice notice--muted">
            PRIVATE_SELF 只产生私人预览与下载，不需要、也不会创建外部分享批准。
          </div>
        ) : (
          <button
            className="btn btn--primary"
            disabled={!canApprove}
            onClick={() => {
              if (!approval.route_draft_id) return;
              onApprove({
                route_draft_id: approval.route_draft_id,
                user_action: 'APPROVE_SHAREABLE_EXPORT',
                idempotency_key: [
                  workspace.asset_id,
                  approval.version_id,
                  approval.route_draft_id,
                  approval.privacy_review_hash,
                ].join(':'),
              });
            }}
          >
            批准当前精确草稿用于外部导出
          </button>
        )}
      </Panel>
    </section>
  );
}

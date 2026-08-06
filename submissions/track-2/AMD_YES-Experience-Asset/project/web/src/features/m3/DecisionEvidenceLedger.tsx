import { Badge, Mono, Panel, type Tone } from '../../components/primitives';
import type {
  EvidenceDisposition,
  LedgerRole,
  M3WorkspaceV1,
} from './types';

const ROLE_LABELS: Record<LedgerRole, string> = {
  ALTERNATIVE: '替代方案',
  REASON: '理由',
  DECISION: '最终决策',
  ACTION: '行动',
  OBSERVED_RESULT: '观察结果',
};

const EVIDENCE_LABELS: Record<EvidenceDisposition, string> = {
  SUPPORTED: '有证据',
  CONFLICTING: '证据冲突',
  UNRESOLVED: '待补充',
};

function evidenceTone(disposition: EvidenceDisposition): Tone {
  if (disposition === 'SUPPORTED') return 'ok';
  return disposition === 'CONFLICTING' ? 'danger' : 'warn';
}

function EvidenceDetails({
  workspace,
  momentIds,
  sourceStatementIds,
  derivedStatementIds,
}: {
  workspace: M3WorkspaceV1;
  momentIds: string[];
  sourceStatementIds: string[];
  derivedStatementIds: string[];
}) {
  const moments = new Map(
    workspace.evidence_moments.map((moment) => [moment.moment_id, moment]),
  );
  const statements = new Map(
    workspace.evidence_statements.map((statement) => [
      statement.statement_id,
      statement,
    ]),
  );
  const renderStatements = (ids: string[], label: string) =>
    ids.length ? (
      <div>
        <strong>{label}</strong>
        <ul>
          {ids.map((id) => {
            const evidence = statements.get(id);
            return (
              <li key={id}>
                <Mono>{id}</Mono>
                {evidence ? (
                  <>
                    ：{evidence.text}
                    {evidence.source_labels.length ? (
                      <small>（来源：{evidence.source_labels.join('、')}）</small>
                    ) : null}
                  </>
                ) : (
                  '：证据内容不可用'
                )}
              </li>
            );
          })}
        </ul>
      </div>
    ) : null;

  return (
    <details data-testid="m3-evidence-details">
      <summary>查看证据内容</summary>
      <div>
        <strong>来源时刻</strong>
        <ul>
          {momentIds.map((id) => {
            const moment = moments.get(id);
            return (
              <li key={id}>
                <Mono>{id}</Mono>
                {moment ? `：${moment.title} — ${moment.description}` : '：证据内容不可用'}
              </li>
            );
          })}
        </ul>
      </div>
      {renderStatements(sourceStatementIds, '来源陈述')}
      {renderStatements(derivedStatementIds, '推导依据')}
    </details>
  );
}

export function DecisionEvidenceLedger({
  workspace,
  onStatementTextChange,
  onStatementAction,
  drafts = {},
}: {
  workspace: M3WorkspaceV1;
  onStatementTextChange?: (statementId: string, text: string) => void;
  onStatementAction?: (statementId: string, action: 'CONFIRM' | 'MARK_UNRESOLVED') => void;
  drafts?: Record<string, string>;
}) {
  const { artifact, progress, latest_failure: failure } = workspace;
  const editable =
    workspace.is_current &&
    artifact.state !== 'INVALIDATED' &&
    workspace.allowed_actions.includes('EDIT') &&
    onStatementTextChange !== undefined;

  return (
    <Panel
      title="Decision and Evidence Ledger"
      testId="m3-decision-evidence-ledger"
      actions={
        <Badge tone={artifact.state === 'INVALIDATED' ? 'danger' : 'info'}>
          {artifact.state}
        </Badge>
      }
    >
      <p>
        绑定 M2：<Mono>{artifact.base_m2_artifact_id}</Mono>
      </p>
      <p>
        绑定规范版本：<Mono>{artifact.base_canonical_version_id}</Mono>
      </p>

      <div data-testid="m3-progress">
        <strong>{progress.stage}</strong>：{progress.safe_message}
        <small>
          修复 {progress.structured_repairs_used}/{progress.structured_repair_budget}；
          重规划 {progress.replans_used}/{progress.replan_budget}；模型调用{' '}
          {progress.model_calls_used}/{progress.model_call_budget}
        </small>
      </div>

      {failure ? (
        <div role="alert" data-testid="m3-failure">
          <strong>{failure.code}</strong>：{failure.safe_user_message}
          <p>{failure.recovery_action}</p>
        </div>
      ) : null}

      {artifact.state === 'INVALIDATED' ? (
        <div role="alert" data-testid="m3-invalidated">
          <strong>该决策账本已失效。</strong> {artifact.invalidation_reason}
        </div>
      ) : null}

      <ol data-testid="m3-decision-list">
        {artifact.entries.map((entry) => (
          <li key={entry.decision_id}>
            <h3>{entry.title}</h3>
            <div>
              {entry.statements.map((statement) => (
                <section
                  key={statement.statement_id}
                  data-testid={`m3-statement-${statement.role.toLowerCase()}`}
                >
                  <label htmlFor={statement.statement_id}>
                    <strong>{ROLE_LABELS[statement.role]}</strong>
                  </label>{' '}
                  <Badge tone={evidenceTone(statement.evidence_disposition)}>
                    {EVIDENCE_LABELS[statement.evidence_disposition]}
                  </Badge>{' '}
                  <Badge tone={statement.confirmation === 'CONFIRMED' ? 'ok' : 'muted'}>
                    {statement.status} / {statement.confirmation}
                  </Badge>
                  <textarea
                    id={statement.statement_id}
                    aria-label={ROLE_LABELS[statement.role]}
                    value={drafts[statement.statement_id] ?? statement.text}
                    readOnly={!editable}
                    onChange={(event) =>
                      onStatementTextChange?.(
                        statement.statement_id,
                        event.target.value,
                      )
                    }
                  />
                  {editable ? <div>
                    <button type="button" onClick={() => onStatementAction?.(statement.statement_id, 'CONFIRM')}>CONFIRM</button>
                    <button type="button" onClick={() => onStatementAction?.(statement.statement_id, 'MARK_UNRESOLVED')}>MARK_UNRESOLVED</button>
                  </div> : null}
                  {statement.unresolved_reason ? (
                    <p data-testid="m3-unresolved-reason">
                      {statement.unresolved_reason}
                    </p>
                  ) : null}
                  <small>
                    来源时刻 {statement.source_moment_ids.length}；来源陈述{' '}
                    {statement.source_statement_ids.length}；推导陈述{' '}
                    {statement.derived_from_statement_ids.length}
                  </small>
                  <EvidenceDetails
                    workspace={workspace}
                    momentIds={statement.source_moment_ids}
                    sourceStatementIds={statement.source_statement_ids}
                    derivedStatementIds={statement.derived_from_statement_ids}
                  />
                </section>
              ))}
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

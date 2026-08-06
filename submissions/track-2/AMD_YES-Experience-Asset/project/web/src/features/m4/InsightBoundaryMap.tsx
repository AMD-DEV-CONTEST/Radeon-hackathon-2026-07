import { Badge, Mono, Panel } from '../../components/primitives';
import { STATE_LABELS, STATE_TONES, type M4View } from './m4View';
import { BOUNDARY_ROLES, type InsightRole, type InsightStatementV1, type M4WorkspaceV1 } from './types';

const ROLE_LABELS: Record<InsightRole, string> = {
  LESSON: '教训',
  SUPPORT: '支持证据',
  COUNTERFACTUAL: '反事实',
  LIMITATION: '适用局限',
  COUNTEREXAMPLE: '反例',
  APPLICABILITY: '迁移条件',
};

function EvidenceDetails({
  statement,
  view,
}: {
  statement: InsightStatementV1;
  view: M4View;
}) {
  if (statement.is_visible_gap) {
    return (
      <p data-testid="m4-gap-reason" className="notice notice--warn">
        <strong>缺口：</strong>
        {statement.gap_reason}
      </p>
    );
  }
  return (
    <details data-testid="m4-evidence-details">
      <summary>查看这条依据的原始证据</summary>
      <ul>
        {statement.source_statement_ids.map((id) => {
          const evidence = view.evidenceById.get(id);
          return (
            <li key={id}>
              <Mono>{id}</Mono>
              {evidence ? (
                <>
                  ：{evidence.text}
                  {evidence.source_refs.length ? (
                    <small>（来源：{evidence.source_refs.join('、')}）</small>
                  ) : null}
                </>
              ) : (
                '：证据内容不可用'
              )}
            </li>
          );
        })}
      </ul>
      {statement.source_decision_ids.length ? (
        <div>
          <strong>来源决策</strong>
          <ul>
            {statement.source_decision_ids.map((id) => (
              <li key={id}>
                <Mono>{id}</Mono>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </details>
  );
}

export function InsightBoundaryMap({
  workspace,
  view,
  drafts = {},
  onStatementTextChange,
  onStatementSave,
  onMarkGap,
}: {
  workspace: M4WorkspaceV1;
  view: M4View;
  drafts?: Record<string, string>;
  onStatementTextChange?: (statementId: string, text: string) => void;
  onStatementSave?: (statementId: string) => void;
  onMarkGap?: (statementId: string) => void;
}) {
  const { map } = workspace;
  const editable = view.canEdit && onStatementTextChange !== undefined;

  return (
    <Panel
      title="Insight and Boundary Map"
      testId="m4-insight-boundary-map"
      actions={
        <Badge tone={STATE_TONES[view.state]} testId="m4-state-badge">
          {STATE_LABELS[view.state]}
        </Badge>
      }
    >
      {view.failure ? (
        <div role="alert" data-testid="m4-failure" className="notice notice--danger">
          <strong>{view.failure.failure_code}</strong>：{view.failure.safe_user_message}
          <p>{view.failure.retryable ? '可以重试。' : '重试不会改变结果。'}</p>
        </div>
      ) : null}

      {view.state === 'IN_PROGRESS' ? (
        <p data-testid="m4-progress">{view.progressMessage || '正在生成洞察与边界图。'}</p>
      ) : null}

      {map === null ? (
        <p data-testid="m4-empty">
          尚未生成洞察与边界图。它需要一份已接受的 M3 决策与证据账本。
        </p>
      ) : null}

      {map ? (
        <>
          <p>
            绑定 M3：<Mono>{map.base_m3_artifact_id}</Mono>
          </p>
          <p>
            绑定规范版本：<Mono>{map.base_canonical_version_id}</Mono>
          </p>

          {map.state === 'INVALIDATED' ? (
            <div role="alert" data-testid="m4-invalidated" className="notice notice--danger">
              <strong>这张图已失效。</strong> {map.invalidation_reason}
              <p>
                继续按原样阅读，等于在读一条建立在你已经修正掉的证据上的教训。
                受影响的洞察 {map.affected_insight_ids.length} 条，可复用{' '}
                {map.reusable_insight_ids.length} 条。
              </p>
            </div>
          ) : null}

          {view.visibleGaps.length ? (
            <div data-testid="m4-gap-summary" className="notice notice--warn">
              这张图有 {view.visibleGaps.length} 处可见缺口，尚未由证据支持。
            </div>
          ) : null}

          <ol data-testid="m4-insight-list">
            {map.entries.map((entry) => (
              <li key={entry.insight_id} data-testid="m4-insight-entry">
                <h3>{entry.title}</h3>
                <div>
                  {entry.statements.map((statement) => (
                    <section
                      key={statement.statement_id}
                      data-testid={`m4-statement-${statement.role.toLowerCase()}`}
                      data-gap={statement.is_visible_gap ? 'true' : 'false'}
                      className={statement.is_visible_gap ? 'statement statement--gap' : 'statement'}
                    >
                      <label htmlFor={statement.statement_id}>
                        <strong>{ROLE_LABELS[statement.role]}</strong>
                      </label>{' '}
                      {BOUNDARY_ROLES.includes(statement.role) ? (
                        <Badge tone="info">边界</Badge>
                      ) : null}{' '}
                      {statement.is_visible_gap ? (
                        <Badge tone="warn" testId="m4-gap-badge">
                          可见缺口
                        </Badge>
                      ) : (
                        <Badge tone="ok">
                          {statement.source_statement_ids.length} 条证据
                        </Badge>
                      )}
                      <textarea
                        id={statement.statement_id}
                        aria-label={ROLE_LABELS[statement.role]}
                        value={drafts[statement.statement_id] ?? statement.text}
                        readOnly={!editable}
                        onChange={(event) =>
                          onStatementTextChange?.(statement.statement_id, event.target.value)
                        }
                      />
                      {editable ? (
                        <div>
                          <button
                            type="button"
                            onClick={() => onStatementSave?.(statement.statement_id)}
                          >
                            保存修改
                          </button>
                          {statement.is_visible_gap ? null : (
                            <button
                              type="button"
                              onClick={() => onMarkGap?.(statement.statement_id)}
                            >
                              标为缺口
                            </button>
                          )}
                        </div>
                      ) : null}
                      <EvidenceDetails statement={statement} view={view} />
                    </section>
                  ))}
                </div>
              </li>
            ))}
          </ol>
        </>
      ) : null}
    </Panel>
  );
}

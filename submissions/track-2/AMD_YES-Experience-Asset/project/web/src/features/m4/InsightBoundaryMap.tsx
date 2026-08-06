import { Badge, Mono, Panel } from '../../components/primitives';
import { STATE_LABELS, STATE_TONES, type M4View } from './m4View';
import { BOUNDARY_ROLES, type InsightRole, type InsightStatementV1, type M4WorkspaceV1 } from './types';

const ROLE_LABELS: Record<InsightRole, string> = {
  LESSON: 'Lesson',
  SUPPORT: 'Supporting evidence',
  COUNTERFACTUAL: 'Counterfactual',
  LIMITATION: 'Limitation',
  COUNTEREXAMPLE: 'Counterexample',
  APPLICABILITY: 'Conditions for reuse',
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
        <strong>Gap:</strong>
        {statement.gap_reason}
      </p>
    );
  }
  return (
    <details data-testid="m4-evidence-details">
      <summary>View the original evidence</summary>
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
                    <small> (Sources: {evidence.source_refs.join(', ')})</small>
                  ) : null}
                </>
              ) : (
                ': Evidence unavailable'
              )}
            </li>
          );
        })}
      </ul>
      {statement.source_decision_ids.length ? (
        <div>
          <strong>Source decisions</strong>
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
          <p>{view.failure.retryable ? 'You can retry.' : 'Retrying will not change the result.'}</p>
        </div>
      ) : null}

      {view.state === 'IN_PROGRESS' ? (
        <p data-testid="m4-progress">{view.progressMessage || 'Building the insight and boundary map…'}</p>
      ) : null}

      {map === null ? (
        <p data-testid="m4-empty">
          No insight map yet. First confirm the M3 decision and evidence ledger.
        </p>
      ) : null}

      {map ? (
        <>
          <p>
            Based on M3: <Mono>{map.base_m3_artifact_id}</Mono>
          </p>
          <p>
            Canonical version: <Mono>{map.base_canonical_version_id}</Mono>
          </p>

          {map.state === 'INVALIDATED' ? (
            <div role="alert" data-testid="m4-invalidated" className="notice notice--danger">
              <strong>This map is out of date.</strong> {map.invalidation_reason}
              <p>
                Some insights rely on evidence you have since corrected. Affected insights:{' '}
                {map.affected_insight_ids.length}; still reusable: {map.reusable_insight_ids.length}.
              </p>
            </div>
          ) : null}

          {view.visibleGaps.length ? (
            <div data-testid="m4-gap-summary" className="notice notice--warn">
              This map has {view.visibleGaps.length} visible evidence gaps.
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
                        <Badge tone="info">Boundary</Badge>
                      ) : null}{' '}
                      {statement.is_visible_gap ? (
                        <Badge tone="warn" testId="m4-gap-badge">
                          Visible gap
                        </Badge>
                      ) : (
                        <Badge tone="ok">
                          {statement.source_statement_ids.length} evidence references
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
                            Save changes
                          </button>
                          {statement.is_visible_gap ? null : (
                            <button
                              type="button"
                              onClick={() => onMarkGap?.(statement.statement_id)}
                            >
                              Mark as a gap
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

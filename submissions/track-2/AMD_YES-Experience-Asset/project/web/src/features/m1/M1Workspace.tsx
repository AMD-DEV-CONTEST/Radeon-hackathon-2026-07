import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { LiveM1Api, M1ApiError, type M1Api } from './api';
import {
  draftFromWorkspace,
  draftMatchesWorkspace,
  type M1Draft,
  type M1SourceKind,
  type M1Workspace,
} from './types';

const ACTIVE_ASSET_KEY = 'experience-asset.m1.active-asset-id';
const EMPTY_DRAFT: M1Draft = { context: '', goal: '', constraints: '', userIntent: '' };

function savedTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'The local operation failed. Please try again.';
}

export function M1ExperienceWorkspace({
  apiBaseUrl = '',
  api: providedApi,
  storage = window.localStorage,
  autosaveDelayMs = 700,
}: {
  apiBaseUrl?: string;
  api?: M1Api;
  storage?: Storage;
  autosaveDelayMs?: number;
}) {
  const api = useMemo(
    () => providedApi ?? new LiveM1Api(apiBaseUrl),
    [apiBaseUrl, providedApi],
  );
  const [workspace, setWorkspace] = useState<M1Workspace | null>(null);
  const [draft, setDraft] = useState<M1Draft>(EMPTY_DRAFT);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const [sourceText, setSourceText] = useState('');
  const [sourceKind, setSourceKind] = useState<M1SourceKind>('PASTED_TEXT');
  const [sourceLabel, setSourceLabel] = useState('My experience');
  const [fileName, setFileName] = useState<string | null>(null);
  const [goalHint, setGoalHint] = useState('');
  const [questionAnswers, setQuestionAnswers] = useState<Record<string, string>>({});
  const [agentGoal, setAgentGoal] = useState('Check the brief against the current source evidence');
  const [allowCurrentSourceSearch, setAllowCurrentSourceSearch] = useState(false);
  const [phase, setPhase] = useState<'restoring' | 'ready' | 'working'>('restoring');
  const [activity, setActivity] = useState('Ready');
  const [error, setError] = useState<string | null>(null);

  const applyWorkspace = useCallback(
    (next: M1Workspace, resetDraft = true) => {
      setWorkspace(next);
      storage.setItem(ACTIVE_ASSET_KEY, next.asset.asset_id);
      if (resetDraft) setDraft(draftFromWorkspace(next));
      setError(null);
    },
    [storage],
  );

  useEffect(() => {
    const assetId = storage.getItem(ACTIVE_ASSET_KEY);
    if (!assetId) {
      setPhase('ready');
      return;
    }
    let cancelled = false;
    api
      .get(assetId)
      .then((next) => {
        if (!cancelled) {
          applyWorkspace(next);
          setActivity('Restored from the local saved version');
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          if (reason instanceof M1ApiError && reason.status === 404) {
            storage.removeItem(ACTIVE_ASSET_KEY);
          } else {
            setError(errorMessage(reason));
          }
        }
      })
      .finally(() => {
        if (!cancelled) setPhase('ready');
      });
    return () => {
      cancelled = true;
    };
  }, [api, applyWorkspace, storage]);

  const hasUnsavedChanges = workspace !== null && !draftMatchesWorkspace(draft, workspace);

  useEffect(() => {
    if (
      !workspace ||
      !hasUnsavedChanges ||
      phase === 'working' ||
      workspace.asset.lifecycle === 'PAUSED' ||
      !workspace.allowed_actions.includes('EDIT')
    ) {
      return;
    }
    const base = workspace;
    const snapshot = draft;
    const timer = window.setTimeout(() => {
      setPhase('working');
      setActivity('Autosaving…');
      api
        .edit(base.asset.asset_id, base.asset.version_id, snapshot)
        .then((next) => {
          const unchangedDuringSave =
            JSON.stringify(draftRef.current) === JSON.stringify(snapshot);
          applyWorkspace(next, unchangedDuringSave);
          setActivity(unchangedDuringSave ? 'Autosaved' : 'Saved — syncing newer edits…');
        })
        .catch(async (reason: unknown) => {
          if (reason instanceof M1ApiError && reason.status === 409) {
            try {
              const current = await api.get(base.asset.asset_id);
              applyWorkspace(current, false);
              setActivity('A newer version was found. Your edits were preserved and will be saved again.');
              return;
            } catch (reloadError: unknown) {
              setError(errorMessage(reloadError));
              return;
            }
          }
          setError(errorMessage(reason));
        })
        .finally(() => setPhase('ready'));
    }, autosaveDelayMs);
    return () => window.clearTimeout(timer);
  }, [
    api,
    applyWorkspace,
    autosaveDelayMs,
    draft,
    hasUnsavedChanges,
    phase,
    workspace,
  ]);

  const runAction = async (
    label: string,
    action: (current: M1Workspace) => Promise<M1Workspace>,
  ) => {
    if (!workspace || hasUnsavedChanges) return;
    setPhase('working');
    setActivity(label);
    setError(null);
    try {
      const next = await action(workspace);
      applyWorkspace(next);
      if (
        label === 'Run local agent' &&
        next.latest_agent_run?.terminal_state &&
        next.latest_agent_run.terminal_state !== 'SUCCEEDED'
      ) {
        setActivity(`Agent stopped safely: ${next.latest_agent_run.terminal_state}`);
      } else {
        setActivity(`${label} complete`);
      }
    } catch (reason: unknown) {
      setError(errorMessage(reason));
    } finally {
      setPhase('ready');
    }
  };

  const start = async () => {
    if (!sourceText.trim()) {
      setError('Paste an experience or choose a .txt / .md file first.');
      return;
    }
    setPhase('working');
    setActivity('Creating Experience Brief v0.1…');
    setError(null);
    try {
      applyWorkspace(
        await api.ingest({
          source_kind: sourceKind,
          text: sourceText,
          display_label: sourceLabel.trim() || fileName || 'My experience',
          ...(fileName ? { original_file_name: fileName } : {}),
          ...(goalHint.trim() ? { goal_hint: goalHint.trim() } : {}),
        }),
      );
      setActivity('Your first brief has been saved');
    } catch (reason: unknown) {
      setError(errorMessage(reason));
    } finally {
      setPhase('ready');
    }
  };

  const readFile = async (file: File | undefined) => {
    if (!file) return;
    const lowerName = file.name.toLowerCase();
    if (!lowerName.endsWith('.txt') && !lowerName.endsWith('.md')) {
      setError('Only .txt and .md files are supported in this version.');
      return;
    }
    const text = await file.text();
    if (text.length > 200_000) {
      setError('The file exceeds 200,000 characters. Please shorten it and try again.');
      return;
    }
    setSourceText(text);
    setSourceLabel(file.name);
    setFileName(file.name);
    setSourceKind(lowerName.endsWith('.md') ? 'MD_FILE' : 'TXT_FILE');
    setError(null);
  };

  const clearWorkspace = () => {
    storage.removeItem(ACTIVE_ASSET_KEY);
    setWorkspace(null);
    setDraft(EMPTY_DRAFT);
    setQuestionAnswers({});
    setActivity('Ready for a new experience');
    setError(null);
  };

  if (phase === 'restoring') {
    return (
      <section className="screen" data-testid="m1-restoring">
        <div className="spinner" aria-hidden="true" />
        <p>Restoring your locally saved Experience Brief…</p>
      </section>
    );
  }

  if (!workspace) {
    return (
      <section className="m1-start panel" data-testid="m1-start">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">Start with one experience</h2>
            <p className="m1-lead">
              It does not need to be polished. Tell the story as you remember it.
            </p>
          </div>
          <span className="badge badge--info">M1</span>
        </div>
        <div className="start-guide" aria-label="Three steps to begin">
          <span><b>1</b> Share the story</span>
          <i aria-hidden="true">→</i>
          <span><b>2</b> Answer focused questions</span>
          <i aria-hidden="true">→</i>
          <span><b>3</b> Confirm your first brief</span>
        </div>
        <label className="form-field">
          <span>What would you like this experience to become? (optional)</span>
          <input
            value={goalHint}
            onChange={(event) => setGoalHint(event.target.value)}
            placeholder="For example: capture what worked so I can reuse it later"
          />
        </label>
        <div className="form-field">
          <span>How would you like to begin?</span>
          <div className="segmented" role="group" aria-label="Input method">
            <button
              type="button"
              className={`seg${sourceKind === 'CONVERSATION' ? ' seg--on' : ''}`}
              aria-pressed={sourceKind === 'CONVERSATION'}
              onClick={() => {
                setSourceKind('CONVERSATION');
                setSourceLabel('My narrated experience');
                setFileName(null);
              }}
            >
              Tell the story
            </button>
            <button
              type="button"
              className={`seg${sourceKind === 'PASTED_TEXT' ? ' seg--on' : ''}`}
              aria-pressed={sourceKind === 'PASTED_TEXT'}
              onClick={() => {
                setSourceKind('PASTED_TEXT');
                setSourceLabel('My experience');
                setFileName(null);
              }}
            >
              Paste existing text
            </button>
          </div>
        </div>
        <label className="form-field">
          <span>Your experience</span>
          <textarea
            rows={10}
            value={sourceText}
            onChange={(event) => {
              setSourceText(event.target.value);
              if (sourceKind === 'TXT_FILE' || sourceKind === 'MD_FILE') {
                setSourceKind('PASTED_TEXT');
                setSourceLabel('My experience');
              }
              setFileName(null);
            }}
            placeholder={
              sourceKind === 'CONVERSATION'
                ? 'Tell it naturally, as if you were speaking to a thoughtful colleague. The agent will ask only what matters.'
                : 'Paste something you personally experienced. You can refine every detail after the first draft.'
            }
            data-testid="m1-source-text"
          />
        </label>
        <div className="m1-start__actions">
          <label className="btn m1-file">
            Upload .txt / .md
            <input
              type="file"
              accept=".txt,.md,text/plain,text/markdown"
              onChange={(event) => void readFile(event.target.files?.[0])}
              data-testid="m1-file"
            />
          </label>
          <button
            type="button"
            className="btn btn--primary"
            disabled={phase === 'working' || !sourceText.trim()}
            onClick={() => void start()}
            data-testid="m1-start-submit"
          >
            {phase === 'working' ? 'Shaping your brief…' : 'Create my first brief →'}
          </button>
        </div>
        <p className="hint">
          Processed in your private local environment. Nothing is published without your approval.
        </p>
        {error ? <div className="notice notice--danger">{error}</div> : null}
      </section>
    );
  }

  const paused = workspace.asset.lifecycle === 'PAUSED';
  const m1Done = ['CONFIRMED', 'COMPLETE_WITH_GAPS'].includes(
    workspace.asset.milestone_states.M1 ?? '',
  );
  const actionsBlocked = phase === 'working' || hasUnsavedChanges;

  return (
    <section className="m1-workspace" data-testid="m1-workspace">
      <div className="m1-summary panel">
        <div>
          <div className="row">
            <span className={`badge ${paused ? 'badge--warn' : 'badge--ok'}`}>
              {paused ? 'Paused' : m1Done ? 'M1 confirmed' : 'M1 in progress'}
            </span>
            <span className="badge badge--neutral">
              {workspace.progress.unresolved_question_count} open questions
            </span>
          </div>
          <strong>{m1Done ? 'Your Experience Brief is confirmed.' : 'Your Experience Brief is saved and ready to refine.'}</strong>
          <p className="hint">
            Version <span className="mono">{workspace.asset.version_id.slice(0, 8)}</span> ·
            Saved {savedTime(workspace.progress.last_saved_at)}
          </p>
        </div>
        <div className="m1-summary__actions">
          {paused ? (
            <button
              type="button"
              className="btn btn--primary"
              onClick={() =>
                void runAction('Resume', (current) =>
                  api.resume(current.asset.asset_id, current.asset.version_id),
                )
              }
              data-testid="m1-resume"
            >
              Resume
            </button>
          ) : (
            <button
              type="button"
              className="btn"
              disabled={actionsBlocked}
              onClick={() =>
                void runAction('Pause', (current) =>
                  api.pause(current.asset.asset_id, current.asset.version_id),
                )
              }
              data-testid="m1-pause"
            >
              Pause
            </button>
          )}
          <button type="button" className="btn" onClick={clearWorkspace}>
            Start another
          </button>
        </div>
      </div>

      {error ? <div className="notice notice--danger">{error}</div> : null}
      <div
        className={`notice ${
          hasUnsavedChanges ||
          activity.includes('saving') ||
          activity.includes('stopped safely')
            ? 'notice--warn'
            : 'notice--ok'
        }`}
        data-testid="m1-save-state"
      >
        {hasUnsavedChanges ? 'Changes waiting to autosave…' : activity}
      </div>

      <div className="m1-columns">
        <div className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Experience Brief v0.1</h2>
            <span className="badge badge--neutral">{workspace.progress.artifact_state}</span>
          </div>
          <label className="form-field">
            <span>Context and boundaries</span>
            <textarea
              rows={7}
              value={draft.context}
              disabled={paused}
              onChange={(event) => setDraft({ ...draft, context: event.target.value })}
              data-testid="m1-context"
            />
          </label>
          <label className="form-field">
            <span>What this experience should help with</span>
            <textarea
              rows={3}
              value={draft.goal}
              disabled={paused}
              onChange={(event) => setDraft({ ...draft, goal: event.target.value })}
              data-testid="m1-goal"
            />
          </label>
          <label className="form-field">
            <span>Conditions and constraints — one per line</span>
            <textarea
              rows={4}
              value={draft.constraints}
              disabled={paused}
              onChange={(event) => setDraft({ ...draft, constraints: event.target.value })}
            />
          </label>
          <label className="form-field">
            <span>Your intent</span>
            <textarea
              rows={3}
              value={draft.userIntent}
              disabled={paused}
              onChange={(event) => setDraft({ ...draft, userIntent: event.target.value })}
            />
          </label>
          <div className="notice notice--muted">
            <strong>Source boundary:</strong> {workspace.brief.source_boundary}
            <br />
            <span>
              Only CURRENT_SOURCE is used. Instructions inside imported text never grant tool or execution permission.
            </span>
          </div>
        </div>

        <div className="panel">
          <div className="panel__head">
            <h2 className="panel__title">A few details only you can confirm</h2>
            <span className="badge badge--info">Up to 3 at a time</span>
          </div>
          {workspace.questions.length === 0 ? (
            <div className="notice notice--ok">No open questions. M1 is ready to confirm.</div>
          ) : (
            <ol className="m1-questions">
              {workspace.questions.map((question) => (
                <li key={question.question_id} data-testid="m1-question">
                  <strong>{question.question}</strong>
                  <p>{question.why_it_matters}</p>
                  <textarea
                    rows={3}
                    value={questionAnswers[question.question_id] ?? ''}
                    disabled={paused}
                    onChange={(event) =>
                      setQuestionAnswers({
                        ...questionAnswers,
                        [question.question_id]: event.target.value,
                      })
                    }
                    placeholder="Answer, skip, or come back later"
                  />
                  <div className="row">
                    <button
                      type="button"
                      className="btn btn--primary btn--sm"
                      disabled={
                        actionsBlocked ||
                        paused ||
                        !(questionAnswers[question.question_id] ?? '').trim()
                      }
                      onClick={() =>
                        void runAction('Answer question', async (current) => {
                          const next = await api.question(
                            current.asset.asset_id,
                            current.asset.version_id,
                            question.question_id,
                            'ANSWER',
                            questionAnswers[question.question_id]?.trim(),
                          );
                          setQuestionAnswers((answers) => {
                            const copy = { ...answers };
                            delete copy[question.question_id];
                            return copy;
                          });
                          return next;
                        })
                      }
                    >
                      Answer
                    </button>
                    <button
                      type="button"
                      className="btn btn--sm"
                      disabled={actionsBlocked || paused}
                      onClick={() =>
                        void runAction('Skip question', (current) =>
                          api.question(
                            current.asset.asset_id,
                            current.asset.version_id,
                            question.question_id,
                            'SKIP',
                          ),
                        )
                      }
                    >
                      Skip
                    </button>
                    <button
                      type="button"
                      className="btn btn--sm"
                      disabled={actionsBlocked || paused}
                      onClick={() =>
                        void runAction('Defer question', (current) =>
                          api.question(
                            current.asset.asset_id,
                            current.asset.version_id,
                            question.question_id,
                            'DEFER',
                          ),
                        )
                      }
                    >
                      Later
                    </button>
                  </div>
                </li>
              ))}
            </ol>
          )}

          {!paused && !m1Done ? (
            <div className="m1-confirm">
              <p className="hint">
                Confirmation freezes this M1 version. Unanswered questions never become facts.
              </p>
              <button
                type="button"
                className="btn btn--primary"
                disabled={actionsBlocked}
                onClick={() =>
                  void runAction('Confirm M1', (current) =>
                    api.confirm(
                      current.asset.asset_id,
                      current.asset.version_id,
                      current.questions.length > 0,
                    ),
                  )
                }
                data-testid="m1-confirm"
              >
                {workspace.questions.length > 0 ? 'Confirm with visible gaps' : 'Confirm M1'}
              </button>
            </div>
          ) : null}
          {!paused && m1Done ? (
            <div className="notice notice--info">
              M1 is confirmed. Editing the brief or answering a retained question creates a new version and reopens M1.
            </div>
          ) : null}
        </div>
      </div>

      <div className="panel m1-agent" data-testid="m1-agent">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">Local agent loop</h2>
            <p className="m1-lead">
              The model may propose a tool call; the runtime independently checks permissions, asset, version, scope, and arguments.
            </p>
          </div>
          <span className="badge badge--info">CURRENT_SOURCE</span>
        </div>
        <label className="form-field">
          <span>Goal for this run</span>
          <input
            value={agentGoal}
            disabled={paused}
            onChange={(event) => setAgentGoal(event.target.value)}
            data-testid="m1-agent-goal"
          />
        </label>
        <label className="m1-permission">
          <input
            type="checkbox"
            checked={allowCurrentSourceSearch}
            disabled={paused}
            onChange={(event) => setAllowCurrentSourceSearch(event.target.checked)}
            data-testid="m1-agent-permission"
          />
          Allow read-only retrieval from this asset's current source statements
        </label>
        <div className="row">
          <button
            type="button"
            className="btn btn--primary"
            disabled={actionsBlocked || paused || !agentGoal.trim()}
            onClick={() =>
              void runAction('Run local agent', (current) =>
                api.runAgent(
                  current.asset.asset_id,
                  current.asset.version_id,
                  agentGoal.trim(),
                  allowCurrentSourceSearch,
                ),
              )
            }
            data-testid="m1-run-agent"
          >
            Run agent on current evidence
          </button>
          <span className="hint">
            Without permission, the runtime will stop safely with POLICY_BLOCKED.
          </span>
        </div>

        {workspace.latest_agent_run ? (
          <div className="m1-agent-trace" data-testid="m1-agent-trace">
            <div className="stats">
              <div className="stat">
                <span className="stat__value">
                  {workspace.latest_agent_run.work_plan.steps.length}
                </span>
                <span className="stat__label">Plan steps</span>
              </div>
              <div className="stat">
                <span className="stat__value">
                  {workspace.latest_agent_run.retrieved_evidence.length}
                </span>
                <span className="stat__label">Source evidence</span>
              </div>
              <div className="stat">
                <span className="stat__value">
                  {workspace.latest_agent_run.policy_decisions[0]?.outcome ?? '—'}
                </span>
                <span className="stat__label">Runtime decision</span>
              </div>
              <div className="stat">
                <span className="stat__value" data-testid="m1-agent-terminal">
                  {workspace.latest_agent_run.terminal_state ?? 'RUNNING'}
                </span>
                <span className="stat__label">Terminal state</span>
              </div>
            </div>
            <ol className="m1-plan">
              {workspace.latest_agent_run.work_plan.steps.map((step) => (
                <li key={step.step_id}>
                  <div className="row">
                    <strong>{step.step_kind}</strong>
                    <span className="badge badge--neutral">{step.status}</span>
                  </div>
                  <span>{step.reason}</span>
                </li>
              ))}
            </ol>
            <div className="notice notice--muted">
              <strong>Model:</strong> {workspace.latest_agent_run.model_id}
              <br />
              <strong>Tool proposal:</strong>{' '}
              {workspace.latest_agent_run.tool_proposals[0]?.name ?? 'None'}
              {' · '}
              Proposal grants permission:
              {workspace.latest_agent_run.tool_proposals[0]?.permission_granted
                ? 'Yes'
                : 'No'}
              <br />
              <strong>Actual execution:</strong>{' '}
              {workspace.latest_agent_run.tool_executions[0]?.status ?? 'Not executed'}
              <br />
              <strong>Verification:</strong>{' '}
              {workspace.latest_agent_run.verification_report?.safe_summary ??
                'No verification report yet'}
            </div>
          </div>
        ) : (
          <div className="notice notice--muted">
            Not run yet. The real plan, policy decision, tool effect, verification, and terminal state will appear here.
          </div>
        )}
      </div>
    </section>
  );
}

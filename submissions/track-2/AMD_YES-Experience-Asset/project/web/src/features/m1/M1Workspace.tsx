import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { LiveM1Api, M1ApiError, type M1Api } from './api';
import { AgentRunTrace } from './AgentRunTrace';
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
  return error instanceof Error ? error.message : '本地操作失败，请重试。';
}

export function M1ExperienceWorkspace({
  apiBaseUrl = '',
  api: providedApi,
  storage = window.localStorage,
  autosaveDelayMs = 700,
  onStatusChange,
}: {
  apiBaseUrl?: string;
  api?: M1Api;
  storage?: Storage;
  autosaveDelayMs?: number;
  onStatusChange?: () => void;
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
  const [sourceLabel, setSourceLabel] = useState('我的经历');
  const [fileName, setFileName] = useState<string | null>(null);
  const [goalHint, setGoalHint] = useState('');
  const [questionAnswers, setQuestionAnswers] = useState<Record<string, string>>({});
  const [agentGoal, setAgentGoal] = useState('按当前证据检查这份 Brief 的来源边界');
  const [allowCurrentSourceSearch, setAllowCurrentSourceSearch] = useState(false);
  const [phase, setPhase] = useState<'restoring' | 'ready' | 'working'>('restoring');
  const [activity, setActivity] = useState('准备就绪');
  const [error, setError] = useState<string | null>(null);

  const applyWorkspace = useCallback(
    (next: M1Workspace, resetDraft = true) => {
      setWorkspace(next);
      storage.setItem(ACTIVE_ASSET_KEY, next.asset.asset_id);
      if (resetDraft) setDraft(draftFromWorkspace(next));
      setError(null);
      onStatusChange?.();
    },
    [onStatusChange, storage],
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
          setActivity('已从本地持久化版本恢复');
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
      setActivity('正在自动保存…');
      api
        .edit(base.asset.asset_id, base.asset.version_id, snapshot)
        .then((next) => {
          const unchangedDuringSave =
            JSON.stringify(draftRef.current) === JSON.stringify(snapshot);
          applyWorkspace(next, unchangedDuringSave);
          setActivity(unchangedDuringSave ? '已自动保存' : '已保存，继续同步新修改…');
        })
        .catch(async (reason: unknown) => {
          if (reason instanceof M1ApiError && reason.status === 409) {
            try {
              const current = await api.get(base.asset.asset_id);
              applyWorkspace(current, false);
              setActivity('检测到新版本，已重新载入并准备保存当前修改');
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
        label === '运行本地 Agent' &&
        next.latest_agent_run?.terminal_state &&
        next.latest_agent_run.terminal_state !== 'SUCCEEDED'
      ) {
        setActivity(`Agent 已安全停止：${next.latest_agent_run.terminal_state}`);
      } else {
        setActivity(`${label}完成`);
      }
    } catch (reason: unknown) {
      setError(errorMessage(reason));
    } finally {
      setPhase('ready');
    }
  };

  const start = async () => {
    if (!sourceText.trim()) {
      setError('请先粘贴一段经历，或选择一个 .txt / .md 文件。');
      return;
    }
    setPhase('working');
    setActivity('正在创建 Experience Brief v0.1…');
    setError(null);
    try {
      applyWorkspace(
        await api.ingest({
          source_kind: sourceKind,
          text: sourceText,
          display_label: sourceLabel.trim() || fileName || '我的经历',
          ...(fileName ? { original_file_name: fileName } : {}),
          ...(goalHint.trim() ? { goal_hint: goalHint.trim() } : {}),
        }),
      );
      setActivity('首个 Brief 已保存');
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
      setError('当前只支持 .txt 和 .md；PDF、图片、音频和视频不属于 E2。');
      return;
    }
    const text = await file.text();
    if (text.length > 200_000) {
      setError('文件超过 200,000 字符，请缩小后再导入。');
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
    setActivity('可创建新的 Experience Asset');
    setError(null);
  };

  if (phase === 'restoring') {
    return (
      <section className="screen" data-testid="m1-restoring">
        <div className="spinner" aria-hidden="true" />
        <p>正在恢复本地保存的 Experience Brief…</p>
      </section>
    );
  }

  if (!workspace) {
    return (
      <section className="m1-start panel" data-testid="m1-start">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">从一段真实经历开始</h2>
            <p className="m1-lead">
              先形成可编辑的 Experience Brief v0.1，再用最多三个问题补齐边界。
            </p>
          </div>
          <span className="badge badge--info">M1</span>
        </div>
        <label className="form-field">
          <span>这份资产想帮助你做什么（可选）</span>
          <input
            value={goalHint}
            onChange={(event) => setGoalHint(event.target.value)}
            placeholder="例如：复盘这次决策，供以后复用"
          />
        </label>
        <div className="form-field">
          <span>输入方式</span>
          <div className="segmented" role="group" aria-label="输入方式">
            <button
              type="button"
              className={`seg${sourceKind === 'CONVERSATION' ? ' seg--on' : ''}`}
              aria-pressed={sourceKind === 'CONVERSATION'}
              onClick={() => {
                setSourceKind('CONVERSATION');
                setSourceLabel('我的口述经历');
                setFileName(null);
              }}
            >
              对话式讲述
            </button>
            <button
              type="button"
              className={`seg${sourceKind === 'PASTED_TEXT' ? ' seg--on' : ''}`}
              aria-pressed={sourceKind === 'PASTED_TEXT'}
              onClick={() => {
                setSourceKind('PASTED_TEXT');
                setSourceLabel('我的经历');
                setFileName(null);
              }}
            >
              粘贴文本
            </button>
          </div>
        </div>
        <label className="form-field">
          <span>经历内容</span>
          <textarea
            rows={10}
            value={sourceText}
            onChange={(event) => {
              setSourceText(event.target.value);
              if (sourceKind === 'TXT_FILE' || sourceKind === 'MD_FILE') {
                setSourceKind('PASTED_TEXT');
                setSourceLabel('我的经历');
              }
              setFileName(null);
            }}
            placeholder={
              sourceKind === 'CONVERSATION'
                ? '像聊天一样讲述一件你亲历的事；提交后 Agent 会继续追问。'
                : '粘贴你亲历的一件事。导入内容只会被当作资料，不会被当作系统指令。'
            }
            data-testid="m1-source-text"
          />
        </label>
        <div className="m1-start__actions">
          <label className="btn m1-file">
            选择 .txt / .md
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
            {phase === 'working' ? '处理中…' : '生成并保存 Brief v0.1'}
          </button>
        </div>
        <p className="hint">
          数据只发送到同设备的本地 FastAPI；E2 不调用外部搜索，也不跨资产检索。
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
              {paused ? '已暂停' : m1Done ? 'M1 已确认' : 'M1 进行中'}
            </span>
            <span className="badge badge--neutral">
              {workspace.progress.unresolved_question_count} 个待处理问题
            </span>
          </div>
          <strong>{workspace.progress_event.message}</strong>
          <p className="hint">
            版本 <span className="mono">{workspace.asset.version_id.slice(0, 8)}</span> ·
            保存于 {savedTime(workspace.progress.last_saved_at)}
          </p>
        </div>
        <div className="m1-summary__actions">
          {paused ? (
            <button
              type="button"
              className="btn btn--primary"
              onClick={() =>
                void runAction('恢复', (current) =>
                  api.resume(current.asset.asset_id, current.asset.version_id),
                )
              }
              data-testid="m1-resume"
            >
              恢复
            </button>
          ) : (
            <button
              type="button"
              className="btn"
              disabled={actionsBlocked}
              onClick={() =>
                void runAction('暂停', (current) =>
                  api.pause(current.asset.asset_id, current.asset.version_id),
                )
              }
              data-testid="m1-pause"
            >
              暂停
            </button>
          )}
          <button type="button" className="btn" onClick={clearWorkspace}>
            新建另一份
          </button>
        </div>
      </div>

      {error ? <div className="notice notice--danger">{error}</div> : null}
      <div
        className={`notice ${
          hasUnsavedChanges ||
          activity.includes('正在') ||
          activity.includes('安全停止')
            ? 'notice--warn'
            : 'notice--ok'
        }`}
        data-testid="m1-save-state"
      >
        {hasUnsavedChanges ? '有修改待自动保存…' : activity}
      </div>

      <div className="m1-columns">
        <div className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Experience Brief v0.1</h2>
            <span className="badge badge--neutral">{workspace.progress.artifact_state}</span>
          </div>
          <label className="form-field">
            <span>经历边界与背景</span>
            <textarea
              rows={7}
              value={draft.context}
              disabled={paused}
              onChange={(event) => setDraft({ ...draft, context: event.target.value })}
              data-testid="m1-context"
            />
          </label>
          <label className="form-field">
            <span>希望解决的问题 / 用途</span>
            <textarea
              rows={3}
              value={draft.goal}
              disabled={paused}
              onChange={(event) => setDraft({ ...draft, goal: event.target.value })}
              data-testid="m1-goal"
            />
          </label>
          <label className="form-field">
            <span>条件与限制（每行一条）</span>
            <textarea
              rows={4}
              value={draft.constraints}
              disabled={paused}
              onChange={(event) => setDraft({ ...draft, constraints: event.target.value })}
            />
          </label>
          <label className="form-field">
            <span>你的意图</span>
            <textarea
              rows={3}
              value={draft.userIntent}
              disabled={paused}
              onChange={(event) => setDraft({ ...draft, userIntent: event.target.value })}
            />
          </label>
          <div className="notice notice--muted">
            <strong>来源边界：</strong> {workspace.brief.source_boundary}
            <br />
            <span>
              当前只使用 CURRENT_SOURCE；导入文本中的命令不会获得工具或执行权限。
            </span>
          </div>
        </div>

        <div className="panel">
          <div className="panel__head">
            <h2 className="panel__title">需要你判断的信息</h2>
            <span className="badge badge--info">每轮最多 3 个</span>
          </div>
          {workspace.questions.length === 0 ? (
            <div className="notice notice--ok">当前没有未解决问题，可以确认 M1。</div>
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
                    placeholder="输入答案，或选择跳过 / 稍后处理"
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
                        void runAction('回答问题', async (current) => {
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
                      回答
                    </button>
                    <button
                      type="button"
                      className="btn btn--sm"
                      disabled={actionsBlocked || paused}
                      onClick={() =>
                        void runAction('跳过问题', (current) =>
                          api.question(
                            current.asset.asset_id,
                            current.asset.version_id,
                            question.question_id,
                            'SKIP',
                          ),
                        )
                      }
                    >
                      跳过
                    </button>
                    <button
                      type="button"
                      className="btn btn--sm"
                      disabled={actionsBlocked || paused}
                      onClick={() =>
                        void runAction('推迟问题', (current) =>
                          api.question(
                            current.asset.asset_id,
                            current.asset.version_id,
                            question.question_id,
                            'DEFER',
                          ),
                        )
                      }
                    >
                      稍后处理
                    </button>
                  </div>
                </li>
              ))}
            </ol>
          )}

          {!paused && !m1Done ? (
            <div className="m1-confirm">
              <p className="hint">
                确认会冻结当前 M1 版本。未回答的问题不会变成事实。
              </p>
              <button
                type="button"
                className="btn btn--primary"
                disabled={actionsBlocked}
                onClick={() =>
                  void runAction('确认 M1', (current) =>
                    api.confirm(
                      current.asset.asset_id,
                      current.asset.version_id,
                      current.questions.length > 0,
                    ),
                  )
                }
                data-testid="m1-confirm"
              >
                {workspace.questions.length > 0 ? '按当前证据确认（保留缺口）' : '确认 M1'}
              </button>
            </div>
          ) : null}
          {!paused && m1Done ? (
            <div className="notice notice--info">
              M1 已确认；继续编辑 Brief 或回答保留问题会创建新版本并重新打开 M1。
            </div>
          ) : null}
        </div>
      </div>

      <div className="panel m1-agent" data-testid="m1-agent">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">本地 Agent 闭环</h2>
            <p className="m1-lead">
              模型只能提出工具调用；Runtime 会独立检查权限、资产、版本、范围和参数。
            </p>
          </div>
          <span className="badge badge--info">CURRENT_SOURCE</span>
        </div>
        <label className="form-field">
          <span>本轮目标</span>
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
          本轮允许 Agent 只读检索当前资产的来源陈述
        </label>
        <div className="row">
          <button
            type="button"
            className="btn btn--primary"
            disabled={actionsBlocked || paused || !agentGoal.trim()}
            onClick={() =>
              void runAction('运行本地 Agent', (current) =>
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
            按当前证据运行 Agent
          </button>
          <span className="hint">
            未勾选权限也可运行，但 Runtime 应给出 POLICY_BLOCKED 安全终态。
          </span>
        </div>

        {workspace.latest_agent_run ? (
          <AgentRunTrace run={workspace.latest_agent_run} />
        ) : (
          <div className="notice notice--muted">
            尚未运行。运行后这里会显示真实计划、裁决、工具效果、验证与终态。
          </div>
        )}
      </div>
    </section>
  );
}

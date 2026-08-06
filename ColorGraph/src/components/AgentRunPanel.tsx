import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Cloud,
  CloudOff,
  Download,
  GitBranch,
  LoaderCircle,
  Pause,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Undo2,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  assetUrl,
  type CreativeAgentDirection,
  type CreativeAgentSnapshot,
  type CreativeAgentStartOptions,
} from "../api";

interface AgentRunPanelProps {
  snapshot: CreativeAgentSnapshot | null;
  loading: boolean;
  busy: boolean;
  error: string;
  preferenceCount: number;
  preferenceExportUrl?: string;
  onRefresh: () => void;
  onStart: (options: CreativeAgentStartOptions) => void;
  onControl: (action: "cancel" | "resume") => void;
  onApply: (candidateId: string) => void;
  onFeedback: (
    candidateId: string,
    feedback: string,
    mode: "adjust_existing_strategy" | "new_thesis_branch",
  ) => void;
  onRememberPreference: (
    candidateId: string,
    comparedCandidateIds: string[],
  ) => void;
  onDeletePreferences: () => void;
}

const STAGES: CreativeAgentSnapshot["stage"][] = [
  "analyzing",
  "interpreting",
  "retrieving",
  "compiling",
  "rendering",
  "criticizing",
  "refining",
  "ready",
];

const STAGE_LABELS: Record<CreativeAgentSnapshot["stage"], string> = {
  idle: "待命",
  analyzing: "分析证据",
  interpreting: "闭卷诠释",
  retrieving: "扩展检索",
  compiling: "确定性编译",
  rendering: "真实渲染",
  criticizing: "盲化批评",
  refining: "最小反思",
  ready: "等待审阅",
};

const DIRECTION_LABELS: Record<CreativeAgentDirection["direction"], string> = {
  faithful: "忠实",
  amplified: "放大",
  counterpoint: "反向诠释",
};

const DIMENSION_LABELS: Record<
  CreativeAgentDirection["critique"][number]["dimension"],
  string
> = {
  concept_alignment: "命题",
  scene_support: "场景",
  visual_hierarchy: "层级",
  expressive_strength: "表达",
  naturalness: "自然",
  distinctiveness: "独特",
  overgrading_risk: "过调风险",
  context_consistency: "连续性",
};

function statusTone(status: CreativeAgentSnapshot["status"]) {
  if (status === "failed") return "is-danger";
  if (status === "cancelled" || status === "waiting_for_consent") {
    return "is-warning";
  }
  if (status === "ready_for_review" || status === "offline_fallback") {
    return "is-ready";
  }
  if (status === "running") return "is-running";
  return "";
}

function scopeLabel(
  scope: CreativeAgentDirection["application_scopes"][number],
) {
  const range = scope.time_range
    ? `${scope.time_range.start_seconds.toFixed(2)}–${scope.time_range.end_seconds.toFixed(2)}s`
    : "完整作用域";
  return [
    scope.scene_id && `Scene ${scope.scene_id}`,
    scope.shot_id && `Shot ${scope.shot_id}`,
    scope.mask_target && `Mask ${scope.mask_target}`,
    range,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function AgentRunPanel({
  snapshot,
  loading,
  busy,
  error,
  preferenceCount,
  preferenceExportUrl,
  onRefresh,
  onStart,
  onControl,
  onApply,
  onFeedback,
  onRememberPreference,
  onDeletePreferences,
}: AgentRunPanelProps) {
  const [sceneId, setSceneId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [feedback, setFeedback] = useState("");
  const [newThesisBranch, setNewThesisBranch] = useState(false);
  const [confirmingApply, setConfirmingApply] = useState(false);
  const [providerShadow, setProviderShadow] = useState(false);
  const [confirmCloudRun, setConfirmCloudRun] = useState(false);
  const [consentCloudUpload, setConsentCloudUpload] = useState(false);

  useEffect(() => {
    if (!snapshot) return;
    const firstScene = snapshot.scenes[0];
    setSceneId((current) =>
      snapshot.scenes.some((item) => item.scene_id === current)
        ? current
        : (firstScene?.scene_id ?? ""),
    );
    setCandidateId((current) => {
      const candidates = snapshot.scenes.flatMap((scene) =>
        scene.directions
          .map((direction) => direction.candidate_id)
          .filter((value): value is string => Boolean(value)),
      );
      if (candidates.includes(current)) return current;
      return (
        snapshot.selection.preferred_candidate_id ??
        candidates[0] ??
        ""
      );
    });
  }, [snapshot]);

  const scene = useMemo(
    () =>
      snapshot?.scenes.find((item) => item.scene_id === sceneId) ??
      snapshot?.scenes[0],
    [sceneId, snapshot],
  );
  const direction = useMemo(
    () =>
      scene?.directions.find((item) => item.candidate_id === candidateId) ??
      scene?.directions[0],
    [candidateId, scene],
  );
  const evidenceById = useMemo(
    () =>
      new Map(
        (scene?.evidence ?? []).map((item) => [item.evidence_id, item]),
      ),
    [scene],
  );
  const comparedCandidates = [
    snapshot?.selection.preferred_candidate_id,
    snapshot?.selection.runner_up_candidate_id,
  ].filter((value): value is string => Boolean(value));
  const mayApply = Boolean(
    direction?.candidate_id &&
      comparedCandidates.includes(direction.candidate_id) &&
      ["ready_for_review", "offline_fallback"].includes(
        snapshot?.status ?? "",
      ) &&
      snapshot?.selection.applied_candidate_id === null,
  );
  const activeStageIndex = snapshot
    ? STAGES.indexOf(snapshot.stage)
    : -1;

  return (
    <aside className="inspector agent-run-panel" aria-label="创意 Agent 审计面板">
      <div className="agent-panel-heading">
        <div>
          <span>CREATIVE AGENT · SHADOW</span>
          <h2>创意运行审计</h2>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading || busy}
          aria-label="刷新 Agent 状态"
        >
          <RefreshCw size={14} className={loading ? "is-spinning" : ""} />
        </button>
      </div>

      {loading && !snapshot ? (
        <div className="agent-panel-empty">
          <LoaderCircle size={20} className="is-spinning" />
          <strong>读取本地运行快照</strong>
          <span>只显示后端已经落盘的真实状态。</span>
        </div>
      ) : !snapshot ? (
        <div className="agent-panel-empty is-error">
          <XCircle size={20} />
          <strong>无法读取 Agent 快照</strong>
          <span>{error || "项目尚未就绪。"}</span>
        </div>
      ) : (
        <>
          <div className={`agent-run-status ${statusTone(snapshot.status)}`}>
            <div>
              {snapshot.status === "running" ? (
                <LoaderCircle size={14} className="is-spinning" />
              ) : snapshot.status === "ready_for_review" ||
                snapshot.status === "offline_fallback" ? (
                <CheckCircle2 size={14} />
              ) : snapshot.status === "failed" ? (
                <XCircle size={14} />
              ) : (
                <Sparkles size={14} />
              )}
              <strong>{STAGE_LABELS[snapshot.stage]}</strong>
            </div>
            <span>{snapshot.progress}%</span>
            <div className="agent-progress-track">
              <i style={{ width: `${snapshot.progress}%` }} />
            </div>
            <p>{snapshot.message}</p>
            {snapshot.last_error && <code>{snapshot.last_error}</code>}
            {snapshot.status === "idle" && (
              <div className="agent-provider-optin">
                <label>
                  <input
                    type="checkbox"
                    checked={providerShadow}
                    onChange={(event) => {
                      const enabled = event.target.checked;
                      setProviderShadow(enabled);
                      if (!enabled) {
                        setConfirmCloudRun(false);
                        setConsentCloudUpload(false);
                      }
                    }}
                  />
                  <span>
                    <strong>真实 Provider Shadow</strong>
                    <small>
                      仅在服务端显式配置后可用；输出仍不能直接修改 Grade Graph。
                    </small>
                  </span>
                </label>
                {providerShadow && (
                  <div className="agent-provider-boundary">
                    <Cloud size={14} />
                    <div>
                      <strong>云端数据边界</strong>
                      <span>
                        闭卷 Director、Strategist 和盲化 Critic 会上传本次运行的代表帧；
                        不上传原片、密钥或可写项目状态。
                      </span>
                      <label>
                        <input
                          type="checkbox"
                          checked={confirmCloudRun}
                          onChange={(event) =>
                            setConfirmCloudRun(event.target.checked)
                          }
                        />
                        我确认发起本次真实 Provider Shadow
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={consentCloudUpload}
                          onChange={(event) =>
                            setConsentCloudUpload(event.target.checked)
                          }
                        />
                        我同意上传本次代表帧
                      </label>
                    </div>
                  </div>
                )}
              </div>
            )}
            <div className="agent-run-actions">
              {snapshot.status === "running" ||
              snapshot.status === "waiting_for_consent" ? (
                <button
                  type="button"
                  onClick={() => onControl("cancel")}
                  disabled={busy || snapshot.cancellation_requested}
                >
                  <Pause size={12} />
                  {snapshot.cancellation_requested ? "已请求取消" : "取消"}
                </button>
              ) : null}
              {snapshot.status === "cancelled" ||
              snapshot.status === "failed" ? (
                <button
                  type="button"
                  onClick={() => onControl("resume")}
                  disabled={busy || snapshot.resume_requested}
                >
                  <Play size={12} />
                  {snapshot.resume_requested ? "已请求恢复" : "恢复"}
                </button>
              ) : null}
              {snapshot.status === "idle" ? (
                <button
                  type="button"
                  onClick={() =>
                    onStart({
                      enableProviderShadow: providerShadow,
                      confirmCloudRun,
                      consentCloudUpload,
                    })
                  }
                  disabled={
                    busy ||
                    (providerShadow &&
                      (!confirmCloudRun || !consentCloudUpload))
                  }
                >
                  {providerShadow ? <Cloud size={12} /> : <Play size={12} />}
                  {providerShadow ? "开始 Provider Shadow" : "开始离线 Shadow"}
                </button>
              ) : null}
              <span>
                {snapshot.shadow_mode ? "Shadow，不覆盖当前图" : "用户已确认应用"}
              </span>
            </div>
          </div>

          <div className="agent-stage-strip" aria-label="Agent 运行阶段">
            {STAGES.map((stage, index) => (
              <span
                key={stage}
                className={
                  snapshot.skipped_stages.includes(stage)
                    ? "is-skipped"
                    : index < activeStageIndex
                    ? "is-complete"
                    : index === activeStageIndex
                      ? "is-active"
                      : ""
                }
                title={STAGE_LABELS[stage]}
              >
                {snapshot.skipped_stages.includes(stage)
                  ? "—"
                  : index < activeStageIndex
                    ? <Check size={9} />
                    : index + 1}
              </span>
            ))}
          </div>

          {snapshot.provider.cloud_upload_required &&
            !snapshot.provider.cloud_upload_consented && (
              <div className="agent-consent-boundary" role="alert">
                <Cloud size={15} />
                <div>
                  <strong>等待显式云端上传同意</strong>
                  <span>
                    当前快照没有上传许可；代表帧不会被静默发送。
                  </span>
                </div>
              </div>
            )}

          <div className="agent-panel-scroll">
            {snapshot.project_visual_thesis ? (
              <section className="agent-thesis">
                <span>PROJECT VISUAL THESIS</span>
                <h3>{snapshot.project_visual_thesis}</h3>
                <dl>
                  <div>
                    <dt>Palette</dt>
                    <dd>{snapshot.palette_character}</dd>
                  </div>
                  <div>
                    <dt>Contrast</dt>
                    <dd>{snapshot.contrast_character}</dd>
                  </div>
                </dl>
              </section>
            ) : (
              <section className="agent-empty-run">
                <CloudOff size={18} />
                <div>
                  <strong>尚无创意 shadow 结果</strong>
                  <span>
                    界面不会生成占位候选；离线规则命令和手动节点仍可使用。
                  </span>
                </div>
              </section>
            )}

            {snapshot.scenes.length > 0 && (
              <>
                <section className="agent-scene-header">
                  <label>
                    <span>Scene role</span>
                    <select
                      value={scene?.scene_id ?? ""}
                      onChange={(event) => setSceneId(event.target.value)}
                    >
                      {snapshot.scenes.map((item) => (
                        <option key={item.scene_id} value={item.scene_id}>
                          {item.scene_label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p>{scene?.narrative_role}</p>
                  <small>{scene?.continuity_notes.join(" · ")}</small>
                </section>

                <div className="agent-direction-tabs" role="tablist">
                  {scene?.directions.map((item) => (
                    <button
                      key={item.brief_id}
                      type="button"
                      role="tab"
                      aria-selected={
                        item.candidate_id
                          ? item.candidate_id === direction?.candidate_id
                          : item.brief_id === direction?.brief_id
                      }
                      className={
                        item.candidate_id === direction?.candidate_id
                          ? "is-active"
                          : ""
                      }
                      onClick={() => {
                        setCandidateId(item.candidate_id ?? "");
                        setConfirmingApply(false);
                      }}
                    >
                      <span>{DIRECTION_LABELS[item.direction]}</span>
                      {item.is_preferred && <i>首选</i>}
                      {item.is_runner_up && <i>第二名</i>}
                    </button>
                  ))}
                </div>

                {direction && (
                  <section className="agent-direction-detail">
                    <div className="agent-candidate-preview">
                      {direction.candidate_thumbnail_urls[0] ? (
                        <img
                          src={assetUrl(direction.candidate_thumbnail_urls[0])}
                          alt={`${direction.title} 候选帧`}
                        />
                      ) : (
                        <div>
                          <LoaderCircle size={18} />
                          <span>尚未渲染候选</span>
                        </div>
                      )}
                      <div>
                        {direction.is_preferred && <span>首选</span>}
                        {direction.is_runner_up && <span>第二名</span>}
                        {direction.is_pareto && <span>Pareto</span>}
                        <span className={`qc-${direction.qc_status}`}>
                          QC {direction.qc_status.toUpperCase()}
                        </span>
                      </div>
                    </div>
                    <h3>{direction.title}</h3>
                    <p>{direction.interpretation}</p>
                    <strong>{direction.emotional_target}</strong>

                    <div className="agent-evidence-columns">
                      <div>
                        <span>支持证据</span>
                        {direction.support_evidence_ids.map((id) => (
                          <small key={id}>
                            {evidenceById.get(id)?.label ?? id}
                          </small>
                        ))}
                      </div>
                      <div>
                        <span>反证</span>
                        {direction.counterevidence_ids.map((id) => (
                          <small key={id}>
                            {evidenceById.get(id)?.label ?? id}
                          </small>
                        ))}
                      </div>
                    </div>

                    {direction.critique.length > 0 && (
                      <div className="agent-critique-grid">
                        {direction.critique.map((item) => {
                          const displayScore =
                            item.dimension === "overgrading_risk"
                              ? 1 - item.score
                              : item.score;
                          return (
                            <div key={item.dimension} title={item.concise_reason}>
                              <span>{DIMENSION_LABELS[item.dimension]}</span>
                              <i>
                                <b style={{ width: `${displayScore * 100}%` }} />
                              </i>
                              <strong>{Math.round(item.score * 100)}</strong>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    <div className="agent-protection-list">
                      <span>
                        <ShieldCheck size={12} /> 保护属性
                      </span>
                      <div>
                        {direction.protections.map((item) => (
                          <small key={item}>{item}</small>
                        ))}
                      </div>
                      {direction.intentional_exceptions.length > 0 && (
                        <>
                          <span>
                            <AlertTriangle size={12} /> 有意例外
                          </span>
                          <div>
                            {direction.intentional_exceptions.map((item) => (
                              <small key={item}>{item}</small>
                            ))}
                          </div>
                        </>
                      )}
                    </div>

                    {direction.refinement && (
                      <div className="agent-refinement-diff">
                        <GitBranch size={13} />
                        <div>
                          <strong>{direction.refinement.hypothesis}</strong>
                          {direction.refinement.changes.map((item) => (
                            <span key={item}>{item}</span>
                          ))}
                        </div>
                        {direction.refinement.rollback_available && (
                          <Undo2 size={13} />
                        )}
                      </div>
                    )}

                    {direction.candidate_id && (
                      <div className="agent-feedback">
                        <textarea
                          value={feedback}
                          onChange={(event) => setFeedback(event.target.value)}
                          placeholder="例如：更克制、让主体更孤寂……"
                          rows={2}
                        />
                        <label>
                          <input
                            type="checkbox"
                            checked={newThesisBranch}
                            onChange={(event) =>
                              setNewThesisBranch(event.target.checked)
                            }
                          />
                          创建显式新命题分支
                        </label>
                        <button
                          type="button"
                          disabled={!feedback.trim() || busy}
                          onClick={() => {
                            onFeedback(
                              direction.candidate_id!,
                              feedback.trim(),
                              newThesisBranch
                                ? "new_thesis_branch"
                                : "adjust_existing_strategy",
                            );
                            setFeedback("");
                            setNewThesisBranch(false);
                          }}
                        >
                          <Sparkles size={12} />
                          提交结构化反馈
                        </button>
                      </div>
                    )}

                    {confirmingApply ? (
                      <div className="agent-apply-confirm" role="alert">
                        <AlertTriangle size={15} />
                        <div>
                          <strong>确认应用此候选？</strong>
                          <span>
                            将先保存可撤销快照，并只修改以下作用域：
                          </span>
                          {direction.application_scopes.map((scope, index) => (
                            <code key={`${scopeLabel(scope)}-${index}`}>
                              {scopeLabel(scope)}
                            </code>
                          ))}
                          <div>
                            <button
                              type="button"
                              onClick={() => setConfirmingApply(false)}
                            >
                              返回
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => {
                                setConfirmingApply(false);
                                onApply(direction.candidate_id!);
                              }}
                            >
                              确认并保留撤销点
                            </button>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="agent-candidate-actions">
                        <button
                          type="button"
                          disabled={!mayApply || busy}
                          onClick={() => setConfirmingApply(true)}
                        >
                          应用候选
                        </button>
                        <button
                          type="button"
                          disabled={
                            !direction.candidate_id ||
                            comparedCandidates.length < 2 ||
                            busy
                          }
                          onClick={() =>
                            onRememberPreference(
                              direction.candidate_id!,
                              comparedCandidates,
                            )
                          }
                        >
                          记住本项目选择
                        </button>
                      </div>
                    )}
                  </section>
                )}
              </>
            )}
          </div>

          <div className="agent-panel-footer">
            <div>
              {snapshot.provider.network_enabled ? (
                <Cloud size={12} />
              ) : (
                <CloudOff size={12} />
              )}
              <span>
                {snapshot.provider.provider_id} · {snapshot.provider.model_id}
              </span>
            </div>
            <div className="agent-budget-line">
              <span>
                调用 {snapshot.budget.model_calls_used}/
                {snapshot.budget.model_calls_limit}
              </span>
              <span>
                帧 {snapshot.budget.rendered_frames_used}/
                {snapshot.budget.rendered_frames_limit}
              </span>
              <span>
                ${snapshot.budget.cost_usd_used.toFixed(2)}/
                {snapshot.budget.cost_usd_limit.toFixed(2)}
              </span>
            </div>
            <div className="agent-memory-actions">
              <span>{preferenceCount} 条项目偏好</span>
              {preferenceExportUrl && (
                <a href={preferenceExportUrl} download>
                  <Download size={11} /> 导出
                </a>
              )}
              <button
                type="button"
                disabled={preferenceCount === 0 || busy}
                onClick={onDeletePreferences}
              >
                <Trash2 size={11} /> 删除
              </button>
            </div>
          </div>
        </>
      )}

      {error && snapshot && (
        <div className="agent-panel-error" role="alert">
          <AlertTriangle size={12} />
          {error}
        </div>
      )}
    </aside>
  );
}

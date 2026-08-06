import {
  Check,
  ChevronRight,
  Cpu,
  Gauge,
  LoaderCircle,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import { PIPELINE_STAGES } from "../data";

interface PipelineModalProps {
  open: boolean;
  stageIndex: number;
  progress?: number;
  message?: string;
  runtime?: string;
  error?: string;
  currentStageId?: string;
  completedStageIds?: string[];
  taskCompleted?: boolean;
  onClose: () => void;
}

export function PipelineModal({
  open,
  stageIndex,
  progress: reportedProgress,
  message,
  runtime = "GPU",
  error,
  currentStageId,
  completedStageIds,
  taskCompleted,
  onClose,
}: PipelineModalProps) {
  if (!open) return null;

  const completed =
    taskCompleted ?? stageIndex >= PIPELINE_STAGES.length;
  const progress =
    reportedProgress ??
    (completed
      ? 100
      : Math.round((stageIndex / PIPELINE_STAGES.length) * 100));
  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="pipeline-modal"
        role="dialog"
        aria-modal="true"
        aria-label="ColorGraph 本地分析流程"
      >
        <button className="modal-close" type="button" onClick={onClose}>
          <X size={15} />
        </button>

        <div className="pipeline-hero">
          <div className={`pipeline-orbit ${completed ? "is-complete" : ""}`}>
            <svg viewBox="0 0 128 128">
              <circle cx="64" cy="64" r="55" />
              <circle
                cx="64"
                cy="64"
                r="55"
                className="orbit-progress"
                style={{
                  strokeDashoffset: 346 - (346 * Math.max(progress, 8)) / 100,
                }}
              />
            </svg>
            <div>
              {completed ? (
                <Check size={25} />
              ) : (
                <strong>{progress}</strong>
              )}
              <span>{completed ? "完成" : "%"}</span>
            </div>
            {!completed && <i />}
          </div>
          <div className="pipeline-copy">
            <span className="eyebrow">
              <Sparkles size={12} />
              COLORGRAPH AGENT
            </span>
            <h2>
              {error
                ? "本地任务失败"
                : completed
                  ? "调色图已编译"
                  : "正在理解画面与意图"}
            </h2>
            <p>
              {error
                ? error
                : message ||
                  (completed
                    ? "节点、参数轨道与语义区域已准备就绪。"
                    : "代表帧、色彩统计与语义区域正在本地 GPU 上批量分析。")}
            </p>
          </div>
        </div>

        <div className="pipeline-stages">
          {PIPELINE_STAGES.map((stage, index) => {
            const status = completedStageIds
              ? completedStageIds.includes(stage.id)
                ? "complete"
                : currentStageId === stage.id && !completed
                  ? "active"
                  : "pending"
              : index < stageIndex
                ? "complete"
                : index === stageIndex && !completed
                  ? "active"
                  : "pending";
            return (
              <div key={stage.id} className={`pipeline-stage is-${status}`}>
                <div className="stage-status">
                  {status === "complete" && <Check size={11} />}
                  {status === "active" && (
                    <LoaderCircle className="spin" size={12} />
                  )}
                  {status === "pending" && <span />}
                </div>
                <div className="stage-copy">
                  <strong>{stage.label}</strong>
                  <span>{stage.detail}</span>
                </div>
                <div className="stage-device">
                  {stage.device === "CPU" ? (
                    <Cpu size={10} />
                  ) : (
                    <Zap size={10} />
                  )}
                  {stage.device === "CPU" ? "CPU" : runtime.toUpperCase()}
                </div>
              </div>
            );
          })}
        </div>

        <div className="pipeline-footer">
          <div className="pipeline-metric">
            <Gauge size={14} />
            <span>
              <strong>{completed ? "100%" : `${progress}%`}</strong>
              <small>真实后台任务</small>
            </span>
          </div>
          <div className="pipeline-metric">
            <Zap size={14} />
            <span>
              <strong>{runtime.toUpperCase()}</strong>
              <small>当前执行后端</small>
            </span>
          </div>
          <button
            className="button button-primary"
            type="button"
            disabled={!completed}
            onClick={onClose}
          >
            进入调色
            <ChevronRight size={14} />
          </button>
        </div>
      </section>
    </div>
  );
}

import {
  Check,
  CheckCircle2,
  Download,
  FileJson,
  Film,
  Layers3,
  Palette,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

interface ExportModalProps {
  open: boolean;
  onClose: () => void;
  onDownloadGraph: (
    onProgress: (progress: number) => void,
  ) => void | Promise<void>;
  deviceLabel?: string;
  runtime?: "cuda" | "rocm" | "cpu";
  media?: {
    width: number;
    height: number;
    fps: number;
    frameCount: number;
    durationSeconds: number;
  };
  maskTargets?: string[];
  qualityReady?: boolean;
}

const MASK_LABELS: Record<string, string> = {
  sky: "天空",
  vegetation: "植被",
  water: "水面",
  mountain: "山体",
  depth_far: "远景深度",
};

export function ExportModal({
  open,
  onClose,
  onDownloadGraph,
  deviceLabel = "本地设备",
  runtime = "cpu",
  media,
  maskTargets = [],
  qualityReady = false,
}: ExportModalProps) {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (!open) setProgress(0);
  }, [open]);

  if (!open) return null;

  const resolution = media
    ? `${media.width} × ${media.height} · ${media.fps.toFixed(2)} FPS`
    : "等待真实媒体";
  const duration = media
    ? `${media.durationSeconds.toFixed(1)} 秒 · ${media.frameCount} 帧`
    : "等待媒体分析";
  const encoder =
    runtime === "cuda"
      ? "HEVC NVENC · Main10 · CQ 18"
      : runtime === "rocm"
        ? "HEVC AMF · Main10"
        : "HEVC x265 · Main10 · CRF 18";
  const maskSummary =
    maskTargets.length > 0
      ? maskTargets.map((target) => MASK_LABELS[target] ?? target).join(" · ")
      : "分析后按实际结果写入";
  const exportAssets = [
    {
      id: "video",
      icon: Film,
      title: "调色成片",
      detail: `HEVC Main10 · 10-bit · ${resolution} · Rec.709`,
    },
    {
      id: "lut",
      icon: Palette,
      title: "逐场景 Look",
      detail: "每个 scene/look 独立 .cube · 33 × 33 × 33",
    },
    {
      id: "graph",
      icon: FileJson,
      title: "时空调色图",
      detail: "Typed Grade Graph · JSON",
    },
    {
      id: "masks",
      icon: Layers3,
      title: "时序蒙版",
      detail: maskSummary,
    },
  ];

  const startExport = async () => {
    setProgress(3);
    try {
      await onDownloadGraph((nextProgress) =>
        setProgress(Math.max(3, Math.min(99, nextProgress))),
      );
      setProgress(100);
    } catch {
      setProgress(0);
    }
  };

  const isRendering = progress > 0 && progress < 100;

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="export-modal"
        role="dialog"
        aria-modal="true"
        aria-label="导出 ColorGraph 交付包"
      >
        <button className="modal-close" type="button" onClick={onClose}>
          <X size={15} />
        </button>
        <div className="export-heading">
          <span>DELIVERABLE PACKAGE</span>
          <h2>导出可编辑创作资产</h2>
          <p>成片、Look、节点参数与蒙版一起交付，后续仍可修改。</p>
        </div>

        <div className="export-layout">
          <div className="export-assets">
            {exportAssets.map(({ id, icon: Icon, title, detail }) => (
                <div key={id} className="is-selected">
                  <span className="export-check">
                    <Check size={11} />
                  </span>
                  <span className="export-asset-icon">
                    <Icon size={16} />
                  </span>
                  <span>
                    <strong>{title}</strong>
                    <small>{detail}</small>
                  </span>
                </div>
              ))}
          </div>

          <div className="export-summary">
            <div className="export-summary-head">
              <span>输出设置</span>
              <strong>源规格无缩放</strong>
            </div>
            <dl>
              <div>
                <dt>渲染设备</dt>
                <dd>{deviceLabel}</dd>
              </div>
              <div>
                <dt>视频规格</dt>
                <dd>{resolution}</dd>
              </div>
              <div>
                <dt>视频编码</dt>
                <dd>{encoder}</dd>
              </div>
              <div>
                <dt>素材时长</dt>
                <dd>{duration}</dd>
              </div>
            </dl>
            <div className="export-note">
              <CheckCircle2 size={13} />
              {qualityReady ? "质量验证已通过，可直接交付" : "导出时将包含当前可用资产"}
            </div>
          </div>
        </div>

        <div className="export-footer">
          <div className="export-progress">
            <div>
              <span>
                {progress === 0 && "准备就绪"}
                {isRendering && "正在生成真实交付包…"}
                {progress === 100 && "交付包已下载"}
              </span>
              <strong>
                {progress > 0 ? `${progress}%` : `${exportAssets.length} 组资产`}
              </strong>
            </div>
            <span className="progress-track">
              <i style={{ width: `${progress}%` }} />
            </span>
          </div>
          <button
            className="button button-primary export-button"
            type="button"
            disabled={isRendering}
            onClick={startExport}
          >
            {progress === 100 ? (
              <>
                <Download size={14} />
                再次导出
              </>
            ) : (
              <>
                <Film size={14} />
                {isRendering ? "渲染中" : "开始导出"}
              </>
            )}
          </button>
        </div>
      </section>
    </div>
  );
}

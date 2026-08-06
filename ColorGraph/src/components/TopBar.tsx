import {
  Check,
  ChevronDown,
  CloudUpload,
  Cpu,
  FolderOpen,
  ImagePlus,
  Play,
  Share2,
  Sparkles,
} from "lucide-react";
import type { ChangeEvent, RefObject } from "react";
import type { InputColorProfile } from "../api";

interface TopBarProps {
  fileInputRef: RefObject<HTMLInputElement | null>;
  referenceInputRef: RefObject<HTMLInputElement | null>;
  projectName: string;
  isAnalyzing: boolean;
  analysisComplete?: boolean;
  deviceLabel?: string;
  runtimeLabel?: string;
  inputColorSpace?: InputColorProfile;
  referenceName?: string | null;
  onInputColorSpaceChange?: (value: InputColorProfile) => void;
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onReferenceFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onLocalImport: () => void;
  onAnalyze: () => void;
  onExport: () => void;
}

export function TopBar({
  fileInputRef,
  referenceInputRef,
  projectName,
  isAnalyzing,
  analysisComplete = false,
  deviceLabel = "检测设备中",
  runtimeLabel = "等待后端",
  inputColorSpace = "rec709",
  referenceName,
  onInputColorSpaceChange,
  onFileChange,
  onReferenceFileChange,
  onLocalImport,
  onAnalyze,
  onExport,
}: TopBarProps) {
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">
          <span />
        </div>
        <div className="brand-name">
          COLOR<span>GRAPH</span>
        </div>
        <div className="brand-edition">BETA</div>
      </div>

      <div className="project-switcher">
        <span className="project-kicker">当前项目</span>
        <button
          className="project-name"
          type="button"
          disabled
          title="启动时自动恢复最近项目"
        >
          {projectName}
          <ChevronDown size={13} strokeWidth={1.7} />
        </button>
      </div>

      <div className="topbar-actions">
        <div className="device-chip" title="由本地 ColorGraph 后端实时上报">
          <Cpu size={14} />
          <span>{deviceLabel}</span>
          <i />
          <span>{runtimeLabel}</span>
        </div>

        <label className="color-space-chip">
          <span>INPUT</span>
          <select
            aria-label="输入色彩空间"
            value={inputColorSpace}
            onChange={(event) =>
              onInputColorSpaceChange?.(
                event.target.value as InputColorProfile,
              )
            }
            disabled={isAnalyzing}
          >
            <option value="rec709">Rec.709</option>
            <option value="dji_mavic3_dlog_rec709_v1">
              DJI M3 D-Log
            </option>
            <option value="sony_slog3_sgamut3cine">
              Sony S-Log3
            </option>
          </select>
        </label>

        <input
          ref={fileInputRef}
          className="visually-hidden"
          type="file"
          accept="video/*"
          onChange={onFileChange}
        />
        <input
          ref={referenceInputRef}
          className="visually-hidden"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={onReferenceFileChange}
        />
        <button
          className={`button button-ghost ${referenceName ? "has-reference" : ""}`}
          type="button"
          title={referenceName ?? "选择可选风格参考图"}
          onClick={() => referenceInputRef.current?.click()}
        >
          <ImagePlus size={15} />
          {referenceName ? "参考图已选" : "参考图"}
        </button>
        <button
          className="button button-ghost"
          type="button"
          title="通过绝对路径接入 ProRes、RAW 或数 GB 大文件"
          onClick={onLocalImport}
        >
          <FolderOpen size={15} />
          本地路径
        </button>
        <button
          className="button button-ghost"
          type="button"
          onClick={() => fileInputRef.current?.click()}
        >
          <CloudUpload size={15} />
          导入素材
        </button>
        <button
          className="button button-secondary"
          type="button"
          onClick={onAnalyze}
          aria-busy={isAnalyzing}
          title={
            isAnalyzing
              ? "重新打开分析进度"
              : analysisComplete
                ? "查看已完成的分析"
                : "启动 AI 分析"
          }
        >
          {isAnalyzing ? (
            <span className="button-spinner" />
          ) : analysisComplete ? (
            <Check size={15} />
          ) : (
            <Sparkles size={15} />
          )}
          {isAnalyzing ? "分析中" : analysisComplete ? "已分析" : "AI 分析"}
        </button>
        <button className="button button-primary" type="button" onClick={onExport}>
          <Share2 size={15} />
          导出
        </button>
      </div>
    </header>
  );
}

export function DemoBadge() {
  return (
    <div className="demo-badge">
      <Play size={9} fill="currentColor" />
      交互演示
    </div>
  );
}

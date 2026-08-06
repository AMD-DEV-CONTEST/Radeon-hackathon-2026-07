import {
  AlertTriangle,
  Box,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  CloudSun,
  Cpu,
  Download,
  Eye,
  EyeOff,
  FileJson,
  Film,
  Gauge,
  Layers3,
  MountainSnow,
  Palette,
  PanelRightClose,
  Route,
  RotateCcw,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  SunMedium,
  Waves,
  Workflow,
} from "lucide-react";
import { LOOKS, SOURCE_IMAGE } from "../data";
import type {
  CandidateComparison,
  DeviceInfo,
  LookRecipeCatalog,
  QualityReport,
} from "../api";
import type {
  GradeNode,
  GradeParameter,
  GradeState,
  LookId,
  PanelId,
} from "../types";

interface InspectorProps {
  activePanel: PanelId;
  nodes: GradeNode[];
  selectedNodeId: string;
  grade: GradeState;
  activeLook: LookId;
  onSelectNode: (id: string) => void;
  onToggleNode: (id: string) => void;
  onGradeChange: (parameter: GradeParameter, value: number) => void;
  onGradeEditStart: () => void;
  onGradeEditCommit: () => void;
  onLookChange: (look: LookId) => void;
  onRestoreOriginalLook: () => void;
  onConfirmLookChange: () => void;
  onCancelLookChange: () => void;
  onExport: () => void;
  device?: DeviceInfo | null;
  previewFps?: number | null;
  quality?: QualityReport | null;
  lookCandidates?: CandidateComparison | null;
  lookRecipeCatalog?: LookRecipeCatalog | null;
  lookCandidatesStale?: boolean;
  lookDirty?: boolean;
  lookOverrides?: Partial<Record<GradeParameter, number>>;
  pendingLookSwitch?: LookId | null;
  isComparingLooks?: boolean;
  isGraphSaving?: boolean;
  maskCount?: number;
  projectName?: string;
  previewSource?: string;
  onCompareLooks: () => void;
}

const NODE_ICONS = {
  input: Route,
  balance: SlidersHorizontal,
  tone: SunMedium,
  mask: MountainSnow,
  look: Palette,
  output: Box,
};

const PARAMETER_LABELS: Record<GradeParameter, string> = {
  exposure: "曝光",
  temperature: "色温",
  contrast: "对比度",
  saturation: "饱和度",
  highlights: "高光",
  strength: "Look 强度",
};

const PARAMETER_RANGES: Record<
  GradeParameter,
  { min: number; max: number; suffix: string }
> = {
  exposure: { min: -50, max: 50, suffix: "" },
  temperature: { min: -50, max: 50, suffix: "" },
  contrast: { min: -30, max: 50, suffix: "" },
  saturation: { min: -40, max: 40, suffix: "" },
  highlights: { min: -50, max: 30, suffix: "" },
  strength: { min: 0, max: 100, suffix: "%" },
};

function InspectorHeading({
  kicker,
  title,
  count,
}: {
  kicker: string;
  title: string;
  count?: string;
}) {
  return (
    <div className="inspector-heading">
      <div>
        <span>{kicker}</span>
        <h2>{title}</h2>
      </div>
      {count && <div className="heading-count">{count}</div>}
      <button type="button" aria-label="收起检查器">
        <PanelRightClose size={15} />
      </button>
    </div>
  );
}

function ParameterSlider({
  parameter,
  value,
  onChange,
  onEditStart,
  onEditCommit,
}: {
  parameter: GradeParameter;
  value: number;
  onChange: (parameter: GradeParameter, value: number) => void;
  onEditStart: () => void;
  onEditCommit: () => void;
}) {
  const range = PARAMETER_RANGES[parameter];
  const percent = ((value - range.min) / (range.max - range.min)) * 100;
  return (
    <label className="parameter-control">
      <span className="parameter-control-head">
        <span>{PARAMETER_LABELS[parameter]}</span>
        <output>
          {value > 0 && parameter !== "strength" ? "+" : ""}
          {value}
          {range.suffix}
        </output>
      </span>
      <span className="range-shell">
        <input
          type="range"
          min={range.min}
          max={range.max}
          step={1}
          value={value}
          style={{ "--range-value": `${percent}%` } as React.CSSProperties}
          onPointerDown={onEditStart}
          onPointerUp={onEditCommit}
          onPointerCancel={onEditCommit}
          onKeyDown={onEditStart}
          onKeyUp={onEditCommit}
          onBlur={onEditCommit}
          onChange={(event) =>
            onChange(parameter, Number(event.target.value))
          }
        />
      </span>
    </label>
  );
}

function GradeInspector({
  nodes,
  selectedNodeId,
  grade,
  activeLook,
  onSelectNode,
  onToggleNode,
  onGradeChange,
  onGradeEditStart,
  onGradeEditCommit,
  onLookChange,
  onRestoreOriginalLook,
  onConfirmLookChange,
  onCancelLookChange,
  device,
  previewFps,
  lookCandidates,
  lookRecipeCatalog,
  lookCandidatesStale = false,
  lookDirty = false,
  lookOverrides = {},
  pendingLookSwitch,
  isComparingLooks = false,
  isGraphSaving = false,
  onCompareLooks,
}: Omit<InspectorProps, "activePanel" | "onExport">) {
  const selectedNode =
    nodes.find((node) => node.id === selectedNodeId) ?? nodes[1];
  if (!selectedNode) {
    return (
      <>
        <InspectorHeading
          kicker="GRADE GRAPH"
          title="时空调色图"
          count="待导入"
        />
        <div className="inspector-empty">
          <Film size={22} />
          <strong>导入风景视频</strong>
          <span>完成媒体分析后，这里会显示真实候选 Look、节点与参数。</span>
        </div>
      </>
    );
  }

  const getControls = (): GradeParameter[] => {
    if (selectedNode.kind === "balance") return ["exposure", "temperature"];
    if (selectedNode.kind === "look" && selectedNode.recipeLook) {
      return [
        "strength",
        "contrast",
        "saturation",
        "temperature",
        "highlights",
      ];
    }
    if (selectedNode.kind === "mask") {
      if (selectedNode.scope === "Vegetation") return ["saturation"];
      return ["highlights", "saturation"];
    }
    if (selectedNode.kind === "tone") return ["highlights"];
    return [];
  };
  const displayedLooks = lookCandidates
    ? lookCandidates.candidates.map((candidate) => ({
        id: candidate.recipe_id,
        candidate,
      }))
    : (
        lookRecipeCatalog?.recipes.map((recipe) => recipe.id) ??
        (["natural", "cool", "warm", "foggy"] as LookId[])
      ).map((id) => ({ id, candidate: null }));
  const overrideEntries = Object.entries(lookOverrides).filter(
    ([, value]) => typeof value === "number",
  ) as Array<[GradeParameter, number]>;

  return (
    <>
      <InspectorHeading
        kicker="GRADE GRAPH"
        title="时空调色图"
        count={`${nodes.filter((node) => node.enabled).length}/${nodes.length}`}
      />
      <div className="inspector-scroll">
        <div className="look-section">
          <div className="section-label">
            <span>候选 Look</span>
            <button
              type="button"
              onClick={onCompareLooks}
              disabled={isComparingLooks || isGraphSaving}
            >
              {isComparingLooks ? (
                <span className="button-spinner" />
              ) : (
                <Sparkles size={11} />
              )}
              {isComparingLooks
                ? "比较中"
                : lookCandidatesStale
                  ? "重新比较"
                  : "本地 A/B"}
            </button>
          </div>
          <div className="look-options">
            {displayedLooks.map(({ id: lookId, candidate }, index) => {
              const look = LOOKS[lookId];
              const isReal = Boolean(candidate);
              const isStale = isReal && lookCandidatesStale;
              return (
                <button
                  key={lookId}
                  className={[
                    activeLook === lookId ? "is-active" : "",
                    isReal ? "is-rendered" : "is-placeholder",
                    isStale ? "is-stale" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  type="button"
                  disabled={!isReal || isStale || isGraphSaving}
                  onClick={() => onLookChange(lookId)}
                  title={
                    candidate
                      ? `真实渲染 · ${Object.entries(candidate.parameters)
                          .map(([key, value]) => `${key} ${value}`)
                          .join(" · ")}`
                      : `${look.en} · 固定配方占位，运行本地 A/B 后可应用`
                  }
                >
                  {candidate ? (
                    <span
                      className="look-thumb"
                      style={{ backgroundImage: `url(${candidate.url})` }}
                    >
                      <span className="look-render-state">
                        {isStale ? "已过期" : "真实渲染"}
                      </span>
                    </span>
                  ) : (
                    <span className="look-thumb look-thumb-placeholder">
                      <Palette size={15} />
                      <span>固定配方</span>
                    </span>
                  )}
                  <span className="look-index">
                    {candidate ? `A/B ${index + 1}` : `配方 ${index + 1}`}
                  </span>
                  <strong>{look.name}</strong>
                  {candidate &&
                    candidate.recipe_id === lookCandidates?.recommended_id && (
                    <span className="look-recommended">推荐</span>
                  )}
                  {activeLook === lookId && (
                    <span className="look-check">
                      <Check size={10} />
                    </span>
                  )}
                  {activeLook === lookId && lookDirty && (
                    <span className="look-modified">已修改</span>
                  )}
                </button>
              );
            })}
          </div>
          <div
            className={`look-comparison-meta ${
              lookCandidatesStale ? "is-stale" : ""
            }`}
          >
            {lookCandidates ? (
              <>
                <span>
                  {lookCandidatesStale ? "候选已过期" : "真实渲染候选"}
                </span>
                <code>
                  Graph {lookCandidates.graph_digest.slice(0, 10)} ·{" "}
                  {lookCandidates.recipe_version}
                </code>
              </>
            ) : (
              <>
                <span>固定配方占位</span>
                <small>未使用 CSS 模拟；运行本地 A/B 生成真实帧。</small>
              </>
            )}
          </div>
          {pendingLookSwitch && (
            <div className="look-switch-confirm" role="alert">
              <AlertTriangle size={14} />
              <div>
                <strong>放弃当前 Look 修改？</strong>
                <span>
                  切换到「{LOOKS[pendingLookSwitch].name}」会移除本项目覆盖。
                </span>
                <div>
                  <button type="button" onClick={onCancelLookChange}>
                    保留修改
                  </button>
                  <button type="button" onClick={onConfirmLookChange}>
                    放弃并切换
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="node-section">
          <div className="section-label">
            <span>节点堆栈</span>
            <button
              type="button"
              onClick={onCompareLooks}
              disabled={isComparingLooks || isGraphSaving}
            >
              <Sparkles size={11} />
              Agent 候选
            </button>
          </div>
          <div className="node-stack">
            {nodes.map((node, index) => {
              const Icon = NODE_ICONS[node.kind];
              return (
                <div
                  key={node.id}
                  className={`node-row ${
                    selectedNode.id === node.id ? "is-selected" : ""
                  } ${!node.enabled ? "is-disabled" : ""}`}
                >
                  <button
                    className="node-main"
                    type="button"
                    onClick={() => onSelectNode(node.id)}
                  >
                    <span className="node-sequence">
                      {index < nodes.length - 1 && <i />}
                      <span>
                        <Icon size={14} strokeWidth={1.7} />
                      </span>
                    </span>
                    <span className="node-copy">
                      <strong>{node.name}</strong>
                      <small>{node.subtitle}</small>
                    </span>
                    <span className="node-scope">{node.scope}</span>
                    <ChevronRight size={12} />
                  </button>
                  <button
                    className="node-toggle"
                    type="button"
                    aria-label={`${node.enabled ? "关闭" : "开启"}${node.name}`}
                    onClick={() => onToggleNode(node.id)}
                  >
                    {node.enabled ? <Eye size={13} /> : <EyeOff size={13} />}
                  </button>
                </div>
              );
            })}
          </div>
        </div>

        <div className="node-settings">
          <div className="settings-heading">
            <div>
              <span>选中节点</span>
              <strong>{selectedNode.name}</strong>
            </div>
            <div className="gpu-tag">
              <Cpu size={11} />
              GPU
            </div>
          </div>
          {selectedNode.kind === "look" && selectedNode.recipeLook && (
            <div className={`look-instance ${lookDirty ? "is-dirty" : ""}`}>
              <div>
                <span>项目 Look 实例</span>
                <strong>
                  {LOOKS[activeLook].name}
                  <small>{lookDirty ? "已修改" : "原始配方"}</small>
                </strong>
              </div>
              {lookDirty && (
                <button
                  type="button"
                  onClick={onRestoreOriginalLook}
                  disabled={isGraphSaving}
                >
                  <RotateCcw size={11} />
                  恢复原 Look
                </button>
              )}
              {overrideEntries.length > 0 && (
                <div className="look-overrides">
                  {overrideEntries.map(([parameter, value]) => (
                    <span key={parameter}>
                      {PARAMETER_LABELS[parameter]}{" "}
                      {value > 0 ? "+" : ""}
                      {(value * 100).toFixed(0)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
          {getControls().length > 0 ? (
            <div className="parameter-list">
              {getControls().map((parameter) => (
                <ParameterSlider
                  key={parameter}
                  parameter={parameter}
                  value={grade[parameter]}
                  onChange={onGradeChange}
                  onEditStart={onGradeEditStart}
                  onEditCommit={onGradeEditCommit}
                />
              ))}
            </div>
          ) : (
            <div className="fixed-node-info">
              <CheckCircle2 size={15} />
              <div>
                <strong>固定色彩管理节点</strong>
                <span>由项目输出规范锁定，无需逐镜头调整。</span>
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="inspector-device">
        <span className="device-orb">
          <i />
        </span>
        <div>
          <strong>本地推理管线</strong>
          <span>
            PyTorch + {device?.runtime.toUpperCase() ?? "后端未连接"} ·
            增量预览
          </span>
        </div>
        <div className="device-fps">
          <strong>{previewFps ? previewFps.toFixed(1) : "—"}</strong>
          <span>FPS · 实测</span>
        </div>
      </div>
    </>
  );
}

function GraphInspector({ nodes }: { nodes: GradeNode[] }) {
  return (
    <>
      <InspectorHeading
        kicker="GRAPH VIEW"
        title="作用域与依赖"
        count={`${nodes.length} 节点`}
      />
      <div className="inspector-scroll graph-inspector">
        <div className="graph-summary">
          <div>
            <span>时间层级</span>
            <strong>Project → Scene → Shot → Keyframe</strong>
          </div>
          <div>
            <span>空间层级</span>
            <strong>Global → Semantic → Depth</strong>
          </div>
        </div>
        <div className="typed-graph">
          {nodes.map((node, index) => {
            const Icon = NODE_ICONS[node.kind];
            return (
              <div key={node.id} className="graph-node">
                <div className="graph-index">
                  <span>{(index + 1).toString().padStart(2, "0")}</span>
                  {index < nodes.length - 1 && <i />}
                </div>
                <div className="graph-node-body">
                  <div>
                    <Icon size={14} />
                    <strong>{node.name}</strong>
                  </div>
                  <span>{node.scope}</span>
                  <small>{node.subtitle}</small>
                </div>
              </div>
            );
          })}
        </div>
        <div className="graph-legend">
          <div>
            <CircleDot size={11} />
            确定性 GPU 节点
          </div>
          <div>
            <Sparkles size={11} />
            Agent 规划作用域
          </div>
        </div>
      </div>
      <div className="inspector-callout">
        <Workflow size={15} />
        <div>
          <strong>Typed Grade Graph</strong>
          <span>每个节点都有明确的时间、空间与参数边界。</span>
        </div>
      </div>
    </>
  );
}

function formatQualityValue(value: number, unit: string) {
  if (unit === "ratio") return `${(value * 100).toFixed(2)}%`;
  return value.toFixed(4);
}

function QualityInspector({
  report,
  onExport,
}: {
  report?: QualityReport | null;
  onExport: () => void;
}) {
  const score = report?.score ?? 0;
  const qualityGroups = report
    ? [
        {
          id: "hard",
          label: "技术硬检查",
          checks: report.checks.filter(
            (check) => !check.category || check.category === "hard_technical",
          ),
        },
        {
          id: "risk",
          label: "感知风险",
          checks: report.checks.filter(
            (check) => check.category === "perceptual_risk",
          ),
        },
      ].filter((group) => group.checks.length > 0)
    : [];
  return (
    <>
      <InspectorHeading
        kicker="QUALITY REPORT"
        title="输出质量"
        count={
          report
            ? report.hard_checks_passed
              ? "已通过"
              : "需修正"
            : "待渲染"
        }
      />
      <div className="inspector-scroll quality-inspector">
        <div className="quality-score">
          <div className="score-ring">
            <svg viewBox="0 0 120 120">
              <circle cx="60" cy="60" r="50" />
              <circle cx="60" cy="60" r="50" className="score-progress" />
            </svg>
            <div>
              <strong>{report ? score : "—"}</strong>
              <span>/ 100</span>
            </div>
          </div>
          <div className="score-copy">
            <span>技术质量</span>
            <strong>
              {report
                ? report.hard_checks_passed
                  ? "稳定，可交付"
                  : "检测到硬质检风险"
                : "尚未生成质检成片"}
            </strong>
            <small>
              {report?.summary ??
                "先完成全片渲染，Verifier 才能基于真实输出帧生成报告。"}
            </small>
          </div>
        </div>

        {report ? (
          <div className="quality-list">
            {qualityGroups.map((group) => (
              <div className="quality-group" key={group.id}>
                <div className="section-label">
                  <span>{group.label}</span>
                </div>
                {group.checks.map((check) => {
                  const rowScore = Math.max(
                    0,
                    Math.min(
                      100,
                      100 -
                        (check.value / Math.max(check.threshold, 1e-6)) * 55,
                    ),
                  );
                  return (
                    <div key={check.id} className="quality-row">
                      <div className="quality-row-head">
                        <span>
                          <CheckCircle2 size={12} />
                          {check.label}
                        </span>
                        <strong>
                          {formatQualityValue(check.value, check.unit)}
                        </strong>
                      </div>
                      <div className="quality-bar">
                        <i style={{ width: `${rowScore}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}
            {(report.aesthetic_preferences?.length ?? 0) > 0 ? (
              <div className="quality-group">
                <div className="section-label">
                  <span>审美偏好（辅助，不参与硬门禁）</span>
                </div>
                {report.aesthetic_preferences?.map((item) => (
                  <div className="quality-row" key={item.id}>
                    <div className="quality-row-head">
                      <span>{item.id}</span>
                      <strong>{(item.value * 100).toFixed(1)}</strong>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="quality-render-guide">
            <div className="section-label">
              <span>如何生成真实成片</span>
            </div>
            <ol>
              <li>
                <strong>01</strong>
                <span>
                  <b>确认当前调色</b>
                  <small>预览、节点和关键帧会写入本次渲染。</small>
                </span>
              </li>
              <li>
                <strong>02</strong>
                <span>
                  <b>开始完整导出</b>
                  <small>按原素材规格渲染 HEVC Main10 成片。</small>
                </span>
              </li>
              <li>
                <strong>03</strong>
                <span>
                  <b>自动运行 Verifier</b>
                  <small>读取真实输出帧，生成质检报告和交付包。</small>
                </span>
              </li>
            </ol>
            <button
              className="button button-primary quality-render-button"
              type="button"
              onClick={onExport}
            >
              <Film size={14} />
              打开导出设置
            </button>
          </div>
        )}

        <div className="quality-findings">
          <div className="section-label">
            <span>Agent 观察</span>
          </div>
          <div>
            <CloudSun size={15} />
            <p>
              {report?.checks[0]?.detail ??
                "渲染后会检测高光剪裁、阴影压死与结构损失。"}
            </p>
          </div>
          <div>
            <Waves size={15} />
            <p>
              {report?.checks[3]?.detail ??
                "时间稳定性会排除硬切，再分析相邻帧亮度变化。"}
            </p>
          </div>
        </div>
      </div>
      <div className="quality-footer">
        <ShieldCheck size={15} />
        <span>
          {report
            ? `Verifier 已分析 ${report.sampled_frames} 个真实采样帧`
            : "完整导出后自动运行 Verifier"}
        </span>
        <strong>{report ? `${report.checks.length} 项指标` : "导出 → 开始导出"}</strong>
      </div>
    </>
  );
}

function AssetsInspector({
  onExport,
  maskCount = 0,
  projectName = "ColorGraph Project",
  previewSource = SOURCE_IMAGE,
}: {
  onExport: () => void;
  maskCount?: number;
  projectName?: string;
  previewSource?: string;
}) {
  const assets = [
    { icon: Film, name: "graded.mp4", meta: "本地 GPU 渲染 · HEVC Main10" },
    { icon: Palette, name: "luts/", meta: "逐场景 · 33 × 33 × 33" },
    { icon: FileJson, name: "grade_graph.json", meta: "Typed Grade Graph v2" },
    { icon: Layers3, name: "masks/", meta: `${maskCount} 组逐帧蒙版` },
  ];
  return (
    <>
      <InspectorHeading kicker="DELIVERABLES" title="可编辑资产" count="4 项" />
      <div className="inspector-scroll assets-inspector">
        <div className="asset-preview">
          <div
            className="asset-preview-image"
            style={{ backgroundImage: `url(${previewSource})` }}
          >
            <span>FINAL · REC.709</span>
          </div>
          <div>
            <strong>{projectName}</strong>
            <span>本地项目 · Rec.709</span>
          </div>
        </div>

        <div className="asset-list">
          {assets.map(({ icon: Icon, name, meta }) => (
            <div key={name}>
              <span className="asset-icon">
                <Icon size={15} />
              </span>
              <span>
                <strong>{name}</strong>
                <small>{meta}</small>
              </span>
              <CheckCircle2 size={13} />
            </div>
          ))}
        </div>

        <div className="package-info">
          <Gauge size={15} />
          <div>
            <strong>增量预览</strong>
            <span>节点修改只刷新当前预览；交付视频当前执行完整确定性渲染。</span>
          </div>
        </div>
      </div>
      <div className="asset-export-footer">
        <button className="button button-primary" type="button" onClick={onExport}>
          <Download size={14} />
          导出交付包
        </button>
      </div>
    </>
  );
}

export function Inspector(props: InspectorProps) {
  return (
    <aside className="inspector">
      {props.activePanel === "grade" && <GradeInspector {...props} />}
      {props.activePanel === "graph" && <GraphInspector nodes={props.nodes} />}
      {props.activePanel === "quality" && (
        <QualityInspector report={props.quality} onExport={props.onExport} />
      )}
      {props.activePanel === "assets" && (
        <AssetsInspector
          onExport={props.onExport}
          maskCount={props.maskCount}
          projectName={props.projectName}
          previewSource={props.previewSource}
        />
      )}
    </aside>
  );
}

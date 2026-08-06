import type { GradeNode, LookId, PipelineStage, Shot } from "./types";

export const SOURCE_IMAGE = "/assets/colorgraph-landscape.png";

export const LOOKS: Record<
  LookId,
  { name: string; en: string; note: string }
> = {
  natural: {
    name: "自然旅拍",
    en: "Natural Travel",
    note: "真实、通透、保留云层",
  },
  cool: {
    name: "清冷纪实",
    en: "Cool Documentary",
    note: "冷静蓝灰，植被克制",
  },
  warm: {
    name: "暖阳电影",
    en: "Warm Sunset",
    note: "暖色日落，压住高光",
  },
  foggy: {
    name: "雾境电影",
    en: "Foggy Cinematic",
    note: "柔和反差，远山分层",
  },
};

export const INITIAL_NODES: GradeNode[] = [
  {
    id: "input",
    name: "输入色彩转换",
    subtitle: "Rec.709 → Linear Rec.709",
    scope: "Project",
    kind: "input",
    enabled: true,
    gpu: true,
  },
  {
    id: "balance",
    name: "基础平衡",
    subtitle: "曝光 +0.08 · 色温 +4",
    scope: "Shot 03",
    kind: "balance",
    enabled: true,
    gpu: true,
    parameter: "exposure",
  },
  {
    id: "highlight",
    name: "高光恢复",
    subtitle: "云层保护 · -0.18",
    scope: "Sky",
    kind: "tone",
    enabled: true,
    gpu: true,
    parameter: "highlights",
  },
  {
    id: "sky",
    name: "天空层次",
    subtitle: "语义蒙版 · 跟踪稳定",
    scope: "Sky",
    kind: "mask",
    enabled: true,
    gpu: true,
    parameter: "highlights",
  },
  {
    id: "vegetation",
    name: "植被保护",
    subtitle: "Hue vs Sat · -0.05",
    scope: "Vegetation",
    kind: "mask",
    enabled: true,
    gpu: true,
    parameter: "saturation",
  },
  {
    id: "look",
    name: "自然旅拍",
    subtitle: "Scene 01 · 强度 72%",
    scope: "Scene 01",
    kind: "look",
    enabled: true,
    gpu: true,
    parameter: "strength",
  },
  {
    id: "output",
    name: "输出色彩转换",
    subtitle: "Linear Rec.709 → Rec.709",
    scope: "Project",
    kind: "output",
    enabled: true,
    gpu: true,
  },
];

export const SHOTS: Shot[] = [
  {
    id: "shot-01",
    label: "01",
    start: 0,
    duration: 5.2,
    position: "18% 50%",
  },
  {
    id: "shot-02",
    label: "02",
    start: 5.2,
    duration: 4.6,
    position: "35% 43%",
  },
  {
    id: "shot-03",
    label: "03",
    start: 9.8,
    duration: 8.4,
    position: "53% 50%",
  },
  {
    id: "shot-04",
    label: "04",
    start: 18.2,
    duration: 5.9,
    position: "72% 46%",
  },
  {
    id: "shot-05",
    label: "05",
    start: 24.1,
    duration: 4.6,
    position: "88% 50%",
  },
];

export const PIPELINE_STAGES: PipelineStage[] = [
  {
    id: "decode",
    label: "媒体解析",
    detail: "FFmpeg / FFprobe · 输入色彩空间",
    device: "CPU",
  },
  {
    id: "shots",
    label: "镜头与变化点",
    detail: "边界检测 · 曝光与白平衡时间序列",
    device: "CPU",
  },
  {
    id: "vision",
    label: "多模态场景理解",
    detail: "CLIP 代表帧场景理解与 Look 推荐",
    device: "GPU",
  },
  {
    id: "masks",
    label: "语义与深度蒙版",
    detail: "SegFormer · Depth Anything · 光流传播",
    device: "GPU",
  },
  {
    id: "graph",
    label: "编译时空调色图",
    detail: "Typed Grade Graph · 参数与关键帧",
    device: "GPU",
  },
  {
    id: "verify",
    label: "渲染与质量验证",
    detail: "技术硬质检 · Verifier 定向修复",
    device: "GPU",
  },
];

export const TOTAL_DURATION = SHOTS.reduce((sum, shot) => sum + shot.duration, 0);

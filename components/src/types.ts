export type MediaType = 'image' | 'video' | 'audio' | 'text';

export interface MediaItem {
  id: string;
  type: MediaType;
  url: string;
  prompt: string;
  timestamp: string;
  aspectRatio?: string;
  resolution?: string;
  duration?: number;
  voiceName?: string;
  style?: string;
  gpuAccelerated: boolean;
  gpuTimeMs: number;
}

export interface GpuPreset {
  id: string;
  name: string;
  gpuModel: string;
  vram: string;
  precision: 'FP32' | 'FP16' | 'INT8';
  throughputMultiplier: number;
  efficiencyRating: string;
  active: boolean;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'model';
  text: string;
  timestamp: string;
  suggestions?: string[];
  mediaRefId?: string;
}

export interface GpuMetricSnapshot {
  vramUsedGb: number;
  vramTotalGb: number;
  gpuLoadPercent: number;
  inferenceLatencyMs: number;
  imagesPerMinute: number;
  videoFpsRate: number;
  temperatureCelsius: number;
  gpuModel?: string;
  activePrecision?: string;
  powerDrawWatts?: number;
}

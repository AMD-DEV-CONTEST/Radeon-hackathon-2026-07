import { create } from "zustand";

export interface AgentStatus {
  id: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  data?: unknown;
}

export interface TimelineEvent {
  id: string;
  timestamp: string;
  agent: string;
  status: string;
  duration?: number;
}

export interface GPUMetrics {
  gpu_name: string;
  vram_used_gb: number;
  vram_total_gb: number;
  gpu_utilization_percent: number;
  gpu_temperature_celsius: number;
  power_draw_watts: number;
  active_agents: number;
}

interface LaunchState {
  currentLaunchId: string | null;
  token: string | null;
  status: "idle" | "running" | "completed" | "failed";
  progress: number;
  agents: Record<string, AgentStatus>;
  timeline: TimelineEvent[];
  gpuMetrics: GPUMetrics | null;
  selectedAgentId: string | null;
  
  setCurrentLaunchId: (id: string | null) => void;
  setStatus: (status: LaunchState["status"]) => void;
  setProgress: (progress: number) => void;
  updateAgent: (agentId: string, status: AgentStatus) => void;
  addTimelineEvent: (event: TimelineEvent) => void;
  setGPUMetrics: (metrics: GPUMetrics) => void;
  setToken: (token: string | null) => void;
  setSelectedAgentId: (id: string | null) => void;
}

export const useLaunchStore = create<LaunchState>((set) => ({
  currentLaunchId: null,
  token: "mock_token_for_hackathon",
  status: "idle",
  progress: 0,
  agents: {},
  timeline: [],
  gpuMetrics: null,
  selectedAgentId: null,
  
  setCurrentLaunchId: (id) => set({ currentLaunchId: id }),
  setStatus: (status) => set({ status }),
  setProgress: (progress) => set({ progress }),
  updateAgent: (agentId, status) => 
    set((state) => ({ agents: { ...state.agents, [agentId]: status } })),
  addTimelineEvent: (event) => 
    set((state) => ({ timeline: [event, ...state.timeline] })),
  setGPUMetrics: (metrics) => set({ gpuMetrics: metrics }),
  setToken: (token) => set({ token }),
  setSelectedAgentId: (id) => set({ selectedAgentId: id }),
}));


"use client";

import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { AgentGraph } from "./AgentGraph";
import { GPUTelemetry } from "./GPUTelemetry";
import { ExecutionTimeline } from "./ExecutionTimeline";
import { AgentReasoningPanel } from "./AgentReasoningPanel";
import { UploadProductModal } from "./UploadProductModal";
import { ProductAnalysisStudio } from "./ProductAnalysisStudio";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useLaunchStore } from "@/stores/launchStore";
import { useState } from "react";
import { Play, Sparkles, ShieldCheck, Activity, BrainCircuit, Cpu, GitFork, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/Button";
import axios from "axios";

export default function DashboardPage() {
  const { updateAgent, addTimelineEvent, setGPUMetrics, setCurrentLaunchId, setStatus, currentLaunchId } =
    useLaunchStore();
  const [isLaunching, setIsLaunching] = useState(false);
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);

  // Hardcoded for demo/testing
  const mockProductId = "123e4567-e89b-12d3-a456-426614174000";
  const activeLaunchId = currentLaunchId || "00000000-0000-0000-0000-000000000000";

  // Connect to the WebSocket endpoint for real-time telemetry updates
  const { isConnected } = useWebSocket({
    url: `ws://localhost:8000/api/v1/ws/${activeLaunchId}?token=mock_token_for_hackathon`,
    onMessage: (msg: any) => {
      console.log("WS Message:", msg);
      if (msg.type === "agent_status") {
        updateAgent(msg.agent, { id: msg.agent, status: msg.status, progress: msg.progress, data: msg.data });
      } else if (msg.type === "timeline_event") {
        addTimelineEvent(msg.event);
      } else if (msg.type === "gpu_metrics") {
        setGPUMetrics(msg.metrics);
      }
    },
  });

  const startOrchestration = async () => {
    setIsLaunching(true);
    setStatus("running");
    try {
      const res = await axios.post(
        "http://localhost:8000/api/v1/launches",
        {
          product_id: mockProductId,
          target_marketplaces: ["amazon", "shopify"],
          preferences: {},
        },
        {
          headers: {
            Authorization: "Bearer mock_token_for_hackathon",
          },
        }
      );
      if (res.data && res.data.id) {
        setCurrentLaunchId(res.data.id);
      }
    } catch (error) {
      console.error("Failed to execute pipeline:", error);
    } finally {
      setIsLaunching(false);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--color-background)] text-[var(--color-foreground)] flex selection:bg-[var(--color-brand-primary)] selection:text-white transition-colors duration-200">
      <Sidebar />

      <div className="flex-1 flex flex-col pl-64 min-w-0">
        <Header />

        <main className="flex-1 pt-6 p-8 overflow-y-auto">
          <div className="max-w-[1600px] mx-auto space-y-8">
            {/* Top Control Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-[var(--color-surface)] border border-[var(--color-border)] p-6 rounded-2xl shadow-2xl relative overflow-hidden transition-colors duration-200">
              {/* Ambient Glow */}
              <div className="absolute top-0 right-0 w-96 h-96 bg-gradient-to-l from-[var(--color-brand-primary)]/15 to-transparent rounded-full blur-3xl pointer-events-none" />

              <div>
                <div className="flex items-center gap-3 mb-3 flex-wrap">
                  <span className="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-red-500/15 to-orange-500/15 border border-red-500/30 px-3.5 py-1.5 text-xs font-semibold text-red-400 backdrop-blur-md shadow-[0_0_15px_rgba(237,28,36,0.15)]">
                    <Cpu className="h-3.5 w-3.5 text-red-500 animate-pulse" />
                    AMD Radeon ROCm 6.1 Cluster
                  </span>

                  <span className="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-emerald-500/15 to-teal-500/15 border border-emerald-500/30 px-3.5 py-1.5 text-xs font-semibold text-emerald-400 backdrop-blur-md shadow-[0_0_15px_rgba(16,185,129,0.15)]">
                    <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
                    15 Autonomous AI Agents
                  </span>

                  {isConnected && (
                    <span className="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-sky-500/15 to-blue-500/15 border border-sky-500/30 px-3.5 py-1.5 text-xs font-semibold text-sky-400 backdrop-blur-md shadow-[0_0_15px_rgba(14,165,233,0.15)]">
                      <span className="h-2 w-2 rounded-full bg-sky-400 animate-ping" />
                      Live WebSocket Synchronized
                    </span>
                  )}
                </div>

                <h1 className="text-3xl lg:text-4xl font-black tracking-tight text-[var(--color-foreground)] flex items-center gap-3 bg-gradient-to-r from-white via-gray-200 to-gray-400 bg-clip-text text-transparent">
                  Autonomous AI Launch Studio
                </h1>
                <p className="text-[var(--color-muted)] text-sm mt-1.5 max-w-2xl font-medium leading-relaxed">
                  Real-time multi-agent orchestration powered by local AMD Radeon GPUs. Watch 15 autonomous agents collaborate to analyze images, generate SEO copy, and optimize pricing in seconds.
                </p>
              </div>

              <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 z-10">
                <Button
                  variant="outline"
                  size="lg"
                  onClick={startOrchestration}
                  disabled={isLaunching}
                  className="gap-2 text-sm font-bold uppercase tracking-wider px-5 py-5 rounded-xl border-[var(--color-border)] hover:bg-[var(--color-surface-hover)] transition-all"
                >
                  <Play className={`w-4 h-4 fill-current text-[var(--color-brand-primary)] ${isLaunching ? "animate-spin" : ""}`} />
                  {isLaunching ? "Demo Executing..." : "Quick Demo Launch"}
                </Button>

                <Button
                  size="lg"
                  onClick={() => setIsUploadModalOpen(true)}
                  disabled={isLaunching}
                  className="gap-2.5 text-sm md:text-base font-bold uppercase tracking-wider px-7 py-5 rounded-xl bg-gradient-to-r from-[var(--color-brand-primary)] via-red-600 to-[#990F16] hover:from-red-600 hover:to-[var(--color-brand-primary)] text-white shadow-[0_0_25px_rgba(237,28,36,0.3)] hover:shadow-[0_0_40px_rgba(237,28,36,0.5)] transition-all transform hover:-translate-y-0.5 active:translate-y-0 border border-white/20"
                >
                  <UploadCloud className="w-5 h-5" />
                  <span>Upload Product & Launch AI</span>
                </Button>
              </div>
            </div>

            {/* PRIMARY CENTERPIECE: Analyzed Product & SEO Studio */}
            <ProductAnalysisStudio />

            {/* Section Divider: Behind the Scenes AI Engine */}
            <div className="pt-6 border-t-2 border-[var(--color-border)]">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
                <div>
                  <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-gradient-to-r from-red-500/15 to-orange-500/15 text-red-500 text-xs font-bold uppercase tracking-wider mb-2 border border-red-500/30 shadow-sm">
                    <Cpu className="w-3.5 h-3.5 inline mr-1 animate-pulse" /> Behind the Scenes AI Engine
                  </span>
                  <h2 className="text-2xl font-black text-[var(--color-foreground)] tracking-tight">
                    How LaunchKart AI Built This: AMD Radeon ROCm & 15-Agent Cluster
                  </h2>
                  <p className="text-sm text-[var(--color-muted)] mt-0.5">
                    Live hardware telemetry and multi-agent workflow monitoring. This is the autonomous orchestration engine that analyzed the photo and generated the SEO copy above.
                  </p>
                </div>
              </div>
            </div>

            {/* GPU Telemetry Cards */}
            <GPUTelemetry />

            {/* Main Execution Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
              {/* Left 2 Columns: Interactive Graph + Reasoning Panel */}
              <div className="lg:col-span-2 space-y-8">
                {/* Graph Card */}
                <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl p-6 shadow-2xl transition-colors duration-200">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-5 gap-2 border-b border-[var(--color-border)] pb-4">
                    <div>
                      <h3 className="text-lg font-bold text-[var(--color-foreground)] flex items-center gap-2">
                        <GitFork className="w-5 h-5 text-[var(--color-brand-primary)]" />
                        Live Agent Workflow & Intelligence Graph
                      </h3>
                      <p className="text-xs text-[var(--color-muted)] mt-0.5">
                        Click on any agent node below to inspect its live reasoning steps, memory vectors, and execution status.
                      </p>
                    </div>
                    <span className="text-xs font-medium text-[var(--color-muted)] bg-[var(--color-surface-hover)] px-3.5 py-1.5 rounded-xl border border-[var(--color-border)] self-start sm:self-auto shadow-sm">
                      ✨ Scroll to Zoom / Drag to Pan
                    </span>
                  </div>

                  <AgentGraph />
                </div>

                {/* Reasoning Panel Card */}
                <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl p-6 shadow-2xl transition-colors duration-200">
                  <div className="flex items-center justify-between mb-5 pb-4 border-b border-[var(--color-border)]">
                    <div>
                      <h3 className="text-lg font-bold text-[var(--color-foreground)] flex items-center gap-2">
                        <Activity className="w-5 h-5 text-emerald-500 animate-pulse" />
                        Live Agent Reasoning & Decision Stream
                      </h3>
                      <p className="text-xs text-[var(--color-muted)] mt-0.5">
                        Real-time intelligence stream showing LLM copywriting, vision analysis, and dynamic pricing calculations.
                      </p>
                    </div>
                    <span className="text-xs font-semibold text-emerald-400 bg-emerald-500/15 border border-emerald-500/30 px-3.5 py-1.5 rounded-xl shadow-[0_0_15px_rgba(16,185,129,0.15)]">
                      ● 15 Agents Synchronized
                    </span>
                  </div>

                  <AgentReasoningPanel />
                </div>
              </div>

              {/* Right 1 Column: Live Timeline */}
              <div className="lg:col-span-1 sticky top-8">
                <ExecutionTimeline />
              </div>
            </div>
          </div>
        </main>
      </div>

      {/* New Product Upload Modal */}
      <UploadProductModal
        isOpen={isUploadModalOpen}
        onClose={() => setIsUploadModalOpen(false)}
        onLaunchStarted={(launchId) => {
          setCurrentLaunchId(launchId);
          setStatus("running");
        }}
        mockProductId={mockProductId}
      />
    </div>
  );
}

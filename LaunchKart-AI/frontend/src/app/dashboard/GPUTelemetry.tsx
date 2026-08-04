"use client";

import { useLaunchStore } from "@/stores/launchStore";
import { Activity, Cpu, Thermometer, Zap } from "lucide-react";
import { motion } from "framer-motion";

export function GPUTelemetry() {
  const storeMetrics = useLaunchStore((state) => state.gpuMetrics);
  const metrics = {
    gpu_name: storeMetrics?.gpu_name ?? "AMD Radeon RX 7900 XTX",
    vram_used_gb: storeMetrics?.vram_used_gb ?? 18.4,
    vram_total_gb: storeMetrics?.vram_total_gb ?? 24.0,
    gpu_utilization_percent: storeMetrics?.gpu_utilization_percent ?? 85,
    gpu_temperature_celsius: storeMetrics?.gpu_temperature_celsius ?? 52,
    power_draw_watts: storeMetrics?.power_draw_watts ?? 285,
    active_agents: storeMetrics?.active_agents ?? 15,
  };

  const vramPercent = (metrics.vram_used_gb / metrics.vram_total_gb) * 100;

  const cards = [
    {
      title: "ROCm GPU Utilization",
      value: `${metrics.gpu_utilization_percent}%`,
      subtitle: metrics.gpu_name,
      icon: <Activity className="h-5 w-5 text-[var(--color-brand-primary)]" />,
      progress: metrics.gpu_utilization_percent,
      color: "from-[var(--color-brand-primary)] to-orange-500",
      glow: "rgba(237, 28, 36, 0.4)",
    },
    {
      title: "VRAM Memory Allocation",
      value: `${metrics.vram_used_gb.toFixed(1)} / ${metrics.vram_total_gb.toFixed(1)} GB`,
      subtitle: `${vramPercent.toFixed(0)}% VRAM Consumed`,
      icon: <Cpu className="h-5 w-5 text-blue-500" />,
      progress: vramPercent,
      color: "from-blue-500 to-cyan-400",
      glow: "rgba(59, 130, 246, 0.4)",
    },
    {
      title: "Core Die Temperature",
      value: `${metrics.gpu_temperature_celsius}°C`,
      subtitle: "Safe Operating Ceiling: 110°C",
      icon: <Thermometer className="h-5 w-5 text-emerald-500" />,
      progress: (metrics.gpu_temperature_celsius / 110) * 100,
      color: "from-emerald-500 to-teal-400",
      glow: "rgba(16, 185, 129, 0.4)",
    },
    {
      title: "Power & Concurrency",
      value: `${metrics.power_draw_watts}W`,
      subtitle: `Active Worker Threads: ${metrics.active_agents} Nodes`,
      icon: <Zap className="h-5 w-5 text-amber-500" />,
      progress: (metrics.power_draw_watts / 355) * 100,
      color: "from-amber-500 to-yellow-400",
      glow: "rgba(245, 158, 11, 0.4)",
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
      {cards.map((card, idx) => (
        <motion.div
          key={card.title}
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: idx * 0.08 }}
          whileHover={{ y: -3, scale: 1.01 }}
          className="relative rounded-2xl border border-white/10 bg-gradient-to-b from-neutral-900/80 to-neutral-950/90 p-5 shadow-xl transition-all duration-300 group hover:border-white/20 overflow-hidden backdrop-blur-xl"
        >
          {/* Top Ambient Glow */}
          <div
            className="absolute -top-12 -right-12 w-28 h-28 rounded-full blur-2xl opacity-20 group-hover:opacity-40 transition-opacity pointer-events-none"
            style={{ background: card.glow }}
          />

          <div className="flex items-center justify-between pb-3">
            <span className="text-xs font-bold uppercase tracking-wider text-neutral-400">
              {card.title}
            </span>
            <div className="w-9 h-9 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center shadow-inner group-hover:scale-110 transition-transform">
              {card.icon}
            </div>
          </div>

          <div className="text-2xl font-black text-white tracking-tight mb-1">
            {card.value}
          </div>

          <div className="text-xs text-neutral-400 font-medium mb-3.5 flex items-center gap-1.5">
            <span className="text-[10px] text-red-500 animate-pulse">●</span>
            {card.subtitle}
          </div>

          {/* Progress Bar */}
          <div className="w-full bg-white/5 border border-white/10 rounded-full h-1.5 p-[1px] overflow-hidden">
            <motion.div
              className={`h-full rounded-full bg-gradient-to-r ${card.color}`}
              style={{ boxShadow: `0 0 12px ${card.glow}` }}
              initial={{ width: 0 }}
              animate={{ width: `${Math.min(card.progress, 100)}%` }}
              transition={{ duration: 0.6, ease: "easeOut" }}
            />
          </div>
        </motion.div>
      ))}
    </div>
  );
}

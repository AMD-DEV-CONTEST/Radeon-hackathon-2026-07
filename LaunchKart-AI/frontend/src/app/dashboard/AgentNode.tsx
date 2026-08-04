"use client";

import { motion } from "framer-motion";
import { useLaunchStore } from "@/stores/launchStore";
import { Handle, Position } from "@xyflow/react";
import {
  Brain,
  Share2,
  Eye,
  Box,
  Search,
  ShieldCheck,
  DollarSign,
  Sparkles,
  Palette,
  FileText,
  Megaphone,
  CheckSquare,
  ShoppingBag,
  Database,
  BarChart3,
  ChevronRight,
} from "lucide-react";
import React from "react";

const iconMap: Record<string, React.ReactNode> = {
  planner: <Brain className="w-5 h-5 text-purple-500" />,
  coordinator: <Share2 className="w-5 h-5 text-blue-500" />,
  vision: <Eye className="w-5 h-5 text-cyan-500" />,
  product: <Box className="w-5 h-5 text-emerald-500" />,
  research: <Search className="w-5 h-5 text-amber-500" />,
  competitor: <ShieldCheck className="w-5 h-5 text-orange-500" />,
  pricing: <DollarSign className="w-5 h-5 text-green-500" />,
  seo: <Sparkles className="w-5 h-5 text-yellow-500" />,
  branding: <Palette className="w-5 h-5 text-pink-500" />,
  listing: <FileText className="w-5 h-5 text-indigo-500" />,
  marketing: <Megaphone className="w-5 h-5 text-rose-500" />,
  qa: <CheckSquare className="w-5 h-5 text-teal-500" />,
  marketplace: <ShoppingBag className="w-5 h-5 text-sky-500" />,
  memory: <Database className="w-5 h-5 text-violet-500" />,
  analytics: <BarChart3 className="w-5 h-5 text-red-500" />,
};

export function AgentNode({ data }: any) {
  const agentId = data.id;
  const statusInfo = useLaunchStore((state) => state.agents[agentId]);
  const selectedAgentId = useLaunchStore((state) => state.selectedAgentId);
  const setSelectedAgentId = useLaunchStore((state) => state.setSelectedAgentId);

  const status = statusInfo?.status || "pending";
  const progress = statusInfo?.progress || 0;
  const isSelected = selectedAgentId === agentId;

  const statusStyles: Record<string, { border: string; badge: string; text: string; dot: string }> = {
    pending: {
      border: "border-white/10 bg-gradient-to-b from-neutral-900/90 to-neutral-950/90 text-neutral-400 hover:border-white/20 backdrop-blur-xl shadow-lg",
      badge: "bg-white/5 text-neutral-400 border border-white/10",
      text: "Ready",
      dot: "bg-neutral-500",
    },
    running: {
      border: "border-red-500/80 bg-gradient-to-b from-red-950/40 via-neutral-900/95 to-neutral-950/95 text-white shadow-[0_0_30px_rgba(237,28,36,0.3)] ring-1 ring-red-500/50",
      badge: "bg-red-500/20 text-red-400 border border-red-500/40 animate-pulse",
      text: "Active",
      dot: "bg-red-500 animate-ping",
    },
    completed: {
      border: "border-emerald-500/40 bg-gradient-to-b from-emerald-950/20 via-neutral-900/95 to-neutral-950/95 text-white hover:border-emerald-500/60 shadow-[0_0_20px_rgba(16,185,129,0.15)]",
      badge: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
      text: "Done",
      dot: "bg-emerald-500",
    },
    failed: {
      border: "border-red-600 bg-red-950/30 text-red-400 shadow-[0_0_25px_rgba(220,38,38,0.4)]",
      badge: "bg-red-600/25 text-red-400 border border-red-500/50",
      text: "Error",
      dot: "bg-red-500",
    },
  };

  const currentStyle = statusStyles[status] || statusStyles.pending;
  const IconComponent = iconMap[agentId] || <Brain className="w-5 h-5 text-neutral-400" />;

  return (
    <motion.div
      initial={{ scale: 0.95, opacity: 0 }}
      animate={{ scale: isSelected ? 1.05 : 1, opacity: 1 }}
      whileHover={{ scale: isSelected ? 1.05 : 1.02 }}
      onClick={() => setSelectedAgentId(agentId)}
      style={{
        boxShadow: isSelected
          ? "0 0 35px rgba(237, 28, 36, 0.45), inset 0 0 20px rgba(237, 28, 36, 0.15)"
          : undefined,
      }}
      className={`relative rounded-2xl border p-4 w-72 shadow-xl transition-all duration-300 cursor-pointer group select-none ${
        isSelected ? "border-red-500 bg-gradient-to-b from-neutral-900 via-neutral-950 to-black z-30 ring-2 ring-red-500/30" : currentStyle.border
      }`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="w-3.5 h-3.5 !bg-red-500 !border-2 !border-neutral-950 shadow-md"
      />

      {/* Top Header Row */}
      <div className="flex justify-between items-center mb-2.5 gap-2">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center shadow-inner group-hover:scale-110 group-hover:border-white/20 transition-all duration-200">
            {IconComponent}
          </div>
          <div>
            <h3 className="font-bold text-sm tracking-tight text-white group-hover:text-red-400 transition-colors leading-tight">
              {data.label}
            </h3>
            <span className="text-[10px] font-medium tracking-wide text-neutral-400 uppercase">
              Agent #{agentId}
            </span>
          </div>
        </div>

        {/* Status Badge */}
        <div
          className={`px-2.5 py-0.5 rounded-full text-[10px] font-semibold tracking-wider uppercase flex items-center gap-1.5 shadow-sm ${currentStyle.badge}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${currentStyle.dot}`} />
          {currentStyle.text}
        </div>
      </div>

      {/* Description */}
      <div className="text-xs text-neutral-300 font-normal leading-relaxed mb-3 line-clamp-2 min-h-[32px]">
        {data.description}
      </div>

      {/* Glowing Progress Bar Track */}
      <div className="w-full bg-white/5 border border-white/10 rounded-full h-1.5 mb-3 p-[1px] overflow-hidden">
        <motion.div
          className={`h-full rounded-full transition-all duration-500 ${
            status === "completed"
              ? "bg-gradient-to-r from-emerald-500 to-teal-400 shadow-[0_0_10px_rgba(16,185,129,0.5)]"
              : status === "running"
              ? "bg-gradient-to-r from-red-500 via-orange-500 to-amber-400 animate-pulse shadow-[0_0_12px_rgba(237,28,36,0.6)]"
              : "bg-neutral-600"
          }`}
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
        />
      </div>

      {/* Footer Info */}
      <div className="flex justify-between items-center text-xs text-neutral-400 pt-2 border-t border-white/10 font-medium">
        <span className="text-neutral-200 font-semibold">{progress}% Complete</span>
        <span className="flex items-center text-[11px] font-semibold text-red-400 group-hover:translate-x-1 transition-transform">
          Live Stream <ChevronRight className="w-3.5 h-3.5 ml-0.5" />
        </span>
      </div>

      <Handle
        type="source"
        position={Position.Right}
        className="w-3.5 h-3.5 !bg-[var(--color-brand-primary)] !border-2 !border-[var(--color-surface)] shadow-md"
      />
    </motion.div>
  );
}

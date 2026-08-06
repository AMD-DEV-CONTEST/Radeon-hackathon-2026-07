"use client";

import { Card } from "@/components/ui/Card";
import { Users, Images, Sparkles, Zap, Cpu, TrendingUp } from "lucide-react";

interface StatsBarProps {
  totalGenerations?: number;
  totalImages?: number;
  gpuUtilization?: number;
  avgGenerationTime?: number;
  styleBreakdown?: { style: string; count: number }[];
}

export function StatsBar({
  totalGenerations = 0,
  totalImages = 0,
  gpuUtilization = 0,
  avgGenerationTime = 0,
  styleBreakdown = [],
}: StatsBarProps) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <Card className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500/20 to-indigo-500/5 flex items-center justify-center">
          <Sparkles className="w-6 h-6 text-indigo-400" />
        </div>
        <div>
          <p className="text-2xl font-bold text-slate-100">{totalGenerations}</p>
          <p className="text-sm text-slate-400">Total Generations</p>
        </div>
      </Card>

      <Card className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-pink-500/20 to-pink-500/5 flex items-center justify-center">
          <Images className="w-6 h-6 text-pink-400" />
        </div>
        <div>
          <p className="text-2xl font-bold text-slate-100">{totalImages}</p>
          <p className="text-sm text-slate-400">Images Created</p>
        </div>
      </Card>

      <Card className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/20 to-cyan-500/5 flex items-center justify-center">
          <Zap className="w-6 h-6 text-cyan-400" />
        </div>
        <div>
          <p className="text-2xl font-bold text-slate-100">{gpuUtilization}%</p>
          <p className="text-sm text-slate-400">GPU Utilization</p>
        </div>
      </Card>

      <Card className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-green-500/20 to-green-500/5 flex items-center justify-center">
          <TrendingUp className="w-6 h-6 text-green-400" />
        </div>
        <div>
          <p className="text-2xl font-bold text-slate-100">{avgGenerationTime > 0 ? `${avgGenerationTime.toFixed(0)}ms` : "--"}</p>
          <p className="text-sm text-slate-400">Avg. Generation</p>
        </div>
      </Card>

      {/* Style Breakdown */}
      {styleBreakdown.length > 0 && (
        <Card className="lg:col-span-4">
          <h3 className="text-sm font-medium text-slate-300 mb-4 flex items-center gap-2">
            <Cpu className="w-4 h-4 text-indigo-400" />
            Generation Style Breakdown
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
            {styleBreakdown.map(({ style, count }) => (
              <div
                key={style}
                className="flex items-center gap-3 p-3 rounded-xl bg-slate-800/30 border border-slate-700/30"
              >
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500/20 to-pink-500/20 flex items-center justify-center">
                  <Sparkles className="w-4 h-4 text-indigo-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-200 truncate capitalize">
                    {style.replace("-", " ")}
                  </p>
                  <p className="text-xs text-slate-500">{count} generations</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

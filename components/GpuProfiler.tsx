import React, { useEffect, useState } from 'react';
import { GpuPreset, GpuMetricSnapshot } from '../types';
import { Cpu, Zap, Thermometer, Database, Gauge, Check, Sliders, Play } from 'lucide-react';

interface GpuProfilerProps {
  activePresetId: string;
  setActivePresetId: (id: string) => void;
  activePrecision: 'FP32' | 'FP16' | 'INT8';
  setActivePrecision: (p: 'FP32' | 'FP16' | 'INT8') => void;
  metrics: GpuMetricSnapshot | null;
  setMetrics: (m: GpuMetricSnapshot) => void;
}

export const GPU_PRESETS: GpuPreset[] = [
  {
    id: 'rx-7900-xtx',
    name: 'Radeon RX 7900 XTX',
    gpuModel: 'AMD Radeon RX 7900 XTX (Navi 31)',
    vram: '24 GB GDDR6',
    precision: 'FP16',
    throughputMultiplier: 1.2,
    efficiencyRating: 'A+',
    active: true
  },
  {
    id: 'pro-w7900',
    name: 'Radeon PRO W7900',
    gpuModel: 'AMD Radeon PRO W7900 (Workstation)',
    vram: '48 GB GDDR6 ECC',
    precision: 'FP16',
    throughputMultiplier: 1.5,
    efficiencyRating: 'A++',
    active: false
  },
  {
    id: 'rx-7700-xt',
    name: 'Radeon RX 7700 XT',
    gpuModel: 'AMD Radeon RX 7700 XT (Navi 32)',
    vram: '12 GB GDDR6',
    precision: 'FP16',
    throughputMultiplier: 0.85,
    efficiencyRating: 'A',
    active: false
  }
];

export default function GpuProfiler({
  activePresetId,
  setActivePresetId,
  activePrecision,
  setActivePrecision,
  metrics,
  setMetrics
}: GpuProfilerProps) {
  const [powerDraw, setPowerDraw] = useState(180);
  const selectedPreset = GPU_PRESETS.find(p => p.id === activePresetId) || GPU_PRESETS[0];

  // Poll server or simulate metrics matching selection
  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        const res = await fetch('/api/gpu-stats', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            presetId: activePresetId,
            precision: activePrecision,
            loadFactor: 1.0 + Math.sin(Date.now() / 10000) * 0.1
          })
        });
        if (res.ok) {
          const data = await res.json();
          setMetrics(data);
          if (data.powerDrawWatts) {
            setPowerDraw(data.powerDrawWatts);
          }
        }
      } catch (err) {
        console.error('Error fetching GPU metrics:', err);
      }
    };

    fetchMetrics();
    const interval = setInterval(fetchMetrics, 3000);
    return () => clearInterval(interval);
  }, [activePresetId, activePrecision]);

  if (!metrics) {
    return (
      <div className="flex items-center justify-center h-48 bg-neutral-900 border border-neutral-800 rounded-xl">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-red-500"></div>
      </div>
    );
  }

  // Calculate percentages for dashboard rendering
  const vramPercent = Math.round((metrics.vramUsedGb / metrics.vramTotalGb) * 100);
  const powerMax = activePresetId === 'pro-w7900' ? 295 : activePresetId === 'rx-7900-xtx' ? 355 : 245;
  const powerPercent = Math.round((powerDraw / powerMax) * 100);

  return (
    <div className="space-y-6 pb-12">
      {/* GPU Presets Selectors */}
      <div className="bg-black border border-white/10 p-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-4 gap-2">
          <div className="flex items-center space-x-3">
            <Cpu className="h-5 w-5 text-[#FF3E3E]" />
            <h3 className="font-black text-lg text-white uppercase tracking-tight italic">Radeon GPU Compute Hardware</h3>
          </div>
          <span className="text-[10px] font-mono bg-[#FF3E3E] text-black px-3 py-1 font-black uppercase tracking-wider block self-start sm:self-auto">
            AMD ROCm™ 6.1 Enabled
          </span>
        </div>
        <p className="text-xs text-white/60 mb-6 leading-relaxed">
          Select an optimized Radeon architectural profile to allocate VRAM, set pipeline quantization boundaries, and accelerate creative workloads.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {GPU_PRESETS.map((p) => {
            const isActive = p.id === activePresetId;
            return (
              <button
                key={p.id}
                onClick={() => setActivePresetId(p.id)}
                className={`flex flex-col text-left p-4 border transition-all duration-300 cursor-pointer ${
                  isActive
                    ? 'bg-white border-white text-black'
                    : 'bg-white/5 border-white/10 hover:border-white/20 hover:bg-white/10 text-white'
                }`}
              >
                <div className="flex items-center justify-between w-full mb-2">
                  <span className="text-xs font-black uppercase tracking-wider">
                    {p.name}
                  </span>
                  {isActive && <Check className="h-4 w-4 text-black" />}
                </div>
                <span className={`text-[10px] font-mono mb-4 ${isActive ? 'text-black/60' : 'text-white/40'}`}>{p.gpuModel}</span>
                <div className={`mt-auto flex items-center justify-between text-[10px] border-t pt-2.5 w-full uppercase tracking-wider font-bold ${isActive ? 'border-black/10 text-black/80' : 'border-white/10 text-white/60'}`}>
                  <span className="flex items-center">
                    <Database className="h-3.5 w-3.5 mr-1 text-current" />
                    {p.vram}
                  </span>
                  <span className={`px-1.5 py-0.5 font-mono text-[9px] font-black ${isActive ? 'bg-black text-white' : 'bg-white/10 text-white/80'}`}>
                    EFF: {p.efficiencyRating}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* GPU Execution Precisions */}
      <div className="bg-black border border-white/10 p-6">
        <div className="flex items-center space-x-3 mb-4">
          <Sliders className="h-5 w-5 text-[#FF3E3E]" />
          <h3 className="font-black text-lg text-white uppercase tracking-tight italic">Precision & Execution Modes</h3>
        </div>
        <p className="text-xs text-white/60 mb-6 leading-relaxed">
          Tuning the compilation precision impacts the arithmetic throughput of double-precision, floating-point, and quantized operations.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {(['FP32', 'FP16', 'INT8'] as const).map((prec) => {
            const isActive = prec === activePrecision;
            let title = '';
            let desc = '';
            let speedup = '';

            if (prec === 'FP32') {
              title = 'Full Precision';
              desc = 'Maximum creative visual detail and floating-point accuracy.';
              speedup = 'Baseline Speed';
            } else if (prec === 'FP16') {
              title = 'Mixed Precision (Default)';
              desc = 'Balanced fidelity and memory footprint. Fully accelerated.';
              speedup = '1.8x Speedup';
            } else {
              title = 'Quantized INT8 (Boost)';
              desc = 'ROCm optimized integer pipeline. Ultra low latency.';
              speedup = '3.5x Speedup';
            }

            return (
              <button
                key={prec}
                onClick={() => setActivePrecision(prec)}
                className={`flex flex-col text-left p-4 border transition-all duration-300 cursor-pointer ${
                  isActive
                    ? 'bg-white border-white text-black'
                    : 'bg-white/5 border-white/10 hover:border-white/20 hover:bg-white/10 text-white'
                }`}
              >
                <div className="flex items-center justify-between w-full mb-1">
                  <span className="text-xs font-black uppercase tracking-widest italic">
                    {prec}
                  </span>
                  <span className={`text-[9px] font-mono font-black px-1.5 py-0.5 uppercase tracking-wider ${isActive ? 'bg-black text-white' : 'bg-[#FF3E3E] text-black'}`}>
                    {speedup}
                  </span>
                </div>
                <span className={`text-[10px] font-bold uppercase tracking-wider mt-2 block ${isActive ? 'text-black' : 'text-white/80'}`}>{title}</span>
                <span className={`text-xs mt-1 leading-relaxed ${isActive ? 'text-black/70' : 'text-white/50'}`}>{desc}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* GPU Performance Monitors / telemetry dashboard */}
      <div className="bg-[#050505] border border-white/10 p-6">
        <h3 className="font-black text-lg text-white uppercase tracking-tight italic mb-6">Hardware Telemetry & Acceleration</h3>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Load Metric */}
          <div className="bg-black border border-white/10 p-4 flex flex-col justify-between">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[9px] text-white/40 font-mono uppercase font-black tracking-widest">GPU Engine Load</span>
              <Gauge className="h-4 w-4 text-[#FF3E3E]" />
            </div>
            <div>
              <span className="text-2xl font-black text-white font-mono">{metrics.gpuLoadPercent}%</span>
              <div className="w-full bg-white/10 h-1 mt-3 overflow-hidden">
                <div
                  className="bg-[#FF3E3E] h-1 transition-all duration-500"
                  style={{ width: `${metrics.gpuLoadPercent}%` }}
                ></div>
              </div>
            </div>
          </div>

          {/* VRAM Metric */}
          <div className="bg-black border border-white/10 p-4 flex flex-col justify-between">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[9px] text-white/40 font-mono uppercase font-black tracking-widest">VRAM Allocation</span>
              <Database className="h-4 w-4 text-sky-400" />
            </div>
            <div>
              <span className="text-2xl font-black text-white font-mono">
                {metrics.vramUsedGb}<span className="text-xs text-white/40">/{metrics.vramTotalGb}GB</span>
              </span>
              <div className="w-full bg-white/10 h-1 mt-3 overflow-hidden">
                <div
                  className="bg-sky-400 h-1 transition-all duration-500"
                  style={{ width: `${vramPercent}%` }}
                ></div>
              </div>
            </div>
          </div>

          {/* Core Temperature */}
          <div className="bg-black border border-white/10 p-4 flex flex-col justify-between">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[9px] text-white/40 font-mono uppercase font-black tracking-widest">GPU Core Temp</span>
              <Thermometer className="h-4 w-4 text-orange-400" />
            </div>
            <div>
              <span className="text-2xl font-black text-white font-mono">{metrics.temperatureCelsius}°C</span>
              <div className="w-full bg-white/10 h-1 mt-3 overflow-hidden">
                <div
                  className="bg-orange-400 h-1 transition-all duration-500"
                  style={{ width: `${Math.min(100, (metrics.temperatureCelsius / 105) * 100)}%` }}
                ></div>
              </div>
            </div>
          </div>

          {/* Power Draw */}
          <div className="bg-black border border-white/10 p-4 flex flex-col justify-between">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[9px] text-white/40 font-mono uppercase font-black tracking-widest">Power Draw</span>
              <Zap className="h-4 w-4 text-yellow-400" />
            </div>
            <div>
              <span className="text-2xl font-black text-white font-mono">{powerDraw}W</span>
              <div className="w-full bg-white/10 h-1 mt-3 overflow-hidden">
                <div
                  className="bg-yellow-400 h-1 transition-all duration-500"
                  style={{ width: `${powerPercent}%` }}
                ></div>
              </div>
            </div>
          </div>
        </div>

        {/* Acceleration speed statistics */}
        <div className="mt-6 p-4 bg-black border border-white/10">
          <h4 className="text-[9px] text-[#FF3E3E] font-mono uppercase tracking-widest mb-4 font-black italic">Model Engine Accelerators</h4>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs font-bold uppercase tracking-wider text-white/70">
            <div className="flex items-center space-x-3 bg-white/5 border border-white/10 p-3">
              <div className="bg-[#FF3E3E] text-black h-6 w-6 flex items-center justify-center font-mono text-[10px] font-black">IPM</div>
              <span>Image Synthesis: <strong className="text-white font-black">{metrics.imagesPerMinute} IMGS/MIN</strong></span>
            </div>
            <div className="flex items-center space-x-3 bg-white/5 border border-white/10 p-3">
              <div className="bg-[#FF3E3E] text-black h-6 w-6 flex items-center justify-center font-mono text-[10px] font-black">FPS</div>
              <span>Video Decoding: <strong className="text-white font-black">{metrics.videoFpsRate} FPS</strong></span>
            </div>
            <div className="flex items-center space-x-3 bg-white/5 border border-white/10 p-3">
              <div className="bg-[#FF3E3E] text-black h-6 w-6 flex items-center justify-center font-mono text-[10px] font-black">LAT</div>
              <span>Inference Latency: <strong className="text-white font-black">{metrics.inferenceLatencyMs} MS</strong></span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

import React from "react";
import { X, Cpu, Sliders, Database, Activity, CheckCircle2, ShieldCheck, HardDrive } from "lucide-react";
import { RuntimeStats } from "../types";

interface RuntimeSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  runtimeStats: RuntimeStats;
  onRefresh: () => void;
}

export const RuntimeSettingsModal: React.FC<RuntimeSettingsModalProps> = ({
  isOpen,
  onClose,
  runtimeStats,
  onRefresh,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 select-none">
      <div className="bg-[#141720] border border-gray-800 rounded-lg w-full max-w-2xl overflow-hidden shadow-2xl font-mono text-xs text-gray-200">

        {/* Modal Header */}
        <div className="bg-[#181c26] px-5 py-3.5 border-b border-gray-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Cpu className="w-4 h-4 text-emerald-400 animate-pulse" />
            <span className="font-bold text-gray-100">LOCAL RUNTIME & AMD RADEON PROOF</span>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-100 p-1 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-6 max-h-[80vh] overflow-y-auto">

          {/* Hardware Hardware Proof Box */}
          <div className="bg-[#0f121a] border border-emerald-500/40 p-4 rounded-lg space-y-3">
            <div className="flex items-center justify-between">
              <span className="font-bold text-emerald-400 flex items-center gap-1.5">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                HARDWARE ACCELERATOR STATUS
              </span>
              <span className="bg-emerald-950 text-emerald-400 px-2 py-0.5 rounded text-[10px] border border-emerald-800 font-bold">
                {runtimeStats.available ? "LOCAL RUNTIME REACHABLE" : "LOCAL RUNTIME UNAVAILABLE"}
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[11px]">
              <div className="bg-[#161a24] p-2.5 rounded border border-gray-800">
                <div className="text-gray-500 text-[10px]">GPU DEVICE</div>
                <div className="font-bold text-gray-100">{runtimeStats.gpuModel || "unknown"}</div>
              </div>

              <div className="bg-[#161a24] p-2.5 rounded border border-gray-800">
                <div className="text-gray-500 text-[10px]">ROCm STACK</div>
                <div className="font-bold text-cyan-400">{runtimeStats.rocmVersion || "unknown"}</div>
              </div>

              <div className="bg-[#161a24] p-2.5 rounded border border-gray-800">
                <div className="text-gray-500 text-[10px]">VRAM USAGE</div>
                <div className="font-bold text-emerald-400">{runtimeStats.vramTotal ? `${runtimeStats.vramUsed} / ${runtimeStats.vramTotal} GiB` : "unavailable"}</div>
              </div>

              <div className="bg-[#161a24] p-2.5 rounded border border-gray-800">
                <div className="text-gray-500 text-[10px]">INFERENCE SPEED</div>
                <div className="font-bold text-amber-400">{runtimeStats.tokenSpeed ? `${runtimeStats.tokenSpeed} tok/s` : "measured per request"}</div>
              </div>
            </div>
          </div>

          {/* Model & Precision Runtime Settings */}
          <div className="space-y-4">
            <div className="text-xs font-bold text-gray-400 flex items-center gap-2 border-b border-gray-800 pb-2">
              <Sliders className="w-4 h-4 text-cyan-400" />
              LOCAL AI MODEL & EMBEDDING CONFIGURATION
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-[11px] text-gray-400">RESIDENT MODEL (READ-ONLY TELEMETRY)</label>
                <div className="w-full bg-[#10131a] border border-gray-700 text-gray-100 rounded p-2 text-xs">
                  {runtimeStats.modelResident || "not reported"}
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[11px] text-gray-400">DTYPE / QUANTIZATION (READ-ONLY)</label>
                <div className="w-full bg-[#10131a] border border-gray-700 text-gray-100 rounded p-2 text-xs">
                  {runtimeStats.precision || runtimeStats.quantization || "not reported"}
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[11px] text-gray-400">LOCAL EMBEDDING MODEL</label>
                <div className="w-full bg-[#10131a] border border-gray-700 text-gray-100 rounded p-2 text-xs">
                  Configured by local indexer (runtime API does not report a model name)
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[11px] text-gray-400">RERANKER MODEL</label>
                <div className="w-full bg-[#10131a] border border-gray-700 text-gray-100 rounded p-2 text-xs">
                  Configured by local indexer (runtime API does not report a model name)
                </div>
              </div>
            </div>
          </div>

          {/* Network Zero-Trust Verification Banner */}
          <div className="bg-[#0e1614] border border-emerald-800/80 p-3 rounded flex items-center justify-between text-[11px] text-emerald-300">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>{runtimeStats.available ? "Local endpoint health confirmed" : runtimeStats.error || "Local endpoint has not been verified"}</span>
            </div>
            <span className="font-bold text-emerald-400">{runtimeStats.externalCalls} external calls reported</span>
          </div>

        </div>

        {/* Modal Footer */}
        <div className="bg-[#181c26] px-5 py-3 border-t border-gray-800 flex justify-end">
          <button
            onClick={onRefresh}
            className="mr-2 bg-cyan-700 hover:bg-cyan-600 text-white font-bold px-4 py-1.5 rounded transition-colors text-xs"
          >
            REFRESH HEALTH
          </button>
          <button
            onClick={onClose}
            className="bg-emerald-500 hover:bg-emerald-400 text-gray-950 font-bold px-4 py-1.5 rounded transition-colors text-xs"
          >
            CONFIRM RUNTIME
          </button>
        </div>

      </div>
    </div>
  );
};

import React from "react";
import { Cpu, ShieldCheck, Zap, Sliders, Activity, Lock, Languages, Sun, Moon } from "lucide-react";
import { RuntimeStats } from "../types";
import { Language, Theme, translations } from "../lib/i18n";

interface HeaderProps {
  runtimeStats: RuntimeStats;
  onOpenRuntimeSettings: () => void;
  activeView: string;
  setActiveView: (view: string) => void;
  lang: Language;
  setLang: (lang: Language) => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

export const Header: React.FC<HeaderProps> = ({
  runtimeStats,
  onOpenRuntimeSettings,
  activeView,
  setActiveView,
  lang,
  setLang,
  theme,
  setTheme,
}) => {
  const t = translations[lang];

  return (
    <header className={`border-b text-xs select-none px-3 sm:px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 transition-colors ${
      theme === 'dark'
        ? "bg-[#101319] border-gray-800 text-gray-200"
        : "bg-white border-gray-200 text-gray-800 shadow-sm"
    }`}>
      {/* Brand & Local Tags */}
      <div className="flex flex-wrap items-center gap-3 w-full xl:w-auto min-w-0">
        <div
          onClick={() => setActiveView("desk")}
          className="flex items-center gap-2 cursor-pointer group"
        >
          <div className="w-7 h-7 rounded bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 font-black font-mono tracking-tighter group-hover:border-emerald-400 transition-colors">
            CC
          </div>
          <span className={`font-bold tracking-wider text-sm font-mono ${
            theme === 'dark' ? "text-gray-100" : "text-gray-900"
          }`}>
            CLAIMCOURT
          </span>
        </div>

        <div className={`h-4 w-[1px] hidden sm:block ${theme === 'dark' ? "bg-gray-800" : "bg-gray-300"}`} />

        {/* Status Pills */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-mono font-medium ${
            theme === 'dark'
              ? "bg-emerald-950/60 text-emerald-400 border border-emerald-800/60"
              : "bg-emerald-50 text-emerald-700 border border-emerald-200"
          }`}>
            <Lock className="w-3 h-3 text-emerald-500" />
            {t.localOnly}
          </span>
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-mono font-medium ${
            theme === 'dark'
              ? "bg-cyan-950/60 text-cyan-400 border border-cyan-800/60"
              : "bg-cyan-50 text-cyan-700 border border-cyan-200"
          }`}>
            <Cpu className="w-3 h-3 text-cyan-500" />
            {runtimeStats.available ? t.radeonReady : (lang === "zh" ? "本地运行时未连接" : "LOCAL RUNTIME OFFLINE")}
          </span>
          <span className={`hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-mono ${
            theme === 'dark'
              ? "bg-gray-800/80 text-gray-300 border border-gray-700/60"
              : "bg-gray-100 text-gray-600 border border-gray-300"
          }`}>
            ROCm {runtimeStats.rocmVersion}
          </span>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className={`flex items-center gap-1 p-1 rounded-lg border font-mono text-[11px] max-w-full overflow-x-auto ${
        theme === 'dark'
          ? "bg-[#161a23] border-gray-800"
          : "bg-gray-100 border-gray-300"
      }`}>
        <button
          onClick={() => setActiveView("desk")}
          className={`px-3 py-1 rounded transition-all ${
            activeView === "desk"
              ? theme === 'dark' ? "bg-gray-800 text-emerald-400 font-medium shadow-sm" : "bg-white text-emerald-600 font-semibold shadow-sm"
              : theme === 'dark' ? "text-gray-400 hover:text-gray-200" : "text-gray-600 hover:text-gray-900"
          }`}
        >
          {t.caseDesk}
        </button>
        <button
          onClick={() => setActiveView("intent")}
          className={`px-3 py-1 rounded transition-all ${
            activeView === "intent"
              ? theme === 'dark' ? "bg-gray-800 text-cyan-400 font-medium shadow-sm" : "bg-white text-cyan-600 font-semibold shadow-sm"
              : theme === 'dark' ? "text-gray-400 hover:text-gray-200" : "text-gray-600 hover:text-gray-900"
          }`}
        >
          {t.intent}
        </button>
        <button
          onClick={() => setActiveView("evidence")}
          className={`px-3 py-1 rounded transition-all ${
            activeView === "evidence"
              ? theme === 'dark' ? "bg-gray-800 text-cyan-400 font-medium shadow-sm" : "bg-white text-cyan-600 font-semibold shadow-sm"
              : theme === 'dark' ? "text-gray-400 hover:text-gray-200" : "text-gray-600 hover:text-gray-900"
          }`}
        >
          {t.evidence}
        </button>
        <button
          onClick={() => setActiveView("court")}
          className={`px-3 py-1 rounded transition-all ${
            activeView === "court"
              ? theme === 'dark' ? "bg-gray-800 text-amber-400 font-medium shadow-sm" : "bg-white text-amber-600 font-semibold shadow-sm"
              : theme === 'dark' ? "text-gray-400 hover:text-gray-200" : "text-gray-600 hover:text-gray-900"
          }`}
        >
          {t.courtroom}
        </button>
        <button
          onClick={() => setActiveView("security")}
          className={`px-3 py-1 rounded transition-all ${
            activeView === "security"
              ? theme === 'dark' ? "bg-gray-800 text-red-400 font-medium shadow-sm" : "bg-white text-red-600 font-semibold shadow-sm"
              : theme === 'dark' ? "text-gray-400 hover:text-gray-200" : "text-gray-600 hover:text-gray-900"
          }`}
        >
          {t.security}
        </button>
      </div>

      {/* Controls & GPU Telemetry */}
      <div className="flex items-center gap-2">
        {/* Language Switcher */}
        <button
          onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded border text-[11px] font-mono transition-colors ${
            theme === 'dark'
              ? "bg-[#161a22] hover:bg-[#1f2430] border-gray-800 text-gray-300"
              : "bg-gray-100 hover:bg-gray-200 border-gray-300 text-gray-700"
          }`}
          title="Switch Language / 切换语言"
        >
          <Languages className="w-3.5 h-3.5 text-cyan-500" />
          <span className="font-semibold">{lang === 'zh' ? '中文' : 'EN'}</span>
        </button>

        {/* Theme Switcher */}
        <button
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          className={`p-1.5 rounded border transition-colors ${
            theme === 'dark'
              ? "bg-[#161a22] hover:bg-[#1f2430] border-gray-800 text-amber-400"
              : "bg-gray-100 hover:bg-gray-200 border-gray-300 text-indigo-600"
          }`}
          title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
        >
          {theme === 'dark' ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
        </button>

        {/* Telemetry Button */}
        <button
          onClick={onOpenRuntimeSettings}
          className={`flex items-center gap-2 px-2.5 py-1 rounded border text-[11px] font-mono group transition-colors ${
            theme === 'dark'
              ? "bg-[#161a22] hover:bg-[#1f2430] border-gray-800 text-gray-300"
              : "bg-gray-100 hover:bg-gray-200 border-gray-300 text-gray-700"
          }`}
          title="Click for AMD Radeon Runtime Details"
        >
          <Activity className="w-3.5 h-3.5 text-emerald-500 animate-pulse" />
          <span className="hidden md:inline text-gray-500">{runtimeStats.gpuModel || "GPU unknown"} •</span>
          <span className="text-emerald-500 font-semibold">{runtimeStats.tokenSpeed ? `${runtimeStats.tokenSpeed} tok/s` : "speed n/a"}</span>
          <span className="text-gray-400">•</span>
          <span className="text-cyan-500">{runtimeStats.externalCalls} external calls</span>
          <Sliders className="w-3.5 h-3.5 text-gray-400 group-hover:text-gray-600 transition-colors ml-0.5" />
        </button>
      </div>
    </header>
  );
};

import React, { useEffect, useState } from "react";
import {
  Search,
  Play,
  Cpu,
  ArrowRight,
  CheckCircle2,
  FileSearch,
  Scale,
  ShieldCheck,
  Sparkles,
  RefreshCw,
  Clock,
  Layers
} from "lucide-react";
import { CaseData } from "../types";
import { Language, Theme, translations } from "../lib/i18n";

interface CaseDeskProps {
  caseData: CaseData;
  onRunInvestigation: (query: string) => void;
  onSelectPresetCase: (presetKey: string) => void;
  onRetrievalFeedback: (selectedSourcePath: string | null, relevant: boolean) => Promise<void>;
  isInvestigating: boolean;
  setActiveView: (view: string) => void;
  lang: Language;
  theme: Theme;
}

export const CaseDesk: React.FC<CaseDeskProps> = ({
  caseData,
  onRunInvestigation,
  onSelectPresetCase,
  onRetrievalFeedback,
  isInvestigating,
  setActiveView,
  lang,
  theme,
}) => {
  const [queryInput, setQueryInput] = useState(caseData.query);
  const [feedbackState, setFeedbackState] = useState<string>("");
  const t = translations[lang];
  const runtime = caseData.runtime;
  const runtimeLabel = runtime?.available
    ? (String(runtime.modelResident || "").includes("(not loaded)") ? "LOCAL RUNTIME REACHABLE" : "LOCAL RUNTIME READY")
    : "LOCAL RUNTIME UNAVAILABLE";
  const runtimeDetail = [runtime?.rocmVersion, runtime?.gpuModel]
    .filter((value) => value && value !== "unknown")
    .join(" • ") || "ROCm / GPU telemetry unavailable";
  const externalCallLabel = `${runtime?.externalCalls ?? 0} external calls • local API boundary`;
  const firstEvidence = caseData.evidenceList[0];
  const evidenceSourceCount = new Set(
    caseData.evidenceList.map((item) => item.sourcePath || item.filename),
  ).size;
  const visibleFileMatches = caseData.retrievalDecision?.status === "multiple_matches"
    ? (caseData.fileMatches || []).slice(0, 24)
    : (caseData.fileMatches || []).slice(0, 3);

  useEffect(() => {
    setQueryInput(caseData.query);
    setFeedbackState("");
  }, [caseData.id, caseData.query]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (queryInput.trim()) {
      onRunInvestigation(queryInput.trim());
    }
  };

  return (
    <div className={`w-full max-w-full flex-1 min-w-0 p-3 sm:p-6 overflow-y-auto overflow-x-hidden space-y-4 sm:space-y-6 select-none transition-colors ${
      theme === 'dark'
        ? "bg-[#12151c] text-gray-200"
        : "bg-gray-100 text-gray-900"
    }`}>

      {/* Top Case Header */}
      <div className={`flex flex-wrap items-center justify-between gap-3 border-b pb-3 ${
        theme === 'dark' ? "border-gray-800" : "border-gray-300"
      }`}>
        <div>
          <div className="text-[10px] font-mono text-emerald-500 font-semibold tracking-wider uppercase flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            {t.activeInvestigationDesk}
          </div>
          <h1 className={`text-lg font-bold font-mono mt-0.5 ${
            theme === 'dark' ? "text-gray-100" : "text-gray-900"
          }`}>
            {caseData.title}
          </h1>
        </div>
        <div className="w-full sm:w-auto max-w-full text-left sm:text-right text-xs font-mono text-gray-500 break-words">
          <div>STATUS: <span className={`font-semibold ${runtime?.available ? "text-emerald-500" : "text-amber-400"}`}>{runtimeLabel}</span></div>
          <div className="text-[10px] text-gray-400">{runtimeDetail}</div>
        </div>
      </div>

      {/* Main Core Search Card */}
      <div className={`w-full max-w-full border rounded-lg p-3 sm:p-5 space-y-4 shadow-xl transition-colors ${
        theme === 'dark'
          ? "bg-[#181c26] border-gray-800 text-gray-200"
          : "bg-white border-gray-300 text-gray-900 shadow-md"
      }`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label className={`text-xs font-mono font-semibold flex items-center gap-2 ${
            theme === 'dark' ? "text-gray-300" : "text-gray-800"
          }`}>
            <Search className="w-4 h-4 text-emerald-500" />
            {t.whatToInvestigate}
          </label>
          <span className="hidden sm:inline text-[11px] font-mono text-gray-400">
            {externalCallLabel}
          </span>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="relative">
            <textarea
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              placeholder={lang === 'zh' ? "您想要证明、查找或核实什么？(例如：供应商是否在合同中承诺了 99.9% 的可用性？)" : "What do you want to prove, find, or verify?"}
              rows={3}
              className={`w-full max-w-full min-w-0 border rounded-md p-3.5 text-sm font-sans resize-none outline-none transition-all ${
                theme === 'dark'
                  ? "bg-[#10131a] border-gray-700/80 focus:border-emerald-500 text-gray-100 placeholder-gray-500"
                  : "bg-gray-50 border-gray-300 focus:border-emerald-500 text-gray-900 placeholder-gray-400"
              }`}
            />
          </div>

          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="w-full lg:w-auto grid grid-cols-2 lg:flex lg:items-center gap-2 text-xs">
              <span className="col-span-2 lg:col-span-1 text-gray-500 font-mono text-[11px]">{t.quickDemos}</span>
              <button
                type="button"
                onClick={() => {
                  onSelectPresetCase("sla-review");
                  setQueryInput("供应商是否在合同中承诺了 99.9% 的可用性？");
                }}
                className={`w-full lg:w-auto px-2.5 py-1 rounded text-xs transition-colors font-medium border ${
                  theme === 'dark'
                    ? "bg-[#202634] hover:bg-[#283042] text-emerald-300 border-emerald-500/30"
                    : "bg-emerald-50 hover:bg-emerald-100 text-emerald-800 border-emerald-200"
                }`}
              >
                {t.contractReviewBtn}
              </button>
              <button
                type="button"
                onClick={() => {
                  onSelectPresetCase("fuzzy-memory");
                  setQueryInput("找回关于操作系统进程调度算法的实验报告文件");
                }}
                className={`w-full lg:w-auto px-2.5 py-1 rounded text-xs transition-colors font-medium border ${
                  theme === 'dark'
                    ? "bg-[#202634] hover:bg-[#283042] text-cyan-300 border-cyan-500/30"
                    : "bg-cyan-50 hover:bg-cyan-100 text-cyan-800 border-cyan-200"
                }`}
              >
                {t.fuzzyMemoryBtn}
              </button>
              <button
                type="button"
                onClick={() => {
                  onSelectPresetCase("sensitive-credentials");
                  setQueryInput("定位本地代码与配置文件中的敏感凭证与密钥");
                }}
                className={`w-full lg:w-auto px-2.5 py-1 rounded text-xs transition-colors font-medium border ${
                  theme === 'dark'
                    ? "bg-[#202634] hover:bg-[#283042] text-red-300 border-red-500/30"
                    : "bg-red-50 hover:bg-red-100 text-red-800 border-red-200"
                }`}
              >
                {t.credentialLeakBtn}
              </button>
            </div>

            <button
              type="submit"
              disabled={isInvestigating}
              className="w-full sm:w-auto justify-center bg-emerald-500 hover:bg-emerald-400 text-gray-950 font-mono font-bold px-5 py-2.5 rounded-md flex items-center gap-2 transition-all shadow-lg disabled:opacity-50 text-xs tracking-wide"
            >
              {isInvestigating ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin text-gray-950" />
                  {t.analyzingOnRadeon}
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-current" />
                  {t.runPrivateInvestigation}
                </>
              )}
            </button>
          </div>
        </form>
      </div>

      {/* Pipeline Bar */}
      <div className={`border rounded-lg p-4 font-mono text-xs ${
        theme === 'dark' ? "bg-[#141720] border-gray-800" : "bg-white border-gray-300"
      }`}>
        <div className="text-[10px] text-gray-500 font-semibold mb-3 tracking-widest uppercase">
          {t.pipelineTitle}
        </div>
        <div className="grid grid-cols-2 sm:flex sm:items-center sm:justify-between text-center gap-2">
          <div className={`w-full sm:flex-1 min-w-0 p-2.5 rounded border font-semibold flex flex-col items-center gap-1 ${
            theme === 'dark' ? "bg-[#1b202c] border-emerald-500/40 text-emerald-400" : "bg-emerald-50 border-emerald-300 text-emerald-800"
          }`}>
            <span className="text-[10px] text-gray-400">STAGE 1</span>
            <span>{t.stage1}</span>
          </div>

          <ArrowRight className="hidden sm:block w-4 h-4 text-gray-400 shrink-0" />

          <div className={`w-full sm:flex-1 min-w-0 p-2.5 rounded border font-semibold flex flex-col items-center gap-1 ${
            theme === 'dark' ? "bg-[#1b202c] border-cyan-500/40 text-cyan-400" : "bg-cyan-50 border-cyan-300 text-cyan-800"
          }`}>
            <span className="text-[10px] text-gray-400">STAGE 2</span>
            <span>{t.stage2}</span>
          </div>

          <ArrowRight className="hidden sm:block w-4 h-4 text-gray-400 shrink-0" />

          <div className={`w-full sm:flex-1 min-w-0 p-2.5 rounded border font-semibold flex flex-col items-center gap-1 ${
            theme === 'dark' ? "bg-[#1b202c] border-amber-500/40 text-amber-400" : "bg-amber-50 border-amber-300 text-amber-800"
          }`}>
            <span className="text-[10px] text-gray-400">STAGE 3</span>
            <span>{t.stage3}</span>
          </div>

          <ArrowRight className="hidden sm:block w-4 h-4 text-gray-400 shrink-0" />

          <div className={`w-full sm:flex-1 min-w-0 p-2.5 rounded border font-semibold flex flex-col items-center gap-1 ${
            theme === 'dark' ? "bg-[#1b202c] border-gray-700 text-gray-300" : "bg-gray-100 border-gray-300 text-gray-800"
          }`}>
            <span className="text-[10px] text-gray-400">STAGE 4</span>
            <span>{t.stage4}</span>
          </div>
        </div>
      </div>

      {/* Real-time Cards */}
      {caseData.fileMatches && caseData.fileMatches.length > 0 && (
        <section className={`border rounded-lg p-4 space-y-3 ${
          theme === 'dark' ? "bg-[#141720] border-gray-800" : "bg-white border-gray-300 shadow-sm"
        }`}>
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-xs font-mono font-bold text-cyan-500">RETRIEVAL DECISION</div>
              <div className="text-xs text-gray-500 mt-1">
                {caseData.retrievalDecision?.status || "ranked candidates"} • {caseData.retrievalDecision?.reason}
              </div>
            </div>
            {feedbackState && <span className="text-xs text-emerald-500 font-mono">{feedbackState}</span>}
          </div>
          <div className="space-y-2">
            {visibleFileMatches.map((match, index) => (
              <div key={match.sourcePath} className={`flex flex-col sm:flex-row sm:items-center justify-between gap-3 border rounded p-3 ${
                theme === 'dark' ? "border-gray-800 bg-[#181c26]" : "border-gray-200 bg-gray-50"
              }`}>
                <div className="min-w-0">
                  <div className="text-sm font-semibold truncate">{index + 1}. {match.source}</div>
                  <div className="text-[11px] font-mono text-gray-500">score {match.score.toFixed(3)} • confidence {Math.round(match.confidence * 100)}%</div>
                  {match.duplicatePaths.length > 0 && (
                    <div className="text-[10px] font-mono text-amber-500 mt-1">
                      {lang === "zh" ? `已归并 ${match.duplicatePaths.length} 个重复或替代版本` : `${match.duplicatePaths.length} duplicate or alternate version(s) grouped`}
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  title={lang === "zh" ? "将该文件记录为正确结果" : "Record this file as the correct result"}
                  onClick={async () => {
                    await onRetrievalFeedback(match.sourcePath, true);
                    setFeedbackState(lang === "zh" ? "已保存本地反馈" : "Local feedback saved");
                  }}
                  className="w-full sm:w-auto shrink-0 inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded border border-emerald-700 text-emerald-500 hover:bg-emerald-950/40 text-xs"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  {lang === "zh" ? "这是正确文件" : "Correct file"}
                </button>
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={async () => {
              await onRetrievalFeedback(null, false);
              setFeedbackState(lang === "zh" ? "已记录候选均不正确" : "No relevant candidate recorded");
            }}
            className="text-xs text-gray-500 hover:text-amber-500 underline underline-offset-4"
          >
            {lang === "zh" ? "这些候选都不正确" : "None of these candidates are correct"}
          </button>
        </section>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

        {/* Card 1: Intent Compiled */}
        <div
          onClick={() => setActiveView("intent")}
          className={`border p-4 rounded-lg cursor-pointer transition-all space-y-2 group ${
            theme === 'dark'
              ? "bg-[#181c26] border-gray-800 hover:border-emerald-500/50"
              : "bg-white border-gray-300 hover:border-emerald-500 shadow-sm"
          }`}
        >
          <div className="flex items-center justify-between text-xs font-mono text-gray-400">
            <span className="font-bold text-emerald-500 group-hover:underline">{t.intentCompiled}</span>
            <span className={`px-1.5 py-0.5 rounded text-[10px] border ${
              theme === 'dark' ? "bg-emerald-950 text-emerald-400 border-emerald-800" : "bg-emerald-100 text-emerald-800 border-emerald-300"
            }`}>
              Compiled ({caseData.intent.confidence}%)
            </span>
          </div>
          <div className={`text-sm font-semibold line-clamp-1 font-mono ${
            theme === 'dark' ? "text-gray-200" : "text-gray-900"
          }`}>
            {caseData.intent.intentType}
          </div>
          <div className="text-xs text-gray-500 truncate">
            Topics: {caseData.intent.topics.join(", ")}
          </div>
          <div className="text-[10px] text-emerald-500 font-mono flex items-center gap-1 pt-1">
            Click to inspect compiler trajectory →
          </div>
        </div>

        {/* Card 2: Evidence Sources */}
        <div
          onClick={() => setActiveView("evidence")}
          className={`border p-4 rounded-lg cursor-pointer transition-all space-y-2 group ${
            theme === 'dark'
              ? "bg-[#181c26] border-gray-800 hover:border-cyan-500/50"
              : "bg-white border-gray-300 hover:border-cyan-500 shadow-sm"
          }`}
        >
          <div className="flex items-center justify-between text-xs font-mono text-gray-400">
            <span className="font-bold text-cyan-500 group-hover:underline">{t.evidenceSources}</span>
            <span className={`px-1.5 py-0.5 rounded text-[10px] border ${
              theme === 'dark' ? "bg-cyan-950 text-cyan-400 border-cyan-800" : "bg-cyan-100 text-cyan-800 border-cyan-300"
            }`}>
              {evidenceSourceCount} {evidenceSourceCount === 1 ? "source" : "sources"}
            </span>
          </div>
          <div className={`text-sm font-semibold line-clamp-1 font-mono ${
            theme === 'dark' ? "text-gray-200" : "text-gray-900"
          }`}>
            {caseData.evidenceList[0]?.filename || "Local Evidence Packet"}
          </div>
          <div className="text-xs text-gray-500 flex items-center gap-2">
            <span>{firstEvidence ? `Page ${firstEvidence.page}` : "No page selected"}</span>
            <span>•</span>
            <span className={`font-semibold ${firstEvidence?.hashVerified ? "text-emerald-500" : "text-amber-400"}`}>
              {firstEvidence ? (firstEvidence.hashVerified ? "SHA-256 Verified" : "SHA-256 Unverified") : "Awaiting evidence"}
            </span>
          </div>
          <div className="text-[10px] text-cyan-500 font-mono flex items-center gap-1 pt-1">
            Click to open source viewer →
          </div>
        </div>

        {/* Card 3: Judge Verdict */}
        <div
          onClick={() => setActiveView("court")}
          className={`border p-4 rounded-lg cursor-pointer transition-all space-y-2 group ${
            theme === 'dark'
              ? "bg-[#181c26] border-gray-800 hover:border-amber-500/50"
              : "bg-white border-gray-300 hover:border-amber-500 shadow-sm"
          }`}
        >
          <div className="flex items-center justify-between text-xs font-mono text-gray-400">
            <span className="font-bold text-amber-500 group-hover:underline">{t.judgeVerdict}</span>
            <span className={`px-1.5 py-0.5 rounded text-[10px] border font-bold ${
              theme === 'dark' ? "bg-amber-950 text-amber-400 border-amber-800" : "bg-amber-100 text-amber-800 border-amber-300"
            }`}>
              {caseData.courtroom.verdictStatus}
            </span>
          </div>
          <div className={`text-sm font-semibold line-clamp-1 ${
            theme === 'dark' ? "text-gray-100" : "text-gray-900"
          }`}>
            {caseData.courtroom.verdictTitle}
          </div>
          <div className="text-xs text-gray-500">
            Confidence: {caseData.courtroom.confidence}% • {caseData.courtroom.citedEvidence.length} Citations
          </div>
          <div className="text-[10px] text-amber-500 font-mono flex items-center gap-1 pt-1">
            Click to enter courtroom →
          </div>
        </div>

      </div>

      {/* Case Overview Summary */}
      <div className={`border rounded-lg p-4 font-mono space-y-3 ${
        theme === 'dark' ? "bg-[#141720] border-gray-800" : "bg-white border-gray-300 shadow-sm"
      }`}>
        <div className={`flex items-center justify-between border-b pb-2 ${
          theme === 'dark' ? "border-gray-800" : "border-gray-200"
        }`}>
          <span className="text-xs font-semibold text-gray-500">{t.currentSummary}</span>
          <span className="text-[11px] text-emerald-500">
            {runtime?.available ? `${runtime.tokenSpeed ? `${runtime.tokenSpeed} tok/s` : "local runtime reachable"} • ${externalCallLabel}` : "Local runtime telemetry unavailable"}
          </span>
        </div>
        <div className={`text-xs leading-relaxed font-sans ${
          theme === 'dark' ? "text-gray-300" : "text-gray-700"
        }`}>
          {caseData.courtroom.verdictSubtitle}
        </div>
      </div>

    </div>
  );
};

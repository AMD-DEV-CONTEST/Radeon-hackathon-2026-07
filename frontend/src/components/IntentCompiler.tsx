import React from "react";
import { Cpu, ArrowDown, Sparkles, Code2, Layers, CheckCircle2, ShieldCheck } from "lucide-react";
import { CaseData } from "../types";
import { Language, Theme, translations } from "../lib/i18n";

interface IntentCompilerProps {
  caseData: CaseData;
  setActiveView: (view: string) => void;
  lang: Language;
  theme: Theme;
}

export const IntentCompiler: React.FC<IntentCompilerProps> = ({
  caseData,
  setActiveView,
  lang,
  theme,
}) => {
  const { intent } = caseData;
  const t = translations[lang];
  const runtime = caseData.runtime;
  const routeLabel = caseData.route || "not routed";
  const searchScope = intent.searchScope?.join(", ") || "indexed workspace";
  const expandedTerms = intent.expandedTerms?.slice(0, 8).join(", ") || intent.topics.join(", ") || "none";

  return (
    <div className={`flex-1 p-6 overflow-y-auto space-y-6 select-none transition-colors ${
      theme === 'dark' ? "bg-[#11141b] text-gray-200" : "bg-gray-100 text-gray-900"
    }`}>

      {/* Header */}
      <div className={`flex items-center justify-between border-b pb-3 font-mono ${
        theme === 'dark' ? "border-gray-800" : "border-gray-300"
      }`}>
        <div>
          <div className="text-[10px] text-cyan-500 font-semibold uppercase tracking-wider flex items-center gap-2">
            <Cpu className="w-3.5 h-3.5 text-cyan-500" />
            {t.intentCompilerEngine}
          </div>
          <h1 className={`text-lg font-bold mt-0.5 ${
            theme === 'dark' ? "text-gray-100" : "text-gray-900"
          }`}>
            {t.fuzzyMemoryCompiledTitle}
          </h1>
        </div>
        <div className="text-right text-xs text-gray-500">
          <div>{t.compiledBy} <span className="text-cyan-500 font-bold">{intent.compiler || "deterministic local compiler"}</span></div>
          <div className="text-[10px] text-emerald-500">
            {runtime?.externalCalls ?? 0} EXTERNAL API CALLS • {runtime?.modelResident || "MODEL UNREPORTED"}
          </div>
        </div>
      </div>

      {/* Visual Trajectory Track */}
      <div className={`border rounded-lg p-5 space-y-4 ${
        theme === 'dark' ? "bg-[#181c26] border-cyan-500/30" : "bg-white border-cyan-300 shadow-sm"
      }`}>
        <div className="text-xs font-mono font-semibold text-cyan-500 flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-cyan-500" />
          NATURAL LANGUAGE TO STRUCTURED INTENT TRAJECTORY
        </div>

        <div className="flex flex-col items-center justify-center space-y-3 py-2 font-mono text-xs max-w-xl mx-auto">
          {/* Step 1 */}
          <div className={`w-full border p-3 rounded text-center ${
            theme === 'dark' ? "bg-[#10131a] border-gray-700/80" : "bg-gray-50 border-gray-300"
          }`}>
            <div className="text-[10px] text-gray-500 font-bold">{t.humanInput}</div>
            <div className={`text-sm font-semibold mt-1 font-sans ${
              theme === 'dark' ? "text-gray-200" : "text-gray-900"
            }`}>
              "{caseData.query}"
            </div>
          </div>

          <ArrowDown className="w-4 h-4 text-cyan-500 animate-bounce" />

          {/* Step 2 */}
          <div className={`w-full border p-3 rounded text-center ${
            theme === 'dark' ? "bg-[#131926] border-cyan-500/40 text-cyan-300" : "bg-cyan-50 border-cyan-300 text-cyan-900"
          }`}>
            <div className="text-[10px] text-cyan-500 font-bold">{t.extractedTopics}</div>
            <div className="text-xs font-medium mt-1">
              Topics: [{intent.topics.join(", ")}] • Artifact: [{intent.artifact}]
            </div>
          </div>

          <ArrowDown className="w-4 h-4 text-cyan-500" />

          {/* Step 3 */}
          <div className={`w-full border p-3 rounded text-center ${
            theme === 'dark' ? "bg-[#0e1f26] border-emerald-500/50 text-emerald-400" : "bg-emerald-50 border-emerald-300 text-emerald-900"
          }`}>
            <div className="text-[10px] text-emerald-500 font-bold">{t.rocmVectorMatch}</div>
            <div className="text-xs font-semibold mt-1">
              ROUTE: {routeLabel} · SCOPE: {searchScope} · TERMS: {expandedTerms}
            </div>
          </div>
        </div>
      </div>

      {/* Structured Intent Parameters Box */}
      <div className={`border rounded-lg p-5 font-mono space-y-4 ${
        theme === 'dark' ? "bg-[#181c26] border-gray-800" : "bg-white border-gray-300 shadow-sm"
      }`}>
        <div className={`flex items-center justify-between border-b pb-3 ${
          theme === 'dark' ? "border-gray-800" : "border-gray-200"
        }`}>
          <span className={`text-xs font-bold flex items-center gap-2 ${
            theme === 'dark' ? "text-gray-300" : "text-gray-800"
          }`}>
            <Code2 className="w-4 h-4 text-cyan-500" />
            {t.compiledDataMatrix}
          </span>
          <span className={`px-2 py-0.5 rounded text-xs border ${
            theme === 'dark' ? "bg-emerald-950 text-emerald-400 border-emerald-800" : "bg-emerald-100 text-emerald-800 border-emerald-300"
          }`}>
            Confidence {intent.confidence}%
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
          <div className={`p-3 rounded border space-y-1 ${
            theme === 'dark' ? "bg-[#10131a] border-gray-800" : "bg-gray-50 border-gray-200"
          }`}>
            <div className="text-[10px] text-gray-500 font-bold">{t.intentType}</div>
            <div className="text-emerald-500 font-bold text-sm">{intent.intentType}</div>
          </div>

          <div className={`p-3 rounded border space-y-1 ${
            theme === 'dark' ? "bg-[#10131a] border-gray-800" : "bg-gray-50 border-gray-200"
          }`}>
            <div className="text-[10px] text-gray-500 font-bold">{t.artifactCategory}</div>
            <div className="text-cyan-500 font-bold text-sm">{intent.artifact}</div>
          </div>

          <div className={`p-3 rounded border space-y-1 md:col-span-2 ${
            theme === 'dark' ? "bg-[#10131a] border-gray-800" : "bg-gray-50 border-gray-200"
          }`}>
            <div className="text-[10px] text-gray-500 font-bold">{t.extractedTopicsLabel}</div>
            <div className="flex flex-wrap gap-1.5 mt-1">
              {intent.topics.map((tp, idx) => (
                <span key={idx} className={`px-2 py-0.5 rounded text-xs border ${
                  theme === 'dark' ? "bg-gray-800 text-gray-200 border-gray-700" : "bg-gray-200 text-gray-800 border-gray-300"
                }`}>
                  #{tp}
                </span>
              ))}
            </div>
          </div>

          <div className={`p-3 rounded border space-y-1 md:col-span-2 ${
            theme === 'dark' ? "bg-[#10131a] border-gray-800" : "bg-gray-50 border-gray-200"
          }`}>
            <div className="text-[10px] text-gray-500 font-bold">{t.memoryReasoningClues}</div>
            <div className={`font-sans text-xs leading-relaxed ${
              theme === 'dark' ? "text-gray-300" : "text-gray-700"
            }`}>{intent.memoryClues}</div>
          </div>

          <div className={`p-3 rounded border space-y-1 md:col-span-2 ${
            theme === 'dark' ? "bg-[#10131a] border-gray-800" : "bg-gray-50 border-gray-200"
          }`}>
            <div className="text-[10px] text-gray-500 font-bold">{t.semanticRelations}</div>
            <div className={`font-sans text-xs leading-relaxed ${
              theme === 'dark' ? "text-gray-300" : "text-gray-700"
            }`}>{intent.relation}</div>
          </div>
        </div>

        <div className="pt-2 flex justify-end">
          <button
            onClick={() => setActiveView("evidence")}
            className="bg-cyan-600 hover:bg-cyan-500 text-white font-bold px-4 py-2 rounded text-xs transition-colors flex items-center gap-2"
          >
            {t.proceedToEvidence}
          </button>
        </div>
      </div>

    </div>
  );
};

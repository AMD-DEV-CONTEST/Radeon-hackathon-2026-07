import React, { useEffect, useState } from "react";
import {
  FileText,
  CheckCircle2,
  ShieldCheck,
  ExternalLink,
  Search,
  Hash,
  Layers,
  Lock,
  Bookmark,
  FileCode
} from "lucide-react";
import { CaseData, EvidenceItem, RuntimeStats } from "../types";
import { Language, Theme, translations } from "../lib/i18n";

interface EvidenceRoomProps {
  caseData: CaseData;
  selectedEvidenceId?: string;
  onSelectEvidence?: (id: string) => void;
  setActiveView: (view: string) => void;
  lang: Language;
  theme: Theme;
  runtimeStats?: RuntimeStats;
}

export const EvidenceRoom: React.FC<EvidenceRoomProps> = ({
  caseData,
  selectedEvidenceId,
  onSelectEvidence,
  setActiveView,
  lang,
  theme,
  runtimeStats,
}) => {
  const [activeItemId, setActiveItemId] = useState(selectedEvidenceId || caseData.evidenceList[0]?.id || "");
  const t = translations[lang];
  const activeItem = caseData.evidenceList.find((e) => e.id === activeItemId) || caseData.evidenceList[0];

  useEffect(() => {
    setActiveItemId(selectedEvidenceId || caseData.evidenceList[0]?.id || "");
  }, [caseData.id, selectedEvidenceId, caseData.evidenceList]);

  const handleSelect = (item: EvidenceItem) => {
    setActiveItemId(item.id);
    if (onSelectEvidence) onSelectEvidence(item.id);
  };

  if (!activeItem) {
    return (
      <div className={`flex-1 flex items-center justify-center p-8 text-center font-mono text-sm ${theme === 'dark' ? 'bg-[#10131a] text-gray-500' : 'bg-gray-100 text-gray-600'}`}>
        <div className="max-w-md space-y-3">
          <Layers className="w-8 h-8 text-cyan-500 mx-auto" />
          <div className="text-cyan-500 font-bold">{t.evidenceAndSourceViewer}</div>
          <div>Index a private workspace or upload a supported document before opening the evidence room.</div>
        </div>
      </div>
    );
  }

  return (
    <div className={`flex-1 flex flex-col h-full overflow-hidden select-none transition-colors ${
      theme === 'dark' ? "bg-[#10131a] text-gray-200" : "bg-gray-100 text-gray-900"
    }`}>

      {/* Top Header */}
      <div className={`px-6 py-3 flex items-center justify-between font-mono text-xs border-b ${
        theme === 'dark' ? "bg-[#141720] border-gray-800" : "bg-white border-gray-300"
      }`}>
        <div className="flex items-center gap-3">
          <Layers className="w-4 h-4 text-cyan-500" />
          <span className={`font-bold ${theme === 'dark' ? "text-gray-100" : "text-gray-900"}`}>{t.evidenceRoomHeader}</span>
          <span className={`px-2 py-0.5 rounded text-[11px] ${
            theme === 'dark' ? "bg-gray-800 text-cyan-400" : "bg-cyan-100 text-cyan-800"
          }`}>
            {caseData.evidenceList.length} {t.indexedSources}
          </span>
        </div>
        <div className="text-gray-500 text-[11px]">
          SHA-256 INTEGRITY: <span className="text-emerald-500 font-bold">{caseData.evidenceList.every((item) => item.hashVerified) ? "ALL VERIFIED" : "PARTIAL / UNVERIFIED"}</span>
        </div>
      </div>

      {/* Split View Container */}
      <div className="flex-1 flex overflow-hidden">

        {/* Left Side: EVIDENCE PACKET */}
        <div className={`w-80 border-r overflow-y-auto p-3 space-y-2 font-mono text-xs ${
          theme === 'dark' ? "bg-[#12151d] border-gray-800" : "bg-gray-50 border-gray-200"
        }`}>
          <div className="text-[10px] text-gray-500 font-bold tracking-wider uppercase px-2 py-1 flex items-center justify-between">
            <span>{t.evidencePacket}</span>
            <span>RELEVANCE</span>
          </div>

          {caseData.evidenceList.map((item) => {
            const isSelected = activeItem.id === item.id;
            return (
              <div
                key={item.id}
                onClick={() => handleSelect(item)}
                className={`p-3 rounded-lg cursor-pointer border transition-all space-y-1.5 ${
                  isSelected
                    ? theme === 'dark'
                      ? "bg-[#1d2331] border-cyan-500 shadow-md text-gray-100"
                      : "bg-cyan-50 border-cyan-500 shadow-sm text-cyan-950 font-medium"
                    : theme === 'dark'
                      ? "bg-[#161a24] border-gray-800 hover:border-gray-700 text-gray-400 hover:text-gray-200"
                      : "bg-white border-gray-200 hover:border-gray-300 text-gray-600 hover:text-gray-900"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-cyan-500 shrink-0" />
                    <span className="font-bold text-cyan-500 text-xs">{item.id}</span>
                  </div>
                  <span
                    className={`px-1.5 py-0.2 rounded text-[9px] uppercase font-bold ${
                      item.status === "signed"
                        ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                        : "bg-amber-100 text-amber-800 border border-amber-300"
                    }`}
                  >
                    {item.status}
                  </span>
                </div>

                <div className={`font-semibold text-xs truncate font-sans ${
                  theme === 'dark' ? "text-gray-200" : "text-gray-800"
                }`}>
                  {item.filename}
                </div>

                <div className="flex items-center justify-between text-[10px] text-gray-500">
                  <span>Page {item.page}</span>
                  <span className="text-cyan-500 font-bold">{(item.score * 100).toFixed(0)}% Match</span>
                </div>

                <div className={`text-[9px] flex items-center gap-1 pt-0.5 ${item.hashVerified ? "text-emerald-500" : "text-amber-400"}`}>
                  <CheckCircle2 className={`w-3 h-3 ${item.hashVerified ? "text-emerald-500" : "text-amber-400"}`} />
                  <span>{item.hashVerified ? "SHA-256 verified" : "SHA-256 unverified"}</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Right Side: SOURCE VIEWER */}
        <div className={`flex-1 overflow-y-auto p-6 font-sans flex flex-col space-y-4 ${
          theme === 'dark' ? "bg-[#161a24]" : "bg-white"
        }`}>

          {/* Document Header Bar */}
          <div className={`border rounded-lg p-4 font-mono text-xs space-y-2 ${
            theme === 'dark' ? "bg-[#1c212e] border-gray-700/80" : "bg-gray-50 border-gray-300"
          }`}>
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <span className="bg-cyan-500/20 text-cyan-500 border border-cyan-500/40 px-2 py-0.5 rounded font-bold">
                  [{activeItem.id}]
                </span>
                <span className={`text-base font-bold font-sans ${
                  theme === 'dark' ? "text-gray-100" : "text-gray-900"
                }`}>{activeItem.filename}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className={`px-2 py-0.5 rounded ${
                  theme === 'dark' ? "bg-gray-800 text-gray-300" : "bg-gray-200 text-gray-700"
                }`}>
                  Page {activeItem.page}
                </span>
                <span className={`${activeItem.hashVerified ? "bg-emerald-100 text-emerald-800 border-emerald-300" : "bg-amber-100 text-amber-800 border-amber-300"} px-2 py-0.5 rounded border font-bold flex items-center gap-1`}>
                  <ShieldCheck className="w-3.5 h-3.5" />
                  {activeItem.hashVerified ? "SHA-256 VERIFIED" : "SHA-256 UNVERIFIED"}
                </span>
              </div>
            </div>

            <div className="text-[11px] text-gray-500 flex items-center gap-2 font-mono">
              <span>Section: <strong className={theme === 'dark' ? "text-gray-200" : "text-gray-800"}>{activeItem.section}</strong></span>
              <span>•</span>
              <span className="text-gray-400 truncate">SHA256: {activeItem.sha256}</span>
            </div>
          </div>

          {/* Document Content View */}
          <div className={`flex-1 border rounded-lg p-6 font-sans text-sm leading-relaxed shadow-inner overflow-y-auto space-y-4 ${
            theme === 'dark' ? "bg-[#10131a] border-gray-800 text-gray-200" : "bg-gray-50 border-gray-300 text-gray-900"
          }`}>
            <div className="flex items-center justify-between border-b border-gray-300/40 pb-2 text-xs font-mono text-gray-500">
              <span>LOCAL FILE CONTENT PREVIEW</span>
              <span className="text-cyan-500 font-bold">CITATIONS [{activeItem.id}] ATTACHED</span>
            </div>

            <div className={`whitespace-pre-wrap font-mono text-xs p-4 rounded border leading-relaxed select-text ${
              theme === 'dark'
                ? "bg-[#181d28] border-gray-800 text-gray-200"
                : "bg-white border-gray-300 text-gray-800 shadow-sm"
            }`}>
              {activeItem.content}
            </div>

            <div className={`border-l-4 border-cyan-500 p-3 text-xs space-y-1 font-mono ${
              theme === 'dark' ? "bg-[#131720]" : "bg-cyan-50 text-cyan-900"
            }`}>
              <div className="text-cyan-500 font-bold">LOCAL EVIDENCE AUDIT STAMP</div>
              <div className="text-gray-500">
                {runtimeStats?.available ? `Local runtime: ${runtimeStats.gpuModel} · ${runtimeStats.rocmVersion}` : "Local runtime telemetry is unavailable; the evidence remains local and citation-addressable."}
              </div>
            </div>
          </div>

          {/* Navigation to Courtroom */}
          <div className="flex justify-between items-center pt-2 font-mono text-xs">
            <span className="text-gray-500">
              Evidence {activeItem.id} attached to Court Record.
            </span>
            <button
              onClick={() => setActiveView("court")}
              className="bg-amber-600 hover:bg-amber-500 text-white font-bold px-4 py-2 rounded transition-colors flex items-center gap-2"
            >
              {t.proceedToCourtroom}
            </button>
          </div>

        </div>

      </div>

    </div>
  );
};

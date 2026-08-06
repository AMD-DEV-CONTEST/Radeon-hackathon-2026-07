import React from "react";
import {
  FolderPlus,
  FileText,
  ShieldAlert,
  Database,
  CheckCircle2,
  Lock,
  Search,
  Scale,
  HardDrive,
  Upload
} from "lucide-react";
import { CaseData } from "../types";
import { Language, Theme, translations } from "../lib/i18n";

interface SidebarProps {
  currentCaseId: string;
  onSelectPresetCase: (presetKey: string) => void;
  onNewCase: () => void;
  onIndexWorkspace: (workspace: string) => void;
  activeView: string;
  setActiveView: (view: string) => void;
  caseData: CaseData;
  onUploadCustomFile: (file: File) => void;
  lang: Language;
  theme: Theme;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentCaseId,
  onSelectPresetCase,
  onNewCase,
  onIndexWorkspace,
  activeView,
  setActiveView,
  caseData,
  onUploadCustomFile,
  lang,
  theme,
}) => {
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const [workspacePath, setWorkspacePath] = React.useState("");
  const t = translations[lang];
  const runtime = caseData.runtime;
  const indexedSources = caseData.indexedSources ?? 0;
  const indexedChunks = caseData.indexedChunks ?? 0;

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      onUploadCustomFile(e.target.files[0]);
    }
  };

  return (
    <aside className={`w-full min-w-0 lg:w-64 max-h-52 lg:max-h-none border-b lg:border-b-0 lg:border-r text-gray-300 flex flex-col justify-between shrink-0 select-none transition-colors ${
      theme === 'dark'
        ? "bg-[#0d0f14] border-gray-800/80"
        : "bg-gray-50 border-gray-200 text-gray-800"
    }`}>
      <div className="p-3 space-y-5 overflow-y-auto flex-1 min-h-0 font-mono text-xs">

        {/* CASES Section */}
        <div>
          <div className="flex items-center justify-between text-[10px] tracking-wider font-semibold text-gray-500 uppercase px-2 mb-2">
            <span>{t.cases}</span>
            <span className={`px-1.5 py-0.5 rounded text-[9px] ${
              theme === 'dark' ? "bg-gray-800 text-gray-400" : "bg-gray-200 text-gray-600"
            }`}>LOCAL</span>
          </div>

          <button
            onClick={onNewCase}
            className={`w-full flex items-center justify-center gap-2 rounded-md py-2 px-3 transition-colors font-medium text-xs mb-3 ${
              theme === 'dark'
                ? "bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:border-emerald-500/50"
                : "bg-emerald-100 hover:bg-emerald-200 text-emerald-800 border border-emerald-300"
            }`}
          >
            <FolderPlus className="w-3.5 h-3.5" />
            {t.newCase}
          </button>

          <div className="space-y-1">
            <div className="text-[10px] text-gray-500 px-2 py-1 font-sans">{t.demoCases}</div>

            <button
              onClick={() => {
                onSelectPresetCase("sla-review");
                setActiveView("desk");
              }}
              className={`w-full text-left px-2.5 py-2 rounded-md transition-all flex items-start gap-2 ${
                currentCaseId === "case-014"
                  ? theme === 'dark'
                    ? "bg-[#181c26] text-emerald-400 border-l-2 border-emerald-500 font-medium"
                    : "bg-emerald-50 text-emerald-700 border-l-2 border-emerald-600 font-medium shadow-sm"
                  : theme === 'dark'
                    ? "hover:bg-[#141720] text-gray-400 hover:text-gray-200"
                    : "hover:bg-gray-100 text-gray-600 hover:text-gray-900"
              }`}
            >
              <Scale className="w-3.5 h-3.5 mt-0.5 shrink-0 text-emerald-500" />
              <div className="truncate">
                <div className="font-semibold text-[11px] truncate">{t.slaReviewTitle}</div>
                <div className="text-[10px] text-gray-500 truncate">{t.slaReviewSub}</div>
              </div>
            </button>

            <button
              onClick={() => {
                onSelectPresetCase("fuzzy-memory");
                setActiveView("desk");
              }}
              className={`w-full text-left px-2.5 py-2 rounded-md transition-all flex items-start gap-2 ${
                currentCaseId === "case-015"
                  ? theme === 'dark'
                    ? "bg-[#181c26] text-cyan-400 border-l-2 border-cyan-500 font-medium"
                    : "bg-cyan-50 text-cyan-700 border-l-2 border-cyan-600 font-medium shadow-sm"
                  : theme === 'dark'
                    ? "hover:bg-[#141720] text-gray-400 hover:text-gray-200"
                    : "hover:bg-gray-100 text-gray-600 hover:text-gray-900"
              }`}
            >
              <Search className="w-3.5 h-3.5 mt-0.5 shrink-0 text-cyan-500" />
              <div className="truncate">
                <div className="font-semibold text-[11px] truncate">{t.fuzzyMemoryTitle}</div>
                <div className="text-[10px] text-gray-500 truncate">{t.fuzzyMemorySub}</div>
              </div>
            </button>

            <button
              onClick={() => {
                onSelectPresetCase("sensitive-credentials");
                setActiveView("desk");
              }}
              className={`w-full text-left px-2.5 py-2 rounded-md transition-all flex items-start gap-2 ${
                currentCaseId === "case-016"
                  ? theme === 'dark'
                    ? "bg-[#181c26] text-red-400 border-l-2 border-red-500 font-medium"
                    : "bg-red-50 text-red-700 border-l-2 border-red-600 font-medium shadow-sm"
                  : theme === 'dark'
                    ? "hover:bg-[#141720] text-gray-400 hover:text-gray-200"
                    : "hover:bg-gray-100 text-gray-600 hover:text-gray-900"
              }`}
            >
              <ShieldAlert className="w-3.5 h-3.5 mt-0.5 shrink-0 text-red-500" />
              <div className="truncate">
                <div className="font-semibold text-[11px] truncate">{t.credentialLeakTitle}</div>
                <div className="text-[10px] text-gray-500 truncate">{t.credentialLeakSub}</div>
              </div>
            </button>
          </div>
        </div>

        {/* EVIDENCE Section */}
        <div className={`border-t pt-4 ${theme === 'dark' ? "border-gray-800/60" : "border-gray-200"}`}>
          <div className="flex items-center justify-between text-[10px] tracking-wider font-semibold text-gray-500 uppercase px-2 mb-2">
            <span>{t.evidencePacket}</span>
            <span className="text-[10px] text-gray-400 font-mono">
              {indexedSources} {t.filesCount} • {indexedChunks} {t.chunksCount}
            </span>
          </div>

          <button
            onClick={() => setActiveView("evidence")}
            className={`w-full text-left px-2.5 py-2 rounded-md transition-all flex items-center justify-between mb-2 ${
              activeView === "evidence"
                ? theme === 'dark'
                  ? "bg-[#181c26] text-cyan-400 border border-cyan-500/30"
                  : "bg-cyan-50 text-cyan-700 border border-cyan-300 font-medium"
                : theme === 'dark'
                  ? "hover:bg-[#141720] text-gray-400 hover:text-gray-200"
                  : "hover:bg-gray-100 text-gray-600 hover:text-gray-900"
            }`}
          >
            <div className="flex items-center gap-2">
              <Database className="w-3.5 h-3.5 text-cyan-500" />
              <span>{t.evidencePacket}</span>
            </div>
            <span className={`px-1.5 py-0.2 rounded text-[10px] ${
              theme === 'dark' ? "bg-gray-800 text-gray-300" : "bg-gray-200 text-gray-700"
            }`}>
              {caseData.evidenceList.length}
            </span>
          </button>

          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            className="hidden"
          />

          <button
            onClick={() => fileInputRef.current?.click()}
            className={`w-full border border-dashed rounded-md py-2 px-2.5 transition-all text-center flex items-center justify-center gap-2 text-[11px] ${
              theme === 'dark'
                ? "border-gray-700/80 hover:border-cyan-500/50 hover:bg-cyan-500/5 text-gray-400 hover:text-cyan-300"
                : "border-gray-300 hover:border-cyan-500 hover:bg-cyan-50 text-gray-600 hover:text-cyan-800"
            }`}
          >
            <Upload className="w-3.5 h-3.5" />
            {t.importLocalDoc}
          </button>

          <div className="mt-3 space-y-2">
            <div className="text-[10px] text-gray-500 px-2 uppercase tracking-wider">{t.workspaceFolder}</div>
            <input
              value={workspacePath}
              onChange={(event) => setWorkspacePath(event.target.value)}
              placeholder={t.workspacePlaceholder}
              aria-label={t.workspaceFolder}
              className={`w-full rounded-md border px-2.5 py-2 text-[11px] outline-none font-mono ${theme === 'dark' ? 'bg-[#10131a] border-gray-700 text-gray-200 placeholder-gray-600 focus:border-cyan-500' : 'bg-white border-gray-300 text-gray-800 placeholder-gray-400 focus:border-cyan-500'}`}
            />
            <button
              type="button"
              disabled={!workspacePath.trim()}
              onClick={() => onIndexWorkspace(workspacePath.trim())}
              className={`w-full rounded-md border py-2 px-2.5 text-[11px] flex items-center justify-center gap-2 transition-colors disabled:opacity-40 ${theme === 'dark' ? 'border-cyan-700/60 text-cyan-300 hover:bg-cyan-500/10' : 'border-cyan-300 text-cyan-800 hover:bg-cyan-50'}`}
            >
              <HardDrive className="w-3.5 h-3.5" />
              {t.indexWorkspace}
            </button>
          </div>
        </div>

        {/* SECURITY Section */}
        <div className={`border-t pt-4 ${theme === 'dark' ? "border-gray-800/60" : "border-gray-200"}`}>
          <div className="text-[10px] tracking-wider font-semibold text-gray-500 uppercase px-2 mb-2">
            {t.securityAudit}
          </div>

          <button
            onClick={() => setActiveView("security")}
            className={`w-full text-left px-2.5 py-2 rounded-md transition-all flex items-center justify-between mb-1 ${
              activeView === "security"
                ? theme === 'dark'
                  ? "bg-[#181c26] text-red-400 border border-red-500/30"
                  : "bg-red-50 text-red-700 border border-red-300 font-medium"
                : theme === 'dark'
                  ? "hover:bg-[#141720] text-gray-400 hover:text-gray-200"
                  : "hover:bg-gray-100 text-gray-600 hover:text-gray-900"
            }`}
          >
            <div className="flex items-center gap-2">
              <Lock className="w-3.5 h-3.5 text-red-500" />
              <span>{t.redactedScan}</span>
            </div>
            <span className={`px-1.5 py-0.2 rounded text-[9px] ${
              theme === 'dark' ? "bg-red-950/60 text-red-400 border border-red-800/50" : "bg-red-100 text-red-700 border border-red-200 font-bold"
            }`}>
              ACTIVE
            </span>
          </button>

          <button
            onClick={() => setActiveView("security")}
            className={`w-full text-left px-2.5 py-2 rounded-md transition-all flex items-center gap-2 ${
              theme === 'dark' ? "hover:bg-[#141720] text-gray-400 hover:text-gray-200" : "hover:bg-gray-100 text-gray-600 hover:text-gray-900"
            }`}
          >
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
            <span>{t.auditLedger}</span>
          </button>
        </div>

      </div>

      {/* AMD Radeon Footer Banner */}
      <div className={`hidden lg:block p-3 border-t text-[10px] font-mono space-y-1 ${
        theme === 'dark'
          ? "bg-[#0a0c0f] border-gray-800/80 text-gray-400"
          : "bg-gray-100 border-gray-200 text-gray-600"
      }`}>
        <div className="flex items-center justify-between font-semibold">
          <span className="text-gray-500">GPU BACKEND</span>
          <span className={runtime?.available ? "text-emerald-500" : "text-amber-400"}>{runtime?.available ? "LOCAL" : "NOT REPORTED"}</span>
        </div>
        <div className="text-emerald-500 font-medium truncate">
          {runtime?.gpuModel || "GPU telemetry unavailable"}
        </div>
        <div className="text-gray-500 flex justify-between">
          <span>{runtime?.tokenSpeed ? `${runtime.tokenSpeed} tok/s` : "speed not measured"}</span>
          <span className="text-cyan-500">{runtime?.externalCalls ?? 0} external calls</span>
        </div>
      </div>
    </aside>
  );
};

import React, { useEffect, useState } from "react";
import { X, Download, ShieldCheck, CheckCircle2, FileText, Printer, Copy, Check } from "lucide-react";
import { CaseData } from "../types";

interface ExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  caseData: CaseData;
  onApproveExport: () => Promise<{ path: string; content: string }>;
}

export const ExportModal: React.FC<ExportModalProps> = ({
  isOpen,
  onClose,
  caseData,
  onApproveExport,
}) => {
  const [copied, setCopied] = useState(false);
  const [approved, setApproved] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportedPath, setExportedPath] = useState("");
  const [exportContent, setExportContent] = useState("");
  const [exportError, setExportError] = useState("");

  useEffect(() => {
    if (isOpen) {
      setApproved(false);
      setExportedPath("");
      setExportContent("");
      setExportError("");
    }
  }, [isOpen, caseData.id]);

  if (!isOpen) return null;

  const exportText = `================================================================================
CLAIMCOURT LOCAL JUDICIAL VERDICT BUNDLE
================================================================================
CASE ID: ${caseData.id}
TITLE: ${caseData.title}
QUERY: ${caseData.query}
TIMESTAMP: ${new Date().toISOString()}
RUNTIME: ${caseData.runtime?.gpuModel || "unknown"} • ROCm ${caseData.runtime?.rocmVersion || "unknown"} • local API only

--------------------------------------------------------------------------------
1. VERDICT SUMMARY
--------------------------------------------------------------------------------
STATUS: ${caseData.courtroom.verdictStatus}
VERDICT TITLE: ${caseData.courtroom.verdictTitle}
CONFIDENCE: ${caseData.courtroom.confidence}%
RATIONALE: ${caseData.courtroom.verdictSubtitle}

--------------------------------------------------------------------------------
2. PROSECUTION ARGUMENTS
--------------------------------------------------------------------------------
${caseData.courtroom.prosecution.map((p, i) => `[P${i + 1}] ${p}`).join("\n")}

--------------------------------------------------------------------------------
3. DEFENSE COUNTER-ARGUMENTS
--------------------------------------------------------------------------------
${caseData.courtroom.defense.map((d, i) => `[D${i + 1}] ${d}`).join("\n")}

--------------------------------------------------------------------------------
4. CITED EVIDENCE INDEX & SHA-256 HASHES
--------------------------------------------------------------------------------
${caseData.evidenceList.map(e => `[${e.id}] ${e.filename} (Page ${e.page}, Status: ${e.status.toUpperCase()})
  SHA-256: ${e.sha256}`).join("\n")}

--------------------------------------------------------------------------------
5. RECOMMENDED NEXT ACTION
--------------------------------------------------------------------------------
${caseData.courtroom.nextAction}

================================================================================
LOCAL API EXPORT: SHA-256 VALUES ARE COPIED FROM THE INDEXED EVIDENCE LEDGER
================================================================================`;

  const handleCopy = () => {
    navigator.clipboard.writeText(exportText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = (content = exportContent) => {
    if (!approved || !content) return;
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `ClaimCourt_${caseData.id}_Verdict.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleApprove = async (): Promise<{ path: string; content: string } | null> => {
    setExporting(true);
    setExportError("");
    try {
      const result = await onApproveExport();
      setExportedPath(result.path);
      setExportContent(result.content);
      return result;
    } catch (error) {
      setExportError(error instanceof Error ? error.message : String(error));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 select-none">
      <div className="bg-[#141720] border border-gray-800 rounded-lg w-full max-w-2xl overflow-hidden shadow-2xl font-mono text-xs text-gray-200">

        {/* Modal Header */}
        <div className="bg-[#181c26] px-5 py-3.5 border-b border-gray-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-amber-400" />
            <span className="font-bold text-gray-100">EXPORT COURT VERDICT BUNDLE</span>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-100 p-1 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-5 space-y-4 max-h-[75vh] overflow-y-auto">
          <div className="bg-[#0f121a] p-3 rounded border border-gray-800 flex items-center justify-between text-[11px] text-gray-400">
            <span className="flex items-center gap-1.5 text-emerald-400 font-bold">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              Local Decision Brief Preview
            </span>
            <span>Hashes copied from indexed evidence</span>
          </div>

          <textarea
            readOnly
            value={exportText}
            rows={14}
            className="w-full bg-[#10131a] border border-gray-800 p-3 rounded text-[11px] font-mono text-gray-300 resize-none outline-none leading-relaxed"
          />
          <label className="flex items-start gap-2 text-[11px] text-gray-400">
            <input type="checkbox" checked={approved} onChange={(event) => setApproved(event.target.checked)} className="mt-0.5 accent-amber-500" />
            <span>I reviewed the cited evidence and approve writing this brief to the local export directory.</span>
          </label>
          {exportedPath && <div className="text-emerald-400 text-[11px]">Approved and written locally: {exportedPath}</div>}
          {exportError && <div className="text-red-300 text-[11px]">Export failed: {exportError}</div>}
        </div>

        {/* Modal Footer */}
        <div className="bg-[#181c26] px-5 py-3 border-t border-gray-800 flex items-center justify-between">
          <button
            onClick={handleCopy}
            className="bg-[#202634] hover:bg-[#283042] text-gray-200 px-3.5 py-1.5 rounded transition-colors text-xs font-bold flex items-center gap-1.5"
          >
            {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
            {copied ? "COPIED TO CLIPBOARD" : "COPY VERDICT TEXT"}
          </button>

          <button
            onClick={async () => { const result = exportedPath ? { content: exportContent } : await handleApprove(); if (result?.content || exportContent) handleDownload(result?.content || exportContent); }}
            disabled={!approved || exporting}
            className="bg-amber-500 hover:bg-amber-400 text-gray-950 font-bold px-4 py-1.5 rounded transition-colors text-xs flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Download className="w-4 h-4" />
            DOWNLOAD (.MD / BUNDLE)
          </button>
        </div>

      </div>
    </div>
  );
};

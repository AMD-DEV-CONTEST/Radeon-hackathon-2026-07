import React from "react";
import { Lock, CheckCircle2, FileCode, AlertOctagon } from "lucide-react";
import { RedactedRecord, RuntimeStats } from "../types";
import { Language, Theme, translations } from "../lib/i18n";

interface SecurityRoomProps {
  records: RedactedRecord[];
  runtimeStats?: RuntimeStats;
  lang: Language;
  theme: Theme;
}

export const SecurityRoom: React.FC<SecurityRoomProps> = ({ records, runtimeStats, lang, theme }) => {
  const t = translations[lang];

  return (
    <div className={`flex-1 p-6 overflow-y-auto space-y-6 select-none transition-colors ${
      theme === 'dark' ? "bg-[#0f1117] text-gray-200" : "bg-gray-100 text-gray-900"
    }`}>

      {/* Header */}
      <div className={`flex items-center justify-between border-b pb-3 font-mono ${
        theme === 'dark' ? "border-gray-800" : "border-gray-300"
      }`}>
        <div>
          <div className="text-[10px] text-red-500 font-bold tracking-widest uppercase flex items-center gap-2">
            <Lock className="w-3.5 h-3.5 text-red-500" />
            LOCAL REDACTION BOUNDARY
          </div>
          <h1 className={`text-xl font-bold mt-0.5 flex items-center gap-2 ${
            theme === 'dark' ? "text-gray-100" : "text-gray-900"
          }`}>
            REDACTION ACTIVE
          </h1>
        </div>
          <div className="text-right text-xs text-gray-500">
          <div className="text-red-500 font-bold font-mono">{records.length} SENSITIVE RECORDS LOCATED LOCALLY</div>
          <div className="text-[10px] text-gray-400">RAW VALUES ARE REDACTED BEFORE DISPLAY</div>
        </div>
      </div>

      {/* Security Status Banner */}
      <div className={`border rounded-lg p-4 font-mono text-xs flex items-center justify-between ${
        theme === 'dark' ? "bg-[#18151a] border-red-500/40" : "bg-red-50 border-red-300 shadow-sm text-red-950"
      }`}>
        <div className="flex items-center gap-3">
          <AlertOctagon className="w-5 h-5 text-red-500 shrink-0" />
          <div>
            <div className="font-bold text-red-500">LOCAL SOFTWARE SECURITY BOUNDARY</div>
            <div className="text-gray-500 text-[11px] mt-0.5">
              Raw plaintexts are redacted before they enter the response or export path. No unmask action exists.
            </div>
          </div>
        </div>
        <span className="bg-red-100 text-red-800 border border-red-300 px-2.5 py-1 rounded font-bold">
          {runtimeStats ? `${runtimeStats.externalCalls} external calls reported` : "Local boundary not measured"}
        </span>
      </div>

      {/* Redacted Records List */}
      <div className="space-y-4">
        {records.length === 0 && (
          <div className={`border rounded-lg p-6 font-mono text-xs text-center ${theme === 'dark' ? 'bg-[#161922] border-gray-800 text-gray-500' : 'bg-white border-gray-300 text-gray-600'}`}>
            No sensitive records have been scanned in the current indexed workspace.
          </div>
        )}
        {records.map((rec, idx) => (
          <div
            key={idx}
            className={`border rounded-lg p-4 font-mono space-y-3 shadow-lg ${
              theme === 'dark' ? "bg-[#161922] border-gray-800" : "bg-white border-gray-300 shadow-sm"
            }`}
          >
            <div className={`flex items-center justify-between flex-wrap gap-2 border-b pb-2 ${
              theme === 'dark' ? "border-gray-800" : "border-gray-200"
            }`}>
              <div className="flex items-center gap-2">
                <FileCode className="w-4 h-4 text-cyan-500" />
                <span className={`font-bold ${theme === 'dark' ? "text-gray-100" : "text-gray-900"}`}>{rec.file}</span>
                <span className="text-gray-400">Line {rec.line}</span>
              </div>
              <span className="bg-red-100 text-red-800 border border-red-300 px-2 py-0.5 rounded text-[10px] font-bold">
                {rec.type}
              </span>
            </div>

            <div className={`p-3 rounded border font-mono text-xs text-red-500 ${
              theme === 'dark' ? "bg-[#10121a] border-gray-800" : "bg-red-50/50 border-red-200"
            }`}>
              <div className="text-[10px] text-gray-400 mb-1">LOCAL MASKED REPRESENTATION</div>
              <div className="font-bold">{rec.maskedValue}</div>
            </div>

            <div className="text-[10px] text-gray-500 flex items-center justify-between truncate">
              <span>Fingerprint: <strong className={theme === 'dark' ? "text-gray-300 font-mono" : "text-gray-700 font-mono"}>{rec.fingerprint}</strong></span>
              <span className="text-emerald-500 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                Audited sha256
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Enforcement Statement Footer */}
      <div className={`border p-4 rounded-lg font-mono text-xs text-gray-500 text-center ${
        theme === 'dark' ? "bg-[#12151f] border-gray-800" : "bg-white border-gray-300"
      }`}>
        Raw values are redacted before UI serialization and the export path. The local API returns paths, fingerprints, and masked previews only.
      </div>

    </div>
  );
};

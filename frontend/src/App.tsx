import React, { useCallback, useEffect, useState } from "react";
import { Header } from "./components/Header";
import { Sidebar } from "./components/Sidebar";
import { CaseDesk } from "./components/CaseDesk";
import { IntentCompiler } from "./components/IntentCompiler";
import { EvidenceRoom } from "./components/EvidenceRoom";
import { Courtroom } from "./components/Courtroom";
import { SecurityRoom } from "./components/SecurityRoom";
import { RuntimeSettingsModal } from "./components/RuntimeSettingsModal";
import { ExportModal } from "./components/ExportModal";
import { CaseData, EvidenceItem, RuntimeStats, SecurityRecord } from "./types";
import { Language, Theme } from "./lib/i18n";

const EMPTY_RUNTIME: RuntimeStats = {
  gpuModel: "unknown",
  rocmVersion: "unknown",
  hipStatus: "Runtime not checked",
  modelResident: "unknown",
  precision: "unknown",
  vramUsed: 0,
  vramTotal: 0,
  tokenSpeed: 0,
  externalCalls: 0,
  available: false,
};

const EMPTY_CASE: CaseData = {
  id: "case-empty",
  title: "NEW LOCAL INVESTIGATION",
  query: "",
  intent: {
    fuzzyText: "",
    intentType: "not compiled",
    topics: [],
    artifact: "document",
    memoryClues: "Awaiting a local request",
    relation: "none",
    confidence: 0,
    trajectory: [],
    compiler: "not run",
  },
  evidenceList: [],
  courtroom: {
    verdictStatus: "NO CASE",
    verdictTitle: "Index a private workspace to begin",
    verdictSubtitle: "The frontend is connected to the local ClaimCourt API. No evidence is fabricated before indexing.",
    confidence: 0,
    prosecution: [],
    defense: [],
    citedEvidence: [],
    timeline: [],
    missingEvidence: ["A selected local workspace or uploaded document"],
    nextAction: "Select a private folder or load the synthetic corpus for a controlled rehearsal.",
  },
  status: "empty",
  indexedSources: 0,
  indexedChunks: 0,
  runtime: EMPTY_RUNTIME,
  securityRecords: [],
};

type ApiEnvelope<T> = { success: boolean; data?: T; error?: string };

function normalizeCaseData(value: Partial<CaseData>, previous: CaseData = EMPTY_CASE): CaseData {
  const intent = value.intent;
  const courtroom = value.courtroom;
  const evidenceList = Array.isArray(value.evidenceList) ? value.evidenceList : [];
  const fileMatches = Array.isArray(value.fileMatches)
    ? value.fileMatches.map((match) => ({
        ...match,
        reasons: Array.isArray(match.reasons) ? match.reasons : [],
        duplicatePaths: Array.isArray(match.duplicatePaths) ? match.duplicatePaths : [],
        evidenceIds: Array.isArray(match.evidenceIds) ? match.evidenceIds : [],
      }))
    : [];

  return {
    ...EMPTY_CASE,
    ...previous,
    ...value,
    intent: {
      ...EMPTY_CASE.intent,
      ...intent,
      topics: Array.isArray(intent?.topics) ? intent.topics : [],
      trajectory: Array.isArray(intent?.trajectory) ? intent.trajectory : [],
    },
    evidenceList,
    courtroom: {
      ...EMPTY_CASE.courtroom,
      ...courtroom,
      prosecution: Array.isArray(courtroom?.prosecution) ? courtroom.prosecution : [],
      defense: Array.isArray(courtroom?.defense) ? courtroom.defense : [],
      citedEvidence: Array.isArray(courtroom?.citedEvidence) ? courtroom.citedEvidence : [],
      timeline: Array.isArray(courtroom?.timeline) ? courtroom.timeline : [],
      missingEvidence: Array.isArray(courtroom?.missingEvidence) ? courtroom.missingEvidence : [],
    },
    fileMatches,
    securityRecords: Array.isArray(value.securityRecords) ? value.securityRecords : [],
  };
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const body = (await response.json()) as ApiEnvelope<T>;
  if (!response.ok || !body.success || body.data === undefined) {
    throw new Error(body.error || `Local API request failed (${response.status})`);
  }
  return body.data;
}

function runtimeFromApi(value: Record<string, any> | undefined): RuntimeStats {
  if (!value) return EMPTY_RUNTIME;
  const vramUsed = Number(value.vram_used_bytes || value.size_vram || 0) / (1024 ** 3);
  const vramTotal = Number(value.vram_total_bytes || 0) / (1024 ** 3);
  const configuredModel = String(value.model || value.modelResident || "unknown");
  return {
    ...EMPTY_RUNTIME,
    gpuModel: value.gpu_name || value.gpuModel || "unknown",
    rocmVersion: value.rocm_version || value.rocmVersion || "unknown",
    hipStatus: value.hip_version ? `HIP ${value.hip_version}` : value.available ? "Runtime reachable" : "Runtime unavailable",
    modelResident: value.modelResident || (value.model_loaded === false ? `${configuredModel} (not loaded)` : configuredModel),
    precision: value.dtype || value.precision || "unknown",
    vramUsed: Number(vramUsed.toFixed(2)),
    vramTotal: Number(vramTotal.toFixed(2)),
    tokenSpeed: Number(value.tokens_per_second ?? value.tokenSpeed ?? 0),
    externalCalls: Number(value.external_calls ?? value.externalCalls ?? 0),
    available: Boolean(value.available),
    error: value.error,
    service: value.service,
    contextLength: Number(value.context_length || 0),
    dtype: value.dtype,
    quantization: value.quantization,
    gpuArchitecture: value.gpu_architecture,
  };
}

export default function App() {
  const [lang, setLang] = useState<Language>("en");
  const [theme, setTheme] = useState<Theme>("dark");
  const [caseData, setCaseData] = useState<CaseData>(EMPTY_CASE);
  const [activeView, setActiveView] = useState<string>("desk");
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string>("");
  const [runtimeStats, setRuntimeStats] = useState<RuntimeStats>(EMPTY_RUNTIME);
  const [securityRecords, setSecurityRecords] = useState<SecurityRecord[]>([]);
  const [isInvestigating, setIsInvestigating] = useState(false);
  const [isRuntimeModalOpen, setIsRuntimeModalOpen] = useState(false);
  const [isExportModalOpen, setIsExportModalOpen] = useState(false);
  const [apiError, setApiError] = useState("");

  const refreshRuntime = useCallback(async () => {
    try {
      const data = await api<{
        runtime: Record<string, any>;
        workspace?: string;
        indexedSources?: number;
        indexedChunks?: number;
      }>("/api/health");
      const nextRuntime = runtimeFromApi(data.runtime);
      setRuntimeStats(nextRuntime);
      setCaseData((previous) => ({
        ...previous,
        runtime: nextRuntime,
        workspace: data.workspace || previous.workspace,
        indexedSources: data.indexedSources ?? previous.indexedSources ?? 0,
        indexedChunks: data.indexedChunks ?? previous.indexedChunks ?? 0,
      }));
    } catch (error) {
      const nextRuntime = { ...EMPTY_RUNTIME, error: error instanceof Error ? error.message : String(error) };
      setRuntimeStats(nextRuntime);
      setCaseData((previous) => previous.status === "empty" ? { ...previous, runtime: nextRuntime } : previous);
    }
  }, []);

  useEffect(() => {
    void refreshRuntime();
  }, [refreshRuntime]);

  const handleIndexWorkspace = async (workspace: string) => {
    setApiError("");
    try {
      const index = await api<Pick<CaseData, "workspace" | "indexedSources" | "indexedChunks" | "scan">>("/api/index", {
        method: "POST",
        body: JSON.stringify({ workspace, source: "workspace" }),
      });
      setCaseData({
        ...EMPTY_CASE,
        title: "LOCAL WORKSPACE READY",
        workspace: index.workspace || workspace,
        indexedSources: index.indexedSources ?? 0,
        indexedChunks: index.indexedChunks ?? 0,
        scan: index.scan,
        runtime: runtimeStats,
      });
      setSelectedEvidenceId("");
      setSecurityRecords([]);
      setActiveView("desk");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : String(error));
    }
  };

  const handleUploadCustomFile = async (file: File) => {
    setApiError("");
    try {
      const contentBase64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const value = String(reader.result || "");
          resolve(value.includes(",") ? value.split(",", 2)[1] : value);
        };
        reader.onerror = () => reject(reader.error || new Error("Could not read local file"));
        reader.readAsDataURL(file);
      });
      const index = await api<Pick<CaseData, "workspace" | "indexedSources" | "indexedChunks" | "scan">>("/api/index", {
        method: "POST",
        body: JSON.stringify({ source: "uploads", files: [{ name: file.name, contentBase64 }] }),
      });
      setCaseData({
        ...EMPTY_CASE,
        title: "LOCAL DOCUMENT READY",
        workspace: index.workspace || "uploaded document",
        indexedSources: index.indexedSources ?? 0,
        indexedChunks: index.indexedChunks ?? 0,
        scan: index.scan,
        runtime: runtimeStats,
      });
      setActiveView("desk");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : String(error));
    }
  };

  const handleSelectPresetCase = async (presetKey: string) => {
    const queries: Record<string, string> = {
      "sla-review": "Did the vendor contractually commit to 99.9% uptime?",
      "fuzzy-memory": "我之前写过一份操作系统实验报告，好像是进程调度的，帮我找出来并告诉我写了什么",
      "sensitive-credentials": "帮我找 USA 服务器宝塔面板的账号密码，只给位置不要显示值",
    };
    setIsInvestigating(true);
    setApiError("");
    try {
      const index = await api<Pick<CaseData, "workspace" | "indexedSources" | "indexedChunks" | "scan">>("/api/index", {
        method: "POST",
        body: JSON.stringify({ source: "demo" }),
      });
      setCaseData((previous) => ({
        ...previous,
        workspace: index.workspace,
        indexedSources: index.indexedSources ?? 0,
        indexedChunks: index.indexedChunks ?? 0,
        scan: index.scan,
      }));
      await handleRunInvestigation(queries[presetKey] || queries["sla-review"]);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : String(error));
    } finally {
      setIsInvestigating(false);
    }
  };

  const handleRunInvestigation = async (query: string) => {
    setIsInvestigating(true);
    setApiError("");
    try {
      const data = await api<CaseData>("/api/investigate", {
        method: "POST",
        body: JSON.stringify({ query, useLocalModel: true }),
      });
      const normalizedRuntime = data.runtime
        ? runtimeFromApi(data.runtime as unknown as Record<string, any>)
        : runtimeStats;
      setCaseData((previous) => normalizeCaseData({
        ...data,
        workspace: data.workspace || previous.workspace,
        indexedSources: data.indexedSources ?? previous.indexedSources ?? 0,
        indexedChunks: data.indexedChunks ?? previous.indexedChunks ?? 0,
        scan: data.scan ?? previous.scan,
        runtime: normalizedRuntime,
      }, previous));
      setRuntimeStats(normalizedRuntime);
      setSecurityRecords(data.securityRecords || []);
      setSelectedEvidenceId(data.evidenceList[0]?.id || "");
      setActiveView(data.route === "sensitive_record_scan" ? "security" : "desk");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : String(error));
    } finally {
      setIsInvestigating(false);
    }
  };

  const handleNewCase = () => {
    setCaseData((previous) => ({
      ...EMPTY_CASE,
      id: `case-${Date.now().toString(36)}`,
      workspace: previous.workspace,
      indexedSources: previous.indexedSources ?? 0,
      indexedChunks: previous.indexedChunks ?? 0,
      scan: previous.scan,
      runtime: runtimeStats,
    }));
    setSecurityRecords([]);
    setActiveView("desk");
  };

  const handleRetrievalFeedback = async (selectedSourcePath: string | null, relevant: boolean) => {
    setApiError("");
    try {
      await api("/api/feedback", {
        method: "POST",
        body: JSON.stringify({
          caseId: caseData.id,
          selectedSourcePath: selectedSourcePath || "",
          relevant,
        }),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setApiError(message);
      throw error;
    }
  };

  const handleSelectCitation = (citationId: string) => {
    setSelectedEvidenceId(citationId);
    setActiveView("evidence");
  };

  const handleExport = async () => {
    const data = await api<{ path: string; content: string }>("/api/export", {
      method: "POST",
      body: JSON.stringify({ caseId: caseData.id, approved: true }),
    });
    return data;
  };

  return (
    <div className={`flex flex-col h-screen w-screen max-w-full font-sans overflow-hidden select-none transition-colors ${theme === "dark" ? "bg-[#0d0f14]" : "bg-gray-100"}`}>
      <Header
        runtimeStats={runtimeStats}
        onOpenRuntimeSettings={() => setIsRuntimeModalOpen(true)}
        activeView={activeView}
        setActiveView={setActiveView}
        lang={lang}
        setLang={setLang}
        theme={theme}
        setTheme={setTheme}
      />
      {apiError && <div className="bg-red-950/70 border-b border-red-800 px-4 py-2 text-xs text-red-200 font-mono">LOCAL API ERROR // {apiError}</div>}
      <div className="flex flex-col lg:flex-row flex-1 min-h-0 overflow-hidden">
        <Sidebar
          currentCaseId={caseData.id}
          onSelectPresetCase={handleSelectPresetCase}
          onNewCase={handleNewCase}
          onIndexWorkspace={handleIndexWorkspace}
          activeView={activeView}
          setActiveView={setActiveView}
          caseData={caseData}
          onUploadCustomFile={handleUploadCustomFile}
          lang={lang}
          theme={theme}
        />
        <main className="w-full max-w-full flex-1 min-w-0 flex overflow-hidden">
          {activeView === "desk" && <CaseDesk caseData={caseData} onRunInvestigation={handleRunInvestigation} onSelectPresetCase={handleSelectPresetCase} onRetrievalFeedback={handleRetrievalFeedback} isInvestigating={isInvestigating} setActiveView={setActiveView} lang={lang} theme={theme} />}
          {activeView === "intent" && <IntentCompiler caseData={caseData} setActiveView={setActiveView} lang={lang} theme={theme} />}
          {activeView === "evidence" && <EvidenceRoom caseData={caseData} selectedEvidenceId={selectedEvidenceId} onSelectEvidence={setSelectedEvidenceId} setActiveView={setActiveView} lang={lang} theme={theme} runtimeStats={runtimeStats} />}
          {activeView === "court" && <Courtroom caseData={caseData} onSelectCitation={handleSelectCitation} onOpenExportModal={() => setIsExportModalOpen(true)} lang={lang} theme={theme} />}
          {activeView === "security" && <SecurityRoom records={securityRecords} runtimeStats={runtimeStats} lang={lang} theme={theme} />}
        </main>
      </div>
      <RuntimeSettingsModal isOpen={isRuntimeModalOpen} onClose={() => setIsRuntimeModalOpen(false)} runtimeStats={runtimeStats} onRefresh={refreshRuntime} />
      <ExportModal isOpen={isExportModalOpen} onClose={() => setIsExportModalOpen(false)} caseData={caseData} onApproveExport={handleExport} />
    </div>
  );
}

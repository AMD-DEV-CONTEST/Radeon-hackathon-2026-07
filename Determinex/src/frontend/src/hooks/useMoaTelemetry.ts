"use client";
import { useEffect } from "react";
import { listen } from "@tauri-apps/api/event";
import { isTauri } from "@/lib/api";
import { emitPolicyBlock } from "@/lib/policy-block-bus";
import type { AgentStatus } from "@/components/MatrixExecutionDisplay";

interface MoaTelemetryHandlers {
  setMatrixLogs: React.Dispatch<React.SetStateAction<string[]>>;
  setCompilerWarning: React.Dispatch<React.SetStateAction<string | null>>;
  setGeneratedFile: React.Dispatch<React.SetStateAction<string | null>>;
  setRetryCount: React.Dispatch<React.SetStateAction<number>>;
  setAgentStatus: React.Dispatch<React.SetStateAction<AgentStatus>>;
}

export function useMoaTelemetry({
  setMatrixLogs,
  setCompilerWarning,
  setGeneratedFile,
  setRetryCount,
  setAgentStatus,
}: MoaTelemetryHandlers): void {
  useEffect(() => {
    if (!isTauri()) return;

    let unlistenFn: (() => void) | undefined;
    let cancelled = false;

    listen<{ agent: string; status: string }>("moa-telemetry", (event) => {
      const { agent, status } = event.payload;

      if (agent === "system" && status === "FlushingVRAM") {
        setMatrixLogs((prev) => [...prev, "[SYSTEM] VRAM flush — evicting model from GPU..."]);
        return;
      }

      if (agent === "system" && status === "SecurityPanic|PathTraversalBlocked") {
        setMatrixLogs((prev) => [
          ...prev,
          "[SECURITY] ⛔ AEGIS FS jail blocked a write outside the workspace sandbox.",
        ]);
        emitPolicyBlock("PATH_TRAVERSAL_BLOCKED", "orchestrator generated-file write");
        return;
      }

      if (agent === "system" && status.startsWith("RAG|")) {
        const count = status.split("|")[1] ?? "0";
        setMatrixLogs((prev) => [
          ...prev,
          `[WORKSPACE-RAG] ${count} snippet(s) injected into Sentinel context.`,
        ]);
        return;
      }

      if (agent === "system" && status.startsWith("RoutingPrecision|")) {
        const parts = status.split("|");
        const skill = parts[1] ?? "unknown";
        const dist = parts[2] ?? "0.000";
        setMatrixLogs((prev) => [
          ...prev,
          `[ROUTING] Companion Skill detected: ${skill} (distance: ${dist})`,
        ]);
        return;
      }

      if (agent === "system" && status.startsWith("SkillLoaded|")) {
        const skill = status.split("|")[1] ?? "unknown";
        setMatrixLogs((prev) => [...prev, `[SKILL] ✨ Activated Companion Skill: ${skill}`]);
        return;
      }

      if (agent === "system" && status.startsWith("CompilerCheck|")) {
        const result = status.split("|")[1];
        setMatrixLogs((prev) => [
          ...prev,
          result === "PASS"
            ? "[COMPILER] ✓ Syntax check passed — feeding result to Observer."
            : "[COMPILER] ✗ Errors detected — injecting diagnostics into Observer prompt.",
        ]);
        if (result !== "PASS") {
          setCompilerWarning(
            "Compiler errors detected — Observer is analyzing diagnostics and will attempt a fix."
          );
        } else {
          setCompilerWarning(null);
        }
        return;
      }

      if (agent === "system" && status.startsWith("FileCommitted|")) {
        const parts = status.split("|");
        const threadId = parts[1] ?? "";
        const filename = parts[2] ?? "output";
        setGeneratedFile(`sessions/${threadId}/sandbox/${filename}`);
        setMatrixLogs((prev) => [
          ...prev,
          `[OUTPUT] ✓ File written → sessions/${threadId}/sandbox/${filename}`,
        ]);
        return;
      }

      if (agent === "observer" && status.startsWith("Rejected|")) {
        const parts = status.split("|");
        const verdict = parts[1] ?? "REJECTED";
        const conf = parseFloat(parts[2] ?? "0");
        const issues = (parts[3] ?? "").split(";").filter(Boolean).join(" · ") || "no details";
        setRetryCount((prev) => prev + 1);
        setAgentStatus((prev) => ({
          ...prev,
          currentAgent: "engineer",
          verdict: null,
          accepted: null,
        }));
        setMatrixLogs((prev) => [
          ...prev,
          `[OBSERVER] ⚠ REJECTED — ${verdict} · confidence ${(conf * 100).toFixed(0)}%`,
          `[OBSERVER] Issues: ${issues}`,
        ]);
        return;
      }

      if (status === "Loading") {
        const agentId = agent as "sentinel" | "engineer" | "observer";
        if (agentId === "sentinel" || agentId === "engineer" || agentId === "observer") {
          setAgentStatus((prev) => ({ ...prev, currentAgent: agentId }));
          setMatrixLogs((prev) => [...prev, `[${agent.toUpperCase()}] Loading model into VRAM...`]);
        }
      } else if (status === "Inferencing") {
        setMatrixLogs((prev) => [...prev, `[${agent.toUpperCase()}] Inferencing...`]);
      } else if (status === "Evaluating") {
        setMatrixLogs((prev) => [...prev, `[OBSERVER] Evaluating output...`]);
      } else if (status === "Done") {
        setMatrixLogs((prev) => [...prev, `[${agent.toUpperCase()}] Stage complete.`]);
      }
    }).then((fn) => {
      if (cancelled) {
        fn();
      } else {
        unlistenFn = fn;
      }
    });

    return () => {
      cancelled = true;
      unlistenFn?.();
    };
  }, [setMatrixLogs, setCompilerWarning, setGeneratedFile, setRetryCount, setAgentStatus]);
}

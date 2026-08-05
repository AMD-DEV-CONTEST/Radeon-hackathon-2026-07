"use client";
import { useState } from "react";
import {
  Play,
  RefreshCw,
  Check,
  X,
  Minus,
  ChevronDown,
  ChevronRight,
  Clock,
  FlaskConical,
} from "lucide-react";
import { isTauri, runTerminalCommand } from "@/lib/api";

type TestStatus = "pass" | "fail" | "skip" | "pending";
type TestCase = {
  id: string;
  name: string;
  status: TestStatus;
  duration?: string;
  message?: string;
};
type Suite = { id: string; name: string; file: string; cases: TestCase[]; expanded?: boolean };

const STATUS_CONFIG: Record<TestStatus, { icon: typeof Check; color: string; bg: string }> = {
  pass: { icon: Check, color: "text-emerald-400", bg: "bg-emerald-950/10" },
  fail: { icon: X, color: "text-red-400", bg: "bg-red-950/15" },
  skip: { icon: Minus, color: "text-gray-500", bg: "" },
  pending: { icon: Clock, color: "text-gray-600", bg: "" },
};

export function TestRunner() {
  const [suites, setSuites] = useState<Suite[]>([]);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState("No test run has been started in this IDE session.");

  const totalPass = suites.flatMap((s) => s.cases).filter((c) => c.status === "pass").length;
  const totalFail = suites.flatMap((s) => s.cases).filter((c) => c.status === "fail").length;
  const totalSkip = suites.flatMap((s) => s.cases).filter((c) => c.status === "skip").length;
  const totalTests = suites.flatMap((s) => s.cases).length;

  const toggle = (id: string) =>
    setSuites((prev) => prev.map((s) => (s.id === id ? { ...s, expanded: !s.expanded } : s)));

  const runAll = async () => {
    if (!isTauri()) {
      setMessage("Run All requires the Tauri desktop runtime.");
      return;
    }
    setRunning(true);
    setMessage("Running npm.cmd test in frontend...");
    setSuites([
      {
        id: "frontend-vitest",
        name: "frontend Vitest",
        file: "frontend/package.json",
        expanded: true,
        cases: [{ id: "frontend-vitest-run", name: "npm.cmd test", status: "pending" }],
      },
    ]);
    const startedAt = performance.now();
    try {
      const result = await runTerminalCommand("npm.cmd test", "frontend");
      const elapsed = `${((performance.now() - startedAt) / 1000).toFixed(1)}s`;
      const output = [result?.stdout ?? "", result?.stderr ?? ""].join("\n").trim();
      const passed = Boolean(result && result.exit_code === 0 && !result.timed_out);
      setSuites([
        {
          id: "frontend-vitest",
          name: "frontend Vitest",
          file: result?.cwd ?? "frontend/package.json",
          expanded: true,
          cases: [
            {
              id: "frontend-vitest-run",
              name: "npm.cmd test",
              status: passed ? "pass" : "fail",
              duration: elapsed,
              message: passed ? undefined : output || "Test command failed without output.",
            },
          ],
        },
      ]);
      setMessage(
        passed
          ? "Latest frontend test run passed."
          : "Latest frontend test run failed. See command output in the failed row."
      );
    } catch (error) {
      setSuites([
        {
          id: "frontend-vitest",
          name: "frontend Vitest",
          file: "frontend/package.json",
          expanded: true,
          cases: [
            {
              id: "frontend-vitest-run",
              name: "npm.cmd test",
              status: "fail",
              message: error instanceof Error ? error.message : "Test command failed.",
            },
          ],
        },
      ]);
      setMessage("Could not run frontend tests.");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div
        className="shrink-0 flex items-center gap-3 px-4 py-2.5 border-b"
        style={{ borderColor: "var(--determinex-border)", background: "rgba(0,0,0,0.2)" }}
      >
        <button
          onClick={runAll}
          disabled={running}
          className="flex items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-950/20 px-3 py-1.5 text-eyebrow font-black uppercase tracking-widest text-emerald-400 disabled:opacity-50 hover:enabled:bg-emerald-950/40 transition-all"
        >
          {running ? <RefreshCw size={10} className="animate-spin" /> : <Play size={10} />}
          {running ? "Running..." : "Run All"}
        </button>
        <div className="flex items-center gap-3 ml-2 text-meta font-mono">
          <span className="text-emerald-400">{totalPass} pass</span>
          <span className="text-red-400">{totalFail} fail</span>
          <span className="text-gray-600">{totalSkip} skip</span>
        </div>
        <div className="ml-auto">
          <div className="h-1.5 w-24 rounded-full bg-white/5 overflow-hidden">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all"
              style={{ width: `${totalTests === 0 ? 0 : (totalPass / totalTests) * 100}%` }}
            />
          </div>
          <div className="text-meta text-gray-700 text-right mt-0.5">
            {totalTests === 0 ? "0" : ((totalPass / totalTests) * 100).toFixed(0)}%
          </div>
        </div>
      </div>

      {/* Suite list */}
      <div className="flex-1 overflow-y-auto no-scrollbar">
        {suites.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center opacity-60">
            <FlaskConical size={24} className="text-gray-600" />
            <p className="text-label text-gray-500 font-mono">{message}</p>
          </div>
        ) : (
          suites.map((suite) => {
            const suitePass = suite.cases.filter((c) => c.status === "pass").length;
            const suiteFail = suite.cases.filter((c) => c.status === "fail").length;
            return (
              <div key={suite.id} className="border-b border-white/[0.03]">
                <button
                  onClick={() => toggle(suite.id)}
                  className="w-full flex items-center gap-2.5 px-4 py-2.5 hover:bg-white/[0.02] transition-colors text-left"
                >
                  {suite.expanded ? (
                    <ChevronDown size={11} className="text-gray-600 shrink-0" />
                  ) : (
                    <ChevronRight size={11} className="text-gray-600 shrink-0" />
                  )}
                  <span className="text-label font-semibold text-white/70 flex-1 truncate">
                    {suite.name}
                  </span>
                  <span className="text-meta font-mono text-emerald-400">
                    {suitePass}/{suite.cases.length}
                  </span>
                  {suiteFail > 0 && (
                    <span className="text-meta font-mono text-red-400">{suiteFail} fail</span>
                  )}
                </button>
                {suite.expanded &&
                  suite.cases.map((tc) => {
                    const { icon: Icon, color, bg } = STATUS_CONFIG[tc.status];
                    return (
                      <div
                        key={tc.id}
                        className={`flex flex-col gap-0.5 pl-10 pr-4 py-2 border-l-2 border-transparent ${bg} ${tc.status === "fail" ? "border-l-red-500/30" : ""}`}
                      >
                        <div className="flex items-center gap-2">
                          <Icon size={11} className={`${color} shrink-0`} />
                          <span
                            className={`text-label ${tc.status === "fail" ? "text-red-300" : "text-gray-400"} flex-1 font-mono truncate`}
                          >
                            {tc.name}
                          </span>
                          {tc.duration && (
                            <span className="text-meta font-mono text-gray-700">{tc.duration}</span>
                          )}
                        </div>
                        {tc.message && (
                          <p className="text-meta font-mono text-red-400/80 pl-5 leading-relaxed">
                            {tc.message}
                          </p>
                        )}
                      </div>
                    );
                  })}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

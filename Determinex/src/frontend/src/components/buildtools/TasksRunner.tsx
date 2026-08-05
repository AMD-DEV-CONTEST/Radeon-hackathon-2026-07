"use client";
import { useState, useEffect } from "react";
import { Play, Square, Plus, Trash2, Check, X, Clock, RefreshCw } from "lucide-react";
import { isTauri, runTerminalCommand } from "@/lib/api";

type TaskStatus = "idle" | "running" | "success" | "failed";
type Task = {
  id: string;
  label: string;
  command: string;
  status: TaskStatus;
  lastDuration?: string;
  lastRan?: string;
  builtin?: boolean;
};

const DEFAULT_TASKS: Task[] = [
  { id: "t1", label: "Build (debug)", command: "cargo build", status: "idle", builtin: true },
  {
    id: "t2",
    label: "Build (release)",
    command: "cargo build --release",
    status: "idle",
    builtin: true,
  },
  { id: "t3", label: "Run tests", command: "cargo test", status: "idle", builtin: true },
  {
    id: "t4",
    label: "Clippy",
    command: "cargo clippy -- -D warnings",
    status: "idle",
    builtin: true,
  },
  {
    id: "t5",
    label: "ProgramBench eval",
    command: "uv run programbench eval T:/determinex-programbench/pilot",
    status: "idle",
    builtin: true,
  },
  { id: "t6", label: "Python lint", command: "ruff check scripts/", status: "idle", builtin: true },
  {
    id: "t7",
    label: "TypeScript check",
    command: "npm.cmd exec tsc -- --noEmit",
    status: "idle",
    builtin: true,
  },
  {
    id: "t8",
    label: "Hive smoke test",
    command: "python scripts/limits_test.py --level 1",
    status: "idle",
    builtin: true,
  },
];

const STATUS_CONFIG: Record<TaskStatus, { icon: typeof Play; color: string; label: string }> = {
  idle: { icon: Clock, color: "text-gray-600", label: "idle" },
  running: { icon: RefreshCw, color: "text-cyan-400", label: "running" },
  success: { icon: Check, color: "text-emerald-400", label: "done" },
  failed: { icon: X, color: "text-red-400", label: "failed" },
};

export function TasksRunner() {
  const [tasks, setTasks] = useState<Task[]>(() => {
    try {
      const saved = localStorage.getItem("determinex-tasks");
      const custom: Task[] = saved ? JSON.parse(saved) : [];
      return [...DEFAULT_TASKS, ...custom];
    } catch {
      return DEFAULT_TASKS;
    }
  });
  const [addLabel, setAddLabel] = useState("");
  const [addCommand, setAddCommand] = useState("");
  const [showAdd, setShowAdd] = useState(false);

  const customTasks = tasks.filter((t) => !t.builtin);
  useEffect(() => {
    localStorage.setItem("determinex-tasks", JSON.stringify(customTasks));
  }, [customTasks]);

  const run = async (id: string) => {
    const task = tasks.find((t) => t.id === id);
    if (!task) return;
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, status: "running" } : t)));
    if (!isTauri()) {
      setTasks((prev) =>
        prev.map((t) =>
          t.id === id
            ? { ...t, status: "failed", lastDuration: "not run", lastRan: "Tauri required" }
            : t
        )
      );
      return;
    }
    const started = performance.now();
    const result = await runTerminalCommand(task.command);
    const seconds = ((performance.now() - started) / 1000).toFixed(1);
    const ok = result !== null && result.exit_code === 0 && !result.timed_out;
    setTasks((prev) =>
      prev.map((t) =>
        t.id === id
          ? {
              ...t,
              status: ok ? "success" : "failed",
              lastDuration: `${seconds}s`,
              lastRan: "just now",
            }
          : t
      )
    );
  };

  // Intentionally does NOT flip status back to "idle": run_terminal_command has no
  // cancellation handle (no PID/session returned to the frontend), so the real
  // child process keeps running regardless of what this button does. The old
  // version silently flipped the UI to "idle" and re-enabled Play -- looked like
  // Stop worked while the real process kept running underneath, and a second
  // click could launch an overlapping duplicate. Found live 2026-07-19 auditing
  // this exact panel. A real fix needs run_terminal_command to hand back a
  // trackable handle and a real kill_terminal_command -- not attempted here.

  const addTask = () => {
    if (!addLabel.trim() || !addCommand.trim()) return;
    const newTask: Task = {
      id: `custom-${Date.now()}`,
      label: addLabel,
      command: addCommand,
      status: "idle",
    };
    setTasks((prev) => [...prev, newTask]);
    setAddLabel("");
    setAddCommand("");
    setShowAdd(false);
  };

  const remove = (id: string) => setTasks((prev) => prev.filter((t) => t.id !== id));

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div
        className="shrink-0 flex items-center justify-between px-4 py-2.5 border-b"
        style={{ borderColor: "var(--determinex-border)", background: "rgba(0,0,0,0.2)" }}
      >
        <span className="text-eyebrow uppercase font-black tracking-widest text-gray-600">
          {tasks.length} tasks
        </span>
        <button
          onClick={() => setShowAdd((v) => !v)}
          className="flex items-center gap-1.5 rounded-lg border border-white/8 bg-white/[0.03] px-2.5 py-1 text-meta font-bold text-gray-500 hover:text-gray-300 transition-all"
        >
          <Plus size={10} /> Add Task
        </button>
      </div>

      {showAdd && (
        <div
          className="shrink-0 flex flex-col gap-2 border-b px-4 py-3"
          style={{ borderColor: "var(--determinex-border)", background: "rgba(0,0,0,0.3)" }}
        >
          <input
            value={addLabel}
            onChange={(e) => setAddLabel(e.target.value)}
            placeholder="Task name"
            className="rounded-lg border border-white/8 bg-black/30 px-3 py-2 text-label text-white/70 placeholder:text-gray-700 outline-none focus:border-[var(--determinex-accent)]/30"
          />
          <input
            value={addCommand}
            onChange={(e) => setAddCommand(e.target.value)}
            placeholder="Shell command"
            onKeyDown={(e) => e.key === "Enter" && addTask()}
            className="rounded-lg border border-white/8 bg-black/30 px-3 py-2 text-label font-mono text-white/70 placeholder:text-gray-700 outline-none focus:border-[var(--determinex-accent)]/30"
          />
          <div className="flex gap-2">
            <button
              onClick={addTask}
              className="flex-1 rounded-lg py-1.5 text-label font-bold text-black transition-all"
              style={{ background: "var(--determinex-accent)" }}
            >
              Save
            </button>
            <button
              onClick={() => setShowAdd(false)}
              className="rounded-lg border border-white/8 px-3 py-1.5 text-label text-gray-500 hover:text-gray-300"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto no-scrollbar divide-y divide-white/[0.03]">
        {tasks.map((task) => {
          const { icon: StatusIcon, color } = STATUS_CONFIG[task.status];
          return (
            <div
              key={task.id}
              className="group flex items-center gap-3 px-4 py-3 hover:bg-white/[0.02] transition-colors"
            >
              <StatusIcon
                size={13}
                className={`shrink-0 ${color} ${task.status === "running" ? "animate-spin" : ""}`}
              />
              <div className="flex-1 min-w-0">
                <div className="text-label font-semibold text-white/80">{task.label}</div>
                <div className="text-meta font-mono text-gray-600 truncate mt-0.5">
                  {task.command}
                </div>
              </div>
              {task.lastRan && (
                <div className="text-right shrink-0">
                  <div className={`text-meta font-mono ${color}`}>{task.lastDuration}</div>
                  <div className="text-meta text-gray-700">{task.lastRan}</div>
                </div>
              )}
              <div className="flex items-center gap-1 shrink-0">
                {task.status === "running" ? (
                  <button
                    disabled
                    title="Not wired yet -- the real process can't be cancelled from here (see code comment)."
                    className="rounded-lg border border-white/8 bg-white/[0.03] p-1.5 text-gray-700 cursor-not-allowed opacity-50"
                  >
                    <Square size={10} />
                  </button>
                ) : (
                  <button
                    onClick={() => run(task.id)}
                    className="rounded-lg border border-white/8 bg-white/[0.03] p-1.5 text-gray-600 hover:text-emerald-400 hover:border-emerald-500/30 transition-all"
                  >
                    <Play size={10} />
                  </button>
                )}
                {!task.builtin && (
                  <button
                    onClick={() => remove(task.id)}
                    className="opacity-0 group-hover:opacity-100 rounded-lg p-1.5 text-gray-700 hover:text-red-400 transition-all"
                  >
                    <Trash2 size={10} />
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

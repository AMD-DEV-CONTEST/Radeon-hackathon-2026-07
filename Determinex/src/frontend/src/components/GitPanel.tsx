"use client";
import React, { useState, useEffect } from "react";
import dynamic from "next/dynamic";
import {
  AlertCircle,
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Check,
  FileCode,
  GitBranch,
  Minus,
  Plus,
  RefreshCw,
} from "lucide-react";
import {
  getGitStatus,
  stageFile,
  unstageFile,
  stageAll,
  commitChanges,
  getGitBranches,
  createGitBranch,
  checkoutBranch,
  pushCommits,
  pullCommits,
  GitFile,
} from "@/lib/gitService";
import { languageForPath } from "@/lib/language";
import { isTauri } from "@/lib/api";

const DiffEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.DiffEditor), {
  ssr: false,
  loading: () => (
    <div className="flex-1 flex items-center justify-center text-label font-mono text-gray-700">
      Loading diff…
    </div>
  ),
});

type Props = {
  workspacePath: string;
};

export default function GitPanel({ workspacePath }: Props) {
  const [status, setStatus] = useState<{
    branch: string;
    upstream: string | null;
    files: GitFile[];
    ahead: number;
    behind: number;
  } | null>(null);
  const [branches, setBranches] = useState<{ name: string; isCurrent: boolean }[]>([]);
  const [selectedFile, setSelectedFile] = useState<GitFile | null>(null);
  const [commitMsg, setCommitMsg] = useState("");
  const [newBranchName, setNewBranchName] = useState("");
  const [showAddBranch, setShowAddBranch] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = async () => {
    if (!workspacePath) return;
    setIsLoading(true);
    setError(null);
    try {
      const s = await getGitStatus(workspacePath);
      const b = await getGitBranches(workspacePath);
      setStatus(s);
      setBranches(b);
    } catch (e: any) {
      setError(e.message || "Failed to load Git status");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (!isTauri()) return;
    loadStatus();
    setSelectedFile(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspacePath]);

  // gitService's write helpers now reject on a real backend failure instead of
  // swallowing it (they returned void either way before, so a rejected stage or
  // push looked exactly like a successful one). These handlers had no catch at
  // all, so they need one now -- otherwise the honest error just becomes an
  // unhandled rejection in the dev overlay.
  const handleStage = async (path: string) => {
    try {
      await stageFile(workspacePath, path);
      if (selectedFile?.path === path) {
        setSelectedFile((prev) => (prev ? { ...prev, status: "staged" } : null));
      }
    } catch (e: any) {
      setError(e?.message || `Could not stage ${path}`);
    }
    loadStatus();
  };

  const handleUnstage = async (path: string) => {
    try {
      await unstageFile(workspacePath, path);
      if (selectedFile?.path === path) {
        setSelectedFile((prev) => (prev ? { ...prev, status: "modified" } : null));
      }
    } catch (e: any) {
      setError(e?.message || `Could not unstage ${path}`);
    }
    loadStatus();
  };

  const handleStageAll = async () => {
    try {
      await stageAll(workspacePath);
    } catch (e: any) {
      setError(e?.message || "Could not stage all changes");
    }
    loadStatus();
  };

  const handleCommit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!commitMsg.trim()) return;
    try {
      await commitChanges(workspacePath, commitMsg);
      setCommitMsg("");
      setSelectedFile(null);
      loadStatus();
    } catch (e: any) {
      setError(e.message || "Commit failed");
    }
  };

  const handleCreateBranch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newBranchName.trim()) return;
    try {
      await createGitBranch(workspacePath, newBranchName);
      setNewBranchName("");
      setShowAddBranch(false);
      loadStatus();
    } catch (e: any) {
      setError(e.message || "Branch creation failed");
    }
  };

  const handleCheckout = async (name: string) => {
    try {
      await checkoutBranch(workspacePath, name);
      loadStatus();
    } catch (e: any) {
      setError(e.message || "Branch switch failed");
    }
  };

  // Push and pull are the two most likely to fail for reasons the user must
  // see (no upstream, auth, rejected non-fast-forward). Both previously
  // reported nothing at all.
  const handlePush = async () => {
    setError(null);
    try {
      await pushCommits(workspacePath);
    } catch (e: any) {
      setError(e?.message || "Push failed");
    }
    loadStatus();
  };

  const handlePull = async () => {
    setError(null);
    try {
      await pullCommits(workspacePath);
    } catch (e: any) {
      setError(e?.message || "Pull failed");
    }
    loadStatus();
  };

  if (!workspacePath) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 bg-[var(--dtx-code-bg)] text-label font-mono text-gray-600">
        No workspace open.
      </div>
    );
  }

  if (!isTauri()) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-2 p-4 bg-[var(--dtx-code-bg)] text-center opacity-40">
        <p className="text-label text-gray-500">Browser mode cannot read real git status</p>
        <p className="text-label text-gray-600">
          Open the Tauri desktop app to stage, commit, and push.
        </p>
      </div>
    );
  }

  // A FAILURE IS NOT A LOAD. `error` is rendered far below, inside the main body -- which is
  // unreachable while `status` is null, so every failed read showed as an eternal
  // "Loading Git Status..." and the real reason was discarded. Found by driving all 33
  // surfaces: Source Control was the only one that rendered nothing actionable, while the
  // backend was returning branch `mojibake-and-count-fix` and 17 changed files perfectly.
  //
  // Three states, three answers, and a way out of each.
  if (!status && error) {
    return (
      <div data-testid="git-panel-error" className="flex-1 flex flex-col items-center justify-center gap-3 p-4 bg-[var(--dtx-code-bg)] text-center">
        <div className="flex items-center gap-2 text-label font-mono text-amber-300">
          <AlertCircle className="h-3.5 w-3.5" />
          Could not read this repository
        </div>
        <p className="max-w-xs text-label font-mono text-gray-500">{error}</p>
        <button
          type="button"
          onClick={() => void loadStatus()}
          className="rounded-md border border-white/10 px-2.5 py-1 text-eyebrow font-bold uppercase tracking-wide text-gray-400 hover:bg-white/5 hover:text-gray-200"
        >
          Try again
        </button>
      </div>
    );
  }

  // Distinguishable states. The first version of this fix kept the same words for the
  // loading branch, so a check could not tell "still loading" from "the fix never shipped" --
  // both rendered 21 characters. A state a test cannot name is a state nobody can diagnose.
  if (!status) {
    return (
      <div
        data-testid={isLoading ? "git-panel-loading" : "git-panel-idle"}
        className="flex-1 flex items-center justify-center p-4 bg-[var(--dtx-code-bg)]"
      >
        <div className="flex items-center gap-2 text-label font-mono text-gray-500 animate-pulse">
          <RefreshCw className="h-3 w-3 animate-spin" />
          {isLoading ? "Loading Git Status..." : "Waiting for a workspace..."}
        </div>
      </div>
    );
  }

  const stagedFiles = status.files.filter((f) => f.status === "staged");
  const unstagedFiles = status.files.filter((f) => f.status !== "staged");

  return (
    <div className="flex flex-col h-full bg-[var(--dtx-code-bg)] text-gray-300 font-mono text-label border-l border-white/5">
      {/* Header Panel */}
      <div className="flex items-center justify-between p-3 border-b border-white/5 bg-[var(--dtx-code-panel)]">
        <div className="flex items-center gap-1.5 font-semibold text-white">
          <GitBranch className="h-3.5 w-3.5 text-blue-400" />
          <span>Source Control</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadStatus}
            disabled={isLoading}
            className="p-1 hover:bg-white/5 rounded text-gray-400 hover:text-white transition-colors"
            title="Refresh Status"
          >
            <RefreshCw className={`h-3 w-3 ${isLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Sync / Remote status */}
      <div className="flex items-center justify-between px-3 py-2 bg-[var(--dtx-code-panel)]/50 border-b border-white/5 text-label">
        <div className="flex items-center gap-3">
          <button
            onClick={handlePull}
            className="flex items-center gap-1 hover:text-white transition-colors"
          >
            <ArrowDown className="h-3 w-3 text-green-400" />
            <span>Pull ({status.behind})</span>
          </button>
          <button
            onClick={handlePush}
            className="flex items-center gap-1 hover:text-white transition-colors"
          >
            <ArrowUp className="h-3 w-3 text-blue-400" />
            <span>Push ({status.ahead})</span>
          </button>
        </div>
        <span className="text-gray-500">{status.upstream || "no upstream"}</span>
      </div>

      {/* Main Grid Content split */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Side: File lists */}
        <div className="w-1/2 border-r border-white/5 flex flex-col overflow-y-auto">
          {/* Branch switcher */}
          <div className="p-3 border-b border-white/5">
            <div className="text-gray-500 mb-1">Branch</div>
            <div className="flex items-center gap-2">
              <select
                value={status.branch}
                onChange={(e) => handleCheckout(e.target.value)}
                className="flex-1 bg-[var(--dtx-code-bg)] border border-white/10 rounded px-2 py-1 text-white focus:outline-none focus:border-blue-500"
              >
                {branches.map((b) => (
                  <option key={b.name} value={b.name}>
                    {b.name}
                  </option>
                ))}
              </select>
              <button
                onClick={() => setShowAddBranch(!showAddBranch)}
                className="p-1.5 bg-[var(--dtx-code-border-subtle)] hover:bg-[var(--dtx-code-border)] text-white rounded transition-colors"
                title="Create Branch"
              >
                <Plus className="h-3 w-3" />
              </button>
            </div>

            {showAddBranch && (
              <form onSubmit={handleCreateBranch} className="mt-2 flex items-center gap-1.5">
                <input
                  type="text"
                  placeholder="New branch name"
                  value={newBranchName}
                  onChange={(e) => setNewBranchName(e.target.value)}
                  className="flex-1 bg-[var(--dtx-code-bg)] border border-white/10 rounded px-2 py-0.5 text-white focus:outline-none"
                />
                <button
                  type="submit"
                  className="px-2 py-0.5 bg-blue-600 hover:bg-blue-500 text-white rounded"
                >
                  Create
                </button>
              </form>
            )}
          </div>

          {/* Staged Section */}
          <div className="p-2">
            <div className="flex items-center justify-between text-gray-500 font-bold px-1 mb-1">
              <span>Staged Changes ({stagedFiles.length})</span>
            </div>
            {stagedFiles.length === 0 ? (
              <div className="text-label text-gray-600 px-1 italic">No staged files</div>
            ) : (
              stagedFiles.map((file) => (
                <div
                  key={file.path}
                  onClick={() => setSelectedFile(file)}
                  className={`group flex items-center justify-between p-1 rounded cursor-pointer hover:bg-white/5 transition-colors ${
                    selectedFile?.path === file.path ? "bg-white/5" : ""
                  }`}
                >
                  <div className="flex items-center gap-1.5 truncate">
                    <FileCode className="h-3.5 w-3.5 text-blue-400 shrink-0" />
                    <span className="truncate text-white">{file.path.split("/").pop()}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="text-meta px-1 bg-green-500/20 text-green-400 rounded">
                      {file.code || "A"}
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleUnstage(file.path);
                      }}
                      className="p-0.5 hover:bg-white/10 rounded text-gray-500 hover:text-white"
                      title="Unstage file"
                    >
                      <Minus className="h-2.5 w-2.5" />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Unstaged Section */}
          <div className="p-2 border-t border-white/5 flex-1">
            <div className="flex items-center justify-between text-gray-500 font-bold px-1 mb-1">
              <span>Changes ({unstagedFiles.length})</span>
              {unstagedFiles.length > 0 && (
                <button
                  onClick={handleStageAll}
                  className="text-meta hover:text-white transition-colors flex items-center gap-0.5"
                >
                  <Plus className="h-2 w-2" /> Stage All
                </button>
              )}
            </div>
            {unstagedFiles.length === 0 ? (
              <div className="text-label text-gray-600 px-1 italic">No unstaged changes</div>
            ) : (
              unstagedFiles.map((file) => (
                <div
                  key={file.path}
                  onClick={() => setSelectedFile(file)}
                  className={`group flex items-center justify-between p-1 rounded cursor-pointer hover:bg-white/5 transition-colors ${
                    selectedFile?.path === file.path ? "bg-white/5" : ""
                  }`}
                >
                  <div className="flex items-center gap-1.5 truncate">
                    <FileCode className="h-3.5 w-3.5 text-gray-500 shrink-0" />
                    <span className="truncate">{file.path.split("/").pop()}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span
                      className={`text-meta px-1 rounded ${
                        file.status === "untracked"
                          ? "bg-yellow-500/20 text-yellow-400"
                          : "bg-blue-500/20 text-blue-400"
                      }`}
                    >
                      {file.code || (file.status === "untracked" ? "U" : "M")}
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleStage(file.path);
                      }}
                      className="p-0.5 hover:bg-white/10 rounded text-gray-500 hover:text-white"
                      title="Stage file"
                    >
                      <Plus className="h-2.5 w-2.5" />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Commit Box Form */}
          <div className="p-3 border-t border-white/5 bg-[var(--dtx-code-panel)]/50">
            {error && (
              <div className="flex items-start gap-1 p-2 bg-red-950/30 border border-red-500/20 rounded text-red-400 mb-2 text-label">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}
            <form onSubmit={handleCommit} className="flex flex-col gap-2">
              <textarea
                placeholder="Commit message... (Ctrl+Enter)"
                value={commitMsg}
                onChange={(e) => setCommitMsg(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                    handleCommit(e);
                  }
                }}
                className="w-full h-14 bg-[var(--dtx-code-bg)] border border-white/10 rounded p-2 text-white placeholder-gray-600 focus:outline-none focus:border-blue-500 resize-none"
              />
              <button
                type="submit"
                disabled={stagedFiles.length === 0}
                className="w-full py-1.5 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800/40 disabled:text-gray-600 font-bold rounded flex items-center justify-center gap-1.5 transition-colors text-white"
              >
                <Check className="h-3.5 w-3.5" />
                <span>Commit {stagedFiles.length > 0 ? `(${stagedFiles.length} files)` : ""}</span>
              </button>
            </form>
          </div>
        </div>

        {/* Right Side: Diff / Details Viewer */}
        <div className="w-1/2 flex flex-col bg-[#0b0e14] overflow-hidden">
          {selectedFile ? (
            <div className="flex-1 flex flex-col h-full overflow-hidden">
              <div className="p-3 border-b border-white/5 bg-[var(--dtx-code-panel)] flex items-center justify-between">
                <span className="font-semibold text-white">{selectedFile.path}</span>
                <span className="text-gray-500 text-meta uppercase">{selectedFile.status}</span>
              </div>
              <div className="flex-1">
                <DiffEditor
                  height="100%"
                  language={languageForPath(selectedFile.path)}
                  theme="vs-dark"
                  original={selectedFile.originalContent ?? ""}
                  modified={selectedFile.currentContent ?? ""}
                  options={{
                    minimap: { enabled: false },
                    wordWrap: "on",
                    fontSize: 11,
                    readOnly: true,
                  }}
                />
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-gray-600 p-4">
              <FileCode className="h-8 w-8 text-gray-700 mb-2" />
              <span>Select a modified file to view diff</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

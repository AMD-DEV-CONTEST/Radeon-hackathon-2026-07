"use client";
import { useState, useCallback, useEffect, useRef } from "react";
import {
  FileCode,
  FolderOpen,
  Check,
  X,
  ChevronRight,
  Plus,
  Save,
  Columns,
  AlertTriangle,
  List,
  PanelLeftOpen,
  PanelLeftClose,
} from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { isTauri, readFileContent, invokeSafe, getFileSystemTree } from "@/lib/api";
import { getLspDiagnostics, getLspSymbols, LspDiagnostic, LspSymbol } from "@/lib/lspService";
import { FileSystemNode, type FileNode } from "./FileSystemNode";
import dynamic from "next/dynamic";

const MonacoEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.default), {
  ssr: false,
  loading: () => (
    <div className="flex-1 flex items-center justify-center bg-[var(--dtx-code-bg)]">
      <span className="text-label font-mono text-gray-700">Loading editor…</span>
    </div>
  ),
});

type OpenFile = { name: string; path: string; content: string; dirty: boolean; lang: string };

const LANG_MAP: Record<string, string> = {
  py: "python",
  rs: "rust",
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  go: "go",
  toml: "toml",
  json: "json",
  md: "markdown",
  sh: "shell",
  css: "css",
};

// No fake demo files -- an empty tab set is the honest default when nothing has
// been restored from a prior session. A real file only appears once the user
// opens one from the file tree or creates a new one.
const NO_FILE_OPEN: OpenFile[] = [];

function FileBadge({
  name,
  dirty,
  active,
  onClose,
  onClick,
}: {
  name: string;
  dirty: boolean;
  active: boolean;
  onClose: (e: React.MouseEvent) => void;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="group flex items-center gap-2 px-3 py-1.5 border-r border-white/5 transition-all text-left shrink-0"
      style={{ background: active ? "rgba(255,255,255,0.06)" : "transparent" }}
    >
      <span
        className={`text-label font-mono ${active ? "text-white/80" : "text-gray-500 group-hover:text-gray-300"}`}
      >
        {name}
      </span>
      {dirty && <span className="h-1.5 w-1.5 rounded-full bg-amber-400 shrink-0" />}
      <span
        onClick={onClose}
        className="text-gray-700 hover:text-white transition-colors shrink-0 hidden group-hover:block"
      >
        <X size={10} />
      </span>
    </button>
  );
}

interface EditorPanelProps {
  // Set by the main app when a real file is opened from the file-explorer tree
  // (see handleOpenFile in app/page.tsx). `requestId` increments on every open
  // request so re-opening the same path (e.g. after an external edit) still
  // triggers the effect below.
  pendingFile?: { path: string; content: string; requestId: number } | null;
  // The open workspace root -- lets get_lsp_diagnostics scope its cargo check to the
  // real project instead of the app's own ambient cwd.
  workspacePath?: string;
}

function langForPath(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() || "";
  return LANG_MAP[ext] || "plaintext";
}

export function EditorPanel({ pendingFile, workspacePath = "" }: EditorPanelProps = {}) {
  const [openFiles, setOpenFiles] = useState<OpenFile[]>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("determinex_editor_tabs");
      if (saved) {
        try {
          return JSON.parse(saved);
        } catch (e) {}
      }
    }
    return NO_FILE_OPEN;
  });
  const [activeIdx, setActiveIdx] = useState(0);
  const [rightActiveIdx, setRightActiveIdx] = useState(1);
  const [saving, setSaving] = useState(false);
  const [isSplit, setIsSplit] = useState(false);
  const [closedTabs, setClosedTabs] = useState<OpenFile[]>([]);
  const [diagnostics, setDiagnostics] = useState<LspDiagnostic[]>([]);
  const [symbols, setSymbols] = useState<LspSymbol[]>([]);
  const [showOutline, setShowOutline] = useState(false);
  const [editorRef, setEditorRef] = useState<any>(null);
  const tauriMode = isTauri();

  const activeFile = openFiles[activeIdx];
  const rightActiveFile = openFiles[rightActiveIdx] || openFiles[0];

  // Shared by both file-open paths: a file pushed in from outside (Space's own
  // tree, via the pendingFile prop) and the embedded tree below. Re-opening an
  // already-open path refreshes its content and re-focuses it instead of
  // duplicating the tab.
  const openOrFocusFile = useCallback((path: string, content: string) => {
    const name = path.split("\\").pop()?.split("/").pop() || path;
    setOpenFiles((prev) => {
      const existingIdx = prev.findIndex((f) => f.path === path);
      if (existingIdx >= 0) {
        const next = [...prev];
        next[existingIdx] = { ...next[existingIdx], content, dirty: false };
        setActiveIdx(existingIdx);
        return next;
      }
      const opened: OpenFile = { name, path, content, dirty: false, lang: langForPath(path) };
      setActiveIdx(prev.length);
      return [...prev, opened];
    });
  }, []);

  // Open a real file requested from the file-explorer tree (see EditorPanelProps).
  // Re-opening the same path (new requestId) refreshes its content and re-focuses it.
  const lastHandledRequestId = useRef(0);
  useEffect(() => {
    if (!pendingFile || pendingFile.requestId === lastHandledRequestId.current) return;
    lastHandledRequestId.current = pendingFile.requestId;
    openOrFocusFile(pendingFile.path, pendingFile.content);
  }, [pendingFile, openOrFocusFile]);

  // Embedded file browser -- previously this panel had NO way to open a file on
  // its own; it only ever showed something if Space's separate tree had already
  // pushed one in via pendingFile. Ryan, live: "we have no way to really look at
  // files... even though the capability exists." Every real code editor keeps
  // its own tree beside the buffer; this gives Code that, reusing the same
  // FileSystemNode/getFileSystemTree Space already uses.
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [showTree, setShowTree] = useState(true);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [noAiContext] = useState<string[]>([]);

  useEffect(() => {
    if (!workspacePath || !tauriMode) return;
    getFileSystemTree(workspacePath)
      .then((res) => setFileTree(res.tree ?? []))
      .catch((err) => setTreeError(String(err)));
  }, [workspacePath, tauriMode]);

  const openFromTree = useCallback(
    async (path: string) => {
      try {
        const res = await readFileContent(path);
        if (res) openOrFocusFile(path, res.content);
      } catch (err) {
        setTreeError(`Could not read ${path.split(/[\\/]/).pop()}: ${err}`);
      }
    },
    [openOrFocusFile]
  );

  // Load diagnostics and symbols
  useEffect(() => {
    if (!activeFile) return;
    getLspDiagnostics(activeFile.name, workspacePath).then(setDiagnostics);
    getLspSymbols(activeFile.name).then(setSymbols);
  }, [activeFile?.name, workspacePath]);

  // Set editor markers when diagnostics or editorRef changes
  useEffect(() => {
    if (!editorRef || !activeFile) return;
    const monaco = (window as any).monaco;
    if (monaco) {
      const markers = diagnostics.map((d) => ({
        startLineNumber: d.line,
        startColumn: d.column,
        endLineNumber: d.line,
        endColumn: d.column + 10,
        message: d.message,
        severity:
          d.severity === "error" ? monaco.MarkerSeverity.Error : monaco.MarkerSeverity.Warning,
      }));
      monaco.editor.setModelMarkers(editorRef.getModel(), "owner", markers);
    }
  }, [diagnostics, editorRef, activeFile]);

  // Tab Persistence
  useEffect(() => {
    localStorage.setItem("determinex_editor_tabs", JSON.stringify(openFiles));
  }, [openFiles]);

  // Handle Ctrl+Shift+T tab restoration
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "t") {
        e.preventDefault();
        if (closedTabs.length > 0) {
          const restored = closedTabs[closedTabs.length - 1];
          setOpenFiles((prev) => {
            if (prev.some((f) => f.path === restored.path)) return prev;
            return [...prev, restored];
          });
          setClosedTabs((prev) => prev.slice(0, -1));
          setActiveIdx(openFiles.length);
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [closedTabs, openFiles]);

  const handleChange = useCallback(
    (value: string | undefined) => {
      if (value === undefined) return;
      setOpenFiles((prev) =>
        prev.map((f, i) => (i === activeIdx ? { ...f, content: value, dirty: true } : f))
      );
    },
    [activeIdx]
  );

  const handleRightChange = useCallback(
    (value: string | undefined) => {
      if (value === undefined) return;
      setOpenFiles((prev) =>
        prev.map((f, i) => (i === rightActiveIdx ? { ...f, content: value, dirty: true } : f))
      );
    },
    [rightActiveIdx]
  );

  // Data loss, previously. This used invokeSafe (which swallows a rejection and
  // returns null) and then cleared `dirty` UNCONDITIONALLY -- so a save that
  // failed still marked the file clean. write_file_content genuinely can fail:
  // it rejects a path outside the workspace boundary, and the write itself can
  // fail on a read-only or locked file. The user saw a clean tab, closed it,
  // and the edits were gone with no error anywhere. The catch below only
  // console.error'd, and could never fire regardless.
  //
  // Raw invoke so a rejection actually propagates; dirty is cleared only after
  // the write is confirmed; the failure is shown instead of logged.
  const handleSave = async () => {
    if (!activeFile) return;
    setSaving(true);
    setSaveError(null);
    try {
      if (tauriMode) {
        await invoke("write_file_content", {
          path: activeFile.path,
          content: activeFile.content,
        });
      }
      setOpenFiles((prev) => prev.map((f, i) => (i === activeIdx ? { ...f, dirty: false } : f)));
    } catch (e) {
      // Leave `dirty` set: the buffer still holds the only copy of this work.
      setSaveError(
        `Could not save ${activeFile.name}: ${e instanceof Error ? e.message : String(e)}`
      );
    } finally {
      setSaving(false);
    }
  };

  const handleClose = (e: React.MouseEvent, idx: number) => {
    e.stopPropagation();
    const tabToClose = openFiles[idx];
    setClosedTabs((prev) => [...prev, tabToClose]);
    const next = openFiles.filter((_, i) => i !== idx);
    setOpenFiles(next);
    setActiveIdx(Math.max(0, Math.min(activeIdx, next.length - 1)));
    setRightActiveIdx(Math.max(0, Math.min(rightActiveIdx, next.length - 1)));
  };

  const handleCreateFile = () => {
    const name = `untitled-${openFiles.length + 1}.py`;
    const path = `scripts/${name}`;
    const newF: OpenFile = {
      name,
      path,
      content: "# New python script\n",
      dirty: true,
      lang: "python",
    };
    setOpenFiles((prev) => [...prev, newF]);
    setActiveIdx(openFiles.length);
  };

  // Closes the tab only -- does NOT delete the file from disk. The confirm copy
  // says exactly that; an earlier version said "delete" here while only ever
  // closing the tab, which misled users into thinking this touched their filesystem.
  const handleCloseActiveFile = () => {
    if (!activeFile) return;
    if (
      activeFile.dirty &&
      !confirm(`${activeFile.name} has unsaved changes. Close the tab without saving?`)
    ) {
      return;
    }
    const next = openFiles.filter((_, i) => i !== activeIdx);
    setOpenFiles(next);
    setActiveIdx(Math.max(0, Math.min(activeIdx, next.length - 1)));
  };

  const ext = activeFile?.name.split(".").pop() ?? "";
  const lang = LANG_MAP[ext] ?? "plaintext";

  const rightExt = rightActiveFile?.name.split(".").pop() ?? "";
  const rightLang = LANG_MAP[rightExt] ?? "plaintext";

  return (
    <div
      className="flex h-full min-h-0 flex-col overflow-hidden"
      style={{ background: "var(--dtx-code-bg)" }}
    >
      {/* Tab bar */}
      <div className="flex items-center border-b border-white/8 bg-black/40 overflow-x-auto no-scrollbar shrink-0">
        {openFiles.map((f, i) => (
          <FileBadge
            key={f.path}
            name={f.name}
            dirty={f.dirty}
            active={i === activeIdx}
            onClick={() => setActiveIdx(i)}
            onClose={(e) => handleClose(e, i)}
          />
        ))}
        <button
          onClick={handleCreateFile}
          className="p-2 text-gray-500 hover:text-white transition-colors"
          title="New File"
        >
          <Plus size={12} />
        </button>
        <div className="flex-1" />
        <div className="flex items-center gap-2 px-3">
          {tauriMode && (
            <button
              onClick={() => setShowTree(!showTree)}
              className={`p-1.5 rounded hover:bg-white/5 transition-all ${showTree ? "text-emerald-400" : "text-gray-500"}`}
              title={showTree ? "Hide file tree" : "Show file tree"}
            >
              {showTree ? <PanelLeftClose size={12} /> : <PanelLeftOpen size={12} />}
            </button>
          )}
          <button
            onClick={() => setIsSplit(!isSplit)}
            className={`p-1.5 rounded hover:bg-white/5 transition-all ${isSplit ? "text-blue-400" : "text-gray-500"}`}
            title="Split Editor"
          >
            <Columns size={12} />
          </button>
          <button
            onClick={() => setShowOutline(!showOutline)}
            className={`p-1.5 rounded hover:bg-white/5 transition-all ${showOutline ? "text-cyan-400" : "text-gray-500"}`}
            title="Toggle Outline"
          >
            <List size={12} />
          </button>
          {activeFile && (
            <button
              onClick={handleCloseActiveFile}
              className="p-1.5 text-gray-500 hover:text-red-400 transition-colors"
              title="Close Tab (does not delete the file from disk)"
            >
              <X size={12} />
            </button>
          )}
          {activeFile?.dirty && (
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-1.5 rounded-lg border border-[var(--determinex-accent)]/30 bg-[var(--determinex-accent)]/10 px-2.5 py-1 text-eyebrow font-bold uppercase tracking-widest text-[var(--determinex-accent)] transition-all hover:bg-[var(--determinex-accent)]/20 disabled:opacity-40"
            >
              <Save size={10} />
              {saving ? "Saving…" : "Save"}
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 flex overflow-hidden">
        {showTree && tauriMode && (
          <div className="w-56 shrink-0 overflow-y-auto no-scrollbar border-r border-white/8 bg-black/20 p-2">
            <div className="mb-1.5 flex items-center gap-1.5 px-1 text-eyebrow font-black uppercase tracking-widest text-gray-600">
              <FolderOpen size={11} /> Explorer
            </div>
            {treeError && <p className="px-1 text-meta text-red-400/80">{treeError}</p>}
            {fileTree.length === 0 ? (
              <p className="px-1 text-meta text-gray-700 font-mono italic">
                {workspacePath ? "Scanning…" : "No workspace open."}
              </p>
            ) : (
              fileTree.map((node, i) => (
                <FileSystemNode
                  key={i}
                  node={node}
                  activeContexts={noAiContext}
                  toggleContext={() => {}}
                  handleOpenFile={openFromTree}
                  onFsError={(msg) => setTreeError(msg)}
                />
              ))
            )}
          </div>
        )}
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
          {/* A failed save must be impossible to miss -- the tab keeps its dirty
          dot, and this says why. Dismissible, but it does not auto-clear:
          the buffer holds the only copy of that work until a save succeeds. */}
          {saveError && (
            <div className="flex shrink-0 items-start gap-2 border-b border-red-500/30 bg-red-950/30 px-4 py-2">
              <AlertTriangle size={12} className="mt-0.5 shrink-0 text-red-400" />
              <p className="flex-1 font-mono text-label leading-relaxed text-red-300">
                {saveError} — your changes are still in the editor, unsaved.
              </p>
              <button
                onClick={() => setSaveError(null)}
                className="shrink-0 text-red-400/60 transition-colors hover:text-red-300"
                title="Dismiss"
              >
                <X size={11} />
              </button>
            </div>
          )}

          {/* File path breadcrumb */}
          {activeFile && (
            <div className="flex items-center gap-1.5 border-b border-white/5 bg-black/20 px-4 py-1.5 shrink-0 justify-between">
              <div className="flex items-center gap-1.5">
                {activeFile.path.split("/").map((part, i, arr) => (
                  <span key={i} className="flex items-center gap-1">
                    <span
                      className={`text-meta font-mono ${i === arr.length - 1 ? "text-white/60" : "text-gray-700"}`}
                    >
                      {part}
                    </span>
                    {i < arr.length - 1 && <ChevronRight size={9} className="text-gray-700" />}
                  </span>
                ))}
              </div>
              {isSplit && rightActiveFile && (
                <div className="flex items-center gap-1.5 border-l border-white/10 pl-4">
                  <span className="text-meta font-mono text-blue-400">
                    Right: {rightActiveFile.name}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Monaco Editor splits rendering */}
          {activeFile ? (
            <div className="flex-1 min-h-0 flex overflow-hidden">
              {/* Left editor */}
              <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
                <MonacoEditor
                  value={activeFile.content}
                  language={lang}
                  onChange={handleChange}
                  theme="vs-dark"
                  onMount={(editor) => {
                    setEditorRef(editor);
                    const monaco = (window as any).monaco;
                    if (monaco) {
                      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
                        handleSave();
                      });
                    }
                  }}
                  options={{
                    fontSize: 13,
                    fontFamily: "var(--determinex-font-mono)",
                    fontLigatures: true,
                    minimap: { enabled: false },
                    lineNumbers: "on",
                    scrollBeyondLastLine: false,
                    renderLineHighlight: "gutter",
                    wordWrap: "on",
                    padding: { top: 16, bottom: 16 },
                    tabSize: 2,
                    insertSpaces: true,
                    smoothScrolling: true,
                    cursorBlinking: "phase",
                    bracketPairColorization: { enabled: true },
                  }}
                />
              </div>

              {/* Split Right editor */}
              {isSplit && rightActiveFile && (
                <div className="flex-1 min-h-0 overflow-hidden flex flex-col border-l border-white/10">
                  <div className="p-1 bg-[var(--dtx-code-panel)]/50 border-b border-white/5 flex items-center gap-2">
                    <select
                      value={rightActiveIdx}
                      onChange={(e) => setRightActiveIdx(Number(e.target.value))}
                      className="bg-[var(--dtx-code-bg)] border border-white/10 rounded px-1 text-white text-meta"
                    >
                      {openFiles.map((f, i) => (
                        <option key={f.path} value={i}>
                          {f.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <MonacoEditor
                    value={rightActiveFile.content}
                    language={rightLang}
                    onChange={handleRightChange}
                    theme="vs-dark"
                    options={{
                      fontSize: 12,
                      fontFamily: "var(--determinex-font-mono)",
                      minimap: { enabled: false },
                      lineNumbers: "on",
                      scrollBeyondLastLine: false,
                      wordWrap: "on",
                      tabSize: 2,
                    }}
                  />
                </div>
              )}

              {/* Outline Sidebar */}
              {showOutline && (
                <div className="w-64 border-l border-white/10 bg-[var(--dtx-code-panel)]/90 flex flex-col font-mono text-label text-gray-300">
                  <div className="p-3 border-b border-white/5 flex items-center justify-between text-white font-bold bg-black/20">
                    <span>OUTLINE & DIAGNOSTICS</span>
                  </div>
                  <div className="flex-1 overflow-y-auto p-3 space-y-4">
                    {/* Diagnostics List */}
                    <div>
                      <div className="text-gray-500 font-bold uppercase tracking-wider mb-1">
                        Diagnostics ({diagnostics.length})
                      </div>
                      {diagnostics.length === 0 ? (
                        <div className="text-gray-600 italic text-meta">No diagnostics found.</div>
                      ) : (
                        diagnostics.map((d, i) => (
                          <div
                            key={i}
                            className="flex gap-1.5 p-1 bg-black/10 rounded mb-1 text-gray-400"
                          >
                            <AlertTriangle
                              className={`h-3 w-3 shrink-0 mt-0.5 ${d.severity === "error" ? "text-red-400" : "text-yellow-400"}`}
                            />
                            <div>
                              <div className="text-white font-semibold">[Line {d.line}]</div>
                              <div>{d.message}</div>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                    {/* Outline Symbols */}
                    <div>
                      <div className="text-gray-500 font-bold uppercase tracking-wider mb-1">
                        Symbols ({symbols.length})
                      </div>
                      {symbols.length === 0 ? (
                        <div className="text-gray-600 italic text-meta">No symbols defined.</div>
                      ) : (
                        symbols.map((s, i) => (
                          <div
                            key={i}
                            onClick={() => {
                              if (editorRef) {
                                editorRef.revealLineInCenter(s.line);
                                editorRef.setPosition({ lineNumber: s.line, column: 1 });
                                editorRef.focus();
                              }
                            }}
                            className="p-1 hover:bg-white/5 rounded cursor-pointer flex items-center justify-between text-gray-400 hover:text-white"
                          >
                            <span>{s.name}</span>
                            <span className="text-eyebrow px-1 bg-cyan-900/30 text-cyan-400 rounded uppercase">
                              {s.kind}
                            </span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center">
              <div className="h-16 w-16 rounded-2xl border border-white/8 bg-white/[0.03] flex items-center justify-center">
                <FileCode size={28} className="text-gray-700" />
              </div>
              <p className="text-body font-bold text-gray-600">No files open</p>
              <p className="text-label text-gray-700 font-mono">
                {!tauriMode
                  ? "Open a file to start editing"
                  : showTree
                    ? "Pick a file from Explorer on the left"
                    : "Open the file tree, or create a new file above"}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Status bar */}
      <div className="flex items-center gap-4 border-t border-white/5 bg-black/50 px-4 py-1.5 shrink-0">
        {activeFile && (
          <>
            <span className="text-meta font-mono text-gray-700">{lang}</span>
            <span className="text-meta font-mono text-gray-700">UTF-8</span>
            <span className="text-meta font-mono text-gray-700">LF</span>
            {activeFile.dirty && (
              <span className="text-meta font-mono text-amber-500">● unsaved</span>
            )}
          </>
        )}
        <div className="flex-1" />
        {!tauriMode && (
          <span className="text-meta font-mono text-gray-500">
            Sandbox/Web Mock Save mode active
          </span>
        )}
      </div>
    </div>
  );
}

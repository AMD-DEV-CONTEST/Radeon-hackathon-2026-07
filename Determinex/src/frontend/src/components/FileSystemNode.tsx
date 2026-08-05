import { useEffect, useMemo, useState } from "react";
import { ChevronRight, Folder, FileText } from "lucide-react";
import { createPath, deletePath, getFileSystemTree, renamePath, revealInExplorer } from "@/lib/api";

// Maximum children to render per directory level to prevent DOM explosion
const MAX_RENDER_CHILDREN = 200;

export interface FileNode {
  name: string;
  path: string;
  isDir: boolean;
  children?: FileNode[];
}

export type GitStatusEntry = { status: string; code: string };

function pathSeparator(path: string): "\\" | "/" {
  return path.includes("\\") ? "\\" : "/";
}

function parentDirOf(path: string): string {
  const idx = Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
  return idx >= 0 ? path.slice(0, idx) : path;
}

function isDescendantPath(candidate: string, ancestor: string): boolean {
  const normCandidate = candidate.replace(/\\/g, "/");
  const normAncestor = ancestor.replace(/\\/g, "/").replace(/\/+$/, "");
  return normCandidate.startsWith(`${normAncestor}/`);
}

/** VS Code-style single-letter status badge: real code/status, never fabricated. */
function gitBadge(entry?: GitStatusEntry): { letter: string; className: string } | null {
  if (!entry) return null;
  if (entry.status === "conflicted") return { letter: "!", className: "text-red-400" };
  if (entry.status === "untracked") return { letter: "U", className: "text-emerald-400" };
  const bare = entry.code.replace(/\s/g, "");
  if (entry.status === "staged") {
    return { letter: bare[0] || "M", className: "text-emerald-400" };
  }
  return { letter: bare[bare.length - 1] || "M", className: "text-amber-400" };
}

type ContextMenuState = { x: number; y: number } | null;

export const FileSystemNode = ({
  node,
  depth = 0,
  activeContexts,
  toggleContext,
  setExplorerRoot,
  handleOpenFile,
  gitStatusMap,
  onFsError,
}: {
  node: FileNode;
  depth?: number;
  activeContexts: string[];
  toggleContext: (path: string) => void;
  setExplorerRoot?: (path: string) => void;
  handleOpenFile?: (path: string) => void;
  gitStatusMap?: Record<string, GitStatusEntry>;
  onFsError?: (message: string) => void;
}) => {
  const [localNode, setLocalNode] = useState(node);
  useEffect(() => setLocalNode(node), [node]);

  const [isOpen, setIsOpen] = useState(false);
  const [children, setChildren] = useState<FileNode[]>(node.children || []);
  const [isLoading, setIsLoading] = useState(false);
  const [isDeleted, setIsDeleted] = useState(false);
  const [menu, setMenu] = useState<ContextMenuState>(null);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(node.name);
  const [creating, setCreating] = useState<"file" | "folder" | null>(null);
  const [createValue, setCreateValue] = useState("");
  const isWhitelisted = activeContexts.includes(localNode.name);

  const reportError = (message: string) => {
    if (onFsError) onFsError(message);
    else console.error(message);
  };

  const refreshChildren = async () => {
    const data = await getFileSystemTree(localNode.path);
    setChildren(data?.tree || []);
  };

  const handleDisplayToggle = async (e: React.MouseEvent) => {
    if (e.shiftKey && localNode.isDir && setExplorerRoot) {
      setExplorerRoot(localNode.path);
      return;
    }
    if (!localNode.isDir) {
      if (e.shiftKey) {
        toggleContext(localNode.name);
      } else if (handleOpenFile) {
        handleOpenFile(localNode.path);
      } else {
        toggleContext(localNode.name);
      }
      return;
    }

    if (!isOpen && children.length === 0) {
      setIsLoading(true);
      await refreshChildren().catch(() => {});
      setIsLoading(false);
    }
    setIsOpen(!isOpen);
  };

  const openContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setMenu({ x: e.clientX, y: e.clientY });
  };

  const startRename = () => {
    setRenameValue(localNode.name);
    setRenaming(true);
    setMenu(null);
  };

  const submitRename = async () => {
    const trimmed = renameValue.trim();
    if (!trimmed || trimmed === localNode.name) {
      setRenaming(false);
      return;
    }
    const sep = pathSeparator(localNode.path);
    const newPath = `${parentDirOf(localNode.path)}${sep}${trimmed}`;
    try {
      await renamePath(localNode.path, newPath);
      setLocalNode((prev) => ({ ...prev, name: trimmed, path: newPath }));
      setRenaming(false);
    } catch (err) {
      reportError(`Rename failed: ${err}`);
    }
  };

  const runDelete = async () => {
    setMenu(null);
    const kind = localNode.isDir ? "folder (and everything inside it)" : "file";
    if (!window.confirm(`Delete this ${kind}?\n\n${localNode.path}`)) return;
    try {
      await deletePath(localNode.path);
      setIsDeleted(true);
    } catch (err) {
      reportError(`Delete failed: ${err}`);
    }
  };

  const startCreate = (kind: "file" | "folder") => {
    setCreateValue("");
    setCreating(kind);
    setMenu(null);
    setIsOpen(true);
  };

  const submitCreate = async () => {
    if (!creating) return;
    const trimmed = createValue.trim();
    if (!trimmed) {
      setCreating(null);
      return;
    }
    const sep = pathSeparator(localNode.path);
    const newPath = `${localNode.path.replace(/[\\/]+$/, "")}${sep}${trimmed}`;
    try {
      await createPath(newPath, creating === "folder");
      setCreating(null);
      await refreshChildren();
    } catch (err) {
      reportError(`Create failed: ${err}`);
    }
  };

  const copyPath = () => {
    void navigator.clipboard.writeText(localNode.path);
    setMenu(null);
  };

  const reveal = async () => {
    setMenu(null);
    try {
      await revealInExplorer(localNode.path);
    } catch (err) {
      reportError(`Reveal in Explorer failed: ${err}`);
    }
  };

  const gitEntry =
    gitStatusMap?.[localNode.path.replace(/\\/g, "/")] ?? gitStatusMap?.[localNode.path];
  const badge = gitBadge(gitEntry);
  const hasDescendantChanges = useMemo(() => {
    if (!localNode.isDir || !gitStatusMap) return false;
    return Object.keys(gitStatusMap).some((p) => isDescendantPath(p, localNode.path));
  }, [gitStatusMap, localNode.isDir, localNode.path]);

  if (isDeleted) return null;

  // Cap rendering to prevent DOM explosion on massive directories
  const visibleChildren = children.slice(0, MAX_RENDER_CHILDREN);
  const isTruncated = children.length > MAX_RENDER_CHILDREN;

  return (
    <div className="flex flex-col">
      <div
        onClick={(e) => handleDisplayToggle(e)}
        onContextMenu={openContextMenu}
        style={{ paddingLeft: `${depth * 14 + 4}px` }}
        className={`flex items-center gap-1.5 py-0.5 cursor-pointer transition-colors group ${isWhitelisted && !localNode.isDir ? "bg-cyan-950/40" : "hover:bg-[var(--dtx-code-border)] text-[#CCCCCC] border border-transparent"}`}
      >
        <div className="w-[14px] shrink-0 flex justify-center items-center">
          {localNode.isDir && (
            <ChevronRight
              size={14}
              className={`text-gray-400 transition-transform ${isOpen ? "rotate-90" : ""}`}
            />
          )}
        </div>
        {localNode.isDir ? (
          <Folder size={14} className="text-[var(--dtx-info)] shrink-0" />
        ) : (
          <FileText
            size={14}
            className={`shrink-0 ${badge ? badge.className : isWhitelisted ? "text-cyan-400" : "text-[var(--dtx-info)]"}`}
          />
        )}
        {renaming ? (
          <input
            autoFocus
            value={renameValue}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void submitRename();
              if (e.key === "Escape") setRenaming(false);
            }}
            onBlur={() => void submitRename()}
            className="min-w-0 flex-1 rounded border border-cyan-500/50 bg-black/60 px-1 text-body font-mono text-gray-100 outline-none"
          />
        ) : (
          <span
            className={`truncate text-body font-mono whitespace-pre ${badge ? badge.className : ""}`}
          >
            {localNode.name}
          </span>
        )}
        {badge && !renaming && (
          <span className={`ml-auto shrink-0 pr-1 text-label font-black ${badge.className}`}>
            {badge.letter}
          </span>
        )}
        {!badge && hasDescendantChanges && !renaming && (
          <span
            className="ml-auto shrink-0 pr-1.5 text-amber-400"
            title="Contains uncommitted changes"
          >
            <span className="block h-1.5 w-1.5 rounded-full bg-current" />
          </span>
        )}
      </div>

      {creating && (
        <div
          style={{ paddingLeft: `${(depth + 1) * 14 + 22}px` }}
          className="flex items-center gap-1.5 py-0.5"
        >
          {creating === "folder" ? (
            <Folder size={14} className="text-[var(--dtx-info)] shrink-0" />
          ) : (
            <FileText size={14} className="shrink-0 text-[var(--dtx-info)]" />
          )}
          <input
            autoFocus
            value={createValue}
            placeholder={creating === "folder" ? "folder name" : "file name"}
            onChange={(e) => setCreateValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void submitCreate();
              if (e.key === "Escape") setCreating(null);
            }}
            onBlur={() => void submitCreate()}
            className="min-w-0 flex-1 rounded border border-emerald-500/50 bg-black/60 px-1 text-body font-mono text-gray-100 outline-none"
          />
        </div>
      )}

      {isOpen && (
        <div className="flex flex-col">
          {isLoading ? (
            <div className="text-label text-gray-500 py-1 pl-4 animate-pulse">Loading...</div>
          ) : (
            <>
              {visibleChildren.map((child, idx) => (
                <FileSystemNode
                  key={idx}
                  node={child}
                  depth={depth + 1}
                  activeContexts={activeContexts}
                  toggleContext={toggleContext}
                  setExplorerRoot={setExplorerRoot}
                  handleOpenFile={handleOpenFile}
                  gitStatusMap={gitStatusMap}
                  onFsError={onFsError}
                />
              ))}
              {isTruncated && (
                <div
                  style={{ paddingLeft: `${(depth + 1) * 14 + 4}px` }}
                  className="text-label text-amber-500/70 py-1 font-mono"
                >
                  ⚠ {children.length - MAX_RENDER_CHILDREN} more items not rendered (Shift+click to
                  drill in)
                </div>
              )}
            </>
          )}
        </div>
      )}

      {menu && (
        <>
          <div
            className="fixed inset-0 z-[200]"
            onClick={() => setMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault();
              setMenu(null);
            }}
          />
          <div
            style={{ position: "fixed", left: menu.x, top: menu.y }}
            className="z-[201] w-44 overflow-hidden rounded-lg border border-white/10 bg-[var(--dtx-code-panel)] py-1 text-body shadow-2xl"
          >
            {localNode.isDir && (
              <>
                <button
                  onClick={() => startCreate("file")}
                  className="block w-full px-3 py-1.5 text-left text-gray-300 hover:bg-white/10"
                >
                  New File
                </button>
                <button
                  onClick={() => startCreate("folder")}
                  className="block w-full px-3 py-1.5 text-left text-gray-300 hover:bg-white/10"
                >
                  New Folder
                </button>
                <div className="my-1 h-px bg-white/10" />
              </>
            )}
            <button
              onClick={startRename}
              className="block w-full px-3 py-1.5 text-left text-gray-300 hover:bg-white/10"
            >
              Rename
            </button>
            <button
              onClick={runDelete}
              className="block w-full px-3 py-1.5 text-left text-red-400 hover:bg-red-500/10"
            >
              Delete
            </button>
            <div className="my-1 h-px bg-white/10" />
            <button
              onClick={reveal}
              className="block w-full px-3 py-1.5 text-left text-gray-300 hover:bg-white/10"
            >
              Reveal in Explorer
            </button>
            <button
              onClick={copyPath}
              className="block w-full px-3 py-1.5 text-left text-gray-300 hover:bg-white/10"
            >
              Copy Path
            </button>
          </div>
        </>
      )}
    </div>
  );
};

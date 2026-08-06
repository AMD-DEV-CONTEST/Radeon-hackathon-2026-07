// 会话侧栏组件 — ChatGPT/Claude 风格
// 功能：会话列表、新建、切换、编辑标题、置顶、删除（两步确认）

import { useState, useEffect } from "react";
import {
  Plus, MessageSquare, Trash2, Check, X, Pin, PinOff,
  PencilLine, Loader2,
} from "lucide-react";

export interface SessionMeta {
  id: string;
  title: string;
  pinned: boolean;
  createdAt: number;
  lastActiveAt: number;
  messageCount: number;
}

const LS_KEY = "xai_sessions_meta";

function loadMetas(): Record<string, SessionMeta> {
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch { return {}; }
}

function saveMetas(metas: Record<string, SessionMeta>) {
  localStorage.setItem(LS_KEY, JSON.stringify(metas));
}

export function createSessionMeta(id: string): SessionMeta {
  const now = Date.now();
  return { id, title: "新对话", pinned: false, createdAt: now, lastActiveAt: now, messageCount: 0 };
}

export function updateSessionMeta(id: string, patch: Partial<SessionMeta>) {
  const metas = loadMetas();
  if (!metas[id]) metas[id] = createSessionMeta(id);
  metas[id] = { ...metas[id], ...patch, lastActiveAt: Date.now() };
  saveMetas(metas);
}

interface SessionSidebarProps {
  currentId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export function SessionSidebar({ currentId, onSelect, onNew, onDelete }: SessionSidebarProps) {
  const [metas, setMetas] = useState<SessionMeta[]>([]);
  const [editId, setEditId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [confirmDel, setConfirmDel] = useState<string | null>(null);

  // 加载
  useEffect(() => {
    const m = loadMetas();
    const list = Object.values(m).sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
      return b.lastActiveAt - a.lastActiveAt;
    });
    setMetas(list);
  }, [currentId]);

  const doEdit = (meta: SessionMeta) => {
    setEditId(meta.id);
    setEditTitle(meta.title);
  };

  const saveEdit = () => {
    if (editId && editTitle.trim()) {
      updateSessionMeta(editId, { title: editTitle.trim() });
      setMetas((prev) => prev.map((m) => m.id === editId ? { ...m, title: editTitle.trim() } : m));
    }
    setEditId(null);
  };

  const togglePin = (id: string, pinned: boolean) => {
    updateSessionMeta(id, { pinned: !pinned });
    setMetas((prev) => prev.map((m) => m.id === id ? { ...m, pinned: !pinned } : m));
  };

  return (
    <div className="w-full flex flex-col text-[12px]">
      {/* 新建按钮 */}
      <button
        onClick={onNew}
        className="flex items-center gap-2 px-3 py-2 mx-1.5 mt-1.5 rounded-lg bg-blue-500 hover:bg-blue-600 text-white text-xs font-medium transition-colors"
      >
        <Plus size={13} /> 新对话
      </button>

      {/* 会话列表 */}
      <div className="flex-1 overflow-auto mt-2 px-1">
        {metas.length === 0 && (
          <div className="text-center text-zinc-400 py-6 text-[11px]">
            暂无对话，点击上方「新对话」开始
          </div>
        )}
        {metas.map((m) => (
          <div key={m.id} className="group relative">
            <button
              onClick={() => onSelect(m.id)}
              className={`w-full text-left px-3 py-2 rounded-lg text-xs flex items-start gap-2 transition-colors ${
                m.id === currentId
                  ? "bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400"
                  : "hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300"
              }`}
            >
              <MessageSquare size={12} className="mt-0.5 shrink-0" />
              <div className="min-w-0 flex-1">
                {/* 标题行 */}
                {editId === m.id ? (
                  <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                    <input
                      autoFocus
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") saveEdit(); if (e.key === "Escape") setEditId(null); }}
                      onBlur={saveEdit}
                      className="flex-1 bg-white dark:bg-zinc-800 border border-blue-300 dark:border-blue-600 rounded px-1.5 py-0.5 text-[11px] outline-none"
                    />
                  </div>
                ) : (
                  <div className="flex items-center gap-1">
                    {m.pinned && <Pin size={10} className="shrink-0 text-amber-500" />}
                    <span className="truncate font-medium">{m.title || "新对话"}</span>
                  </div>
                )}
                {/* 副行 */}
                <div className="text-[10px] text-zinc-400 mt-0.5 flex items-center gap-1.5">
                  <span>{fmtTime(m.lastActiveAt)}</span>
                  {m.messageCount > 0 && <span>· {m.messageCount} 条</span>}
                </div>
              </div>
            </button>

            {/* 操作按钮 — hover时显示 */}
            <div className="absolute right-1 top-1 hidden group-hover:flex items-center gap-1 rounded-md px-1 py-0.5 shadow-md backdrop-blur-md border" style={{ background: "var(--glass-bg-light)", borderColor: "var(--color-border-focus)" }}>
              <button onClick={(e) => { e.stopPropagation(); doEdit(m); }} title="编辑标题"
                className="p-1.5 rounded text-zinc-400 dark:text-zinc-400 hover:text-blue-500 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 transition-colors">
                <PencilLine size={14} />
              </button>
              <button onClick={(e) => { e.stopPropagation(); togglePin(m.id, m.pinned); }} title={m.pinned ? "取消置顶" : "置顶"}
                className={`p-1.5 rounded transition-colors hover:bg-zinc-100 dark:hover:bg-zinc-700/50 ${m.pinned ? "text-amber-500" : "text-zinc-400 dark:text-zinc-400 hover:text-amber-500"}`}>
                {m.pinned ? <PinOff size={14} /> : <Pin size={14} />}
              </button>
              {confirmDel === m.id ? (
                <span className="flex items-center gap-1">
                  <button onClick={(e) => { e.stopPropagation(); onDelete(m.id); setConfirmDel(null); }} title="确认删除"
                    className="p-1.5 rounded text-red-500 hover:bg-red-500/10 transition-colors">
                    <Check size={14} />
                  </button>
                  <button onClick={(e) => { e.stopPropagation(); setConfirmDel(null); }} title="取消"
                    className="p-1.5 rounded text-zinc-400 dark:text-zinc-400 hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 transition-colors">
                    <X size={14} />
                  </button>
                </span>
              ) : (
                <button onClick={(e) => { e.stopPropagation(); setConfirmDel(m.id); }} title="删除"
                  className="p-1.5 rounded text-zinc-400 dark:text-zinc-400 hover:text-red-500 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 transition-colors">
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function fmtTime(ts: number): string {
  const d = new Date(ts);
  const now = new Date();
  const diff = now.getTime() - ts;
  if (diff < 60000) return "刚刚";
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

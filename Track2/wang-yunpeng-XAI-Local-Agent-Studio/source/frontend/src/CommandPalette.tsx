/**
 * CommandPalette — Cmd+K 全局命令面板
 * 
 * 行业标准交互（对标 Cursor/VS Code/Linear）：
 * - Cmd+K 打开，Esc 关闭
 * - 搜索过滤导航项 + 历史会话 + 快捷操作
 * - ↑↓ 导航，Enter 执行
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { Search, ArrowRight, MessageSquare, Cpu, Shield, Brain, BookOpen, Users } from "lucide-react";
import { listSessions, searchMemory, type MemorySearchHit } from "./lib/api";

interface CommandItem {
  id: string;
  icon: React.ReactNode;
  label: string;
  desc?: string;
  action: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onNavigate: (pageIndex: number) => void;
  onSession: (id: string) => void;
}

const NAV_QUICK: { icon: React.ReactNode; label: string; index: number }[] = [
  { icon: <MessageSquare size={14} />, label: "控制台", index: 0 },
  { icon: <Cpu size={14} />, label: "Grok Build", index: 1 },
  { icon: <Brain size={14} />, label: "Memory", index: 5 },
  { icon: <Shield size={14} />, label: "Guardian", index: 8 },
  { icon: <Users size={14} />, label: "Agent 协作室", index: 11 },
  { icon: <BookOpen size={14} />, label: "知识库", index: -1 },
];

export default function CommandPalette({ open, onClose, onNavigate, onSession }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const [sessions, setSessions] = useState<{ id: string; title?: string }[]>([]);
  const [memHits, setMemHits] = useState<MemorySearchHit[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // 打开时加载会话列表
  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIdx(0);
      listSessions().then(setSessions).catch(() => setSessions([]));
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // 搜索记忆（防抖）
  useEffect(() => {
    if (query.length < 2) { setMemHits([]); return; }
    const t = setTimeout(() => {
      searchMemory(query, 3).then(setMemHits).catch(() => setMemHits([]));
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  // 构建命令列表
  const items: CommandItem[] = [];
  const q = query.toLowerCase();

  // 导航项
  for (const n of NAV_QUICK) {
    if (!q || n.label.toLowerCase().includes(q)) {
      items.push({ id: `nav:${n.index}`, icon: n.icon, label: n.label, desc: "导航", action: () => { onNavigate(n.index); onClose(); } });
    }
  }

  // 历史会话
  for (const s of sessions.slice(0, 5)) {
    const title = s.title || "对话";
    if (!q || title.toLowerCase().includes(q)) {
      items.push({ id: `session:${s.id}`, icon: <MessageSquare size={14} />, label: title.slice(0, 40), desc: "历史对话", action: () => { onSession(s.id); onClose(); } });
    }
  }

  // 记忆搜索结果
  for (const h of memHits) {
    items.push({
      id: `mem:${h.key}`,
      icon: <Brain size={14} />,
      label: h.key.slice(0, 40),
      desc: `记忆 · ${(h.value || "").slice(0, 60)}`,
      action: () => { setQuery(h.key); onClose(); },
    });
  }

  // 键盘导航
  const onKey = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx((i) => Math.min(i + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActiveIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (items[activeIdx]) items[activeIdx].action(); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  }, [items, activeIdx, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]">
      {/* 遮罩 */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      {/* 面板 */}
      <div className="relative z-10 w-full max-w-lg mx-4 rounded-2xl overflow-hidden
                      bg-[var(--color-bg-card)] border border-[var(--color-border)]
                      shadow-[var(--shadow-lg)]">
        {/* 搜索栏 */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--color-border-subtle)]">
          <Search size={16} className="text-[var(--color-text-muted)] shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActiveIdx(0); }}
            onKeyDown={onKey}
            placeholder="搜索页面、会话、记忆…"
            className="flex-1 bg-transparent outline-none text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)]"
          />
          <kbd className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.06] text-[var(--color-text-muted)] font-mono">esc</kbd>
        </div>
        {/* 结果列表 */}
        <div className="max-h-64 overflow-auto py-1">
          {items.length === 0 && (
            <div className="px-4 py-8 text-center text-xs text-[var(--color-text-muted)]">无匹配结果</div>
          )}
          {items.map((item, i) => (
            <button
              key={item.id}
              onClick={item.action}
              onMouseEnter={() => setActiveIdx(i)}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors duration-100
                ${i === activeIdx ? "bg-white/[0.06]" : ""}`}
            >
              <span className="shrink-0 text-[var(--color-text-muted)]">{item.icon}</span>
              <span className="flex-1 text-sm text-[var(--color-text)] truncate">{item.label}</span>
              {item.desc && (
                <span className="text-xs text-[var(--color-text-muted)] truncate max-w-[200px]">{item.desc}</span>
              )}
              <ArrowRight size={12} className="shrink-0 text-[var(--color-text-muted)] opacity-0 group-hover:opacity-100" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

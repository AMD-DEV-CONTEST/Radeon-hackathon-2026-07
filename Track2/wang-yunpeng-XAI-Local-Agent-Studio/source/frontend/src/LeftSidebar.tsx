// XAI 统一左侧栏（Ollama Flow Liquid Glass 质感）
import { useState, useEffect } from "react";
import {
  Plus, MessageSquare, LayoutDashboard, Users, Workflow, Clock,
  Brain, Boxes, Wrench, BookOpen, Shield, Dna, Cpu, Sparkles,
  Search, Settings, ChevronDown, ChevronRight, Pin, PinOff,
  PencilLine, Trash2, Check, X, CalendarDays, ClipboardCheck,
} from "lucide-react";
import { listSessions } from "./lib/api";
import { fetchGuardianPending } from "./lib/api";

const LS_KEY = "xai_sessions_meta";
function loadMetas(): Record<string, any> { try { const r = localStorage.getItem(LS_KEY); return r ? JSON.parse(r) : {}; } catch { return {}; } }
function saveMetas(metas: Record<string, any>) { localStorage.setItem(LS_KEY, JSON.stringify(metas)); }

interface LeftSidebarProps {
  currentPage: number; currentSessionId: string | null;
  onPageSelect: (page: number) => void; onSessionSelect: (id: string) => void;
  onNewSession: () => void; onDeleteSession: (id: string) => void;
  onSearch?: () => void;
  onSettings?: () => void;
}

const NAV_ITEMS = [
  { icon: <MessageSquare size={14} />, label: "控制台" }, { icon: <Cpu size={14} />, label: "Grok Build" },
  { icon: <Sparkles size={14} />, label: "Demo 测试" }, { icon: <LayoutDashboard size={14} />, label: "工作台" },
  { icon: <Clock size={14} />, label: "执行时间线" }, { icon: <Brain size={14} />, label: "Memory" },
  { icon: <Boxes size={14} />, label: "能力注册表" }, { icon: <Wrench size={14} />, label: "工具中心" },
  { icon: <Shield size={14} />, label: "Guardian" },
  { icon: <CalendarDays size={14} />, label: "备忘录日历" },
  { icon: <ClipboardCheck size={14} />, label: "验收调试台" },
  { icon: <Users size={14} />, label: "Agent 协作室" },
];
const AGENTS = [{ name: "Hermes", status: "就绪" }, { name: "Grok Build", status: "就绪" }, { name: "Reviewer", status: "就绪" }];

export function LeftSidebar({ currentPage, currentSessionId, onPageSelect, onSessionSelect, onNewSession, onDeleteSession, onSearch, onSettings }: LeftSidebarProps) {
  const [sessions, setSessions] = useState<any[]>([]);
  const [editId, setEditId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [sessionsCollapsed, setSessionsCollapsed] = useState(false);
  const [guardianPending, setGuardianPending] = useState(0);

  // Guardian 待审批轮询（每 10s）
  useEffect(() => {
    const poll = () => { fetchGuardianPending().then((t) => setGuardianPending(t.length)).catch(() => {}); };
    poll(); const iv = setInterval(poll, 10_000); return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    const refresh = async () => {
      try {
        const backend = await listSessions();
        const metas = loadMetas();
        const merged = backend.map((s: any) => ({ ...s, ...metas[s.id], lastActiveAt: metas[s.id]?.lastActiveAt || s.ts || 0 }))
          .sort((a: any, b: any) => { if ((a.pinned || false) !== (b.pinned || false)) return a.pinned ? -1 : 1; return (b.lastActiveAt || 0) - (a.lastActiveAt || 0); });
        setSessions(merged);
      } catch { setSessions(Object.values(loadMetas())); }
    };
    refresh(); const iv = setInterval(refresh, 5000); return () => clearInterval(iv);
  }, [currentSessionId]);

  const doEdit = (s: any) => { setEditId(s.id); setEditTitle(s.title || ""); };
  const saveEdit = () => {
    if (editId && editTitle.trim()) {
      const metas = loadMetas(); metas[editId] = { ...metas[editId], id: editId, title: editTitle.trim() };
      saveMetas(metas); setSessions((prev) => prev.map((s) => s.id === editId ? { ...s, title: editTitle.trim() } : s));
    } setEditId(null);
  };
  const togglePin = (id: string, pinned: boolean) => {
    const metas = loadMetas(); metas[id] = { ...metas[id], id, pinned: !pinned };
    saveMetas(metas); setSessions((prev) => prev.map((s) => s.id === id ? { ...s, pinned: !pinned } : s));
  };
  const doDel = (id: string) => { onDeleteSession(id); const metas = loadMetas(); delete metas[id]; saveMetas(metas); setConfirmDel(null); };

  const glass: React.CSSProperties = { background: "rgba(255,255,255,0.04)", backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)" };
  const sep = { height: 1, background: "linear-gradient(90deg, transparent, rgba(167,139,250,0.2), transparent)" };
  const secHdr: React.CSSProperties = { color: "#a78bfa", opacity: 0.8, letterSpacing: "0.1em" };
  const dotOn = (c: string) => ({ background: c, boxShadow: `0 0 6px ${c}80` });
  const activeBg: React.CSSProperties = { background: "linear-gradient(135deg, rgba(124,58,237,0.15), rgba(99,102,241,0.08))" };

  return (
    <div className="w-56 shrink-0 h-full flex flex-col text-xs" style={{ borderRight: "1px solid rgba(255,255,255,0.08)", ...glass, color: "var(--color-text)" }}>
      {/* Logo */}
      <div className="px-3 pt-3 pb-2 flex items-center gap-2" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
        <span className="font-semibold text-sm" style={{ background: "linear-gradient(135deg, #a78bfa, #818cf8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>XAI Station</span>
        <span className="text-[10px] text-zinc-500">v4</span>
        <div className="ml-auto flex items-center gap-1">
          <button title="搜索 (⌘K)" onClick={onSearch} className="p-1 rounded text-zinc-500 hover:text-white transition-colors"><Search size={13} /></button>
          <button title="设置" onClick={onSettings} className="p-1 rounded text-zinc-500 hover:text-white transition-colors"><Settings size={13} /></button>
        </div>
      </div>
      {/* 新建 */}
      <div className="px-2 mt-2">
        <button onClick={onNewSession}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl text-xs font-medium text-white transition-all duration-200"
          style={{ background: "linear-gradient(135deg, #7c3aed, #6366f1)", boxShadow: "0 2px 8px rgba(124,58,237,0.25)" }}
          onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.boxShadow = "0 4px 16px rgba(124,58,237,0.4)"; }}
          onMouseLeave={e => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "0 2px 8px rgba(124,58,237,0.25)"; }}>
          <Plus size={14} /> 新建对话
        </button>
      </div>
      {/* scroll */}
      <div className="flex-1 overflow-y-auto px-2 pb-3 mt-3 space-y-3 custom-scrollbar">
        {/* 助理 */}
        <div><div className="flex items-center px-1 py-1 text-[10px] font-semibold uppercase tracking-wider" style={secHdr}>助理</div>
          <div className="space-y-0.5">{AGENTS.map(a => (
            <div key={a.name} className="flex items-center gap-2 px-2.5 py-2 rounded-xl transition-all duration-200 hover:translate-x-0.5" style={{ background: "rgba(255,255,255,0.03)", color: "var(--color-text)", cursor: "default" }}>
              <span className="w-1.5 h-1.5 rounded-full" style={dotOn("#10b981")} /><span className="flex-1 text-[12px]">{a.name}</span>
              <span className="text-[10px] text-emerald-400/60 font-mono">{a.status}</span></div>))}
          </div></div>
        <div style={sep} />
        {/* 导航 */}
        <div><button onClick={() => setNavCollapsed(!navCollapsed)} className="w-full flex items-center px-1 py-1 text-[10px] font-semibold uppercase tracking-wider transition-colors" style={secHdr}>
          导航 {navCollapsed ? <ChevronRight size={10} className="ml-auto" /> : <ChevronDown size={10} className="ml-auto" />}</button>
          {!navCollapsed && <div className="space-y-0.5 mt-0.5">{NAV_ITEMS.map((item, i) => (
            <button key={item.label} onClick={() => onPageSelect(i)}
              className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-xl transition-all duration-200 hover:translate-x-0.5 text-[12px]"
              style={{ background: currentPage === i ? "linear-gradient(135deg, rgba(124,58,237,0.15), rgba(99,102,241,0.08))" : "transparent", color: currentPage === i ? "#a78bfa" : "var(--color-text)", borderLeft: currentPage === i ? "2px solid #a78bfa" : "2px solid transparent" }}>
              <span className="w-4 h-4 flex items-center justify-center opacity-70">{item.icon}</span>
              <span className="flex-1 text-left">{item.label}</span>
              {item.label === "Guardian" && guardianPending > 0 && (
                <span className="flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold leading-none">
                  {guardianPending > 99 ? "99+" : guardianPending}
                </span>
              )}
            </button>))}</div>}
        </div>
        <div style={sep} />
        {/* 历史对话 */}
        <div><button onClick={() => setSessionsCollapsed(!sessionsCollapsed)} className="w-full flex items-center px-1 py-1 text-[10px] font-semibold uppercase tracking-wider transition-colors" style={secHdr}>
          历史对话 <span className="ml-auto font-mono normal-case tracking-normal text-zinc-500">{sessions.filter((s: any) => s.pinned).length} 置顶</span>
          {sessionsCollapsed ? <ChevronRight size={10} className="ml-1" /> : <ChevronDown size={10} className="ml-1" />}</button>
          {!sessionsCollapsed && <div className="space-y-0.5 mt-0.5">
            {sessions.length === 0 && <div className="text-[11px] text-center py-3" style={{ color: "var(--color-text-muted)" }}>暂无对话</div>}
            {sessions.slice(0, 20).map((s: any) => (
              <div key={s.id} className="group relative">
                <button onClick={() => onSessionSelect(s.id)}
                  className="w-full text-left px-2.5 py-2 rounded-xl text-[12px] flex items-start gap-1.5 transition-all duration-200 hover:translate-x-0.5"
                  style={{ background: s.id === currentSessionId ? "linear-gradient(135deg, rgba(124,58,237,0.12), rgba(99,102,241,0.05))" : "transparent", borderLeft: s.id === currentSessionId ? "2px solid #a78bfa" : "2px solid transparent" }}>
                  <MessageSquare size={11} className="mt-0.5 shrink-0 opacity-50" />
                  <div className="min-w-0 flex-1">
                    {editId === s.id ? (
                      <input autoFocus value={editTitle} onChange={e => setEditTitle(e.target.value)} onKeyDown={e => { if (e.key === "Enter") saveEdit(); if (e.key === "Escape") setEditId(null); }} onBlur={saveEdit} onClick={e => e.stopPropagation()}
                        className="w-full rounded px-1.5 py-0.5 text-[11px] outline-none" style={{ background: "rgba(255,255,255,0.08)", border: "1px solid #a78bfa", color: "var(--color-text)" }} />
                    ) : (
                      <div className="flex items-center gap-1">{s.pinned && <Pin size={9} className="shrink-0 text-amber-400" />}<span className="truncate">{s.title || "新对话"}</span></div>)}
                    <div className="text-[10px] text-zinc-500 mt-0.5">{fmtTime(s.lastActiveAt || 0)}</div>
                  </div></button>
                <div className="absolute right-1 top-1 hidden group-hover:flex items-center gap-1 rounded-md px-1 py-0.5 shadow-md backdrop-blur-md z-10 border" style={{ background: "var(--glass-bg-light)", borderColor: "var(--color-border-focus)" }}>
                  <button onClick={e => { e.stopPropagation(); doEdit(s); }} title="编辑标题" className="p-1.5 rounded text-zinc-500 dark:text-zinc-400 hover:text-violet-400 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 transition-colors"><PencilLine size={14} /></button>
                  <button onClick={e => { e.stopPropagation(); togglePin(s.id, s.pinned); }} title={s.pinned ? "取消置顶" : "置顶"} className={`p-1.5 rounded transition-colors hover:bg-zinc-100 dark:hover:bg-zinc-700/50 ${s.pinned ? "text-amber-400" : "text-zinc-500 dark:text-zinc-400 hover:text-amber-400"}`}>{s.pinned ? <PinOff size={14} /> : <Pin size={14} />}</button>
                  {confirmDel === s.id ? (
                    <span className="flex items-center gap-1">
                      <button onClick={e => { e.stopPropagation(); doDel(s.id); }} title="确认删除" className="p-1.5 rounded text-red-400 hover:text-red-300 hover:bg-red-500/10 transition-colors"><Check size={14} /></button>
                      <button onClick={e => { e.stopPropagation(); setConfirmDel(null); }} title="取消" className="p-1.5 rounded text-zinc-500 dark:text-zinc-400 hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 transition-colors"><X size={14} /></button></span>
                  ) : (<button onClick={e => { e.stopPropagation(); setConfirmDel(s.id); }} title="删除" className="p-1.5 rounded text-zinc-500 dark:text-zinc-400 hover:text-red-400 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 transition-colors"><Trash2 size={14} /></button>)}
                </div></div>))}
          </div>}</div>
        <div style={sep} />
        {/* 创意项目 */}
        <div><div className="flex items-center px-1 py-1 text-[10px] font-semibold uppercase tracking-wider" style={secHdr}>创意项目</div>
          <div className="space-y-0.5"><div className="flex items-center gap-2 px-2.5 py-2 rounded-xl transition-all duration-200 hover:translate-x-0.5" style={{ background: "rgba(255,255,255,0.03)", color: "var(--color-text)", cursor: "default" }}>
            <span className="w-1.5 h-1.5 rounded-full" style={dotOn("#818cf8")} /><span className="flex-1 text-[12px]">默认工作区</span></div></div></div>
      </div>
      {/* 底栏 */}
      <div className="px-3 py-2 flex items-center gap-2 text-[10px]" style={{ borderTop: "1px solid rgba(255,255,255,0.04)", color: "var(--color-text-muted)" }}>
        <span className="w-1.5 h-1.5 rounded-full" style={dotOn("#10b981")} />后端已连接 · :8000
      </div>
    </div>
  );
}
function fmtTime(ts: number): string { if (!ts) return ""; const d = new Date(ts), diff = Date.now() - ts; if (diff < 6e4) return "刚刚"; if (diff < 36e5) return `${Math.floor(diff / 6e4)} 分钟前`; if (diff < 864e5) return `${Math.floor(diff / 36e5)} 小时前`; return `${d.getMonth() + 1}/${d.getDate()}`; }

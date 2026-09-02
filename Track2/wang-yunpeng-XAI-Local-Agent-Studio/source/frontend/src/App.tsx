import { useEffect, useState, useRef, useCallback } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { MessageSquare, LayoutDashboard, Clock, Brain, Shield, Boxes, Wrench, Cpu, ChevronDown, Loader2, Check, Sparkles, PanelRight, PanelRightClose, CalendarDays, ClipboardCheck, Users } from "lucide-react";
import ChatConsole from "./ChatConsole";
import GrokConsole from "./GrokConsole";
import DemoCanvas from "./DemoCanvas";
import Workspace from "./Workspace";
import Timeline from "./Timeline";
import MemoryCenter from "./MemoryCenter";
import CapabilityRegistry from "./CapabilityRegistry";
import ToolHub from "./ToolHub";
import GuardianCenter from "./GuardianCenter";
import MemoCalendar from "./MemoCalendar";
import AcceptancePanel from "./AcceptancePanel";
import AgentRoom from "./AgentRoom";
import { LeftSidebar } from "./LeftSidebar";
import StatusWidget from "./StatusWidget";
import { ThemeToggle } from "./ThemeToggle";
import CommandPalette from "./CommandPalette";
import SettingsModal from "./SettingsModal";
import { useTheme } from "./theme-context";
import { fetchStatus, fetchMemoryStats, fetchSystemHealth, fetchSystemSandbox, fetchSystemErrors, fetchModels, activateModel, type SystemHealth, type SystemSandbox, type SystemErrors, type ModelEntry } from "./lib/api";

interface SystemStatus { xai_engine: string; model: string; pending_approvals: number; [k: string]: any; }

interface PageDef { icon: JSX.Element; label: string; render: (props?: any) => JSX.Element; }

const PAGES: PageDef[] = [
  { icon: <MessageSquare size={16} />, label: "控制台",     render: (p) => <ChatConsole currentSessionId={p?.currentSessionId} activeModelVision={p?.activeModelVision} /> },
  { icon: <Cpu size={16} />, label: "Grok Build",   render: () => <GrokConsole /> },
  { icon: <Sparkles size={16} />, label: "Demo 测试",  render: () => <DemoCanvas /> },
  { icon: <LayoutDashboard size={16} />, label: "工作台",   render: () => <Workspace /> },
  { icon: <Clock size={16} />, label: "执行时间线", render: () => <Timeline /> },
  { icon: <Brain size={16} />, label: "Memory",     render: () => <MemoryCenter /> },
  { icon: <Boxes size={16} />, label: "能力注册表", render: () => <CapabilityRegistry /> },
  { icon: <Wrench size={16} />, label: "工具中心",   render: () => <ToolHub /> },
  { icon: <Shield size={16} />, label: "Guardian",  render: () => <GuardianCenter /> },
  { icon: <CalendarDays size={16} />, label: "备忘录日历", render: () => <MemoCalendar /> },
  { icon: <ClipboardCheck size={16} />, label: "验收调试台", render: () => <AcceptancePanel /> },
  { icon: <Users size={16} />, label: "Agent 协作室", render: () => <AgentRoom /> },
];

export default function App() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [memInfo, setMemInfo] = useState<{ layers: number; total: number } | null>(null);
  const [sysHealth, setSysHealth] = useState<SystemHealth | null>(null);
  const [sysSandbox, setSysSandbox] = useState<SystemSandbox | null>(null);
  const [sysErrors, setSysErrors] = useState<SystemErrors | null>(null);
  const [page, setPage] = useState(0);
  const [showStatusPanel, setShowStatusPanel] = useState(false); // 默认隐藏右侧状态面板
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [activeModelId, setActiveModelId] = useState("");
  const [modelOpen, setModelOpen] = useState(false);
  const [modelLoading, setModelLoading] = useState(false);
  const [modelRect, setModelRect] = useState<DOMRect | null>(null);
  const modelRef = useRef<HTMLDivElement>(null);

  // A: 搜索命令面板
  const [paletteOpen, setPaletteOpen] = useState(false);
  // B: 设置弹窗
  const [settingsOpen, setSettingsOpen] = useState(false);
  // 后端地址
  const [backendUrl, setBackendUrl] = useState(() => {
    try { return localStorage.getItem("xai_backend_url") || "http://localhost:8000"; } catch { return "http://localhost:8000"; }
  });
  const { themeMode, setThemeMode } = useTheme();

  // 滚动到当前激活页（当 page 变化时重置滚动）
  const mainRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (mainRef.current) mainRef.current.scrollTop = 0; }, [page]);

  // Cmd+K / Esc 快捷键
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPaletteOpen((prev) => !prev);
      }
      if (e.key === "Escape") {
        setPaletteOpen(false);
        setSettingsOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // 会话列表（给命令面板用）
  const [sessionsMeta, setSessionsMeta] = useState<{ id: string; title: string }[]>([]);
  useEffect(() => {
    try {
      const raw = localStorage.getItem("xai_sessions_meta");
      if (raw) {
        const metas = JSON.parse(raw);
        setSessionsMeta(Object.values(metas).map((m: any) => ({ id: m.id, title: m.title || "新对话" })));
      }
    } catch {}
    const iv = setInterval(() => {
      try {
        const raw = localStorage.getItem("xai_sessions_meta");
        if (raw) {
          const metas = JSON.parse(raw);
          setSessionsMeta(Object.values(metas).map((m: any) => ({ id: m.id, title: m.title || "新对话" })));
        }
      } catch {}
    }, 5000);
    return () => clearInterval(iv);
  }, []);

  // 页面列表（给命令面板用）
  const pageDefs = PAGES.map((p) => ({ icon: p.icon, label: p.label }));
  const themeLabel = themeMode === "light" ? "亮色" : themeMode === "dark" ? "暗色" : "跟随系统";

  const onToggleTheme = useCallback(() => {
    const cycle: Record<string, "light" | "dark" | "system"> = { light: "dark", dark: "system", system: "light" };
    setThemeMode(cycle[themeMode] || "light");
  }, [themeMode, setThemeMode]);

  // 点击外部关闭模型下拉
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (modelRef.current && !modelRef.current.contains(e.target as Node)) setModelOpen(false);
    };
    if (modelOpen) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [modelOpen]);

  useEffect(() => {
    fetchStatus().then(setStatus).catch(() => {});
    fetchMemoryStats()
      .then((m) => {
        const ls = Object.values(m.layers || {});
        setMemInfo({ layers: ls.length, total: ls.reduce((n, l) => n + (l.count || 0), 0) });
      })
      .catch(() => {});
    fetchSystemHealth().then(setSysHealth).catch(() => {});
    fetchSystemSandbox().then(setSysSandbox).catch(() => {});
    fetchSystemErrors().then(setSysErrors).catch(() => {});
    fetchModels().then((r) => {
      setModels(r.models || []);
      const a = r.models?.find((m: ModelEntry) => m.is_active);
      if (a) setActiveModelId(a.id);
    }).catch(() => {});
  }, []);

  const switchModel = async (id: string) => {
    setModelLoading(true);
    try {
      await activateModel(id);
      const r = await fetchModels();
      setModels(r.models || []);
      const a = r.models?.find((m: ModelEntry) => m.is_active);
      if (a) setActiveModelId(a.id);
      fetchStatus().then(setStatus).catch(() => {});
      fetchSystemHealth().then(setSysHealth).catch(() => {});
      // 切完模型刷新记忆（不同模型可能有不同上下文）
      fetchMemoryStats().then((m) => {
        const ls = Object.values(m.layers || {});
        setMemInfo({ layers: ls.length, total: ls.reduce((n, l) => n + (l.count || 0), 0) });
      }).catch(() => {});
    } catch { /* 静默 */ }
    finally { setModelLoading(false); setModelOpen(false); }
  };

  const activeModel = models.find((m) => m.id === activeModelId) || null;

  return (
    <div className="xai-root h-screen w-screen flex flex-col font-sans">
      {/* Top Bar */}
      <header className="h-11 glass-panel flex items-center px-4 gap-6 text-xs shrink-0">
        <div className="font-semibold text-sm">XAI Station v4</div>
        <span className={`px-2 py-0.5 rounded-full text-[10px] ${status ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300" : "bg-zinc-100 text-zinc-400"}`}>
          {status?.xai_engine || "连接中…"}
        </span>
          <span className="text-zinc-400 relative" ref={modelRef}>
          <button onClick={() => {
            setModelRect(modelRef.current?.getBoundingClientRect() || null);
            setModelOpen(!modelOpen);
          }} className="flex items-center gap-1 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors">
            {modelLoading ? <Loader2 size={10} className="animate-spin" /> : null}
            模型 {activeModel?.name || status?.model || "-"}
            {activeModel && (
              <span className={`text-[9px] px-1 rounded ${
                activeModel.provider === "deepseek" ? "bg-blue-100 text-blue-600 dark:bg-blue-900/50 dark:text-blue-300" :
                activeModel.provider === "llamacpp" ? "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300" :
                "bg-zinc-100 text-zinc-400 dark:bg-zinc-800"
              }`}>
                {activeModel.provider === "deepseek" ? "云端" : activeModel.provider === "llamacpp" ? "本地" : activeModel.provider}
              </span>
            )}
            {activeModel?.vision && (
              <span className="text-[9px] px-1 rounded bg-violet-100 text-violet-600 dark:bg-violet-900/50 dark:text-violet-300">视觉</span>
            )}
            <ChevronDown size={10} className={`transition-transform ${modelOpen ? "rotate-180" : ""}`} />
          </button>
          {modelOpen && modelRect && createPortal(
            <div
              className="fixed inset-0 z-[9999]"
              style={{ background: "rgba(0,0,0,0.4)" }}
              onMouseDown={(e) => { if (e.target === e.currentTarget) setModelOpen(false); }}
            >
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.12 }}
                className="absolute w-56 bg-white dark:bg-zinc-900 rounded-lg border border-zinc-200 dark:border-zinc-700 shadow-xl py-1 max-h-80 overflow-auto"
                style={{ top: modelRect.bottom + 6, right: Math.max(8, window.innerWidth - modelRect.right) }}
              >
                {(() => {
                  const cloud = models.filter(m => m.provider === "deepseek" || m.provider === "grok");
                  const local = models.filter(m => m.provider === "llamacpp");
                  const groups: { label: string; items: typeof models }[] = [];
                  if (cloud.length) groups.push({ label: "云端", items: cloud });
                  if (local.length) groups.push({ label: "本地", items: local });
                  return groups.map((g) => (
                    <div key={g.label}>
                      <div className="px-3 py-1 text-[9px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                        {g.label} — {g.items.length} 个
                      </div>
                      {g.items.map((m) => (
                        <button
                          key={m.id}
                          onClick={() => switchModel(m.id)}
                          className={`w-full text-left px-3 py-1.5 text-[11px] flex items-center justify-between hover:bg-zinc-100 dark:hover:bg-zinc-800 ${
                            m.id === activeModelId ? "bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400" : ""
                          }`}
                        >
                          <span className="truncate flex-1">{m.name}</span>
                          {m.vision && <span className="text-[9px] px-1 rounded bg-violet-100 text-violet-600 dark:bg-violet-900/50 dark:text-violet-300 shrink-0 mr-1">视觉</span>}
                          {m.id === activeModelId && <Check size={12} className="text-blue-500 shrink-0 ml-2" />}
                        </button>
                      ))}
                    </div>
                  ));
                })()}
              </motion.div>
            </div>,
            document.body
          )}
        </span>
        <span className="text-zinc-400">审批 {status?.pending_approvals ?? 0}</span>
        <div className="ml-auto flex items-center gap-3">
          <span className="text-zinc-400">默认工作区</span>
          <button
            onClick={() => setShowStatusPanel(!showStatusPanel)}
            title={showStatusPanel ? "隐藏状态面板" : "显示状态面板"}
            className="p-1.5 rounded text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors">
            {showStatusPanel ? <PanelRightClose size={14} /> : <PanelRight size={14} />}
          </button>
          <ThemeToggle />
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* 统一左侧栏（WorkBuddy 风格） */}
        <LeftSidebar
          currentPage={page}
          currentSessionId={currentSessionId}
          onPageSelect={setPage}
          onSessionSelect={(id) => { setCurrentSessionId(id); setPage(0); }}
          onSearch={() => setPaletteOpen(true)}
          onSettings={() => setSettingsOpen(true)}
          onNewSession={() => {
            const id = crypto.randomUUID?.() || `s${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
            try {
              const raw = localStorage.getItem("xai_sessions_meta");
              const metas = raw ? JSON.parse(raw) : {};
              metas[id] = { id, title: "新对话", pinned: false, createdAt: Date.now(), lastActiveAt: Date.now() };
              localStorage.setItem("xai_sessions_meta", JSON.stringify(metas));
            } catch {}
            setCurrentSessionId(id);
            setPage(0);
          }}
          onDeleteSession={(id) => {
            import("./lib/api").then(({ deleteSession }) => deleteSession(id).catch(() => {}));
            try {
              const raw = localStorage.getItem("xai_sessions_meta");
              if (raw) {
                const metas = JSON.parse(raw);
                delete metas[id];
                localStorage.setItem("xai_sessions_meta", JSON.stringify(metas));
              }
            } catch {}
            if (currentSessionId === id) setCurrentSessionId(null);
          }}
        />

        {/* Main Content */}
        <div className="xai-page flex-1 overflow-hidden">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={page}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.22, ease: "easeOut" }}
              className="h-full overflow-auto"
            >
              {PAGES[page].render({ currentSessionId, activeModelVision: activeModel?.vision })}
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Right Panel */}
        {showStatusPanel && (
          <aside className="w-64 glass-panel p-3 shrink-0 overflow-auto">
            <StatusWidget status={status} memInfo={memInfo} sysHealth={sysHealth} sysSandbox={sysSandbox} sysErrors={sysErrors} />
          </aside>
        )}
      </div>

      {/* Bottom Bar */}
      <footer className="h-7 glass-panel flex items-center px-3 text-[10px] gap-4 shrink-0">
        <span className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${status ? "bg-emerald-400" : "bg-zinc-400"}`} />
          {status ? "后端已连接" : "连接中…"}
        </span>
        <span>:8000</span>
        <span className="ml-auto">XAI 统一操作台 v4.0 · {status?.project?.name || "默认工作区"}</span>
      </footer>

      {/* 命令面板 —— props 对齐 CommandPaletteProps（open/onClose/onNavigate/onSession）。
          此前调用处仍在传 isOpen/pages/sessions/onSelectSession/onToggleTheme 等已废弃入参，
          与组件契约漂移，tsc 报 TS2322；组件内部自行加载会话与导航项，无需外部注入。 */}
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onNavigate={(idx) => setPage(idx)}
        onSession={(id) => { setCurrentSessionId(id); setPage(0); }}
      />

      {/* 设置弹窗 */}
      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        themeMode={themeMode}
        onThemeChange={setThemeMode}
        backendUrl={backendUrl}
        onBackendUrlChange={(url) => { setBackendUrl(url); try { localStorage.setItem("xai_backend_url", url); } catch {} }}
        version="v4.0 · Phase 0 加固"
        commitCount={63}
        dataDir="~/.xai/"
      />
    </div>
  );
}

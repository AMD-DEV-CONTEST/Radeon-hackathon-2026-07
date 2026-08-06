// XAI Settings Modal — 系统设置弹窗
import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Settings, X, Sun, Moon, Monitor, Check, Server, Info, FolderOpen, GitCommit, Loader2 } from "lucide-react";
import { getToken, apiBase } from "./lib/api";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  themeMode: "system" | "light" | "dark";
  onThemeChange: (mode: "system" | "light" | "dark") => void;
  backendUrl: string;
  onBackendUrlChange: (url: string) => void;
  version: string;
  commitCount: number;
  dataDir: string;
}

export default function SettingsModal({ isOpen, onClose, themeMode, onThemeChange, backendUrl, onBackendUrlChange, version, commitCount, dataDir }: Props) {
  const [urlDraft, setUrlDraft] = useState(backendUrl);
  const [urlSaved, setUrlSaved] = useState(false);
  const [changelog, setChangelog] = useState<string[]>([]);
  const [changeLoading, setChangeLoading] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setChangeLoading(true);
      getToken().then((t) =>
        fetch(apiBase() + "/api/system/changelog", { headers: { "X-Auth-Token": t } })
          .then((r) => r.json())
          .then((d) => setChangelog(d.commits || []))
          .catch(() => setChangelog([]))
          .finally(() => setChangeLoading(false))
      ).catch(() => setChangeLoading(false));
    }
  }, [isOpen]);

  useEffect(() => { setUrlDraft(backendUrl); }, [backendUrl]);

  const saveUrl = () => {
    onBackendUrlChange(urlDraft);
    setUrlSaved(true);
    setTimeout(() => setUrlSaved(false), 1500);
  };

  const themes = [
    { mode: "light", label: "\u4eae\u8272", icon: <Sun size={14} /> },
    { mode: "dark", label: "\u6697\u8272", icon: <Moon size={14} /> },
    { mode: "system", label: "\u8ddf\u968f\u7cfb\u7edf", icon: <Monitor size={14} /> },
  ] as const;

  if (!isOpen) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[9998] flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.4)", backdropFilter: "blur(2px)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <motion.div
        initial={{ opacity: 0, y: -6, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: -4, scale: 0.98 }}
        transition={{ duration: 0.15, ease: "easeOut" }}
        className="w-[400px] rounded-xl border shadow-2xl overflow-hidden"
        style={{
          background: "var(--glass-bg-light)",
          borderColor: "var(--color-border-focus)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
        }}
      >
        {/* Header */}
        <div className="flex items-center gap-2 px-4 py-3 border-b" style={{ borderColor: "rgba(255,255,255,0.06)" }}>
          <Settings size={14} className="text-violet-400" />
          <span className="font-semibold text-sm" style={{ color: "var(--color-text)" }}>\u8bbe\u7f6e</span>
          <button onClick={onClose} className="ml-auto p-1 rounded text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors">
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="px-4 py-3 space-y-4" style={{ color: "var(--color-text)" }}>
          {/* Theme */}
          <section>
            <label className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500 mb-2 block">\u4e3b\u9898</label>
            <div className="flex gap-2">
              {themes.map((t) => (
                <button
                  key={t.mode}
                  onClick={() => onThemeChange(t.mode)}
                  className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs transition-colors border ${
                    themeMode === t.mode
                      ? "bg-violet-100 dark:bg-violet-900/30 border-violet-300 dark:border-violet-600 text-violet-700 dark:text-violet-300"
                      : "border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  }`}
                  style={themeMode === t.mode ? {} : { background: "rgba(255,255,255,0.03)" }}
                >
                  {t.icon}
                  {t.label}
                </button>
              ))}
            </div>
          </section>

          {/* Backend URL */}
          <section>
            <label className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500 mb-2 flex items-center gap-1.5">
              <Server size={12} /> \u540e\u7aef\u5730\u5740
            </label>
            <div className="flex gap-2">
              <input
                value={urlDraft}
                onChange={(e) => setUrlDraft(e.target.value)}
                className="flex-1 px-2.5 py-1.5 rounded-lg text-xs outline-none border border-zinc-200 dark:border-zinc-700 focus:border-violet-400 transition-colors"
                style={{ background: "rgba(255,255,255,0.05)", color: "var(--color-text)" }}
                placeholder="http://localhost:8000"
              />
              <button
                onClick={saveUrl}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1 transition-colors ${
                  urlSaved ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300" : "bg-violet-500 text-white hover:bg-violet-600"
                }`}
              >
                {urlSaved ? <><Check size={12} /> \u5df2\u4fdd\u5b58</> : "\u4fdd\u5b58"}
              </button>
            </div>
          </section>

          {/* About */}
          <section>
            <label className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500 mb-2 flex items-center gap-1.5">
              <Info size={12} /> \u5173\u4e8e\u672c\u7cfb\u7edf
            </label>
            <div className="space-y-1.5 text-xs" style={{ color: "var(--color-text)" }}>
              <div className="flex justify-between">
                <span className="text-zinc-400 dark:text-zinc-500">\u7248\u672c</span>
                <span className="font-mono">{version}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400 dark:text-zinc-500">\u672c\u5730\u63d0\u4ea4</span>
                <span className="font-mono">{commitCount} commits</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400 dark:text-zinc-500">\u6570\u636e\u76ee\u5f55</span>
                <span className="font-mono text-[11px]">{dataDir}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400 dark:text-zinc-500">\u540e\u7aef\u7aef\u53e3</span>
                <span className="font-mono">{backendUrl}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400 dark:text-zinc-500">\u90e8\u7f72\u5f62\u6001</span>
                <span>\u672c\u5730\u79c1\u6709\u5355\u673a</span>
              </div>
            </div>
          </section>

          {/* Changelog */}
          <section>
            <label className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500 mb-2 flex items-center gap-1.5">
              <GitCommit size={12} /> 最近更新
            </label>
            {changeLoading ? (
              <div className="flex items-center gap-2 py-2 text-xs text-zinc-400"><Loader2 size={12} className="animate-spin" /> 加载中…</div>
            ) : changelog.length > 0 ? (
              <div className="space-y-1 max-h-32 overflow-auto text-[10px] font-mono" style={{ color: "var(--color-text)" }}>
                {changelog.slice(0, 8).map((line, i) => (
                  <div key={i} className="truncate py-0.5 px-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800" style={{ borderLeft: "2px solid var(--color-border-focus)" }}>
                    <span className="text-violet-400">{line.substring(0, 7)}</span>
                    <span className="text-zinc-500 dark:text-zinc-400 ml-1">{line.substring(8)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[10px] text-zinc-400 py-1">无法获取更新日志</div>
            )}
          </section>

          {/* Data Directory button */}
          <div>
            <button
              onClick={() => {
                // Copy data dir to clipboard
                navigator.clipboard?.writeText(dataDir);
              }}
              className="w-full flex items-center justify-center gap-2 py-2 rounded-lg text-xs text-violet-400 hover:text-violet-300 transition-colors"
              style={{ background: "rgba(124,58,237,0.06)" }}
            >
              <FolderOpen size={13} /> \u590d\u5236\u6570\u636e\u76ee\u5f55\u8def\u5f84
            </button>
          </div>
        </div>
      </motion.div>
    </div>,
    document.body
  );
}

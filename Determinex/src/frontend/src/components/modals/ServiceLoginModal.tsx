"use client";
import { useEffect } from "react";
import { Globe, KeyRound, Shield } from "lucide-react";
import { saveServiceKey, getToolRegistry } from "@/lib/api";
import { useSettings } from "@/contexts/SettingsContext";

export function ServiceLoginModal() {
  const {
    showServiceLogin,
    setShowServiceLogin,
    serviceKeyInput,
    setServiceKeyInput,
    refreshToolRegistry,
  } = useSettings();

  const onClose = () => {
    setShowServiceLogin(null);
    setServiceKeyInput("");
  };

  useEffect(() => {
    if (!showServiceLogin) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [showServiceLogin]);

  if (!showServiceLogin) return null;

  const handleSave = async () => {
    try {
      const svcName = showServiceLogin.split("_")[0];
      await saveServiceKey(svcName, serviceKeyInput.trim());
      await refreshToolRegistry();
      onClose();
    } catch {
      /* error logged in api.ts */
    }
  };

  return (
    <div
      className="absolute inset-0 z-[60] bg-[var(--dtx-code-bg-deep)]/85 backdrop-blur-md flex items-center justify-center p-8"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md bg-[var(--dtx-code-bg)] border border-[var(--dtx-code-border)] rounded-xl shadow-2xl p-6 flex flex-col gap-5 animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--dtx-code-border)] pb-4">
          <div className="flex items-center gap-3">
            <Globe className="text-amber-400" size={22} />
            <div>
              <h2 className="text-base font-bold text-gray-200">Connect Service</h2>
              <p className="text-meta text-gray-500 uppercase tracking-widest mt-0.5">
                {showServiceLogin}
              </p>
            </div>
          </div>
          <Shield size={16} className="text-emerald-400" />
        </div>

        <div className="bg-[var(--dtx-code-bg-deep)] border border-[var(--dtx-code-border-subtle)] rounded-lg p-4 space-y-3">
          <p className="text-label text-gray-400 leading-relaxed">
            Paste your <span className="text-amber-400 font-bold">{showServiceLogin}</span> token
            below. It&apos;s stored locally in this device&apos;s app database — never sent to
            external servers.
          </p>
          <div className="flex flex-col gap-1.5">
            <label className="text-eyebrow uppercase font-bold text-gray-500 tracking-widest">
              API Key / Token
            </label>
            <input
              type="password"
              autoFocus
              value={serviceKeyInput}
              onChange={(e) => setServiceKeyInput(e.target.value)}
              placeholder={`Paste ${showServiceLogin} token here...`}
              className="bg-[var(--dtx-code-panel)] border border-[var(--dtx-code-border)] focus:border-amber-500 outline-none rounded-lg p-3 text-sm text-gray-300 w-full font-mono transition-colors"
            />
          </div>
          <div className="text-meta text-gray-600 flex items-center gap-1.5 mt-1">
            <KeyRound size={10} className="text-gray-500" />
            Stored in local SQLite → injected into os.environ → available to ToolForge
          </div>
        </div>

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm text-gray-400 hover:bg-[var(--dtx-code-border)] transition-colors"
          >
            Cancel
          </button>
          <button
            disabled={!serviceKeyInput.trim()}
            onClick={handleSave}
            className="px-5 py-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg text-sm font-bold shadow-[0_0_15px_rgba(245,158,11,0.3)] transition-all"
          >
            Save &amp; Activate
          </button>
        </div>
      </div>
    </div>
  );
}

"use client";
import { HelpCircle } from "lucide-react";

interface HelpModalProps {
  helpModal: { title: string; desc: string } | null;
  onClose: () => void;
}

export function HelpModal({ helpModal, onClose }: HelpModalProps) {
  if (!helpModal) return null;
  return (
    <div
      className="absolute inset-0 z-[100] bg-[var(--dtx-code-bg-deep)]/80 backdrop-blur-md flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm bg-[var(--dtx-code-bg)] border border-cyan-500/50 shadow-[0_0_30px_rgba(0,229,255,0.2)] rounded-xl p-6 flex flex-col gap-3 animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-[var(--dtx-code-border)] pb-3 mb-2">
          <HelpCircle className="text-cyan-400" />
          <h2 className="text-sm uppercase tracking-widest font-bold text-gray-200">
            {helpModal.title}
          </h2>
        </div>
        <p className="text-sm text-gray-400 leading-relaxed tracking-wide">{helpModal.desc}</p>
        <button
          onClick={onClose}
          className="mt-4 w-full py-2.5 bg-cyan-900/40 hover:bg-cyan-800/60 text-cyan-400 border border-cyan-500/30 hover:border-cyan-500/80 rounded-md text-xs font-bold uppercase tracking-widest transition-all"
        >
          Understood.
        </button>
      </div>
    </div>
  );
}

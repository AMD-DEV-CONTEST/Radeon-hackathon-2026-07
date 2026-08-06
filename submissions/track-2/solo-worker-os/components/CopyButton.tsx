'use client';

import { useState } from 'react';
import { useLang } from './LanguageProvider';

export default function CopyButton({
  text,
  label,
}: {
  text: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);
  const { t } = useLang();
  const displayLabel = label ?? t.copy.copy;

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard may be unavailable
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-bold transition-all duration-300 ease-expo ${
        copied
          ? 'border-amber-400/30 bg-amber-400/10 text-amber-600 dark:text-amber-300'
          : 'border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.03] text-gray-500 dark:text-white/50 hover:border-gray-300 dark:hover:border-white/[0.12] hover:text-gray-800 dark:hover:text-white/80'
      }`}
    >
      {copied ? (
        <>
          <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M16.7 5.3a1 1 0 0 1 0 1.4l-7.5 7.5a1 1 0 0 1-1.4 0L3.3 9.7a1 1 0 1 1 1.4-1.4l3.1 3.1 6.8-6.8a1 1 0 0 1 1.4 0Z" clipRule="evenodd" />
          </svg>
          {t.copy.copied}
        </>
      ) : (
        <>
          <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
            <path d="M7 3a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2H7Z" />
            <path d="M3 7a2 2 0 0 1 1-1.7V15a2 2 0 0 0 2 2h7.7A2 2 0 0 1 12 18H6a3 3 0 0 1-3-3V7Z" />
          </svg>
          {displayLabel}
        </>
      )}
    </button>
  );
}

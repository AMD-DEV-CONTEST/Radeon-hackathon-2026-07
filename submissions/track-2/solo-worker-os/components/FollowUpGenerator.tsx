'use client';

import { useState } from 'react';
import Markdown from './Markdown';
import CopyButton from './CopyButton';
import { useLang } from './LanguageProvider';

type Tone = 'polite' | 'firm' | 'final_notice';

export default function FollowUpGenerator({ projectId, clientName }: { projectId: string; clientName?: string }) {
  const { t, lang } = useLang();
  const [tone, setTone] = useState<Tone>('polite');
  const [output, setOutput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const tones = [
    { value: 'polite' as Tone, label: t.project.polite, desc: t.project.politeDesc },
    { value: 'firm' as Tone, label: t.project.firm, desc: t.project.firmDesc },
    { value: 'final_notice' as Tone, label: t.project.finalNotice, desc: t.project.finalNoticeDesc },
  ];

  async function generate() {
    setLoading(true); setError(''); setOutput('');
    try {
      const toneLabel = lang === 'zh'
      ? { polite: '礼貌', firm: '正式', final_notice: '最后催告' }[tone]
      : { polite: 'polite', firm: 'firm', final_notice: 'final notice' }[tone];
    const prompt = lang === 'zh'
      ? `为客户「${clientName ?? ''}」的项目生成一封${toneLabel}语气的催款邮件。`
      : `Generate a ${toneLabel} follow-up message for the project with client ${clientName ?? ''}.`;
    const res = await fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ persist: false, messages: [{ role: 'user', content: prompt }] }),
    });
      if (!res.ok || !res.body) { setError(await res.text().catch(() => 'Request failed')); return; }
      const reader = res.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split('\n\n'); buffer = chunks.pop() ?? '';
        for (const chunk of chunks) {
          const line = chunk.trim(); if (!line.startsWith('data: ')) continue;
          let data: { type: string; delta?: string; message?: string };
          try { data = JSON.parse(line.slice(6)); } catch { continue; }
          if (data.type === 'text' && data.delta) setOutput((prev) => prev + data.delta);
          else if (data.type === 'error') setError(data.message ?? 'Unknown error');
        }
      }
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setLoading(false); }
  }

  return (
    <div className="glass rounded-2xl p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-[15px] font-bold text-gray-800 dark:text-white/80">{t.project.followupTitle}</h3>
          <p className="mt-0.5 text-[13px] text-gray-400 dark:text-white/40">{t.project.followupDesc}</p>
        </div>
        <button type="button" onClick={() => void generate()} disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-xl bg-amber-400 px-4 py-2 text-[13px] font-bold text-black transition-all duration-200 hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-40">
          {loading ? (<><span className="h-3 w-3 animate-pulse-soft rounded-full bg-black" />{t.project.generating}</>) : t.project.generate}
        </button>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2">
        {tones.map((t_) => (
          <button key={t_.value} type="button" onClick={() => setTone(t_.value)}
            className={`rounded-xl border p-3 text-left transition-colors duration-200 ${tone === t_.value ? 'border-amber-400/30 bg-amber-400/10' : 'border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] hover:border-gray-300 dark:hover:border-white/[0.12] hover:bg-gray-100 dark:hover:bg-white/5'}`}>
            <p className={`text-[13px] font-bold ${tone === t_.value ? 'text-amber-600 dark:text-amber-300' : 'text-gray-600 dark:text-white/60'}`}>{t_.label}</p>
            <p className="mt-0.5 text-[11px] text-gray-400 dark:text-white/30">{t_.desc}</p>
          </button>
        ))}
      </div>
      {error && <p className="mt-4 rounded-lg border border-red-400/20 bg-red-400/5 px-3 py-2 text-[12px] font-medium text-red-400">{error}</p>}
      {output && (
        <div className="mt-4 rounded-xl border border-gray-200 dark:border-white/[0.04] bg-gray-50 dark:bg-white/[0.02] p-4">
          <div className="mb-3 flex justify-end"><CopyButton text={output} /></div>
          <Markdown content={output} />
        </div>
      )}
    </div>
  );
}

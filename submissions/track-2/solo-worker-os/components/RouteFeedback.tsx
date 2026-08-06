'use client';

import { useState } from 'react';
import { useLang } from './LanguageProvider';
import { getUserFacingSubagents, getSubagentLabel } from '@/lib/agent/subagent-display';

interface Props {
  /** The original user message that was routed */
  message: string;
  /** The subagent the router actually selected */
  originalSubagent: string;
  /** The route reason (for debugging context) */
  reason?: string;
}

type FeedbackState = 'idle' | 'sending_correct' | 'correct' | 'selecting' | 'submitting' | 'submitted' | 'error';

/**
 * Route feedback UI — lets the user correct or confirm routing decisions.
 *
 * "对" (correct): sends a positive feedback record to the API so the
 * correction rate accurately reflects routing quality. A correct route
 * does NOT nudge keyword weights (the learning layer skips same-subagent
 * records), but it IS counted in the denominator of the correction rate.
 *
 * "错" (wrong): shows a dropdown to pick the correct subagent, then
 * POSTs the correction which updates learned keyword weights.
 */
export default function RouteFeedback({ message, originalSubagent }: Props) {
  const { lang } = useLang();
  const [state, setState] = useState<FeedbackState>('idle');
  const [selectedSubagent, setSelectedSubagent] = useState<string>('');

  const handleCorrect = async () => {
    setState('sending_correct');
    try {
      // Send positive feedback — correctSubagent === originalSubagent
      const resp = await fetch('/api/router-feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          correctSubagent: originalSubagent,
          originalSubagent,
        }),
      });
      if (!resp.ok) throw new Error('Failed to submit');
      setState('correct');
    } catch {
      // Still show as correct — don't punish the user for a network error
      setState('correct');
    }
  };

  const handleWrong = () => {
    setState('selecting');
  };

  const handleSubmit = async () => {
    if (!selectedSubagent) return;
    setState('submitting');
    try {
      const resp = await fetch('/api/router-feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          correctSubagent: selectedSubagent,
          originalSubagent,
        }),
      });
      if (!resp.ok) throw new Error('Failed to submit');
      setState('submitted');
    } catch {
      setState('error');
    }
  };

  const labels = {
    correct: lang === 'zh' ? '对' : '✓',
    wrong: lang === 'zh' ? '错' : '✗',
    correctTitle: lang === 'zh' ? '路由正确' : 'Route correct',
    wrongTitle: lang === 'zh' ? '路由错误，点击纠正' : 'Route wrong — click to correct',
    routedCorrectly: lang === 'zh' ? '路由正确' : 'Routed correctly',
    shouldRouteTo: lang === 'zh' ? '应该路由到：' : 'Should route to:',
    select: lang === 'zh' ? '选择...' : 'Select...',
    submit: lang === 'zh' ? '提交纠正' : 'Submit correction',
    submitting: lang === 'zh' ? '提交中...' : 'Submitting...',
    submitted: lang === 'zh' ? '✓ 已记录，权重已更新' : '✓ Recorded, weights updated',
    failed: lang === 'zh' ? '提交失败' : 'Submission failed',
    retry: lang === 'zh' ? '重试' : 'Retry',
  };

  // Don't show feedback UI while streaming
  if (state === 'idle') {
    return (
      <div className="mt-0.5 flex items-center gap-1 px-1">
        <button
          onClick={handleCorrect}
          title={labels.correctTitle}
          className="inline-flex items-center gap-1 rounded-md border border-emerald-400/15 bg-emerald-400/[0.03] px-1.5 py-0.5 text-[10px] font-semibold text-gray-700 dark:text-white/30 transition-all duration-200 hover:border-emerald-400/30 hover:bg-emerald-400/10 hover:text-emerald-300"
        >
          <svg className="h-2.5 w-2.5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clipRule="evenodd" />
          </svg>
          {labels.correct}
        </button>
        <button
          onClick={handleWrong}
          title={labels.wrongTitle}
          className="inline-flex items-center gap-1 rounded-md border border-red-400/15 bg-red-400/[0.03] px-1.5 py-0.5 text-[10px] font-semibold text-gray-700 dark:text-white/30 transition-all duration-200 hover:border-red-400/30 hover:bg-red-400/10 hover:text-red-300"
        >
          <svg className="h-2.5 w-2.5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM8.28 7.22a.75.75 0 0 0-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 1 0 1.06 1.06L10 11.06l1.72 1.72a.75.75 0 1 0 1.06-1.06L11.06 10l1.72-1.72a.75.75 0 0 0-1.06-1.06L10 8.94 8.28 7.22Z" clipRule="evenodd" />
          </svg>
          {labels.wrong}
        </button>
      </div>
    );
  }

  if (state === 'sending_correct' || state === 'correct') {
    return (
      <span className="mt-0.5 inline-flex items-center gap-1 px-1 text-[10px] text-emerald-400/60">
        <svg className="h-2.5 w-2.5" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clipRule="evenodd" />
        </svg>
        {labels.routedCorrectly}
      </span>
    );
  }

  if (state === 'selecting' || state === 'submitting' || state === 'submitted' || state === 'error') {
    const options = getUserFacingSubagents().filter((s) => s.id !== originalSubagent);
    return (
      <div className="mt-0.5 flex flex-col gap-1 px-1">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold text-gray-400 dark:text-white/40">{labels.shouldRouteTo}</span>
          <select
            value={selectedSubagent}
            onChange={(e) => setSelectedSubagent(e.target.value)}
            disabled={state === 'submitted' || state === 'submitting'}
            className="rounded-md border border-gray-200 dark:border-white/10 bg-white dark:bg-black/60 px-2 py-0.5 text-[11px] text-gray-700 dark:text-white/70 outline-none focus:border-amber-400/30 disabled:opacity-50"
          >
            <option value="">{labels.select}</option>
            {options.map((s) => (
              <option key={s.id} value={s.id}>
                {getSubagentLabel(s.id, lang)} ({s.id})
              </option>
            ))}
          </select>
          {state === 'selecting' && (
            <button
              onClick={handleSubmit}
              disabled={!selectedSubagent}
              className="rounded-md bg-amber-400/20 px-2 py-0.5 text-[10px] font-semibold text-amber-300 transition-colors hover:bg-amber-400/30 disabled:opacity-30"
            >
              {labels.submit}
            </button>
          )}
          {state === 'submitting' && (
            <span className="text-[10px] font-semibold text-amber-300/70">
              {labels.submitting}
            </span>
          )}
          {state === 'submitted' && (
            <span className="text-[10px] font-semibold text-emerald-400/70">
              {labels.submitted}
            </span>
          )}
          {state === 'error' && (
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-semibold text-red-400/70">
                {labels.failed}
              </span>
              <button
                onClick={handleSubmit}
                className="rounded-md bg-red-400/15 px-2 py-0.5 text-[10px] font-semibold text-red-300 transition-colors hover:bg-red-400/25"
              >
                {labels.retry}
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  return null;
}

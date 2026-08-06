import Markdown from './Markdown';
import RouteFeedback from './RouteFeedback';
import { formatChatTime } from '@/lib/utils';
import { getSubagentDisplay, getSubagentLabel } from '@/lib/agent/subagent-display';
import Link from 'next/link';

export interface ToolChip { name: string; summary: string }

export interface RouteBadge {
  subagent: string;
  confidence: number;
  routedBy: string;
  reason: string;
}

interface Props {
  role: 'user' | 'assistant';
  content: string;
  tools?: ToolChip[];
  timestamp?: number;
  isStreaming?: boolean;
  route?: RouteBadge;
  /** The original user message that triggered this assistant response (for feedback) */
  userMessage?: string;
  /** When true (from /demo), hide the route feedback buttons to avoid signaling uncertainty */
  demoMode?: boolean;
  /** Current language for i18n */
  lang?: 'zh' | 'en';
}

export default function ChatMessage({ role, content, tools, timestamp, isStreaming, route, userMessage, demoMode, lang = 'zh' }: Props) {
  const isUser = role === 'user';
  const timeStr = timestamp ? formatChatTime(timestamp) : '';

  const nameLabel = isUser
    ? (lang === 'zh' ? '你' : 'You')
    : (lang === 'zh' ? '助手' : 'Agent');

  const routedByLabel = route
    ? route.routedBy === 'keyword'
      ? (lang === 'zh' ? '关键词路由' : 'keyword')
      : route.routedBy === 'llm'
      ? (lang === 'zh' ? 'LLM 路由' : 'llm')
      : (lang === 'zh' ? '默认' : 'default')
    : '';

  const dashboardLabel = lang === 'zh' ? '查看仪表盘' : 'View Dashboard';

  return (
    <div className={`flex gap-3 animate-fade-up ${isUser ? 'justify-end' : 'justify-start'}`}>
      {/* Assistant avatar — real image */}
      {!isUser && (
        <div className="flex-shrink-0 mt-0.5">
          <div className="relative h-8 w-8 overflow-hidden rounded-xl ring-1 ring-inset ring-white/20">
            <img src="/assistant-avatar.jpg" alt="AI Assistant" className="h-full w-full object-cover" />
          </div>
        </div>
      )}

      <div className={`flex flex-col gap-1 ${isUser ? 'items-end' : 'items-start'} max-w-[82%]`}>
        {/* Name + time row */}
        <div className={`flex items-center gap-2 px-1 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
          <span className="text-[12px] font-semibold text-gray-400 dark:text-white/30">
            {nameLabel}
          </span>
          {timeStr && (
            <span className="text-[11px] text-gray-400 dark:text-white/20 font-mono">{timeStr}</span>
          )}
        </div>

        {/* Bubble */}
        <div
          className={`rounded-2xl px-4 py-3 text-[14px] leading-relaxed ${
            isUser
              ? 'rounded-tr-sm bg-gray-100 dark:bg-white/[0.08] text-gray-900 dark:text-white ring-1 ring-inset ring-gray-200 dark:ring-white/10'
              : 'rounded-tl-sm glass text-gray-900 dark:text-white/90'
          }`}
        >
          {content ? (
            isUser ? (
              <span className="whitespace-pre-wrap break-words">{content}</span>
            ) : (
              <span>
                <Markdown content={content} />
                {isStreaming && (
                  <span className="ml-0.5 inline-block h-[1em] w-0.5 animate-cursor-blink bg-amber-400 align-text-bottom opacity-90" />
                )}
              </span>
            )
          ) : (
            /* Typing indicator */
            <span className="inline-flex items-center gap-1.5 py-0.5">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
            </span>
          )}
        </div>

        {/* Route badge — shows which Subagent handled this turn */}
        {!isUser && route && (() => {
          const display = getSubagentDisplay(route.subagent);
          const label = getSubagentLabel(route.subagent, lang);
          return (
            <div className="mt-0.5 flex items-center gap-1.5 px-1">
              <span
                title={route.reason}
                className={`inline-flex items-center gap-1.5 rounded-lg border ${display.badge.bg} px-2 py-0.5 text-[10px] font-semibold ${display.badge.text}`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${display.badge.bg.replace('bg-', 'bg-').replace('/10', '/60')}`} />
                {label}
                <span className="text-gray-300 dark:text-white/20">·</span>
                <span className="font-mono text-gray-400 dark:text-white/30">{routedByLabel}</span>
                <span className="text-gray-300 dark:text-white/20">·</span>
                <span className="font-mono text-gray-400 dark:text-white/30">{Math.round(route.confidence * 100)}%</span>
              </span>
              {/* Router self-learning feedback — only show when not streaming and not in demo mode */}
              {!isStreaming && userMessage && !demoMode && (
                <RouteFeedback
                  message={userMessage}
                  originalSubagent={route.subagent}
                  reason={route.reason}
                />
              )}
            </div>
          );
        })()}

        {/* Tool chips */}
        {!isUser && tools && tools.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2 px-1">
            {tools.map((t, i) => {
              const isFinanceTool = ['generate_invoice', 'record_payment', 'export_monthly_report'].includes(t.name);
              const isDocTool = ['generate_contract', 'generate_followup_message'].includes(t.name);
              const dotColor = isFinanceTool ? 'bg-emerald-400' : isDocTool ? 'bg-sky-400' : 'bg-amber-400';
              return (
                <span
                  key={i}
                  title={t.summary}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/[0.03] px-2.5 py-1 text-[11px] font-semibold text-gray-600 dark:text-white/60 transition-colors hover:border-gray-300 dark:hover:border-white/20 hover:text-gray-800 dark:hover:text-white/80"
                >
                  <span className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${dotColor}`} />
                  {t.name}
                  {t.summary && (
                    <span className="max-w-[160px] truncate text-[10px] font-normal text-gray-400 dark:text-white/30">
                      · {t.summary}
                    </span>
                  )}
                </span>
              );
            })}
            {/* Dashboard link — appears when a data-modifying tool was called */}
            {tools.some((t) => ['create_project', 'update_project_status', 'record_payment', 'generate_invoice'].includes(t.name)) && !isStreaming && (
              <Link
                href="/dashboard"
                className="inline-flex items-center gap-1 rounded-lg border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/[0.03] px-2.5 py-1 text-[11px] font-semibold text-gray-500 dark:text-white/50 transition-colors hover:border-gray-300 dark:hover:border-white/20 hover:text-gray-700 dark:hover:text-white/80"
              >
                <svg className="h-3 w-3 flex-shrink-0 opacity-70" viewBox="0 0 20 20" fill="currentColor"><path d="M3 4.25a1.25 1.25 0 0 1 1.25-1.25h11.5a1.25 1.25 0 0 1 1.25 1.25v11.5a1.25 1.25 0 0 1-1.25 1.25H4.25A1.25 1.25 0 0 1 3 15.75V4.25ZM6.5 6a.75.75 0 0 0 0 1.5h7a.75.75 0 0 0 0-1.5h-7ZM6.5 9.25a.75.75 0 0 0 0 1.5h4a.75.75 0 0 0 0-1.5h-4ZM6.5 12.5a.75.75 0 0 0 0 1.5h7a.75.75 0 0 0 0-1.5h-7Z" /></svg>
                {dashboardLabel}
              </Link>
            )}
          </div>
        )}
      </div>

      {/* User avatar — real image */}
      {isUser && (
        <div className="flex-shrink-0 mt-0.5">
          <div className="relative h-8 w-8 overflow-hidden rounded-xl ring-1 ring-inset ring-white/15">
            <img src="/avatar.jpg" alt="User" className="h-full w-full object-cover" />
          </div>
        </div>
      )}
    </div>
  );
}

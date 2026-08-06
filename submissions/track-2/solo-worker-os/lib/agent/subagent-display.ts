/**
 * Single source of truth for subagent display metadata.
 *
 * Every component that renders subagent labels, badges, or options MUST
 * import from here — no local copies. This eliminates the drift that
 * previously existed across ChatMessage, ChatClient, trace, RouteFeedback,
 * and demo pages.
 */

import type { SubagentId } from './types';

export interface SubagentDisplayConfig {
  id: SubagentId;
  /** Short label shown in badges and dropdowns */
  labelZh: string;
  labelEn: string;
  /** Tailwind classes for badge styling */
  badge: { bg: string; border: string; text: string };
  /** Whether this subagent appears in the router feedback dropdown */
  userFacing: boolean;
}

export const SUBAGENT_DISPLAY: Record<string, SubagentDisplayConfig> = {
  general: {
    id: 'general',
    labelZh: '项目管理',
    labelEn: 'General',
    badge: { bg: 'bg-amber-400/10', border: 'border-amber-400/20', text: 'text-amber-300' },
    userFacing: true,
  },
  knowledge_rag: {
    id: 'knowledge_rag',
    labelZh: '知识搜索',
    labelEn: 'Knowledge',
    badge: { bg: 'bg-teal-400/10', border: 'border-teal-400/20', text: 'text-teal-300' },
    userFacing: true,
  },
  data_analysis: {
    id: 'data_analysis',
    labelZh: '数据分析',
    labelEn: 'Analytics',
    badge: { bg: 'bg-sky-400/10', border: 'border-sky-400/20', text: 'text-sky-300' },
    userFacing: true,
  },
  writing_assistant: {
    id: 'writing_assistant',
    labelZh: '智能写作',
    labelEn: 'Writing',
    badge: { bg: 'bg-violet-400/10', border: 'border-violet-400/20', text: 'text-violet-300' },
    userFacing: true,
  },
  quick_chat: {
    id: 'quick_chat',
    labelZh: '闲聊',
    labelEn: 'Quick Chat',
    badge: { bg: 'bg-white/5', border: 'border-white/10', text: 'text-white/50' },
    userFacing: true,
  },
  blockchain: {
    id: 'blockchain',
    labelZh: '区块链',
    labelEn: 'Blockchain',
    badge: { bg: 'bg-indigo-400/10', border: 'border-indigo-400/20', text: 'text-indigo-300' },
    userFacing: true,
  },
};

/** Get display config with safe fallback for unknown subagent IDs */
export function getSubagentDisplay(id: string): SubagentDisplayConfig {
  return SUBAGENT_DISPLAY[id] ?? {
    id: id as SubagentId,
    labelZh: id,
    labelEn: id,
    badge: { bg: 'bg-white/5', border: 'border-white/10', text: 'text-white/50' },
    userFacing: false,
  };
}

/** Get localized label */
export function getSubagentLabel(id: string, lang: 'zh' | 'en'): string {
  const config = getSubagentDisplay(id);
  return lang === 'zh' ? config.labelZh : config.labelEn;
}

/** Get all user-facing subagent options (for feedback dropdowns) */
export function getUserFacingSubagents(): SubagentDisplayConfig[] {
  return Object.values(SUBAGENT_DISPLAY).filter((s) => s.userFacing);
}

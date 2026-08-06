/**
 * Demo scenarios across 5 business domains.
 *
 * Each domain targets a different Subagent and exercises a different tool.
 * Used by /demo and /chat prefilled prompts.
 */

import type { SubagentId } from '@/lib/agent/types';

export interface DemoScenario {
  id: string;
  domain: DemoDomain;
  title: string;
  subtitle: string;
  prompt: string;
  expectedSubagent: SubagentId;
  expectedTool: string | null;
}

export type DemoDomain =
  | 'project_management'
  | 'knowledge_search'
  | 'data_analysis'
  | 'writing_assistant'
  | 'schedule_tasks';

export interface DemoDomainConfig {
  id: DemoDomain;
  label: string;
  labelEn: string;
  description: string;
}

// ─── Domain metadata ──────────────────────────────────────────────────────────

export const DEMO_DOMAINS: DemoDomainConfig[] = [
  {
    id: 'project_management',
    label: '项目管理',
    labelEn: 'Project Management',
    description: '用对话创建项目、更新状态，系统自动整理客户和预算信息',
  },
  {
    id: 'knowledge_search',
    label: '知识搜索',
    labelEn: 'Knowledge Base',
    description: '从你的合同模板、客户备注、报价标准中快速找到答案',
  },
  {
    id: 'data_analysis',
    label: '数据分析',
    labelEn: 'Analytics',
    description: '一句话生成业务概况、收入统计、逾期分析',
  },
  {
    id: 'writing_assistant',
    label: '智能写作',
    labelEn: 'Writing',
    description: '自动生成服务合同、催款邮件、跟进消息',
  },
  {
    id: 'schedule_tasks',
    label: '日程待办',
    labelEn: 'Schedule',
    description: '查看截止日期、逾期项目和待办提醒',
  },
];

// ─── Scenarios ────────────────────────────────────────────────────────────────

export const DEMO_SCENARIOS: DemoScenario[] = [
  // ── Project Management ──
  {
    id: 'pm-1',
    domain: 'project_management',
    title: '创建项目',
    subtitle: '一句话录入客户和项目信息',
    prompt: '新客户 — 周晨，需要做企业官网改版，预算 12000 元，截止日期 8月20日。请帮我创建项目。',
    expectedSubagent: 'general',
    expectedTool: 'create_project',
  },
  {
    id: 'pm-2',
    domain: 'project_management',
    title: '更新状态',
    subtitle: '对话式更新，不用填表',
    prompt: '把 张明 的项目状态更新为 delivered',
    expectedSubagent: 'general',
    expectedTool: 'update_project_status',
  },
  {
    id: 'pm-3',
    domain: 'project_management',
    title: '汇率查询',
    subtitle: '多币种业务实时换算',
    prompt: '查一下 USD 到 CNY 的汇率',
    expectedSubagent: 'general',
    expectedTool: 'get_exchange_rates',
  },

  // ── Knowledge Search ──
  {
    id: 'ks-1',
    domain: 'knowledge_search',
    title: '付款条款',
    subtitle: '从合同模板中找到条款',
    prompt: '我的标准付款条款是什么？',
    expectedSubagent: 'knowledge_rag',
    expectedTool: 'search_knowledge_base',
  },
  {
    id: 'ks-2',
    domain: 'knowledge_search',
    title: '客户偏好',
    subtitle: '查找客户备注和沟通习惯',
    prompt: '查找客户偏好和备注',
    expectedSubagent: 'knowledge_rag',
    expectedTool: 'search_knowledge_base',
  },
  {
    id: 'ks-3',
    domain: 'knowledge_search',
    title: '催款模板',
    subtitle: '匹配催款邮件模板',
    prompt: 'Search for payment reminder templates',
    expectedSubagent: 'knowledge_rag',
    expectedTool: 'search_knowledge_base',
  },

  // ── Data Analysis ──
  {
    id: 'da-1',
    domain: 'data_analysis',
    title: '业务概况',
    subtitle: '一句话汇总全部业务',
    prompt: '给我一个业务概况 overview',
    expectedSubagent: 'data_analysis',
    expectedTool: 'analyze_business_data',
  },
  {
    id: 'da-2',
    domain: 'data_analysis',
    title: '收入统计',
    subtitle: '按状态分组统计收入',
    prompt: '统计一下我的收入情况',
    expectedSubagent: 'data_analysis',
    expectedTool: 'analyze_business_data',
  },
  {
    id: 'da-3',
    domain: 'data_analysis',
    title: '逾期分析',
    subtitle: '识别逾期项目并提醒',
    prompt: '哪些项目逾期了？',
    expectedSubagent: 'data_analysis',
    expectedTool: 'analyze_business_data',
  },

  // ── Writing Assistant ──
  {
    id: 'wa-1',
    domain: 'writing_assistant',
    title: '生成合同',
    subtitle: '基于项目信息自动生成',
    prompt: '为 王浩 的项目生成一份合同',
    expectedSubagent: 'writing_assistant',
    expectedTool: 'generate_contract',
  },
  {
    id: 'wa-2',
    domain: 'writing_assistant',
    title: '催款邮件',
    subtitle: '根据状态选择催款语气',
    prompt: '给 张明 写一封催款邮件',
    expectedSubagent: 'writing_assistant',
    expectedTool: 'generate_followup_message',
  },
  {
    id: 'wa-3',
    domain: 'writing_assistant',
    title: '跟进消息',
    subtitle: '匹配项目上下文生成',
    prompt: '为 刘洋 的宣传视频项目写一封跟进消息',
    expectedSubagent: 'writing_assistant',
    expectedTool: 'generate_followup_message',
  },

  // ── Schedule & Tasks ──
  {
    id: 'st-1',
    domain: 'schedule_tasks',
    title: '本周待办',
    subtitle: '查看本周截止和逾期项目',
    prompt: '本周有什么要交的？帮我看看待办日程',
    expectedSubagent: 'general',
    expectedTool: 'get_upcoming_deadlines',
  },
  {
    id: 'st-2',
    domain: 'schedule_tasks',
    title: '即将到期',
    subtitle: '按截止日期排优先级',
    prompt: '未来三天有哪些截止日期？帮我排个优先级',
    expectedSubagent: 'general',
    expectedTool: 'get_upcoming_deadlines',
  },
  {
    id: 'st-3',
    domain: 'schedule_tasks',
    title: '逾期提醒',
    subtitle: '识别逾期并按优先级排序',
    prompt: '查看我的待办提醒，有没有逾期的项目？',
    expectedSubagent: 'general',
    expectedTool: 'get_upcoming_deadlines',
  },
];

// ─── Featured scenarios (shown on landing page — 6 only) ─────────────────────

export const FEATURED_SCENARIO_IDS = ['pm-1', 'wa-1', 'da-1', 'pm-2', 'ks-1', 'st-1'];

export function getFeaturedScenarios(): DemoScenario[] {
  return FEATURED_SCENARIO_IDS
    .map((id) => DEMO_SCENARIOS.find((s) => s.id === id))
    .filter((s): s is DemoScenario => s !== undefined);
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

export function getScenariosByDomain(domain: DemoDomain): DemoScenario[] {
  return DEMO_SCENARIOS.filter((s) => s.domain === domain);
}

export function getDomainConfig(domain: DemoDomain): DemoDomainConfig {
  return DEMO_DOMAINS.find((d) => d.id === domain)!;
}

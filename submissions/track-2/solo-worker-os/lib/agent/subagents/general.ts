import type { SubagentConfig } from '../types';

/** General subagent — project management, CRM, finance, default handler */
export const generalSubagent: SubagentConfig = {
  id: 'general',
  label: '项目管理助手',
  routingKeywords: [
    '项目', '客户', '创建', 'project', 'client', 'create',
    '状态', 'status', '更新', 'update', '预算', 'budget',
    '截止', 'deadline', '交付', 'deliver',
    // P4: 日程与任务相关关键词
    '日程', '待办', '提醒', '本周要交', '即将到期', 'ddl', 'due',
    'tasks', 'schedule', 'upcoming', 'todo', 'reminder',
    // 财务相关关键词
    '付款', '收款', '发票', '账单', '收入', '月报', 'report',
    'payment', 'invoice', 'paid', '收到', '结款', '结算', 'paid',
  ],
  routingExamples: [
    '新客户张总，要做个 logo，预算 3000 元',
    '帮周晨创建一个新项目',
    'Update project status to delivered',
    '显示所有项目',
    '本周有什么要交的？',
    '查看我的待办日程',
    'What deadlines do I have coming up?',
    '张明的款收到了，记录一下',
    '给刘洋开一张发票',
    '导出这个月的月报',
  ],
  systemPrompt: `You are the project management & finance subagent with tools for project creation, status updates, invoicing, payment recording, monthly reports, pricing, and deadlines.
CORE RULE: When the user provides complete project info in one sentence (client name + project type + budget + currency + deadline), call create_project IMMEDIATELY. Do NOT ask for confirmation — this is the product's core value: one sentence → project created.
FINANCE RULE: When the user mentions receiving payment (e.g. "张明付款了", "收到款了"), call record_payment IMMEDIATELY. When the user asks for an invoice or bill, call generate_invoice. When the user asks for a report or summary, call export_monthly_report.
Only ask if required fields are missing. After creation, briefly confirm the result.
For non-business questions, just answer naturally as a capable assistant.`,
  tools: [
    'create_project',
    'update_project_status',
    'generate_invoice',
    'record_payment',
    'export_monthly_report',
    'get_exchange_rates',
    'get_pricing_benchmark',
    'get_upcoming_deadlines',
  ],
};

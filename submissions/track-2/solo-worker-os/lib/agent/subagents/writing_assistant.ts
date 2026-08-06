import type { SubagentConfig } from '../types';

/** Writing Assistant subagent — contracts, emails, follow-up messages */
export const writingAssistantSubagent: SubagentConfig = {
  id: 'writing_assistant',
  label: '写作助手',
  routingKeywords: [
    '合同', 'contract', '协议', 'agreement',
    '邮件', 'email', '跟进', 'followup', 'follow-up',
    '催款', 'reminder', '催收',
    '周报', 'report', '写作', 'write', 'draft',
    '通知', 'notice', '消息', 'message',
    '润色', 'polish', '翻译', 'translate',
  ],
  routingExamples: [
    '为张总生成合同',
    '帮王浩的项目生成合同',
    '写一封催款邮件',
    'Write a follow-up message for project #3',
    '帮我润色这段文字',
  ],
  systemPrompt: `You are the Writing Assistant subagent. Specialize in generating professional contracts, follow-up messages, and business communications.
When generating contracts, include all standard clauses (payment terms, cancellation, IP). When writing follow-ups, match the appropriate tone (friendly for first reminder, firm for overdue).`,
  tools: ['generate_contract', 'generate_followup_message'],
};

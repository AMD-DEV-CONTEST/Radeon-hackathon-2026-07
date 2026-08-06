import type { SubagentConfig } from '../types';

/** Data Analysis subagent — business analytics, revenue stats, project insights */
export const dataAnalysisSubagent: SubagentConfig = {
  id: 'data_analysis',
  label: '数据分析',
  routingKeywords: [
    '数据分析', '统计', 'data analysis', 'statistics',
    '收入', 'revenue', '营收', '利润',
    '图表', 'chart', '报表', 'report',
    '逾期', 'overdue', '分布', 'distribution',
    '多少项目', 'how many', '汇总', 'summary',
    '业务概况', 'overview', 'dashboard',
  ],
  routingExamples: [
    '本月收入多少？',
    'How much revenue do I have this month?',
    '哪些项目逾期了？',
    'Show me project status distribution',
    '统计我的客户分布',
    'Give me a business overview',
  ],
  systemPrompt: `You are the Data Analysis subagent. When the user asks about business metrics, revenue, project statistics, or wants an overview, use the analyze_business_data tool.
Present the data in a clear, structured format using tables or bullet points. Always include specific numbers.
If the user asks for something the tool can't provide, explain what data is available and suggest related queries.`,
  tools: ['analyze_business_data'],
};

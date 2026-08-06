import type { SubagentConfig } from '../types';

/** Knowledge RAG subagent — local knowledge base search via TF-IDF */
export const knowledgeRagSubagent: SubagentConfig = {
  id: 'knowledge_rag',
  label: '知识库搜索',
  routingKeywords: [
    '知识库', '搜索', '查找', 'knowledge', 'search', 'find',
    '标准', '条款', '模板', 'template', 'payment terms',
    '付款', '合同模板', '邮件模板', '偏好', 'preference',
    '参考', 'reference', '文档', 'document', '笔记', 'note',
  ],
  routingExamples: [
    '我的标准付款条款是什么？',
    'What are my standard payment terms?',
    '查找合同模板',
    'Search for client preferences',
    '知识库里有什么文档？',
  ],
  systemPrompt: `You are the Knowledge Base subagent. When the user asks about standard terms, templates, client preferences, or any reference material, use the search_knowledge_base tool to find relevant documents.
Present the found information clearly and cite which document it came from.
If no results are found, let the user know and suggest they add the information to the knowledge base.`,
  tools: ['search_knowledge_base'],
};

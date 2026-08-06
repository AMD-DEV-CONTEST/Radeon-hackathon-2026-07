/**
 * router.test.ts — FunctionRouter 关键词路由核心测试
 *
 * 通过 `routeMessageSync` 间接测试 `keywordRoute`（Layer 1 关键词匹配）。
 * 同时覆盖 tie-breaker 逻辑、默认路由以及 `getRoutedTools` 的工具隔离。
 *
 * 注意：以下测试基于 lib/agent/subagents/ 中各子智能体实际配置的
 * `routingKeywords`，反映路由器的真实行为。
 */

import { describe, it, expect } from 'vitest';
import { routeMessageSync, getRoutedTools } from '@/lib/agent/router';
import type { SubagentId } from '@/lib/agent/types';

// ─── keywordRoute（通过 routeMessageSync 间接测试）─────────────────────────────

describe('keywordRoute (via routeMessageSync)', () => {
  // ─── general 子智能体路由 ───────────────────────────────────────────────────
  describe('general 子智能体路由', () => {
    it('包含"项目"关键词时路由到 general', () => {
      // "创建" + "项目" 均命中 general，score = 2
      const result = routeMessageSync('帮周晨创建一个新项目');
      expect(result.subagent).toBe('general');
      expect(result.routedBy).toBe('keyword');
    });

    it('包含"客户"关键词时路由到 general', () => {
      const result = routeMessageSync('新客户张总，要做个 logo');
      expect(result.subagent).toBe('general');
      expect(result.routedBy).toBe('keyword');
    });

    it('包含"预算"关键词时路由到 general', () => {
      const result = routeMessageSync('预算 3000 元');
      expect(result.subagent).toBe('general');
      expect(result.routedBy).toBe('keyword');
    });

    it('包含"截止"关键词时路由到 general', () => {
      const result = routeMessageSync('截止日期快到了');
      expect(result.subagent).toBe('general');
      expect(result.routedBy).toBe('keyword');
    });
  });

  // ─── knowledge_rag 子智能体路由 ─────────────────────────────────────────────
  describe('knowledge_rag 子智能体路由', () => {
    it('包含"知识库"关键词时路由到 knowledge_rag', () => {
      // "搜索" + "知识库" 均命中 knowledge_rag，score = 2
      const result = routeMessageSync('搜索知识库');
      expect(result.subagent).toBe('knowledge_rag');
      expect(result.routedBy).toBe('keyword');
    });

    it('包含"文档"关键词时路由到 knowledge_rag', () => {
      // "查找" + "文档" 均命中 knowledge_rag
      const result = routeMessageSync('查找文档');
      expect(result.subagent).toBe('knowledge_rag');
      expect(result.routedBy).toBe('keyword');
    });

    it('包含"搜索"关键词时路由到 knowledge_rag', () => {
      // "搜索" + "参考" + "文档" 命中 knowledge_rag，score = 3
      const result = routeMessageSync('搜索参考文档');
      expect(result.subagent).toBe('knowledge_rag');
      expect(result.routedBy).toBe('keyword');
    });
  });

  // ─── tie-breaker 逻辑 ───────────────────────────────────────────────────────
  describe('tie-breaker：general 与 specific 得分相同时优先 specific', () => {
    it('general 与 knowledge_rag 得分相同（各 1）时优先 knowledge_rag', () => {
      // "项目" 命中 general (score 1)，"模板" 命中 knowledge_rag (score 1)
      // 两者得分相同，confidence = 1/2 = 0.5 >= 0.4，触发 tie-breaker
      const result = routeMessageSync('项目模板');
      expect(result.subagent).toBe('knowledge_rag');
      expect(result.confidence).toBe(0.5);
      expect(result.routedBy).toBe('keyword');
      expect(result.reason).toContain('Tie-breaker');
    });

    it('general 与 writing_assistant 得分相同（各 1）时优先 writing_assistant', () => {
      // "项目" 命中 general (score 1)，"合同" 命中 writing_assistant (score 1)
      const result = routeMessageSync('项目合同');
      expect(result.subagent).toBe('writing_assistant');
      expect(result.confidence).toBe(0.5);
      expect(result.routedBy).toBe('keyword');
      expect(result.reason).toContain('Tie-breaker');
    });

    it('tie-breaker 总是将 general 让位给任意 specific 子智能体', () => {
      // "状态" 命中 general (score 1)，"统计" 命中 data_analysis (score 1)
      const result = routeMessageSync('状态统计');
      expect(result.subagent).toBe('data_analysis');
      expect(result.confidence).toBe(0.5);
    });
  });

  // ─── 默认路由 ───────────────────────────────────────────────────────────────
  describe('无匹配时默认路由到 general', () => {
    it('无任何关键词命中时路由到 general，confidence 为 0.3', () => {
      const result = routeMessageSync('qwerty asdf zxcv');
      expect(result.subagent).toBe('general');
      expect(result.confidence).toBe(0.3);
      expect(result.routedBy).toBe('default');
      expect(result.reason).toContain('default');
    });

    it('中文无匹配文本也默认路由到 general', () => {
      const result = routeMessageSync('今天中午吃什么好呢');
      expect(result.subagent).toBe('general');
      expect(result.confidence).toBe(0.3);
      expect(result.routedBy).toBe('default');
    });
  });
});

// ─── getRoutedTools 工具隔离 ────────────────────────────────────────────────────

describe('getRoutedTools — 工具隔离', () => {
  it('general 子智能体返回其专属工具集', () => {
    const tools = getRoutedTools('general', []);
    expect(tools).toEqual(
      expect.arrayContaining([
        'create_project',
        'update_project_status',
        'get_exchange_rates',
        'get_pricing_benchmark',
        'get_upcoming_deadlines',
      ]),
    );
    // 不应包含其他子智能体的工具
    expect(tools).not.toContain('search_knowledge_base');
    expect(tools).not.toContain('generate_contract');
  });

  it('knowledge_rag 子智能体只返回 search_knowledge_base', () => {
    const tools = getRoutedTools('knowledge_rag', []);
    expect(tools).toEqual(['search_knowledge_base']);
    expect(tools).not.toContain('create_project');
  });

  it('writing_assistant 子智能体返回写作工具', () => {
    const tools = getRoutedTools('writing_assistant', []);
    expect(tools).toEqual(
      expect.arrayContaining(['generate_contract', 'generate_followup_message']),
    );
    expect(tools).not.toContain('create_project');
    expect(tools).not.toContain('search_knowledge_base');
  });

  it('data_analysis 子智能体返回 analyze_business_data', () => {
    const tools = getRoutedTools('data_analysis', []);
    expect(tools).toEqual(['analyze_business_data']);
  });

  it('quick_chat 子智能体（lightweight）不返回任何工具', () => {
    const tools = getRoutedTools('quick_chat', []);
    expect(tools).toEqual([]);
  });

  it('不同子智能体返回互不相同的工具集', () => {
    const subagents: SubagentId[] = [
      'general',
      'knowledge_rag',
      'writing_assistant',
      'data_analysis',
      'quick_chat',
    ];
    const toolSets = subagents.map((id) => getRoutedTools(id, []));

    // 每个子智能体的工具集互不相同
    for (let i = 0; i < toolSets.length; i++) {
      for (let j = i + 1; j < toolSets.length; j++) {
        expect(toolSets[i]).not.toEqual(toolSets[j]);
      }
    }

    // quick_chat 工具集为空（工具隔离的最严格形式）
    expect(toolSets[4]).toEqual([]);
  });

  it('allToolNames 参数不影响结果（工具来自子智能体配置）', () => {
    // 即使传入大量工具名，getRoutedTools 仍只返回该子智能体配置的工具
    const tools = getRoutedTools('knowledge_rag', [
      'create_project',
      'generate_contract',
      'analyze_business_data',
      'search_knowledge_base',
    ]);
    expect(tools).toEqual(['search_knowledge_base']);
  });
});

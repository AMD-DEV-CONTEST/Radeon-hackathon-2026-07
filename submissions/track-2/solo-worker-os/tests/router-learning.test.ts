/**
 * router-learning.test.ts — Router 自学习模块测试
 *
 * 覆盖：
 *   1. FeedbackStore —— 反馈记录的增删查、纠正率计算、超限自动淘汰
 *   2. KeywordWeightAdjuster —— 权重重算、默认值、正确/错误子智能体权重增减
 *
 * 所有测试使用独立实例（new FeedbackStore / new KeywordWeightAdjuster），
 * 不依赖模块级单例，确保用例间状态隔离。
 *
 * 权重调整规则（源自 router-learning.ts）：
 *   - 每条纠正反馈（correctSubagent != originalSubagent）：
 *       correct 子智能体匹配关键词  +0.1  (CORRECT_BOOST)
 *       wrong  子智能体匹配关键词  -0.05 (WRONG_PENALTY)
 *   - 权重钳制在 [0.1, 2.0]
 *   - 无学习信号时权重为 1.0 (DEFAULT_WEIGHT)
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
  FeedbackStore,
  KeywordWeightAdjuster,
} from '@/lib/agent/router-learning';

// ─── FeedbackStore ─────────────────────────────────────────────────────────────

describe('FeedbackStore', () => {
  let store: FeedbackStore;

  beforeEach(() => {
    // 每个用例使用全新实例，避免相互干扰
    store = new FeedbackStore(1000);
  });

  // ─── addFeedback ─────────────────────────────────────────────────────────────
  describe('addFeedback', () => {
    it('添加一条反馈记录并返回完整记录', () => {
      const record = store.addFeedback('搜索项目', 'knowledge_rag', 'general');

      expect(record).toBeDefined();
      expect(record.message).toBe('搜索项目');
      expect(record.correctSubagent).toBe('knowledge_rag');
      expect(record.originalSubagent).toBe('general');
      expect(typeof record.timestamp).toBe('number');
      expect(record.timestamp).toBeGreaterThan(0);
      expect(store.size()).toBe(1);
    });

    it('连续添加多条记录后 size 正确递增', () => {
      store.addFeedback('msg1', 'knowledge_rag', 'general');
      expect(store.size()).toBe(1);

      store.addFeedback('msg2', 'data_analysis', 'general');
      expect(store.size()).toBe(2);

      store.addFeedback('msg3', 'writing_assistant', 'general');
      expect(store.size()).toBe(3);
    });

    it('correctSubagent 与 originalSubagent 可以相同（非纠正反馈）', () => {
      const record = store.addFeedback('你好', 'quick_chat', 'quick_chat');
      expect(record.correctSubagent).toBe(record.originalSubagent);
      expect(store.size()).toBe(1);
    });
  });

  // ─── getFeedbackHistory ──────────────────────────────────────────────────────
  describe('getFeedbackHistory', () => {
    it('返回的记录按最新优先排序', () => {
      store.addFeedback('first', 'knowledge_rag', 'general');
      store.addFeedback('second', 'data_analysis', 'general');
      store.addFeedback('third', 'writing_assistant', 'general');

      const history = store.getFeedbackHistory();
      expect(history).toHaveLength(3);
      // 最新（最后插入的）排在最前
      expect(history[0].message).toBe('third');
      expect(history[1].message).toBe('second');
      expect(history[2].message).toBe('first');
    });

    it('limit 参数限制返回条数（仍为最新优先）', () => {
      for (let i = 0; i < 10; i++) {
        store.addFeedback(`msg-${i}`, 'knowledge_rag', 'general');
      }

      const history = store.getFeedbackHistory(3);
      expect(history).toHaveLength(3);
      expect(history[0].message).toBe('msg-9'); // 最新
      expect(history[1].message).toBe('msg-8');
      expect(history[2].message).toBe('msg-7');
    });

    it('空 store 返回空数组', () => {
      const history = store.getFeedbackHistory();
      expect(history).toEqual([]);
    });

    it('返回的是防御性副本，修改不影响内部状态', () => {
      store.addFeedback('msg1', 'knowledge_rag', 'general');
      const history = store.getFeedbackHistory();
      history.pop();
      history.push({
        message: 'injected',
        correctSubagent: 'general',
        originalSubagent: 'general',
        timestamp: 0,
      });

      // 内部状态不受影响
      const fresh = store.getFeedbackHistory();
      expect(fresh).toHaveLength(1);
      expect(fresh[0].message).toBe('msg1');
    });
  });

  // ─── getCorrectionRate ───────────────────────────────────────────────────────
  describe('getCorrectionRate', () => {
    it('空 store 返回全零', () => {
      const rate = store.getCorrectionRate();
      expect(rate.total).toBe(0);
      expect(rate.corrected).toBe(0);
      expect(rate.rate).toBe(0);
    });

    it('正确计算纠正率（correct != original 视为纠正）', () => {
      // 3 条纠正 + 1 条非纠正
      store.addFeedback('msg1', 'knowledge_rag', 'general'); // 纠正
      store.addFeedback('msg2', 'data_analysis', 'general'); // 纠正
      store.addFeedback('msg3', 'general', 'general'); // 非纠正
      store.addFeedback('msg4', 'writing_assistant', 'general'); // 纠正

      const rate = store.getCorrectionRate();
      expect(rate.total).toBe(4);
      expect(rate.corrected).toBe(3);
      expect(rate.rate).toBe(0.75);
    });

    it('全部为非纠正时 corrected 为 0', () => {
      store.addFeedback('msg1', 'general', 'general');
      store.addFeedback('msg2', 'knowledge_rag', 'knowledge_rag');

      const rate = store.getCorrectionRate();
      expect(rate.total).toBe(2);
      expect(rate.corrected).toBe(0);
      expect(rate.rate).toBe(0);
    });

    it('全部为纠正时 rate 为 1', () => {
      store.addFeedback('msg1', 'knowledge_rag', 'general');
      store.addFeedback('msg2', 'data_analysis', 'general');

      const rate = store.getCorrectionRate();
      expect(rate.total).toBe(2);
      expect(rate.corrected).toBe(2);
      expect(rate.rate).toBe(1);
    });
  });

  // ─── 超限自动淘汰 ────────────────────────────────────────────────────────────
  describe('超过 maxRecords 时自动淘汰', () => {
    it('超出容量时淘汰最旧记录', () => {
      const smallStore = new FeedbackStore(3);

      smallStore.addFeedback('first', 'knowledge_rag', 'general');
      smallStore.addFeedback('second', 'knowledge_rag', 'general');
      smallStore.addFeedback('third', 'knowledge_rag', 'general');
      expect(smallStore.size()).toBe(3);

      // 插入第 4 条，触发淘汰
      smallStore.addFeedback('fourth', 'knowledge_rag', 'general');
      expect(smallStore.size()).toBe(3); // 仍然 3 条

      const history = smallStore.getFeedbackHistory();
      const messages = history.map((r) => r.message);

      // "first" 被淘汰，保留 second / third / fourth
      expect(messages).not.toContain('first');
      expect(messages).toContain('second');
      expect(messages).toContain('third');
      expect(messages).toContain('fourth');
    });

    it('连续大量插入后只保留最后 maxRecords 条', () => {
      const smallStore = new FeedbackStore(5);

      for (let i = 0; i < 20; i++) {
        smallStore.addFeedback(`msg-${i}`, 'knowledge_rag', 'general');
      }

      expect(smallStore.size()).toBe(5);

      const history = smallStore.getFeedbackHistory();
      const messages = history.map((r) => r.message);
      // 保留最后 5 条：msg-15 ~ msg-19
      expect(messages).toEqual([
        'msg-19',
        'msg-18',
        'msg-17',
        'msg-16',
        'msg-15',
      ]);
    });

    it('maxRecords=1 时只保留最新一条', () => {
      const tinyStore = new FeedbackStore(1);
      tinyStore.addFeedback('first', 'knowledge_rag', 'general');
      tinyStore.addFeedback('second', 'knowledge_rag', 'general');

      expect(tinyStore.size()).toBe(1);
      expect(tinyStore.getFeedbackHistory()[0].message).toBe('second');
    });
  });
});

// ─── KeywordWeightAdjuster ─────────────────────────────────────────────────────

describe('KeywordWeightAdjuster', () => {
  let store: FeedbackStore;
  let adjuster: KeywordWeightAdjuster;

  beforeEach(() => {
    store = new FeedbackStore(1000);
    adjuster = new KeywordWeightAdjuster(store);
  });

  // ─── getAdjustedWeight 默认值 ────────────────────────────────────────────────
  describe('getAdjustedWeight 默认值', () => {
    it('无学习信号时返回 1.0', () => {
      // 空 store，无任何反馈
      const weight = adjuster.getAdjustedWeight('general', '项目');
      expect(weight).toBe(1.0);
    });

    it('未参与纠正的关键词返回 1.0', () => {
      // 添加一条只涉及 "搜索" 的反馈
      store.addFeedback('搜索', 'knowledge_rag', 'general');
      adjuster.recompute();

      // "预算" 没有出现在消息中，不受影响
      const weight = adjuster.getAdjustedWeight('general', '预算');
      expect(weight).toBe(1.0);
    });

    it('无纠正反馈（correct == original）时所有关键词均为 1.0', () => {
      store.addFeedback('项目', 'general', 'general');
      adjuster.recompute();

      expect(adjuster.getAdjustedWeight('general', '项目')).toBe(1.0);
      expect(adjuster.hasAdjustments()).toBe(false);
    });
  });

  // ─── recompute 权重计算 ──────────────────────────────────────────────────────
  describe('recompute 权重计算', () => {
    it('正确子智能体关键词权重增加，错误子智能体权重减少', () => {
      // 消息 "搜索项目"：
      //   knowledge_rag 命中 "搜索"  → +0.1 → 1.1
      //   general       命中 "项目"  → -0.05 → 0.95
      store.addFeedback('搜索项目', 'knowledge_rag', 'general');
      adjuster.recompute();

      const correctWeight = adjuster.getAdjustedWeight('knowledge_rag', '搜索');
      const wrongWeight = adjuster.getAdjustedWeight('general', '项目');

      expect(correctWeight).toBeCloseTo(1.1, 3);
      expect(wrongWeight).toBeCloseTo(0.95, 3);
    });

    it('recompute 是幂等的 —— 多次调用结果一致', () => {
      store.addFeedback('搜索项目', 'knowledge_rag', 'general');

      adjuster.recompute();
      const w1 = adjuster.getAdjustedWeight('knowledge_rag', '搜索');

      adjuster.recompute();
      adjuster.recompute();
      const w2 = adjuster.getAdjustedWeight('knowledge_rag', '搜索');

      expect(w2).toBe(w1);
    });

    it('非纠正反馈（correct == original）不产生任何权重调整', () => {
      store.addFeedback('搜索项目', 'general', 'general');
      adjuster.recompute();

      expect(adjuster.hasAdjustments()).toBe(false);
      expect(adjuster.getAdjustedWeight('general', '项目')).toBe(1.0);
      expect(adjuster.getAdjustedWeight('knowledge_rag', '搜索')).toBe(1.0);
    });

    it('多条纠正反馈的权重增量会累加', () => {
      // 两条都涉及 knowledge_rag 的 "搜索"
      store.addFeedback('搜索项目', 'knowledge_rag', 'general'); // +0.1
      store.addFeedback('搜索文档', 'knowledge_rag', 'general'); // +0.1
      adjuster.recompute();

      // "搜索" 被两次 boost：1.0 + 0.1 + 0.1 = 1.2
      const weight = adjuster.getAdjustedWeight('knowledge_rag', '搜索');
      expect(weight).toBeCloseTo(1.2, 3);
    });

    it('权重上限钳制为 2.0', () => {
      // 20 次纠正，每次 "搜索" +0.1 → 理论 3.0，钳制为 2.0
      for (let i = 0; i < 20; i++) {
        store.addFeedback('搜索', 'knowledge_rag', 'general');
      }
      adjuster.recompute();

      const weight = adjuster.getAdjustedWeight('knowledge_rag', '搜索');
      expect(weight).toBe(2.0);
    });

    it('权重下限钳制为 0.1', () => {
      // 20 次纠正，general 的 "项目" 每次 -0.05 → 理论 0.0，钳制为 0.1
      for (let i = 0; i < 20; i++) {
        store.addFeedback('项目', 'knowledge_rag', 'general');
      }
      adjuster.recompute();

      const weight = adjuster.getAdjustedWeight('general', '项目');
      expect(weight).toBe(0.1);
    });

    it('hasAdjustments 在有纠正反馈时返回 true', () => {
      expect(adjuster.hasAdjustments()).toBe(false);

      store.addFeedback('搜索项目', 'knowledge_rag', 'general');
      adjuster.recompute();

      expect(adjuster.hasAdjustments()).toBe(true);
    });

    it('getAdjustments 返回所有非默认权重调整', () => {
      store.addFeedback('搜索项目', 'knowledge_rag', 'general');
      adjuster.recompute();

      const adjustments = adjuster.getAdjustments();
      // 至少包含 knowledge_rag/"搜索" 和 general/"项目"
      expect(adjustments.length).toBeGreaterThanOrEqual(2);

      const hasCorrect = adjustments.some(
        (a) => a.subagentId === 'knowledge_rag' && a.keyword === '搜索',
      );
      const hasWrong = adjustments.some(
        (a) => a.subagentId === 'general' && a.keyword === '项目',
      );
      expect(hasCorrect).toBe(true);
      expect(hasWrong).toBe(true);
    });

    it('markDirty 后下次访问触发重算', () => {
      store.addFeedback('搜索', 'knowledge_rag', 'general');
      adjuster.recompute();
      const w1 = adjuster.getAdjustedWeight('knowledge_rag', '搜索');
      expect(w1).toBeCloseTo(1.1, 3);

      // 新增反馈后标记 dirty
      store.addFeedback('搜索', 'knowledge_rag', 'general');
      adjuster.markDirty();

      // 下次 getAdjustedWeight 自动重算
      const w2 = adjuster.getAdjustedWeight('knowledge_rag', '搜索');
      expect(w2).toBeCloseTo(1.2, 3); // 1.0 + 0.1 + 0.1
    });
  });
});

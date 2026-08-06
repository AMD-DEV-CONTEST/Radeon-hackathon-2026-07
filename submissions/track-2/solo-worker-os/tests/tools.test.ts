/**
 * tools.test.ts — 工具注册表（Tool Registry）核心测试
 *
 * 测试 lib/tools/registry.ts 的：
 *   - registerTool：注册工具
 *   - getTool：按名查询工具
 *   - getToolSpecsForMode：按模式过滤工具
 *   - 重复注册的幂等性
 *
 * 直接从 registry.ts 导入（不经过 index.ts，避免触发 registerAllTools
 * 引入 supabase / zod 等运行时依赖）。每个测试使用带唯一前缀的工具名，
 * 避免模块级 Map 状态在用例间互相干扰。
 */

import { describe, it, expect } from 'vitest';
import {
  registerTool,
  getTool,
  getAllTools,
  getToolSpecsForMode,
} from '@/lib/tools/registry';
import type { ToolConfig } from '@/lib/tools/types';

// ─── 测试辅助 ──────────────────────────────────────────────────────────────────

/** 构造一个最小可用的 ToolConfig，可选覆盖部分字段。 */
function makeTool(
  name: string,
  overrides: Partial<ToolConfig> = {},
): ToolConfig {
  return {
    name,
    description: overrides.description ?? `Tool ${name}`,
    input_schema:
      overrides.input_schema ?? { type: 'object', properties: {} },
    subagent: overrides.subagent,
    tags: overrides.tags,
    modes: overrides.modes,
    handler:
      overrides.handler ??
      (async () => ({ toolResult: 'ok', clientSummary: 'ok' })),
  };
}

// ─── registerTool & getTool ────────────────────────────────────────────────────

describe('registerTool & getTool', () => {
  it('注册工具后可通过 getTool 查询到', () => {
    registerTool(
      makeTool('test-registry-basic', {
        description: 'A basic test tool',
        subagent: 'general',
        tags: ['test'],
      }),
    );

    const tool = getTool('test-registry-basic');
    expect(tool).toBeDefined();
    expect(tool?.name).toBe('test-registry-basic');
    expect(tool?.description).toBe('A basic test tool');
    expect(tool?.subagent).toBe('general');
    expect(tool?.tags).toEqual(['test']);
    expect(typeof tool?.handler).toBe('function');
  });

  it('getTool 查询不存在的工具返回 undefined', () => {
    const tool = getTool('test-nonexistent-xyz-12345');
    expect(tool).toBeUndefined();
  });

  it('注册多个工具后 getAllTools 返回全部', () => {
    const before = getAllTools().length;

    registerTool(makeTool('test-multi-1'));
    registerTool(makeTool('test-multi-2'));
    registerTool(makeTool('test-multi-3'));

    const after = getAllTools().length;
    expect(after).toBe(before + 3);

    const names = getAllTools().map((t) => t.name);
    expect(names).toContain('test-multi-1');
    expect(names).toContain('test-multi-2');
    expect(names).toContain('test-multi-3');
  });

  it('保留完整的 ToolConfig 字段（含 input_schema 与 handler）', () => {
    const schema = {
      type: 'object',
      properties: { query: { type: 'string' } },
      required: ['query'],
    };
    registerTool(
      makeTool('test-full-config', {
        description: 'full config tool',
        input_schema: schema,
        modes: ['default'],
      }),
    );

    const tool = getTool('test-full-config');
    expect(tool?.input_schema).toEqual(schema);
    expect(tool?.modes).toEqual(['default']);
    expect(typeof tool?.handler).toBe('function');
  });
});

// ─── 重复注册幂等性 ────────────────────────────────────────────────────────────

describe('重复注册是幂等的', () => {
  it('同名工具重复注册不会覆盖已有配置', () => {
    // 第一次注册
    registerTool(
      makeTool('test-idempotent', { description: 'original' }),
    );
    const before = getTool('test-idempotent');
    expect(before?.description).toBe('original');

    // 用不同 description 再次注册
    registerTool(
      makeTool('test-idempotent', { description: 'updated' }),
    );
    const after = getTool('test-idempotent');

    // 仍是原始配置 —— registerTool 对已存在名称直接 return
    expect(after?.description).toBe('original');
  });

  it('重复注册不会增加 getAllTools 的数量', () => {
    registerTool(makeTool('test-idempotent-count'));
    const countBefore = getAllTools().filter((t) =>
      t.name.startsWith('test-idempotent-count'),
    ).length;

    // 重复注册 5 次
    for (let i = 0; i < 5; i++) {
      registerTool(makeTool('test-idempotent-count'));
    }

    const countAfter = getAllTools().filter((t) =>
      t.name.startsWith('test-idempotent-count'),
    ).length;

    expect(countAfter).toBe(countBefore);
    expect(countAfter).toBe(1);
  });
});

// ─── getToolSpecsForMode ───────────────────────────────────────────────────────

describe('getToolSpecsForMode', () => {
  // 为模式过滤测试注册一组带不同 modes 的工具
  // 使用唯一前缀避免与其他测试冲突
  const modeTools = [
    makeTool('test-mode-default', { modes: ['default', 'qwen'] }),
    makeTool('test-mode-casper', { modes: ['casper'] }),
    makeTool('test-mode-qwen-only', { modes: ['qwen'] }),
    makeTool('test-mode-universal'), // 无 modes → 所有模式可用
  ];

  // 在 describe 内注册一次（registerTool 幂等，重复调用安全）
  modeTools.forEach(registerTool);

  it('default 模式返回含 default 的工具及无 modes 限制的工具', () => {
    const specs = getToolSpecsForMode('default');
    const names = specs.map((s) => s.name);

    expect(names).toContain('test-mode-default');
    expect(names).toContain('test-mode-universal');
    expect(names).not.toContain('test-mode-casper');
    expect(names).not.toContain('test-mode-qwen-only');
  });

  it('casper 模式只返回含 casper 的工具及无 modes 限制的工具', () => {
    const specs = getToolSpecsForMode('casper');
    const names = specs.map((s) => s.name);

    expect(names).toContain('test-mode-casper');
    expect(names).toContain('test-mode-universal');
    expect(names).not.toContain('test-mode-default');
    expect(names).not.toContain('test-mode-qwen-only');
  });

  it('qwen 模式返回同时支持 default 和 qwen-only 的工具', () => {
    const specs = getToolSpecsForMode('qwen');
    const names = specs.map((s) => s.name);

    expect(names).toContain('test-mode-default'); // modes 包含 qwen
    expect(names).toContain('test-mode-qwen-only');
    expect(names).toContain('test-mode-universal');
    expect(names).not.toContain('test-mode-casper');
  });

  it('不存在的模式只返回无 modes 限制的工具', () => {
    const specs = getToolSpecsForMode('nonexistent-mode');
    const names = specs.map((s) => s.name);

    expect(names).toContain('test-mode-universal');
    expect(names).not.toContain('test-mode-default');
    expect(names).not.toContain('test-mode-casper');
    expect(names).not.toContain('test-mode-qwen-only');
  });

  it('返回的 ToolSpec 仅包含 name / description / input_schema', () => {
    const specs = getToolSpecsForMode('default');
    const spec = specs.find((s) => s.name === 'test-mode-default');

    expect(spec).toBeDefined();
    expect(spec).toHaveProperty('name', 'test-mode-default');
    expect(spec).toHaveProperty('description');
    expect(spec).toHaveProperty('input_schema');

    // ToolSpec 不应包含 handler / modes / tags 等内部字段
    expect(spec).not.toHaveProperty('handler');
    expect(spec).not.toHaveProperty('modes');
    expect(spec).not.toHaveProperty('tags');
    expect(spec).not.toHaveProperty('subagent');
  });

  it('空模式字符串时无 modes 限制的工具仍可返回', () => {
    const specs = getToolSpecsForMode('');
    const names = specs.map((s) => s.name);
    expect(names).toContain('test-mode-universal');
  });
});

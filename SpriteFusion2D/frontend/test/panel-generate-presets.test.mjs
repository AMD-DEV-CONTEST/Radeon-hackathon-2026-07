// G02：生成预设接入生成面板。
//
// 这里不去 mock 整个 DOM 跑 GeneratePanel（这个仓库没有 jsdom 依赖），而是直接
// 验证面板真正依赖的那条数据通路：面板构造 payload 用的就是 mergeGenerationPreset，
// 所以对它的约束成立，面板发出去的请求就是对的。面板侧另有 node --check 保证语法。

import { strict as assert } from 'node:assert';
import test from 'node:test';

import {
  GENERATION_PRESET_IDS,
  SDXL_TURBO_LIMITS,
  getGenerationPreset,
  mergeGenerationPreset,
} from '../renderer/js/generate-presets.js';

import en from '../locales/en.js';
import zhCN from '../locales/zh-CN.js';

// 面板里 _buildRequest 的等价物：保持和 panel-generate.js 同样的调用形状。
function buildRequest(presetId, { prompt = '', negative = '', size, count, steps, cfg } = {}) {
  const preset = getGenerationPreset(presetId);
  return mergeGenerationPreset(presetId, {
    prompt,
    negative,
    size: size ?? preset.size,
    count: count ?? preset.count,
    steps: steps ?? preset.steps,
    cfg: cfg ?? preset.cfg,
  });
}

test('默认参数与真实 SDXL-Turbo 限制一致，不是被后端砍掉的假值', () => {
  for (const id of GENERATION_PRESET_IDS) {
    const req = buildRequest(id, { prompt: 'a knight' });
    assert.ok(req.steps <= SDXL_TURBO_LIMITS.maxSteps, `${id} steps ${req.steps} > 4`);
    assert.ok(req.cfg <= SDXL_TURBO_LIMITS.maxCfg, `${id} cfg ${req.cfg} > 1.0`);
    // 面板改造前的假默认值是 steps=20 / cfg=7，确认它们没有回潮。
    assert.notEqual(req.steps, 20);
    assert.notEqual(req.cfg, 7);
  }
});

test('角色/道具/场景三类产生不同的请求', () => {
  const prompts = GENERATION_PRESET_IDS.map((id) => buildRequest(id, { prompt: 'a knight' }).prompt);
  assert.equal(new Set(prompts).size, GENERATION_PRESET_IDS.length);
  const negatives = GENERATION_PRESET_IDS.map((id) => buildRequest(id, { prompt: 'x' }).negative);
  assert.equal(new Set(negatives).size, GENERATION_PRESET_IDS.length);
});

test('用户的主体描述不被静默丢弃，原样出现在最终 prompt 里', () => {
  const subject = 'a girl in a red dress, front view';
  for (const id of GENERATION_PRESET_IDS) {
    const req = buildRequest(id, { prompt: subject });
    assert.ok(req.prompt.includes(subject), `${id} 丢了用户描述: ${req.prompt}`);
    assert.ok(req.prompt.startsWith(subject), `${id} 用户描述不在开头: ${req.prompt}`);
  }
});

test('用户的负面提示与预设叠加，而不是覆盖预设的', () => {
  const req = buildRequest('character', { prompt: 'a knight', negative: 'blue background' });
  const preset = getGenerationPreset('character');
  assert.ok(req.negative.includes('blue background'), '丢了用户的负面提示');
  assert.ok(req.negative.includes(preset.negativePrompt), '丢了预设的负面提示');
});

test('滑块给出的超限值仍会被夹紧，后端不会收到会被悄悄改写的数值', () => {
  const req = buildRequest('character', { prompt: 'a knight', steps: 50, cfg: 15 });
  assert.equal(req.steps, SDXL_TURBO_LIMITS.maxSteps);
  assert.equal(req.cfg, SDXL_TURBO_LIMITS.maxCfg);
});

test('空描述由面板自己拒绝：这里确认预设不会凭空替用户编出一个主体', () => {
  const req = buildRequest('character', { prompt: '' });
  const preset = getGenerationPreset('character');
  // 没有用户输入时，prompt 只剩预设后缀——面板必须在提交前拦下这种情况，
  // 否则用户会拿到一张"纯风格、没有主体"的图。
  assert.equal(req.prompt, preset.promptSuffix);
});

test('面板用到的预设相关字典键在 en 和 zh-CN 中都存在', () => {
  const keys = [
    'generate.presetLabel',
    'generate.presetHint',
    'generate.effectiveSummary',
    'generate.negativeAppendHint',
    'generate.turboLimitHint',
    ...GENERATION_PRESET_IDS.map((id) => `generate.preset.${id}`),
  ];
  for (const key of keys) {
    assert.ok(key in en, `en 缺键 ${key}`);
    assert.ok(key in zhCN, `zh-CN 缺键 ${key}`);
  }
});

// 生成预设单测 —— Luna 任务图 G01（docs/luna-workpack/TASK_GRAPH.md）
//
// 覆盖点：三类预设都存在且参数在 SDXL-Turbo 真实上限内；合并函数不吞用户的主体
// 描述；合并结果能被 JSON 序列化；不出现专用 LoRA/checkpoint 的暗示性文案。

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const P = await import(
  pathToFileURL(path.join(here, '..', 'renderer', 'js', 'generate-presets.js')).href
);

test('三类预设都存在，id/label/文案齐全', () => {
  assert.deepEqual(P.GENERATION_PRESET_IDS, ['character', 'item', 'environment']);
  for (const id of P.GENERATION_PRESET_IDS) {
    const preset = P.GENERATION_PRESETS[id];
    assert.ok(preset, `缺少预设 ${id}`);
    assert.equal(preset.id, id);
    assert.equal(typeof preset.label, 'string');
    assert.match(preset.label, /^[A-Za-z][A-Za-z ]*$/, `label 必须是英文标签: ${preset.label}`);
    assert.equal(typeof preset.promptSuffix, 'string');
    assert.ok(preset.promptSuffix.length > 0);
    assert.equal(typeof preset.negativePrompt, 'string');
    assert.ok(preset.negativePrompt.length > 0);
    assert.equal(typeof preset.size, 'number');
    assert.equal(typeof preset.count, 'number');
    assert.equal(typeof preset.steps, 'number');
    assert.equal(typeof preset.cfg, 'number');
  }
});

test('listGenerationPresets 按固定顺序返回三个预设对象', () => {
  const list = P.listGenerationPresets();
  assert.deepEqual(list.map((p) => p.id), ['character', 'item', 'environment']);
});

test('getGenerationPreset 未知 id 返回 null 而不是抛错', () => {
  assert.equal(P.getGenerationPreset('vehicle'), null);
  assert.equal(P.getGenerationPreset(undefined), null);
});

test('预设的 steps/cfg 在 comfyui.py 真实执行的 SDXL-Turbo 上限内', () => {
  // sprite_workshop/generate/comfyui.py `_workflow()`：
  //   steps = min(request.steps, 4) if is_turbo else request.steps
  //   cfg   = min(request.cfg, 1.0) if is_turbo else request.cfg
  assert.equal(P.SDXL_TURBO_LIMITS.maxSteps, 4);
  assert.equal(P.SDXL_TURBO_LIMITS.maxCfg, 1.0);
  for (const preset of P.listGenerationPresets()) {
    assert.ok(preset.steps <= P.SDXL_TURBO_LIMITS.maxSteps, `${preset.id} steps 超出 turbo 上限`);
    assert.ok(preset.steps >= P.SDXL_TURBO_LIMITS.minSteps, `${preset.id} steps 低于下限`);
    assert.ok(preset.cfg <= P.SDXL_TURBO_LIMITS.maxCfg, `${preset.id} cfg 超出 turbo 上限`);
    assert.ok(preset.cfg >= P.SDXL_TURBO_LIMITS.minCfg, `${preset.id} cfg 低于下限`);
  }
  // 明确回归：旧的前端假默认值（20 steps / CFG 7）不应该再出现在预设里。
  for (const preset of P.listGenerationPresets()) {
    assert.notEqual(preset.steps, 20);
    assert.notEqual(preset.cfg, 7);
  }
});

test('mergeGenerationPreset 不覆盖用户主体描述：原文整段出现在结果 prompt 里', () => {
  const userPrompt = 'a girl in a red dress, standing, front view';
  const merged = P.mergeGenerationPreset('character', { prompt: userPrompt });
  assert.ok(merged.prompt.startsWith(userPrompt), 'prompt 必须以用户原文开头');
  assert.ok(merged.prompt.includes(userPrompt));
  assert.ok(merged.prompt.length > userPrompt.length, '预设后缀应当被追加，而不是被丢弃');
});

test('mergeGenerationPreset 对三类预设都保留用户主体描述', () => {
  const userPrompt = 'a rusty iron sword with a leather grip';
  for (const id of P.GENERATION_PRESET_IDS) {
    const merged = P.mergeGenerationPreset(id, { prompt: userPrompt });
    assert.ok(merged.prompt.includes(userPrompt), `${id} 丢失了用户主体描述`);
    assert.equal(merged.presetId, id);
  }
});

test('用户没写描述时，退化为纯预设后缀，不产生多余的逗号/空白前缀', () => {
  const merged = P.mergeGenerationPreset('environment', {});
  const preset = P.getGenerationPreset('environment');
  assert.equal(merged.prompt, preset.promptSuffix);
});

test('用户已填的字段优先于预设推荐值', () => {
  const merged = P.mergeGenerationPreset('item', {
    prompt: 'a golden key',
    negative: 'rust',
    size: 768,
    count: 2,
  });
  assert.equal(merged.size, 768, '用户显式填写的 size 不应被预设覆盖');
  assert.equal(merged.count, 2, '用户显式填写的 count 不应被预设覆盖');
  assert.ok(merged.negative.startsWith('rust'), '用户的负面描述应当保留在前面');
  assert.ok(merged.negative.includes(P.getGenerationPreset('item').negativePrompt));
});

test('未填的字段用预设推荐值补齐', () => {
  const merged = P.mergeGenerationPreset('character', { prompt: 'a knight' });
  const preset = P.getGenerationPreset('character');
  assert.equal(merged.size, preset.size);
  assert.equal(merged.count, preset.count);
  assert.equal(merged.steps, preset.steps);
  assert.equal(merged.cfg, preset.cfg);
});

test('即使调用方传入超出 turbo 上限的 steps/cfg，合并结果也会被夹回真实上限', () => {
  const merged = P.mergeGenerationPreset('character', {
    prompt: 'a knight',
    steps: 50, // 旧面板滑杆允许到 50，但后端会静默砍到 4
    cfg: 7, // 旧面板滑杆允许到 15，但后端会静默砍到 1.0
  });
  assert.equal(merged.steps, P.SDXL_TURBO_LIMITS.maxSteps);
  assert.equal(merged.cfg, P.SDXL_TURBO_LIMITS.maxCfg);
});

test('未知预设 id 抛出明确错误，而不是静默生成错误请求', () => {
  assert.throws(() => P.mergeGenerationPreset('vehicle', { prompt: 'a car' }), /unknown generation preset/);
});

test('合并结果是纯 JSON 可序列化数据：没有函数、没有循环引用，往返后深度相等', () => {
  for (const id of P.GENERATION_PRESET_IDS) {
    const merged = P.mergeGenerationPreset(id, {
      prompt: 'test subject',
      negative: 'test negative',
    });
    const roundTripped = JSON.parse(JSON.stringify(merged));
    assert.deepEqual(roundTripped, merged);
    for (const value of Object.values(merged)) {
      assert.ok(typeof value === 'string' || typeof value === 'number');
    }
  }
});

test('预设数据本身也可以整体 JSON 序列化（数据模块必须是纯数据）', () => {
  const serialized = JSON.stringify(P.GENERATION_PRESETS);
  const parsed = JSON.parse(serialized);
  assert.deepEqual(parsed, P.GENERATION_PRESETS);
});

test('不声称使用专用 LoRA 或专门微调的 checkpoint', () => {
  const blob = JSON.stringify(P.GENERATION_PRESETS).toLowerCase();
  for (const banned of ['lora', 'fine-tune', 'finetuned', 'dreambooth', 'checkpoint', 'custom model']) {
    assert.ok(!blob.includes(banned), `预设文案里不应出现 "${banned}"`);
  }
});

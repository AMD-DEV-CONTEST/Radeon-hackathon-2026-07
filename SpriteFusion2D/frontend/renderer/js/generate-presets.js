// 生成预设 —— 纯数据 + 纯函数，不碰 DOM，不发 RPC（Luna 任务图 G01，
// docs/luna-workpack/TASK_GRAPH.md）。
//
// 三类预设：character / item / environment。数值定死在当前唯一验证过的
// checkpoint（SDXL-Turbo）真正能吃的范围内：sprite_workshop/generate/comfyui.py
// 的 `_workflow()` 里，只要模型名带 "turbo" 就会做
//   steps = min(request.steps, 4)
//   cfg   = min(request.cfg, 1.0)
// 后端会悄悄砍掉超出这个范围的值，所以这里不再放会被砍掉的假 20 steps / CFG 7
// 默认值——预设推荐值和导出的硬上限都直接对齐这条真实约束。
//
// 不含任何专用 LoRA 或微调 checkpoint 引用：三个预设都只是在同一个基座模型上做
// 提示词工程（后缀 + 负面提示），不要在文案或数据里暗示用了专门训练的角色/道具/
// 场景模型。

/** SDXL-Turbo 在 comfyui.py 里真正会被强制执行的采样上下限。 */
export const SDXL_TURBO_LIMITS = Object.freeze({
  minSteps: 1,
  maxSteps: 4, // comfyui.py: min(request.steps, 4)
  minCfg: 0.1,
  maxCfg: 1.0, // comfyui.py: min(request.cfg, 1.0)
});

export const GENERATION_PRESET_IDS = Object.freeze(['character', 'item', 'environment']);

const RECOMMENDED = Object.freeze({
  size: 512,
  count: 4,
  steps: 4,
  cfg: 1.0,
});

export const GENERATION_PRESETS = Object.freeze({
  character: Object.freeze({
    id: 'character',
    label: 'Character',
    promptSuffix:
      'centered full-body 2D game character sprite, clean silhouette, ' +
      'limited color palette, plain background, no text',
    negativePrompt:
      'text, watermark, blurry, photorealistic, cropped, extra limbs, multiple characters',
    ...RECOMMENDED,
  }),
  item: Object.freeze({
    id: 'item',
    label: 'Item',
    promptSuffix:
      'single 2D game item icon, centered, plain background, no drop shadow, no text',
    negativePrompt:
      'text, watermark, blurry, photorealistic, cropped, multiple objects, hands, characters',
    ...RECOMMENDED,
  }),
  environment: Object.freeze({
    id: 'environment',
    label: 'Environment',
    promptSuffix:
      '2D game environment tile, flat even lighting, no characters, no text, no watermark',
    negativePrompt:
      'text, watermark, blurry, photorealistic, people, characters, signature',
    ...RECOMMENDED,
  }),
});

/** 按固定顺序（character, item, environment）返回预设数组，方便渲染选择器。 */
export function listGenerationPresets() {
  return GENERATION_PRESET_IDS.map((id) => GENERATION_PRESETS[id]);
}

/** 查一个预设；未知 id 返回 null 而不是抛错，方便调用方先判断再渲染。 */
export function getGenerationPreset(presetId) {
  return GENERATION_PRESETS[presetId] ?? null;
}

function clampTurboSampling(steps, cfg) {
  const { minSteps, maxSteps, minCfg, maxCfg } = SDXL_TURBO_LIMITS;
  return {
    steps: Math.min(maxSteps, Math.max(minSteps, steps)),
    cfg: Math.min(maxCfg, Math.max(minCfg, cfg)),
  };
}

/**
 * 把预设合并进用户已经写好的生成请求里。
 *
 * 规则（对应 G01 验收项）：
 * - 绝不覆盖用户的主体描述：`userInput.prompt` 的原文一定会整段出现在结果
 *   `prompt` 里，预设只是在后面追加风格/构图后缀，不做替换、不做截断。
 * - 用户已经明确填写的字段（negative/size/count/steps/cfg）优先于预设推荐值；
 *   只有用户没填（undefined、null 或空字符串）的字段才用预设值补齐。
 * - steps/cfg 无论来自用户还是预设，最终都会被夹到 SDXL_TURBO_LIMITS 内——
 *   避免面板上出现一个会被后端悄悄改写掉的“假”数值。
 * - 返回值是纯 JSON 可序列化对象（只有字符串/数字，没有函数、没有 class
 *   实例），可以直接 `JSON.stringify` 后当 RPC payload 用。
 *
 * @param {string} presetId 'character' | 'item' | 'environment'
 * @param {{prompt?: string, negative?: string, size?: number, count?: number,
 *          steps?: number, cfg?: number}} [userInput]
 * @returns {{presetId: string, prompt: string, negative: string, size: number,
 *            count: number, steps: number, cfg: number}}
 */
export function mergeGenerationPreset(presetId, userInput = {}) {
  const preset = getGenerationPreset(presetId);
  if (!preset) {
    throw new Error(`unknown generation preset: ${presetId}`);
  }

  const userPrompt = (userInput.prompt ?? '').trim();
  const userNegative = (userInput.negative ?? '').trim();

  const prompt = userPrompt ? `${userPrompt}, ${preset.promptSuffix}` : preset.promptSuffix;
  const negative = userNegative
    ? `${userNegative}, ${preset.negativePrompt}`
    : preset.negativePrompt;

  const rawSteps = userInput.steps ?? preset.steps;
  const rawCfg = userInput.cfg ?? preset.cfg;
  const { steps, cfg } = clampTurboSampling(rawSteps, rawCfg);

  return {
    presetId: preset.id,
    prompt,
    negative,
    size: userInput.size ?? preset.size,
    count: userInput.count ?? preset.count,
    steps,
    cfg,
  };
}

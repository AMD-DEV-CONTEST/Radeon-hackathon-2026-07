import { createBlankForm } from "./form-defaults";
import type { Capabilities, GenerationForm, SampleParams } from "./types";

function finiteOrFallback(value: unknown, fallback: number): number {
    return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function assignSampleParams(
    target: SampleParams,
    sample: Record<string, any>,
    fallbackSteps: number,
): void {
    const guidance = sample.guidance || {};
    const slg = guidance.slg || {};

    target.scheduler = sample.scheduler || "default";
    target.sample_method = sample.sample_method || "default";
    target.sample_steps = finiteOrFallback(sample.sample_steps, fallbackSteps);
    target.eta = sample.eta == null ? "" : sample.eta;
    target.shifted_timestep = finiteOrFallback(sample.shifted_timestep, 0);
    target.flow_shift = sample.flow_shift == null ? "" : sample.flow_shift;

    target.guidance.txt_cfg = finiteOrFallback(guidance.txt_cfg, 7);
    target.guidance.img_cfg = guidance.img_cfg == null ? "" : guidance.img_cfg;
    target.guidance.distilled_guidance = finiteOrFallback(guidance.distilled_guidance, 3.5);
    target.guidance.slg_layers = Array.isArray(slg.layers) ? slg.layers.join(",") : "7,8,9";
    target.guidance.layer_start = finiteOrFallback(slg.layer_start, 0.01);
    target.guidance.layer_end = finiteOrFallback(slg.layer_end, 0.2);
    target.guidance.scale = finiteOrFallback(slg.scale, 0);
}

export function formFromCapabilities(capabilities: Capabilities): GenerationForm {
    const currentMode = capabilities?.current_mode;
    const defaultsByMode = capabilities?.defaults_by_mode || {};
    const defaults: Record<string, any> = (currentMode && defaultsByMode[currentMode]) || {};
    const sample = defaults.sample_params || {};
    const highNoiseSample = defaults.high_noise_sample_params || {};
    const tiling = defaults.vae_tiling_params || {};
    const form = createBlankForm();

    form.prompt = defaults.prompt || "";
    form.negative_prompt = defaults.negative_prompt || "";
    form.width = finiteOrFallback(defaults.width, 512);
    form.height = finiteOrFallback(defaults.height, 512);
    form.batch_count = finiteOrFallback(defaults.batch_count, 1);
    form.video_frames = finiteOrFallback(defaults.video_frames, 33);
    form.fps = finiteOrFallback(defaults.fps, 16);
    form.seed = typeof defaults.seed === "number" ? defaults.seed : -1;
    form.clip_skip = typeof defaults.clip_skip === "number" ? defaults.clip_skip : -1;
    form.strength = finiteOrFallback(defaults.strength, 0.75);
    form.control_strength = finiteOrFallback(defaults.control_strength, 0.9);
    form.moe_boundary = finiteOrFallback(defaults.moe_boundary, 0.875);
    form.vace_strength = finiteOrFallback(defaults.vace_strength, 1.0);
    form.output_format = defaults.output_format || "png";
    form.output_compression = finiteOrFallback(defaults.output_compression, 100);

    assignSampleParams(form.sample_params, sample, 20);
    assignSampleParams(form.high_noise_sample_params, highNoiseSample, -1);

    form.vae_tiling_params.enabled = Boolean(tiling.enabled);
    form.vae_tiling_params.tile_size_x = finiteOrFallback(tiling.tile_size_x, 0);
    form.vae_tiling_params.tile_size_y = finiteOrFallback(tiling.tile_size_y, 0);
    form.vae_tiling_params.target_overlap = finiteOrFallback(tiling.target_overlap, 0.5);
    form.vae_tiling_params.rel_size_x = finiteOrFallback(tiling.rel_size_x, 0);
    form.vae_tiling_params.rel_size_y = finiteOrFallback(tiling.rel_size_y, 0);

    form.cache.mode = defaults.cache_mode || "disabled";
    form.cache.option = defaults.cache_option || "";
    form.cache.scm_mask = defaults.scm_mask || "";
    form.cache.scm_policy_dynamic =
        typeof defaults.scm_policy_dynamic === "boolean"
            ? defaults.scm_policy_dynamic
            : true;

    return form;
}

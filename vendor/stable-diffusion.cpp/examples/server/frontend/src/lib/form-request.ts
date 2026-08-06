import type { GenerationForm, GenerationMode, SampleParams } from "./types";

function parseNumber(value: unknown, fallback: number): number {
    if (value === "" || value == null) {
        return fallback;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}

function nullable(value: unknown): unknown {
    return value === "" || value == null ? null : value;
}

interface SampleParamsRequest {
    sample_steps: number;
    shifted_timestep: number;
    custom_sigmas: number[];
    guidance: {
        txt_cfg: number;
        distilled_guidance: number;
        slg: {
            layers: number[];
            layer_start: number;
            layer_end: number;
            scale: number;
        };
        img_cfg?: number;
    };
    eta?: number;
    flow_shift?: number;
    scheduler?: string;
    sample_method?: string;
}

function buildSampleParams(sample: SampleParams, defaultSteps: number): SampleParamsRequest {
    const eta = nullable(sample.eta);
    const flowShift = nullable(sample.flow_shift);
    const imgCfg = nullable(sample.guidance.img_cfg);

    const sampleParams: SampleParamsRequest = {
        sample_steps: parseNumber(sample.sample_steps, defaultSteps),
        shifted_timestep: parseNumber(sample.shifted_timestep, 0),
        custom_sigmas: [],
        guidance: {
            txt_cfg: parseNumber(sample.guidance.txt_cfg, 7),
            distilled_guidance: parseNumber(sample.guidance.distilled_guidance, 3.5),
            slg: {
                layers: String(sample.guidance.slg_layers || "")
                    .split(",")
                    .map((item) => Number(item.trim()))
                    .filter((value) => Number.isInteger(value)),
                layer_start: parseNumber(sample.guidance.layer_start, 0.01),
                layer_end: parseNumber(sample.guidance.layer_end, 0.2),
                scale: parseNumber(sample.guidance.scale, 0),
            },
        },
    };

    if (eta != null) {
        sampleParams.eta = Number(eta);
    }
    if (flowShift != null) {
        sampleParams.flow_shift = Number(flowShift);
    }
    if (imgCfg != null) {
        sampleParams.guidance.img_cfg = Number(imgCfg);
    }

    const scheduler =
        sample.scheduler && sample.scheduler !== "default"
            ? sample.scheduler
            : undefined;
    const sampleMethod =
        sample.sample_method && sample.sample_method !== "default"
            ? sample.sample_method
            : undefined;

    if (scheduler) {
        sampleParams.scheduler = scheduler;
    }
    if (sampleMethod) {
        sampleParams.sample_method = sampleMethod;
    }

    return sampleParams;
}

function buildLoraRequest(form: GenerationForm) {
    return form.lora
        .filter((item) => String(item.path || "").trim())
        .map((item) => ({
            path: String(item.path).trim(),
            multiplier: parseNumber(item.multiplier, 1.0),
            is_high_noise: Boolean(item.is_high_noise),
        }));
}

function buildTilingRequest(form: GenerationForm) {
    return {
        enabled: Boolean(form.vae_tiling_params.enabled),
        tile_size_x: parseNumber(form.vae_tiling_params.tile_size_x, 0),
        tile_size_y: parseNumber(form.vae_tiling_params.tile_size_y, 0),
        target_overlap: parseNumber(form.vae_tiling_params.target_overlap, 0.5),
        rel_size_x: parseNumber(form.vae_tiling_params.rel_size_x, 0),
        rel_size_y: parseNumber(form.vae_tiling_params.rel_size_y, 0),
    };
}

export function buildRequestBody(form: GenerationForm) {
    const request = {
        prompt: String(form.prompt || "").trim(),
        negative_prompt: form.negative_prompt,
        clip_skip: parseNumber(form.clip_skip, -1),
        width: parseNumber(form.width, 512),
        height: parseNumber(form.height, 512),
        strength: parseNumber(form.strength, 0.75),
        seed: parseNumber(form.seed, -1),
        sample_params: buildSampleParams(form.sample_params, 20),
        lora: buildLoraRequest(form),
        vae_tiling_params: buildTilingRequest(form),
        cache_mode: form.cache.mode || "disabled",
        cache_option: String(form.cache.option || ""),
        scm_mask: String(form.cache.scm_mask || ""),
        scm_policy_dynamic: Boolean(form.cache.scm_policy_dynamic),
        output_format: form.output_format,
        output_compression: parseNumber(form.output_compression, 100),
    };

    if (!request.prompt) {
        throw new Error("prompt is required");
    }

    return request;
}

export function buildImageRequestBody(form: GenerationForm) {
    return {
        ...buildRequestBody(form),
        batch_count: parseNumber(form.batch_count, 1),
        auto_resize_ref_image: true,
        increase_ref_index: false,
        control_strength: parseNumber(form.control_strength, 0.9),
        init_image: form.init_image ? form.init_image.dataUrl : null,
        ref_images: form.ref_images.map((item) => item.dataUrl),
        mask_image: form.mask_image ? form.mask_image.dataUrl : null,
        control_image: form.control_image ? form.control_image.dataUrl : null,
    };
}

export function buildVideoRequestBody(form: GenerationForm) {
    return {
        ...buildRequestBody(form),
        video_frames: parseNumber(form.video_frames, 33),
        fps: parseNumber(form.fps, 16),
        moe_boundary: parseNumber(form.moe_boundary, 0.875),
        vace_strength: parseNumber(form.vace_strength, 1.0),
        init_image: form.init_image ? form.init_image.dataUrl : null,
        end_image: form.end_image ? form.end_image.dataUrl : null,
        control_frames: form.control_frames.map((item) => item.dataUrl),
        high_noise_sample_params: buildSampleParams(form.high_noise_sample_params, -1),
    };
}

export function buildRequestBodyForMode(mode: GenerationMode, form: GenerationForm) {
    return mode === "video" ? buildVideoRequestBody(form) : buildImageRequestBody(form);
}

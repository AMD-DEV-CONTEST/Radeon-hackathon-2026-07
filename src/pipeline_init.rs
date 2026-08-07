//! Pipeline initialization — creates all compute pipelines from WGSL shaders.
//! This is the final glue that connects shaders → pipelines → forward pass.

use crate::forward_pass::LayerPipelines;
use crate::tensor_chunker::ChunkedMatmulPipeline;
use crate::shader_ops::{DequantPipeline, RmsNormPipeline};

/// Helper to create a bind group layout entry for storage buffers.
fn bgl_storage(binding: u32, read_only: bool) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility: wgpu::ShaderStages::COMPUTE,
        ty: wgpu::BindingType::Buffer {
            ty: wgpu::BufferBindingType::Storage { read_only },
            has_dynamic_offset: false,
            min_binding_size: None,
        },
        count: None,
    }
}

fn bgl_uniform(binding: u32) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility: wgpu::ShaderStages::COMPUTE,
        ty: wgpu::BindingType::Buffer {
            ty: wgpu::BufferBindingType::Uniform,
            has_dynamic_offset: false,
            min_binding_size: None,
        },
        count: None,
    }
}

/// Create a compute pipeline from WGSL source with a given bind group layout.
fn create_pipeline(
    device: &wgpu::Device,
    label: &str,
    source: &str,
    bgl: &wgpu::BindGroupLayout,
    cache: Option<&wgpu::PipelineCache>,
) -> wgpu::ComputePipeline {
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some(label),
        source: wgpu::ShaderSource::Wgsl(source.into()),
    });
    let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some(&format!("{}_layout", label)),
        bind_group_layouts: &[bgl],
        push_constant_ranges: &[],
    });
    device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
        label: Some(label),
        layout: Some(&layout),
        module: &shader,
        entry_point: Some("main"),
        compilation_options: Default::default(),
        cache,
    })
}

/// Initialize all layer pipelines from WGSL shader sources.
/// This is called once at startup after GPU device creation.
pub fn init_layer_pipelines(device: &wgpu::Device) -> LayerPipelines {
    // ── RMSNorm ─────────────────────────────────────────────────────────────
    let rmsnorm = RmsNormPipeline::new(device);

    // ── Chunked Matmul (includes tiled pipeline) ────────────────────────────
    let chunked_matmul = ChunkedMatmulPipeline::new(device);

    // ── RoPE ────────────────────────────────────────────────────────────────
    let rope_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("rope_bgl"),
        entries: &[
            bgl_storage(0, false), // qk buffer (read-write)
            bgl_uniform(1),        // params
        ],
    });
    let rope = create_pipeline(device, "rope",
        include_str!("../shaders/rope.wgsl"), &rope_bgl);

    // ── Attention (QK^T + causal mask) ──────────────────────────────────────
    let attention_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("attention_bgl"),
        entries: &[
            bgl_storage(0, true),  // query
            bgl_storage(1, true),  // key_cache
            bgl_storage(2, false), // scores output
            bgl_uniform(3),        // params
        ],
    });
    let attention = create_pipeline(device, "attention",
        include_str!("../shaders/attention.wgsl"), &attention_bgl);

    // ── Softmax ─────────────────────────────────────────────────────────────
    let softmax_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("softmax_bgl"),
        entries: &[
            bgl_storage(0, true),  // scores input
            bgl_storage(1, false), // probs output
            bgl_uniform(2),        // params
        ],
    });
    let softmax = create_pipeline(device, "softmax",
        include_str!("../shaders/softmax.wgsl"), &softmax_bgl);

    // ── SwiGLU ──────────────────────────────────────────────────────────────
    let swiglu_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("swiglu_bgl"),
        entries: &[
            bgl_storage(0, true),  // gate_proj
            bgl_storage(1, true),  // up_proj
            bgl_storage(2, false), // output
            bgl_uniform(3),        // params
        ],
    });
    let swiglu = create_pipeline(device, "swiglu",
        include_str!("../shaders/swiglu.wgsl"), &swiglu_bgl);

    // ── Elementwise Add (residual connections) ──────────────────────────────
    let add_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("add_bgl"),
        entries: &[
            bgl_storage(0, true),  // a
            bgl_storage(1, true),  // b
            bgl_storage(2, false), // output
            bgl_uniform(3),        // params
        ],
    });
    let add = create_pipeline(device, "add",
        include_str!("../shaders/add.wgsl"), &add_bgl);

    // ── Attention-Value weighted sum ────────────────────────────────────────
    let av_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("av_bgl"),
        entries: &[
            bgl_storage(0, true),  // probs
            bgl_storage(1, true),  // v_cache
            bgl_storage(2, false), // output
            bgl_uniform(3),        // params
        ],
    });
    let av = create_pipeline(device, "attn_value",
        include_str!("../shaders/attn_value.wgsl"), &av_bgl);

    // ── Q6_K GPU Dequantization ───────────────────────────────────────────
    let dequant_q6k = crate::shader_ops::DequantQ6KPipeline::new(device);

    // ── Matrix Transpose (row-major → column-major for tiled matmul) ────
    let transpose_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("transpose_bgl"),
        entries: &[
            bgl_storage(0, true),  // source (row-major)
            bgl_storage(1, false), // dest (column-major)
            bgl_uniform(2),        // params {rows, cols}
        ],
    });
    let transpose = create_pipeline(device, "transpose",
        include_str!("../shaders/transpose.wgsl"), &transpose_bgl);

    // ── Matrix-Vector Multiply (GGUF native layout, no transpose) ───────
    let matvec_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("matvec_bgl"),
        entries: &[
            bgl_storage(0, true),  // input vector [K]
            bgl_storage(1, true),  // weights [N × K] row-major
            bgl_storage(2, false), // output vector [N]
            bgl_uniform(3),        // params {N, K}
        ],
    });
    let matvec = create_pipeline(device, "matvec",
        include_str!("../shaders/matvec.wgsl"), &matvec_bgl);

    // ── Fused Matrix-Vector + Bias (eliminates copy hazard on P100) ─────
    let matvec_bias_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("matvec_bias_bgl"),
        entries: &[
            bgl_storage(0, true),  // input vector [K]
            bgl_storage(1, true),  // weights [N × K] row-major
            bgl_storage(2, false), // output vector [N]
            bgl_uniform(3),        // params {N, K}
            bgl_storage(4, true),  // bias [N]
        ],
    });
    let matvec_bias = create_pipeline(device, "matvec_bias",
        include_str!("../shaders/matvec_bias.wgsl"), &matvec_bias_bgl);

    LayerPipelines {
        rmsnorm,
        chunked_matmul,
        rope,
        rope_bgl,
        attention,
        attention_bgl,
        softmax,
        softmax_bgl,
        swiglu,
        swiglu_bgl,
        add,
        add_bgl,
        av,
        av_bgl,
        dequant_q6k,
        transpose,
        transpose_bgl,
        matvec,
        matvec_bgl,
        matvec_bias,
        matvec_bias_bgl,
    }
}

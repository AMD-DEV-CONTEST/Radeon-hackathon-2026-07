//! GPU shader dispatch wrappers for dequantization and normalization.
//!
//! These are the core compute kernels that sit between the tensor loader
//! and the matmul pipeline:
//!   GGUF bytes → dequant_q4km → f32 buffer → matmul → output
//!   hidden_state → rmsnorm → normalized → next layer

use bytemuck::{Pod, Zeroable};
use std::sync::Arc;
use wgpu;

// ── Dequantization Pipeline ─────────────────────────────────────────────────

/// Parameters for Q4_K_M dequantization dispatch.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct DequantParams {
    pub total_blocks: u32,
    pub _pad0: u32,
    pub _pad1: u32,
    pub _pad2: u32,
}

/// Pipeline for Q4_K_M → F32 dequantization on GPU.
pub struct DequantPipeline {
    pub pipeline: wgpu::ComputePipeline,
    pub bgl: wgpu::BindGroupLayout,
}

impl DequantPipeline {
    /// Create the dequantization pipeline.
    pub fn new(device: &wgpu::Device) -> Self {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("dequant_q4km"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/dequant_q4km.wgsl").into()),
        });

        let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("dequant_bgl"),
            entries: &[
                // binding 0: quantized input blocks (read-only storage)
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: true },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                // binding 1: f32 output buffer (read-write storage)
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: false },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                // binding 2: params uniform
                wgpu::BindGroupLayoutEntry {
                    binding: 2,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
            ],
        });

        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("dequant_layout"),
            bind_group_layouts: &[&bgl],
            push_constant_ranges: &[],
        });

        let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("dequant_pipeline"),
            layout: Some(&layout),
            module: &shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });

        Self { pipeline, bgl }
    }

    /// Dispatch Q4_K_M dequantization.
    ///
    /// - `quant_buf`: Buffer containing raw Q4_K_M blocks (144 bytes per 256 elements)
    /// - `output_buf`: Buffer to write dequantized f32 values
    /// - `total_blocks`: Number of Q4_K_M super-blocks to process
    /// - `n_elements`: Total number of weight elements (= total_blocks * 256)
    pub fn dispatch(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        encoder: &mut wgpu::CommandEncoder,
        quant_buf: &wgpu::Buffer,
        output_buf: &wgpu::Buffer,
        total_blocks: u32,
    ) {
        let params = DequantParams {
            total_blocks,
            _pad0: 0,
            _pad1: 0,
            _pad2: 0,
        };

        let params_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("dequant_params"),
            size: std::mem::size_of::<DequantParams>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        queue.write_buffer(&params_buf, 0, bytemuck::cast_slice(&[params]));

        let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("dequant_bg"),
            layout: &self.bgl,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: quant_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: output_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 2, resource: params_buf.as_entire_binding() },
            ],
        });

        // Each thread processes one element. 256 threads per workgroup.
        // Total elements = total_blocks * 256
        let n_elements = total_blocks * 256;
        let workgroups = (n_elements + 255) / 256;

        let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, Some(&bg), &[]);
        pass.dispatch_workgroups(workgroups, 1, 1);
    }
}

// ── RMSNorm Pipeline ────────────────────────────────────────────────────────

/// Parameters for RMSNorm dispatch.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct RmsNormParams {
    pub hidden_dim: u32,
    pub hidden_dim_vec4: u32,
    pub epsilon: f32,
    pub _pad: u32,
}

/// Pipeline for RMSNorm on GPU.
pub struct RmsNormPipeline {
    pub pipeline: wgpu::ComputePipeline,
    pub bgl: wgpu::BindGroupLayout,
}

impl RmsNormPipeline {
    /// Create the RMSNorm pipeline.
    pub fn new(device: &wgpu::Device) -> Self {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("rmsnorm"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/rmsnorm.wgsl").into()),
        });

        let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("rmsnorm_bgl"),
            entries: &[
                // binding 0: input hidden state (read-only, vec4<f32>)
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: true },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                // binding 1: norm weights (read-only, vec4<f32>)
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: true },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                // binding 2: output hidden state (read-write, vec4<f32>)
                wgpu::BindGroupLayoutEntry {
                    binding: 2,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: false },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                // binding 3: params uniform
                wgpu::BindGroupLayoutEntry {
                    binding: 3,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
            ],
        });

        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("rmsnorm_layout"),
            bind_group_layouts: &[&bgl],
            push_constant_ranges: &[],
        });

        let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("rmsnorm_pipeline"),
            layout: Some(&layout),
            module: &shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });

        Self { pipeline, bgl }
    }

    /// Dispatch RMSNorm over one or more rows (tokens).
    ///
    /// - `input_buf`: Hidden state buffer [n_tokens × hidden_dim] as f32
    /// - `weight_buf`: Norm weight vector [hidden_dim] as f32
    /// - `output_buf`: Output buffer [n_tokens × hidden_dim] as f32
    /// - `hidden_dim`: Hidden dimension (must be divisible by 4)
    /// - `n_tokens`: Number of tokens (rows) to normalize
    /// - `epsilon`: RMSNorm epsilon (typically 1e-5 or 1e-6)
    pub fn dispatch(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        encoder: &mut wgpu::CommandEncoder,
        input_buf: &wgpu::Buffer,
        weight_buf: &wgpu::Buffer,
        output_buf: &wgpu::Buffer,
        hidden_dim: u32,
        n_tokens: u32,
        epsilon: f32,
    ) {
        assert!(hidden_dim % 4 == 0, "hidden_dim must be divisible by 4 for vec4 loads");

        let params = RmsNormParams {
            hidden_dim,
            hidden_dim_vec4: hidden_dim / 4,
            epsilon,
            _pad: 0,
        };

        let params_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("rmsnorm_params"),
            size: std::mem::size_of::<RmsNormParams>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        queue.write_buffer(&params_buf, 0, bytemuck::cast_slice(&[params]));

        let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("rmsnorm_bg"),
            layout: &self.bgl,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: input_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: weight_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 2, resource: output_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 3, resource: params_buf.as_entire_binding() },
            ],
        });

        // One workgroup per token row. Each workgroup (256 threads) processes one full row.
        let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, Some(&bg), &[]);
        pass.dispatch_workgroups(n_tokens, 1, 1);
    }
}


// ── Q6_K GPU Dequantization Pipeline ────────────────────────────────────────

/// Parameters for Q6_K dequantization.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct DequantQ6KParams {
    pub total_blocks: u32,
    pub _pad0: u32,
    pub _pad1: u32,
    pub _pad2: u32,
}

/// Pipeline for Q6_K → F32 dequantization on GPU.
pub struct DequantQ6KPipeline {
    pub pipeline: wgpu::ComputePipeline,
    pub bgl: wgpu::BindGroupLayout,
}

impl DequantQ6KPipeline {
    pub fn new(device: &wgpu::Device) -> Self {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("dequant_q6k"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/dequant_q6k.wgsl").into()),
        });

        let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("dequant_q6k_bgl"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: true },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: false },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 2,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
            ],
        });

        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("dequant_q6k_layout"),
            bind_group_layouts: &[&bgl],
            push_constant_ranges: &[],
        });

        let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("dequant_q6k_pipeline"),
            layout: Some(&layout),
            module: &shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });

        Self { pipeline, bgl }
    }

    /// Dispatch Q6_K dequantization on GPU.
    ///
    /// - `quant_buf`: Raw Q6_K data (210 bytes per 256-element block)
    /// - `output_buf`: F32 output buffer (n_elements * 4 bytes)
    /// - `n_elements`: Total number of weight elements
    pub fn dispatch(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        encoder: &mut wgpu::CommandEncoder,
        quant_buf: &wgpu::Buffer,
        output_buf: &wgpu::Buffer,
        n_elements: u32,
    ) {
        let total_blocks = (n_elements + 255) / 256;
        let params = DequantQ6KParams {
            total_blocks,
            _pad0: 0,
            _pad1: 0,
            _pad2: 0,
        };

        let params_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("dequant_q6k_params"),
            size: std::mem::size_of::<DequantQ6KParams>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        queue.write_buffer(&params_buf, 0, bytemuck::cast_slice(&[params]));

        let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("dequant_q6k_bg"),
            layout: &self.bgl,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: quant_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: output_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 2, resource: params_buf.as_entire_binding() },
            ],
        });

        // One thread per element, 256 threads per workgroup
        let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, Some(&bg), &[]);
        let workgroups = (n_elements + 255) / 256;
        pass.dispatch_workgroups(workgroups, 1, 1);
    }
}

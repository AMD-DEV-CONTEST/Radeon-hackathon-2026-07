//! wgpu device initialization, pipeline compilation, and GPU matmul dispatch.
//! Uses f32 shader — works on ALL Vulkan GPUs (Pascal, Maxwell, Kelvin, AMD, Intel).

use crate::wgpu_uniform::MatrixDimensions;
use std::sync::Arc;

pub struct GpuContext {
    pub device: Arc<wgpu::Device>,
    pub queue: Arc<wgpu::Queue>,
    pub matmul_pipeline: Arc<wgpu::ComputePipeline>,
    pub bind_group_layout: Arc<wgpu::BindGroupLayout>,
    pub buf_a: wgpu::Buffer,
    pub buf_b_t: wgpu::Buffer,
    pub buf_c: wgpu::Buffer,
    pub buf_dims: wgpu::Buffer,
    pub max_n: usize,
    pub max_k: usize,
}

impl GpuContext {
    /// Initialize wgpu device on a specific GPU index.
    pub async fn init(gpu_index: usize) -> Result<Self, String> {
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
            backends: wgpu::Backends::VULKAN,
            ..Default::default()
        });

        let adapters: Vec<_> = instance.enumerate_adapters(wgpu::Backends::VULKAN)
            .into_iter()
            .filter(|a| matches!(a.get_info().device_type, wgpu::DeviceType::DiscreteGpu))
            .collect();

        if adapters.is_empty() {
            return Err("No discrete Vulkan GPUs found. Check that `vulkaninfo` shows your P100s.".to_string());
        }

        let adapter = &adapters[gpu_index.min(adapters.len() - 1)];
        tracing::info!("Selected GPU {}: {} ({:?})", gpu_index, adapter.get_info().name, adapter.get_info().backend);

        let (device, queue) = adapter.request_device(
            &wgpu::DeviceDescriptor {
                label: Some("cesarops_device"),
                required_features: wgpu::Features::empty(),
                required_limits: wgpu::Limits {
                    max_storage_buffer_binding_size: 1024 * 1024 * 1024,
                    max_buffer_size: 1024 * 1024 * 1024,
                    ..Default::default()
                },
                memory_hints: wgpu::MemoryHints::Performance,
            },
            None,
        ).await.map_err(|e| format!("Device request failed: {}", e))?;

        let shader_source = include_str!("../shaders/matmul_f32.wgsl");
        let shader_module = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("matmul_f32"),
            source: wgpu::ShaderSource::Wgsl(shader_source.into()),
        });

        let bind_group_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("matmul_bgl"),
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
                        ty: wgpu::BufferBindingType::Storage { read_only: true },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
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

        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("matmul_pipeline_layout"),
            bind_group_layouts: &[&bind_group_layout],
            push_constant_ranges: &[],
        });

        let matmul_pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("matmul_pipeline"),
            layout: Some(&pipeline_layout),
            module: &shader_module,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });

        // Pre-allocate buffers for largest expected matmul (lm_head: 1x1536 x 151936x1536)
        const MAX_K: usize = 4096;
        const MAX_N: usize = 160_000;
        const MAX_M: usize = 8192;

        let buf_a_size = (MAX_M * MAX_K) * std::mem::size_of::<f32>();
        let buf_b_t_size = (MAX_K * MAX_N) * std::mem::size_of::<f32>();
        let buf_c_size = (MAX_M * MAX_N) * std::mem::size_of::<f32>();

        let buf_a = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("buf_a"), size: buf_a_size as u64,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST, mapped_at_creation: false,
        });
        let buf_b_t = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("buf_b_t"), size: buf_b_t_size as u64,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST, mapped_at_creation: false,
        });
        let buf_c = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("buf_c"), size: buf_c_size as u64,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC, mapped_at_creation: false,
        });
        let buf_dims = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("buf_dims"), size: std::mem::size_of::<MatrixDimensions>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST, mapped_at_creation: false,
        });

        Ok(Self {
            device: Arc::new(device),
            queue: Arc::new(queue),
            matmul_pipeline: Arc::new(matmul_pipeline),
            bind_group_layout: Arc::new(bind_group_layout),
            buf_a, buf_b_t, buf_c, buf_dims,
            max_n: MAX_N, max_k: MAX_K,
        })
    }

    /// Dispatches C = A x B^T on the GPU and returns C.
    pub fn matmul_gpu(&self, a: &[f32], b_t: &[f32], m: usize, k: usize, n: usize) -> Vec<f32> {
        // 1. Upload dimensions uniform
        self.queue.write_buffer(&self.buf_dims, 0, bytemuck::cast_slice(&[MatrixDimensions { m: m as u32, k: k as u32, n: n as u32, pad: 0 }]));

        // 2. Write input matrices to storage buffers
        let actual_a_len = (m * k).min(a.len());
        let actual_b_t_len = (k * n).min(b_t.len());

        self.queue.write_buffer(&self.buf_a, 0, bytemuck::cast_slice(&a[..actual_a_len]));
        self.queue.write_buffer(&self.buf_b_t, 0, bytemuck::cast_slice(&b_t[..actual_b_t_len]));

        // 3. Create bind group with actual buffers
        let bind_group = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("matmul_bg"),
            layout: &self.bind_group_layout,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: self.buf_a.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: self.buf_b_t.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 2, resource: self.buf_c.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 3, resource: self.buf_dims.as_entire_binding() },
            ],
        });

        // 4. Encode compute pass
        let c_size = (m * n) * std::mem::size_of::<f32>();
        let mut encoder = self.device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("matmul_encoder") });

        {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
            pass.set_pipeline(&self.matmul_pipeline);
            pass.set_bind_group(0, Some(&bind_group), &[]);
            // Dispatch 8x8 workgroups covering M x N space
            let wg_x = ((n + 7) / 8).max(1);
            let wg_y = ((m + 7) / 8).max(1);
            pass.dispatch_workgroups(wg_x as u32, wg_y as u32, 1);
        }

        // 5. Copy result to staging buffer for readback
        let staging_buf = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("staging_buf"), size: c_size as u64,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ, mapped_at_creation: false,
        });
        encoder.copy_buffer_to_buffer(&self.buf_c, 0, &staging_buf, 0, c_size as u64);

        // 6. Submit and block until mapping completes
        self.queue.submit(std::iter::once(encoder.finish()));

        let slice = staging_buf.slice(..);
        let (tx, rx) = std::sync::mpsc::channel();
        slice.map_async(wgpu::MapMode::Read, move |result| {
            let _ = tx.send(result);
        });

        // Poll device until map callback fires
        loop {
            self.device.poll(wgpu::Maintain::Poll);
            if let Ok(_) = rx.try_recv() {
                break;
            }
            std::thread::sleep(std::time::Duration::from_micros(10));
        }

        let data = slice.get_mapped_range();
        let result: Vec<f32> = bytemuck::cast_slice(&data).to_vec();
        drop(data);
        staging_buf.unmap();

        result
    }
}

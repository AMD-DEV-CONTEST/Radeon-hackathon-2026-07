#![recursion_limit = "256"]
//! cesarops-inference — Native Rust LLM inference engine + maritime SAR detection.
//!
//! Features:
//! - `wgpu-backend` (default): Custom WGSL shaders for P100 Pascal GPUs
//! - `cuda-backend` (optional): Mistral-RS with native CUDA for V100+ GPUs

pub mod hardware;
pub mod loader;
pub mod bridge;
pub mod sampling;
pub mod server;
pub mod mcp;
pub mod geo_filter;
pub mod grammar;
pub mod arena;
pub mod attention;
pub mod transformer;
pub mod matmul;
pub mod moe;
pub mod chat_template;
pub mod kv_cache;
pub mod tokenizer;
pub mod weight_cache;
pub mod hybrid_core;
pub mod cake_kv;
pub mod wgpu_injection;
pub mod wgpu_uniform;
pub mod wgpu_dynamic_binder;
pub mod backend_trait;
pub mod backend_wgpu;
pub mod backend_cuda;
pub mod gpu_context;
pub mod tensor_chunker;
pub mod tensor_loader_safe;
pub mod device_profile;
pub mod shader_ops;
pub mod forward_pass;
pub mod attention_dispatch;
pub mod generate;
pub mod telemetry_tuner;
pub mod pipeline_init;
pub mod dequant_probe;
pub mod universal_bridge;
pub mod satellite_stitch;
pub mod optical_mass;
pub mod galvanic_battery;
pub mod magnetic_eraser;
pub mod model_arch;
pub mod scratch_buffers;
pub mod arch_detect;
pub mod pipeline_cache;

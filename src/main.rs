// src/main.rs — cesarops-inference binary entry point
//!
//! Loads a GGUF model, audits hardware, and starts the KoboldCPP-compatible server.
//! The server runs real inference: embed → transformer forward → sample → decode.

use std::path::PathBuf;
use std::sync::Arc;
use std::env;
use tracing::{info, warn, error, Level};
use tracing_subscriber::FmtSubscriber;

use cesarops_inference::hardware;
use cesarops_inference::loader;
use cesarops_inference::arena::InferenceArena;
use cesarops_inference::tokenizer::ZeroAllocBpeTokenizer;
use cesarops_inference::server;
use cesarops_inference::gpu_context;
use cesarops_inference::tensor_chunker::ChunkedMatmulPipeline;
use cesarops_inference::tensor_loader_safe::{TensorRegistry, TensorType};
use cesarops_inference::forward_pass::{LayerPipelines, LayerWeights, KVCache, ModelConfig};
use cesarops_inference::shader_ops::{DequantPipeline, RmsNormPipeline};
use cesarops_inference::generate::{self, ModelWeightsGpu, GenerationParams, gguf_tensor_name};
use cesarops_inference::telemetry_tuner;
use cesarops_inference::device_profile::DeviceProfile;

#[derive(Debug)]
struct Args {
    model: PathBuf,
    tokenizer: Option<PathBuf>,
    port: u16,
    backend: String,
    gpu: usize,
    mode: String,       // "serve" or "generate"
    prompt: String,     // For generate mode
    max_tokens: usize,  // For generate mode
}

fn parse_args() -> Result<Args, anyhow::Error> {
    let args: Vec<String> = env::args().collect();
    let mut model = None;
    let mut tokenizer = None;
    let mut port = 5001;
    let mut backend = "wgpu".to_string();
    let mut gpu = 0usize;
    let mut mode = "serve".to_string();
    let mut prompt = String::new();
    let mut max_tokens = 256usize;

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "generate" => { mode = "generate".to_string(); i += 1; }
            "serve" => { mode = "serve".to_string(); i += 1; }
            "--model" => {
                if i + 1 < args.len() {
                    model = Some(PathBuf::from(&args[i + 1]));
                    i += 2;
                } else {
                    return Err(anyhow::anyhow!("Missing value for --model"));
                }
            }
            "--tokenizer" => {
                if i + 1 < args.len() {
                    tokenizer = Some(PathBuf::from(&args[i + 1]));
                    i += 2;
                } else {
                    return Err(anyhow::anyhow!("Missing value for --tokenizer"));
                }
            }
            "--port" => {
                if i + 1 < args.len() {
                    port = args[i + 1].parse::<u16>()?;
                    i += 2;
                } else {
                    return Err(anyhow::anyhow!("Missing value for --port"));
                }
            }
            "--backend" => {
                if i + 1 < args.len() {
                    backend = args[i + 1].clone();
                    i += 2;
                } else {
                    return Err(anyhow::anyhow!("Missing value for --backend"));
                }
            }
            "--gpu" => {
                if i + 1 < args.len() {
                    gpu = args[i + 1].parse::<usize>()?;
                    i += 2;
                } else {
                    return Err(anyhow::anyhow!("Missing value for --gpu"));
                }
            }
            "--prompt" => {
                if i + 1 < args.len() {
                    prompt = args[i + 1].clone();
                    i += 2;
                } else {
                    return Err(anyhow::anyhow!("Missing value for --prompt"));
                }
            }
            "--max-tokens" => {
                if i + 1 < args.len() {
                    max_tokens = args[i + 1].parse::<usize>()?;
                    i += 2;
                } else {
                    return Err(anyhow::anyhow!("Missing value for --max-tokens"));
                }
            }
            _ => {
                return Err(anyhow::anyhow!("Unknown argument: {}", args[i]));
            }
        }
    }

    let model = model.ok_or_else(|| anyhow::anyhow!("Missing: --model <path_to_gguf>"))?;
    Ok(Args { model, tokenizer, port, backend, gpu, mode, prompt, max_tokens })
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let subscriber = FmtSubscriber::builder()
        .with_max_level(Level::INFO)
        .finish();
    tracing::subscriber::set_global_default(subscriber)?;

    info!("cesarops-inference starting...");

    let args = match parse_args() {
        Ok(a) => a,
        Err(e) => {
            eprintln!("CLI Error: {}", e);
            eprintln!("Usage:");
            eprintln!("  cesarops-inference serve --model <path.gguf> [--port 5001] [--backend wgpu] [--gpu 0]");
            eprintln!("  cesarops-inference generate --model <path.gguf> --prompt \"text\" [--max-tokens 256]");
            std::process::exit(1);
        }
    };

    info!("Auditing hardware...");
    let profile = hardware::audit_system();

    info!("Loading model from {:?}...", args.model);
    let weights = loader::load(&args.model, &profile)?;
    let model_name = args.model.file_name()
        .unwrap_or_default()
        .to_string_lossy()
        .into_owned();
    info!("Model loaded: {} ({} layers, {} hidden, {} heads, {} kv_heads, {} vocab, {} tensors)",
        model_name, weights.n_layers, weights.hidden_dim, weights.n_heads,
        weights.n_kv_heads, weights.vocab_size, weights.tensors.len());

    // Print first few tensor names for debugging
    info!("Sample tensors:");
    for (i, name) in weights.tensors.keys().take(8).enumerate() {
        info!("  [{}] {}", i, name);
    }

    info!("Allocating 1GB inference arena (NUMA node 0)...");
    let arena = InferenceArena::new(1024 * 1024 * 1024, 0);

    // Load tokenizer
    let tokenizer = load_tokenizer(&args, &arena);
    let weights = Arc::new(weights);

    match args.mode.as_str() {
        "generate" => {
            run_generate_mode(&args, &weights, &tokenizer).await?;
        }
        _ => {
            // Default: serve mode
            let gpu_context = if args.backend == "wgpu" {
                info!("Initializing wgpu GPU backend on GPU {}...", args.gpu);
                match gpu_context::GpuContext::init(args.gpu).await {
                    Ok(ctx) => {
                        info!("GPU backend ready!");
                        Some(Arc::new(ctx))
                    }
                    Err(e) => {
                        warn!("GPU init failed: {} — falling back to CPU", e);
                        None
                    }
                }
            } else {
                None
            };

            info!("Starting server on port {}...", args.port);
            server::run_server(model_name, args.port, weights, arena, tokenizer, gpu_context).await?;
        }
    }

    Ok(())
}

/// Load tokenizer from explicit path or auto-detect.
fn load_tokenizer(args: &Args, arena: &Arc<InferenceArena>) -> Arc<ZeroAllocBpeTokenizer> {
    if let Some(tok_path) = &args.tokenizer {
        info!("Loading tokenizer from {:?}...", tok_path);
        match ZeroAllocBpeTokenizer::load_from_file(tok_path, Arc::clone(arena)) {
            Ok(t) => {
                info!("Tokenizer loaded: {} vocab entries, {} merges", t.vocab.len(), t.merges.len());
                return Arc::new(t);
            }
            Err(e) => {
                warn!("Failed to load tokenizer: {} — falling back to byte-level", e);
            }
        }
    } else {
        let auto_path = args.model.parent()
            .map(|p| p.join("tokenizer.json"))
            .unwrap_or_default();
        if auto_path.exists() {
            info!("Auto-detected tokenizer at {:?}", auto_path);
            match ZeroAllocBpeTokenizer::load_from_file(&auto_path, Arc::clone(arena)) {
                Ok(t) => {
                    info!("Tokenizer loaded: {} vocab entries, {} merges", t.vocab.len(), t.merges.len());
                    return Arc::new(t);
                }
                Err(e) => {
                    warn!("Failed to load auto-detected tokenizer: {} — byte-level fallback", e);
                }
            }
        }
    }
    info!("No tokenizer.json found — using byte-level tokenization");
    Arc::new(ZeroAllocBpeTokenizer::new(Arc::clone(arena)))
}

/// Run the native GPU generation pipeline.
async fn run_generate_mode(
    args: &Args,
    weights: &Arc<loader::ModelWeights>,
    tokenizer: &Arc<ZeroAllocBpeTokenizer>,
) -> anyhow::Result<()> {
    use std::io::Write;

    let raw_prompt = if args.prompt.is_empty() {
        "Hello, I am CESARops, a search and rescue AI assistant.".to_string()
    } else {
        args.prompt.clone()
    };

    // Apply Qwen chat template if prompt doesn't already contain special tokens
    let prompt = if raw_prompt.contains("<|im_start|>") {
        raw_prompt
    } else {
        format!("<|im_start|>user\n{}<|im_end|>\n<|im_start|>assistant\n", raw_prompt)
    };
    let prompt = prompt.as_str();

    info!("=== NATIVE GPU GENERATION MODE ===");
    info!("Prompt: \"{}\"", &prompt[..prompt.len().min(80)]);
    info!("Max tokens: {}", args.max_tokens);

    // Initialize wgpu
    info!("Initializing Vulkan via wgpu...");
    let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
        backends: wgpu::Backends::VULKAN,
        ..Default::default()
    });

    let adapter = instance.request_adapter(&wgpu::RequestAdapterOptions {
        power_preference: wgpu::PowerPreference::HighPerformance,
        compatible_surface: None,
        force_fallback_adapter: false,
    }).await.ok_or_else(|| anyhow::anyhow!("No Vulkan GPU found"))?;

    let adapter_info = adapter.get_info();
    info!("GPU: {} ({:?})", adapter_info.name, adapter_info.backend);

    let device_profile = DeviceProfile::from_adapter_info(&adapter_info);

    let (device, queue) = adapter.request_device(
        &wgpu::DeviceDescriptor {
            label: Some("cesarops_generate"),
            required_features: wgpu::Features::empty(),
            required_limits: wgpu::Limits {
                max_storage_buffer_binding_size: 900 * 1024 * 1024,
                max_buffer_size: 900 * 1024 * 1024,
                ..Default::default()
            },
            memory_hints: wgpu::MemoryHints::Performance,
        },
        None,
    ).await?;

    let device = Arc::new(device);
    let queue = Arc::new(queue);

    // Run hardware profiler (or load cached)
    info!("Running hardware profiler...");
    let optimal = telemetry_tuner::profile_or_load_cached(
        &device, &queue, &adapter_info.name, "/tmp/cesarops_profiles"
    );
    info!("Optimal config: tile={}, {:.1} GFLOPS", optimal.tile_dimension, optimal.measured_throughput_gflops);

    // Build model config dynamically from GGUF metadata
    let config = ModelConfig {
        hidden_dim: weights.hidden_dim as u32,
        intermediate_dim: {
            // Try to find intermediate dim from a gate/up tensor shape
            let gate_name = format!("blk.0.ffn_gate.weight");
            let up_name = format!("blk.0.ffn_up.weight");
            if let Some(region) = weights.tensors.get(&gate_name) {
                // GGUF shape [ne0, ne1] — ne1 is the output dim for gate/up
                region.shape.get(1).copied().unwrap_or(weights.hidden_dim * 4) as u32
            } else if let Some(region) = weights.tensors.get(&up_name) {
                region.shape.get(1).copied().unwrap_or(weights.hidden_dim * 4) as u32
            } else {
                (weights.hidden_dim * 4) as u32
            }
        },
        n_heads: weights.n_heads as u32,
        n_kv_heads: weights.n_kv_heads as u32,
        head_dim: (weights.hidden_dim / weights.n_heads) as u32,
        n_layers: weights.n_layers as u32,
        vocab_size: {
            // Use actual tensor shape instead of metadata (which may be padded)
            let embed_name = "token_embd.weight".to_string();
            if let Some(region) = weights.tensors.get(&embed_name) {
                // GGUF shape [ne0, ne1] = [hidden_dim, vocab_size]
                region.shape.get(1).copied().unwrap_or(weights.vocab_size) as u32
            } else {
                weights.vocab_size as u32
            }
        },
        max_seq_len: 2048,
        rms_norm_eps: 1e-6,
    };

    info!("Model config: {}L, {}H, {}KV, {}HD, {}V",
        config.n_layers, config.n_heads, config.n_kv_heads, config.head_dim, config.vocab_size);

    // Load tensors to GPU via safe loader
    info!("Loading tensors to GPU...");
    let mut registry = TensorRegistry::new(Arc::clone(&device), Arc::clone(&queue));

    // Load embedding table
    let embed_name = gguf_tensor_name(0, "embed");
    if let Some(region) = weights.tensors.get(&embed_name) {
        if let Some(bytes) = weights.tensor_bytes(&embed_name) {
            // GGUF stores dims as [ne0, ne1] (inner-first). Reverse to [rows, cols].
            // Reference: Ratchet does dimensions.reverse() after reading from GGUF.
            let shape = if region.shape.len() >= 2 {
                [region.shape[1], region.shape[0]] // Reverse: [ne0,ne1] → [ne1,ne0] = [rows,cols]
            } else {
                [config.vocab_size as usize, config.hidden_dim as usize]
            };
            let dtype = TensorType::from_gguf(region.quant_type).unwrap_or(TensorType::F16);
            let _ = registry.load_tensor_safe(&embed_name, shape, dtype, bytes);
            info!("  Loaded: {} [{} × {}] (qt={})", embed_name, shape[0], shape[1], region.quant_type);
        }
    }

    // Load per-layer weights — single pass, load directly by GGUF name
    for layer in 0..config.n_layers as usize {
        let tensor_names = [
            format!("blk.{}.attn_norm.weight", layer),
            format!("blk.{}.ffn_norm.weight", layer),
            format!("blk.{}.attn_q.weight", layer),
            format!("blk.{}.attn_k.weight", layer),
            format!("blk.{}.attn_v.weight", layer),
            format!("blk.{}.attn_output.weight", layer),
            format!("blk.{}.ffn_gate.weight", layer),
            format!("blk.{}.ffn_up.weight", layer),
            format!("blk.{}.ffn_down.weight", layer),
            format!("blk.{}.attn_q.bias", layer),
            format!("blk.{}.attn_k.bias", layer),
            format!("blk.{}.attn_v.bias", layer),
        ];

        for name in &tensor_names {
            if let Some(region) = weights.tensors.get(name) {
                if let Some(bytes) = weights.tensor_bytes(name) {
                    let shape = if region.shape.len() >= 2 {
                        [region.shape[1], region.shape[0]]
                    } else {
                        [region.shape[0], 1]
                    };
                    let dtype = TensorType::from_gguf(region.quant_type).unwrap_or(TensorType::F16);
                    // Debug: check attn_norm loading
                    if name.contains("blk.0.attn_norm") {
                        let first4: &[f32] = bytemuck::cast_slice(&bytes[..16]);
                        info!("  LOADING blk.0.attn_norm: shape={:?} qt={} dtype={:?} first4={:?}",
                            shape, region.quant_type, dtype, first4);
                    }
                    let _ = registry.load_tensor_safe(name, shape, dtype, bytes);
                }
            }
        }

        if layer % 10 == 0 {
            info!("  Loaded layer {}/{}", layer + 1, config.n_layers);
        }
    }

    // Load final norm and lm_head
    let final_norm_name = gguf_tensor_name(0, "final_norm");
    if let Some(bytes) = weights.tensor_bytes(&final_norm_name) {
        let region = &weights.tensors[&final_norm_name];
        let shape = [region.shape[0], if region.shape.len() > 1 { region.shape[1] } else { 1 }];
        let dtype = TensorType::from_gguf(region.quant_type).unwrap_or(TensorType::F16);
        let _ = registry.load_tensor_safe(&final_norm_name, shape, dtype, bytes);
    }

    let lm_head_name = gguf_tensor_name(0, "lm_head");
    if let Some(bytes) = weights.tensor_bytes(&lm_head_name) {
        let region = &weights.tensors[&lm_head_name];
        let shape = if region.shape.len() >= 2 {
            [region.shape[1], region.shape[0]] // Reverse GGUF dims
        } else {
            [config.vocab_size as usize, config.hidden_dim as usize]
        };
        let dtype = TensorType::from_gguf(region.quant_type).unwrap_or(TensorType::F16);
        let _ = registry.load_tensor_safe(&lm_head_name, shape, dtype, bytes);
    }

    registry.print_stats();

    // Initialize all compute pipelines
    info!("Compiling WGSL shader pipelines...");
    let pipelines = cesarops_inference::pipeline_init::init_layer_pipelines(&device);
    info!("All pipelines compiled.");

    // Run dequant probe to validate shader correctness
    let probe_result = cesarops_inference::dequant_probe::run_dequant_probe(
        &device, &queue, &pipelines.dequant_q6k,
    );
    if !probe_result.passed {
        warn!("Dequant probe failed — output may be garbled. Debugging needed.");
    }

    // Self-healing telemetry: read back first 8 dequanted values from token_embd
    // and compare against known-good Python reference values
    {
        let embed_name = gguf_tensor_name(0, "embed");
        if let Some(handle) = registry.get_buffer(&embed_name) {
            // Read first 8 f32 values from the dequanted embedding buffer
            let readback_size = 32u64; // 8 * 4 bytes
            let staging = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("telemetry_staging"),
                size: readback_size,
                usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
                mapped_at_creation: false,
            });
            let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
            enc.copy_buffer_to_buffer(handle, 0, &staging, 0, readback_size);
            queue.submit(std::iter::once(enc.finish()));

            let slice = staging.slice(..);
            let (tx, rx) = std::sync::mpsc::channel();
            slice.map_async(wgpu::MapMode::Read, move |r| { let _ = tx.send(r); });
            loop {
                device.poll(wgpu::Maintain::Poll);
                if rx.try_recv().is_ok() { break; }
                std::thread::sleep(std::time::Duration::from_micros(10));
            }
            let data = slice.get_mapped_range();
            let vals: &[f32] = bytemuck::cast_slice(&data);
            info!("═══ SELF-HEALING TELEMETRY: token_embd.weight[0..8] ═══");
            info!("  GPU values: {:?}", &vals[..8.min(vals.len())]);
            info!("  Expected (Python ref): [-0.0151, 0.0109, -0.0067, 0.0075, 0.0034, -0.0042, -0.0268, -0.0059]");
            // Check if values are in reasonable range
            let any_nan = vals.iter().any(|v| v.is_nan());
            let any_huge = vals.iter().any(|v| v.abs() > 10.0);
            let all_zero = vals.iter().all(|v| *v == 0.0);
            if any_nan { error!("  ✗ NaN detected in embedding weights!"); }
            else if any_huge { error!("  ✗ Values too large — dequant scale error"); }
            else if all_zero { error!("  ✗ All zeros — data offset likely wrong"); }
            else { info!("  ✓ Values in reasonable range"); }
            drop(data);
            staging.unmap();
        }
    }

    // Allocate KV caches
    let kv_bytes_per_layer = (config.max_seq_len as u64) * (config.n_kv_heads as u64) * (config.head_dim as u64) * 4;
    let mut kv_caches: Vec<cesarops_inference::forward_pass::KVCache> = (0..config.n_layers)
        .map(|i| cesarops_inference::forward_pass::KVCache {
            key_cache: device.create_buffer(&wgpu::BufferDescriptor {
                label: Some(&format!("kv_k_{}", i)),
                size: kv_bytes_per_layer,
                usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::COPY_SRC,
                mapped_at_creation: false,
            }),
            value_cache: device.create_buffer(&wgpu::BufferDescriptor {
                label: Some(&format!("kv_v_{}", i)),
                size: kv_bytes_per_layer,
                usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::COPY_SRC,
                mapped_at_creation: false,
            }),
            current_len: 0,
            max_seq: config.max_seq_len,
        })
        .collect();
    info!("KV cache: {:.1} MB", (kv_bytes_per_layer * 2 * config.n_layers as u64) as f64 / 1e6);

    // Tokenize
    let prompt_tokens = tokenizer.encode(prompt);
    info!("Prompt: {} tokens — IDs: {:?}", prompt_tokens.len(), &prompt_tokens[..prompt_tokens.len().min(20)]);

    // Build LayerWeights from registry
    info!("Mapping tensors to layer weight structures...");
    let embed_buf = registry.take_buffer("token_embd.weight")
        .expect("Missing token_embd.weight");
    let final_norm_buf = registry.take_buffer("output_norm.weight")
        .expect("Missing output_norm.weight");
    let lm_head_buf = registry.take_buffer("output.weight")
        .unwrap_or_else(|| registry.take_buffer("token_embd.weight")
            .expect("Missing output.weight and no tied weights"));

    let dummy_buf = |label: &str| -> wgpu::Buffer {
        device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(label), size: 4,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
            mapped_at_creation: false,
        })
    };

    let mut layer_weights_vec: Vec<cesarops_inference::forward_pass::LayerWeights> = Vec::new();
    for i in 0..config.n_layers as usize {
        layer_weights_vec.push(cesarops_inference::forward_pass::LayerWeights {
            attn_norm: registry.take_buffer(&format!("blk.{}.attn_norm.weight", i))
                .unwrap_or_else(|| dummy_buf("dummy_attn_norm")),
            ffn_norm: registry.take_buffer(&format!("blk.{}.ffn_norm.weight", i))
                .unwrap_or_else(|| dummy_buf("dummy_ffn_norm")),
            q_proj: registry.take_buffer(&format!("blk.{}.attn_q.weight", i))
                .unwrap_or_else(|| dummy_buf("dummy_q")),
            k_proj: registry.take_buffer(&format!("blk.{}.attn_k.weight", i))
                .unwrap_or_else(|| dummy_buf("dummy_k")),
            v_proj: registry.take_buffer(&format!("blk.{}.attn_v.weight", i))
                .unwrap_or_else(|| dummy_buf("dummy_v")),
            o_proj: registry.take_buffer(&format!("blk.{}.attn_output.weight", i))
                .unwrap_or_else(|| dummy_buf("dummy_o")),
            gate_proj: registry.take_buffer(&format!("blk.{}.ffn_gate.weight", i))
                .unwrap_or_else(|| dummy_buf("dummy_gate")),
            up_proj: registry.take_buffer(&format!("blk.{}.ffn_up.weight", i))
                .unwrap_or_else(|| dummy_buf("dummy_up")),
            down_proj: registry.take_buffer(&format!("blk.{}.ffn_down.weight", i))
                .unwrap_or_else(|| dummy_buf("dummy_down")),
            q_bias: registry.take_buffer(&format!("blk.{}.attn_q.bias", i)),
            k_bias: registry.take_buffer(&format!("blk.{}.attn_k.bias", i)),
            v_bias: registry.take_buffer(&format!("blk.{}.attn_v.bias", i)),
        });
    }
    info!("All {} layers mapped.", config.n_layers);

    // Build the model weights struct for generate
    let model_weights = cesarops_inference::generate::ModelWeightsGpu {
        token_embeddings: embed_buf,
        layers: layer_weights_vec,
        final_norm: final_norm_buf,
        lm_head: lm_head_buf,
    };

    let start = std::time::Instant::now();

    println!("\n╔══════════════════════════════════════════════════════════════╗");
    println!("║  CESARops Native Inference Engine v0.1                      ║");
    println!("╠══════════════════════════════════════════════════════════════╣");
    println!("║  GPU: {} (tile={}×{}, {:.0} GFLOPS)", adapter_info.name, optimal.tile_dimension, optimal.tile_dimension, optimal.measured_throughput_gflops);
    println!("║  Model: {}L × {}H × {}V ({:.2} GB)", config.n_layers, config.hidden_dim, config.vocab_size, registry.stats.total_bytes as f64 / 1e9);
    println!("║  Generating from {} prompt tokens...", prompt_tokens.len());
    println!("╚══════════════════════════════════════════════════════════════╝\n");

    // Run generation
    let gen_params = GenerationParams {
        temperature: 0.0,  // Greedy for debugging
        top_p: 1.0,
        max_tokens: args.max_tokens,
        stop_tokens: vec![151643, 151645],
    };

    match generate::generate_tokens(
        &device, &queue, &config, &pipelines,
        &model_weights, &mut kv_caches,
        &prompt_tokens, &gen_params,
    ) {
        Ok(output_tokens) => {
            let elapsed = start.elapsed();
            let output_text = tokenizer.decode(&output_tokens);
            println!("{}", output_text);
            println!("\n────────────────────────────────────────");
            println!("Token IDs: {:?}", &output_tokens[..output_tokens.len().min(20)]);
            println!("Generated {} tokens in {:.2?} ({:.1} t/s)",
                output_tokens.len(), elapsed,
                output_tokens.len() as f64 / elapsed.as_secs_f64());
        }
        Err(e) => {
            eprintln!("Generation error: {}", e);
        }
    }

    Ok(())
}

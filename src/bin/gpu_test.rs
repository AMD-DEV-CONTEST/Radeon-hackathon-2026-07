use cesarops_inference::gpu_context::GpuContext;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();
    println!("Initializing GPU context on GPU 0...");
    match GpuContext::init(0).await {
        Ok(gpu) => {
            println!("GPU init success!");

            // Small test: 2x3 * 3x2
            let a: Vec<f32> = vec![1.0, 2.0, 3.0, 4.0, 5.0, 6.0]; // 2x3
            let b_t: Vec<f32> = vec![1.0, 3.0, 5.0, 2.0, 4.0, 6.0]; // 2x3 (B transposed)
            println!("Running 2x3 * 3x2 matmul on GPU...");
            let result = gpu.matmul_gpu(&a, &b_t, 2, 3, 2);
            println!("Result: {:?}", result);
            println!("Expected: [22.0, 28.0, 49.0, 64.0]");

            // Larger test: simulates a single projection (1x1536 * 1536x1536)
            let big_a: Vec<f32> = (0..1536).map(|i| (i as f32) * 0.001).collect();
            let big_b: Vec<f32> = (0..1536 * 1536).map(|i| ((i % 7) as f32 - 3.0) * 0.01).collect();
            println!("\nRunning 1x1536 * 1536x1536 projection on GPU...");
            let start = std::time::Instant::now();
            let big_result = gpu.matmul_gpu(&big_a, &big_b, 1, 1536, 1536);
            let elapsed = start.elapsed();
            println!("Done in {:?}", elapsed);
            println!("Output[0..5] = {:?}", &big_result[..5.min(big_result.len())]);

            // LM head size test: 1x1536 * 151936x1536
            println!("\nRunning 1x1536 * 151936x1536 (lm_head) on GPU...");
            let lm_b: Vec<f32> = (0..151936 * 1536).map(|i| ((i % 11) as f32 - 5.0) * 0.001).collect();
            let start2 = std::time::Instant::now();
            let lm_result = gpu.matmul_gpu(&big_a, &lm_b, 1, 1536, 151936);
            let elapsed2 = start2.elapsed();
            println!("Done in {:?}", elapsed2);
            println!("Output[0..5] = {:?}", &lm_result[..5.min(lm_result.len())]);
        }
        Err(e) => {
            println!("GPU init failed: {}", e);
            println!("Check: vulkan drivers, GPU availability, SHADER_F16 support");
        }
    }
}

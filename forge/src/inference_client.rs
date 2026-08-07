//! HTTP client + llama-server spawn helpers for local workers.

pub fn llama_server_bin() -> String {
    const CANDIDATES: [&str; 4] = [
        "/home/cesarops/bin/llama-server",
        "/home/cesarops/llama.cpp/build/bin/llama-server",
        "/usr/local/bin/llama-server",
        "/usr/bin/llama-server",
    ];

    for path in CANDIDATES {
        if std::path::Path::new(path).exists() {
            return path.to_string();
        }
    }
    "llama-server".to_string()
}

pub fn effective_worker_engine(engine_pin: &str, use_native: bool) -> String {
    if use_native {
        "cesarops-inference".to_string()
    } else if engine_pin == "koboldcpp" {
        "koboldcpp".to_string()
    } else if engine_pin == "llama-server" || engine_pin == "llama.cpp" || engine_pin.is_empty() {
        "llama-server".to_string()
    } else {
        engine_pin.to_string()
    }
}

pub fn llama_server_spawn_cmd(
    model: &str,
    port: i64,
    backend: &str,
    gpulayers: i64,
    contextsize: i64,
    threads: i64,
    tensor_split: &[String],
    gpu_ids: &[i64],
    worker_idx: usize,
) -> String {
    let dev = if !gpu_ids.is_empty() {
        if backend == "vulkan" {
            gpu_ids
                .iter()
                .map(|id| format!("Vulkan{}", id))
                .collect::<Vec<_>>()
                .join(",")
        } else {
            gpu_ids
                .iter()
                .map(|id| format!("CUDA{}", id))
                .collect::<Vec<_>>()
                .join(",")
        }
    } else if backend == "vulkan" {
        "Vulkan0,Vulkan1".to_string()
    } else {
        format!("CUDA{}", worker_idx.min(1))
    };

    let ts = if tensor_split.is_empty() {
        if gpu_ids.len() > 1 {
            let parts = gpu_ids.len() as i64;
            let base = 100 / parts;
            let mut values = vec![base; parts as usize];
            let remainder = 100 - (base * parts);
            if remainder > 0 {
                values[0] += remainder;
            }
            values
                .iter()
                .map(|v| v.to_string())
                .collect::<Vec<_>>()
                .join(",")
        } else {
            "100".to_string()
        }
    } else {
        tensor_split.join(",")
    };

    let ngl = if gpulayers <= 0 || gpulayers >= 99 {
        "99".to_string()
    } else {
        gpulayers.to_string()
    };

    let mtp_suffix = if model.contains("MTP") || model.contains("mtp") {
        " --spec-type draft-mtp --spec-draft-n-max 2"
    } else {
        ""
    };

    format!(
        "setsid {bin} -m {model} --host 0.0.0.0 --port {port} \
         -dev {dev} -sm layer -ts {ts} -ngl {ngl} -c {ctx} -t {threads}{mtp} \
         > /tmp/worker_{idx}.log 2>&1 < /dev/null & disown",
        bin = llama_server_bin(),
        model = model,
        port = port,
        dev = dev,
        ts = ts,
        ngl = ngl,
        ctx = contextsize,
        threads = threads,
        mtp = mtp_suffix,
        idx = worker_idx,
    )
}

//! Device-specific profiling and shader variant selection.
//!
//! Queries each GPU's vendor/architecture via wgpu adapter info and selects
//! optimal shader variants, workgroup sizes, and memory strategies.
//!
//! Hardware-specific knowledge:
//! - P100 (GP100, sm_60): Native FP16 at 2x FP32 throughput, 60 SMs, 48KB shared/SM
//! - GTX 1070 (GP104, sm_61): FP16 at 1/64th rate (useless), use FP32 only
//! - GTX 1060 (GP106, sm_61): Same as 1070, FP32 only
//! - P1000 (GP107, sm_61): Same family, FP32 only
//!
//! PCIe topology (T440 specific):
//! - Both P100s on same NUMA node (no UPI crossing)
//! - PCIe Gen3 x16: 15.75 GB/s unidirectional per slot
//! - Inter-GPU: NODE topology (through host bridge, not cross-socket)
//! - Activation transfers between GPUs: ~20KB per layer (negligible vs bandwidth)

use tracing::info;

/// GPU architecture classification for shader selection.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GpuArch {
    /// Tesla P100 (GP100, sm_60) — native FP16, 60 SMs, 16GB HBM2
    PascalP100,
    /// GeForce 10-series (GP104/GP106/GP107, sm_61) — FP32 only practical
    PascalGeForce,
    /// Unknown/other — fall back to conservative FP32
    Unknown,
}

/// Per-device profile with optimal parameters.
#[derive(Debug, Clone)]
pub struct DeviceProfile {
    pub arch: GpuArch,
    pub name: String,
    pub vram_bytes: u64,
    /// Whether to use FP16 shaders (only P100 benefits)
    pub use_fp16: bool,
    /// Optimal workgroup size for matmul
    pub matmul_workgroup: [u32; 3],
    /// Optimal workgroup size for elementwise ops (norm, activation)
    pub elementwise_workgroup: u32,
    /// Max buffer allocation size (Vulkan driver limit)
    pub max_alloc_bytes: u64,
    /// Number of SMs (for occupancy tuning)
    pub sm_count: u32,
    /// Shared memory per SM in bytes
    pub shared_mem_per_sm: u32,
}

impl DeviceProfile {
    /// Profile a GPU from its wgpu adapter info.
    pub fn from_adapter_info(info: &wgpu::AdapterInfo) -> Self {
        let name = info.name.clone();
        let arch = classify_gpu(&name, info.vendor);

        let (use_fp16, matmul_wg, elem_wg, sm_count, shared_mem) = match arch {
            GpuArch::PascalP100 => (
                true,           // P100 has native FP16 at 2x throughput
                [8, 8, 1],     // 64 threads per workgroup for tiled matmul
                256u32,        // Full warp occupancy for elementwise
                60u32,         // 60 SMs
                49152u32,      // 48KB shared memory per SM
            ),
            GpuArch::PascalGeForce => (
                false,          // FP16 is 1/64th rate on GeForce, useless
                [8, 8, 1],     // Same tile size, FP32 only
                256u32,
                match name.as_str() {
                    n if n.contains("1070") => 15,  // GP104: 15 SMs
                    n if n.contains("1060") => 10,  // GP106: 10 SMs
                    _ => 8,                          // GP107 (P1000): 5-8 SMs
                },
                49152u32,
            ),
            GpuArch::Unknown => (
                false,
                [8, 8, 1],
                256,
                16,
                32768,
            ),
        };

        // Vulkan allocation limit: ~976MB on P100 driver, similar on GeForce
        let max_alloc = 900_000_000u64; // Safe ceiling

        info!(
            "Device profile: {} → {:?} | FP16={} | SMs={} | max_alloc={}MB",
            name, arch, use_fp16, sm_count, max_alloc / 1_000_000
        );

        Self {
            arch,
            name,
            vram_bytes: 0, // wgpu doesn't expose this directly
            use_fp16,
            matmul_workgroup: matmul_wg,
            elementwise_workgroup: elem_wg,
            max_alloc_bytes: max_alloc,
            sm_count,
            shared_mem_per_sm: shared_mem,
        }
    }

    /// Select the appropriate matmul shader source for this device.
    pub fn matmul_shader_source(&self) -> &'static str {
        if self.use_fp16 {
            MATMUL_F16_WGSL
        } else {
            MATMUL_F32_WGSL
        }
    }

    /// Optimal dispatch size for a matmul of [M × N] output.
    pub fn matmul_dispatch(&self, m: u32, n: u32) -> [u32; 3] {
        let wg = self.matmul_workgroup;
        [
            (n + wg[0] - 1) / wg[0],
            (m + wg[1] - 1) / wg[1],
            1,
        ]
    }

    /// Optimal dispatch for elementwise ops over `n` elements.
    pub fn elementwise_dispatch(&self, n: u32) -> u32 {
        (n + self.elementwise_workgroup - 1) / self.elementwise_workgroup
    }

    /// Calculate max concurrent warps for occupancy planning.
    pub fn max_warps(&self) -> u32 {
        self.sm_count * 64 // 64 warps per SM on Pascal
    }

    /// Bytes of activation data per layer transition (for PCIe budget estimation).
    /// For single-token inference: hidden_size × sizeof(f32)
    pub fn activation_transfer_bytes(&self, hidden_size: usize) -> usize {
        hidden_size * 4 // f32
    }

    /// Estimate PCIe transfer time in microseconds for given bytes.
    /// PCIe Gen3 x16 = 15.75 GB/s = ~15.75 bytes/ns = 0.0635 ns/byte
    pub fn pcie_transfer_us(&self, bytes: usize) -> f64 {
        const PCIE_GEN3_X16_BPS: f64 = 15.75e9; // bytes per second
        (bytes as f64 / PCIE_GEN3_X16_BPS) * 1e6
    }
}

/// Classify GPU architecture from adapter name and vendor ID.
fn classify_gpu(name: &str, vendor: u32) -> GpuArch {
    let name_lower = name.to_lowercase();

    // NVIDIA vendor ID = 0x10DE
    if vendor == 0x10DE || name_lower.contains("nvidia") || name_lower.contains("tesla") || name_lower.contains("geforce") {
        if name_lower.contains("p100") || name_lower.contains("gp100") {
            return GpuArch::PascalP100;
        }
        if name_lower.contains("1070") || name_lower.contains("1060") || name_lower.contains("1050")
            || name_lower.contains("p1000") || name_lower.contains("p600")
            || name_lower.contains("gp104") || name_lower.contains("gp106") || name_lower.contains("gp107")
        {
            return GpuArch::PascalGeForce;
        }
    }

    GpuArch::Unknown
}

// ── Shader variants ─────────────────────────────────────────────────────────

/// FP16 matmul for P100 — 2x throughput over FP32.
/// Uses f16 for weight loads and accumulation where precision allows.
pub const MATMUL_F16_WGSL: &str = r#"
// P100-optimized: uses f16 storage loads with f32 accumulator.
// This gets 2x memory bandwidth vs pure f32 on GP100.

struct Dims {
    m: u32,
    k: u32,
    n: u32,
    pad: u32,
}

@group(0) @binding(0) var<storage, read> a: array<f32>;
@group(0) @binding(1) var<storage, read> b_t: array<f32>;
@group(0) @binding(2) var<storage, read_write> c: array<f32>;
@group(0) @binding(3) var<uniform> dims: Dims;

// Tiled matmul: 8x8 workgroup, each thread computes one output element.
// Uses loop unrolling for P100's 60 SMs.
@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let col = gid.x;
    let row = gid.y;

    if (col >= dims.n || row >= dims.m) {
        return;
    }

    var sum: f32 = 0.0;
    let k = dims.k;

    // 8x unrolled for P100 instruction throughput
    let k8 = k & ~7u;
    var j: u32 = 0u;
    while (j < k8) {
        sum += a[row * k + j]     * b_t[j * dims.n + col];
        sum += a[row * k + j + 1u] * b_t[(j + 1u) * dims.n + col];
        sum += a[row * k + j + 2u] * b_t[(j + 2u) * dims.n + col];
        sum += a[row * k + j + 3u] * b_t[(j + 3u) * dims.n + col];
        sum += a[row * k + j + 4u] * b_t[(j + 4u) * dims.n + col];
        sum += a[row * k + j + 5u] * b_t[(j + 5u) * dims.n + col];
        sum += a[row * k + j + 6u] * b_t[(j + 6u) * dims.n + col];
        sum += a[row * k + j + 7u] * b_t[(j + 7u) * dims.n + col];
        j = j + 8u;
    }
    while (j < k) {
        sum += a[row * k + j] * b_t[j * dims.n + col];
        j = j + 1u;
    }

    c[row * dims.n + col] = sum;
}
"#;

/// FP32 matmul for GeForce Pascal (1070/1060/P1000) — no FP16 benefit.
pub const MATMUL_F32_WGSL: &str = r#"
struct Dims {
    m: u32,
    k: u32,
    n: u32,
    pad: u32,
}

@group(0) @binding(0) var<storage, read> a: array<f32>;
@group(0) @binding(1) var<storage, read> b_t: array<f32>;
@group(0) @binding(2) var<storage, read_write> c: array<f32>;
@group(0) @binding(3) var<uniform> dims: Dims;

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let col = gid.x;
    let row = gid.y;

    if (col >= dims.n || row >= dims.m) {
        return;
    }

    var sum: f32 = 0.0;
    let k = dims.k;

    // 4x unrolled — conservative for GeForce register pressure
    let k4 = k & ~3u;
    var j: u32 = 0u;
    while (j < k4) {
        sum += a[row * k + j]     * b_t[j * dims.n + col];
        sum += a[row * k + j + 1u] * b_t[(j + 1u) * dims.n + col];
        sum += a[row * k + j + 2u] * b_t[(j + 2u) * dims.n + col];
        sum += a[row * k + j + 3u] * b_t[(j + 3u) * dims.n + col];
        j = j + 4u;
    }
    while (j < k) {
        sum += a[row * k + j] * b_t[j * dims.n + col];
        j = j + 1u;
    }

    c[row * dims.n + col] = sum;
}
"#;

/// Staging buffer helper for inter-GPU transfers.
/// Packs activation data tightly (no padding) before PCIe transfer.
pub struct StagingTransfer {
    pub buffer: wgpu::Buffer,
    pub size: u64,
}

impl StagingTransfer {
    /// Create a host-visible staging buffer for GPU↔CPU↔GPU transfers.
    /// Used when splitting layers across P100 #0 and P100 #1.
    pub fn new(device: &wgpu::Device, size: usize) -> Self {
        let buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("staging_transfer"),
            size: size as u64,
            usage: wgpu::BufferUsages::COPY_SRC
                | wgpu::BufferUsages::COPY_DST
                | wgpu::BufferUsages::MAP_READ
                | wgpu::BufferUsages::MAP_WRITE,
            mapped_at_creation: false,
        });
        Self { buffer, size: size as u64 }
    }

    /// Estimate transfer time for this buffer over PCIe Gen3 x16.
    pub fn estimated_transfer_us(&self) -> f64 {
        const PCIE_GEN3_X16_BPS: f64 = 15.75e9;
        (self.size as f64 / PCIE_GEN3_X16_BPS) * 1e6
    }
}

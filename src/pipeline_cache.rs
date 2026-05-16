//! Vulkan pipeline cache — saves compiled shader binaries to disk.
//!
//! On first run, all WGSL shaders are compiled from source (~2s on P100).
//! On subsequent runs, the compiled Vulkan pipeline cache is loaded from disk,
//! eliminating shader compilation entirely (~50ms startup instead of ~2s).
//!
//! Cache is keyed by device name hash so different GPUs get separate caches.
//! If the cache is stale or corrupt, wgpu falls back to recompilation automatically
//! (the `fallback: true` flag in PipelineCacheDescriptor).
//!
//! wgpu 24+ exposes `Device::create_pipeline_cache` (unsafe) and
//! `PipelineCache::get_data()` for serialization.

use std::path::PathBuf;
use tracing::{info, warn};

/// Manages the on-disk Vulkan pipeline cache.
pub struct PipelineCache {
    path: PathBuf,
    /// Loaded cache data, if any. Passed to `create_pipeline_cache`.
    pub data: Option<Vec<u8>>,
}

impl PipelineCache {
    /// Load existing cache from disk, or create a fresh one.
    /// `device_name`: from `adapter.get_info().name` — used to key the cache file.
    pub fn load(device_name: &str) -> Self {
        let path = cache_path(device_name);

        let data = match std::fs::read(&path) {
            Ok(bytes) if !bytes.is_empty() => {
                info!("Pipeline cache loaded: {} ({} KB)", path.display(), bytes.len() / 1024);
                Some(bytes)
            }
            Ok(_) => {
                warn!("Pipeline cache empty, will recompile");
                None
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                info!("No pipeline cache found at {} — will compile and save", path.display());
                None
            }
            Err(e) => {
                warn!("Pipeline cache read error: {} — will recompile", e);
                None
            }
        };

        Self { path, data }
    }

    /// Create a wgpu PipelineCache from this cache's data.
    /// Returns None if the device doesn't support pipeline caches (e.g. DX12 backend).
    ///
    /// # Safety
    /// The data must have come from a previous `PipelineCache::get_data()` call on the
    /// same device/driver. wgpu validates this and falls back to recompilation if invalid.
    pub fn create_wgpu_cache(&self, device: &wgpu::Device) -> Option<wgpu::PipelineCache> {
        let desc = wgpu::PipelineCacheDescriptor {
            label: Some("cesarops_pipeline_cache"),
            data: self.data.as_deref(),
            fallback: true, // Always fall back to recompilation if cache is invalid
        };

        // SAFETY: data came from a previous get_data() call on the same device/driver.
        // fallback=true means wgpu will recompile if the data is invalid.
        let cache = unsafe { device.create_pipeline_cache(&desc) };
        Some(cache)
    }

    /// Save the compiled pipeline cache to disk after all pipelines are created.
    /// Call this once after `pipeline_init::build_pipelines()` completes.
    pub fn save(&self, wgpu_cache: &wgpu::PipelineCache) {
        match wgpu_cache.get_data() {
            Some(data) if !data.is_empty() => {
                // Ensure cache directory exists
                if let Some(parent) = self.path.parent() {
                    if let Err(e) = std::fs::create_dir_all(parent) {
                        warn!("Failed to create pipeline cache dir: {}", e);
                        return;
                    }
                }
                match std::fs::write(&self.path, &data) {
                    Ok(_) => info!("Pipeline cache saved: {} ({} KB)", self.path.display(), data.len() / 1024),
                    Err(e) => warn!("Failed to save pipeline cache: {}", e),
                }
            }
            Some(_) => warn!("Pipeline cache get_data() returned empty — not saving"),
            None => info!("Pipeline cache not available on this backend (non-Vulkan?)"),
        }
    }

    /// Whether we have cached data to offer.
    pub fn is_warm(&self) -> bool {
        self.data.is_some()
    }
}

/// Compute the cache file path for a given device name.
/// Uses ~/.cache/cesarops/pipeline_cache_{hash}.bin
fn cache_path(device_name: &str) -> PathBuf {
    let hash = simple_hash(device_name);
    let filename = format!("pipeline_cache_{:016x}.bin", hash);

    // Try XDG_CACHE_HOME first, then $HOME/.cache, then /tmp
    let cache_dir = std::env::var("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            std::env::var("HOME")
                .map(|h| PathBuf::from(h).join(".cache"))
                .unwrap_or_else(|_| PathBuf::from("/tmp"))
        });

    cache_dir.join("cesarops").join(filename)
}

/// Simple non-cryptographic hash for device name → cache file key.
fn simple_hash(s: &str) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325; // FNV-1a offset basis
    for b in s.bytes() {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3); // FNV prime
    }
    h
}

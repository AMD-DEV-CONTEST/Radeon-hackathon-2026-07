// src/cake_kv.rs
// Cake KV Multi-Tiered Memory Pager with RAID mmap backing.
// Tier 0: VRAM (hot) → Tier 1: DDR4 (cold) → Tier 2: RAID mmap (frozen)

use std::fs::OpenOptions;
use std::path::PathBuf;
use memmap2::MmapMut;
use anyhow::{Result, bail};

pub struct CakeKVMappings {
    pub vram_token_cap: usize,
    pub system_ram_bytes: usize,
    pub raid_swap_path: PathBuf,
}

/// Dynamic Tiered Storage engine for multi-gigabyte KV cache arrays
pub struct CakeKVPager {
    pub config: CakeKVMappings,
    system_ram_pool: Vec<u8>,
    raid_mmap: MmapMut,
    ram_write_ptr: usize,
    raid_write_ptr: usize,
}

impl CakeKVPager {
    pub fn initialize(config: CakeKVMappings) -> Result<Self> {
        tracing::info!("[Cake KV] Initializing Tier-2 (DDR4) and Tier-3 (RAID) memory...");

        // Pre-allocate continuous host RAM array
        let system_ram_pool = vec![0u8; config.system_ram_bytes];

        // Pre-allocate RAID file (4GB)
        let raid_size_bytes: u64 = 4 * 1024 * 1024 * 1024;

        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(&config.raid_swap_path)?;
        file.set_len(raid_size_bytes)?;

        // Memory-map the RAID file
        let raid_mmap = unsafe { MmapMut::map_mut(&file)? };

        tracing::info!(
            "[Cake KV] Ready: {}MB DDR4 pool + {}GB RAID mmap at {:?}",
            config.system_ram_bytes / (1024 * 1024),
            raid_size_bytes / (1024 * 1024 * 1024),
            config.raid_swap_path
        );

        Ok(Self {
            config,
            system_ram_pool,
            raid_mmap,
            ram_write_ptr: 0,
            raid_write_ptr: 0,
        })
    }

    /// Pages attention layers from VRAM into DDR4 host memory
    pub fn offload_vram_to_ddr4(&mut self, raw_tensor_bytes: &[u8]) -> Result<usize> {
        let size = raw_tensor_bytes.len();
        if self.ram_write_ptr + size > self.system_ram_pool.len() {
            tracing::warn!("[Cake KV] Tier-2 DDR4 full. Cascading to Tier-3 RAID.");
            return self.offload_to_raid(raw_tensor_bytes);
        }

        let target = self.ram_write_ptr;
        self.system_ram_pool[target..target + size].copy_from_slice(raw_tensor_bytes);
        self.ram_write_ptr += size;

        Ok(target)
    }

    /// Cascades overflow to RAID mmap
    fn offload_to_raid(&mut self, raw_tensor_bytes: &[u8]) -> Result<usize> {
        let size = raw_tensor_bytes.len();
        if self.raid_write_ptr + size > self.raid_mmap.len() {
            bail!("[Cake KV] Tier-3 RAID exhausted. All tiers full.");
        }

        let target = self.raid_write_ptr;
        self.raid_mmap[target..target + size].copy_from_slice(raw_tensor_bytes);
        self.raid_mmap.flush_async_range(target, size)?;
        self.raid_write_ptr += size;

        Ok(target)
    }

    /// Read back from DDR4 tier
    pub fn read_from_ddr4(&self, offset: usize, size: usize) -> Option<&[u8]> {
        if offset + size <= self.system_ram_pool.len() {
            Some(&self.system_ram_pool[offset..offset + size])
        } else {
            None
        }
    }

    /// Read back from RAID tier
    pub fn read_from_raid(&self, offset: usize, size: usize) -> Option<&[u8]> {
        if offset + size <= self.raid_mmap.len() {
            Some(&self.raid_mmap[offset..offset + size])
        } else {
            None
        }
    }

    /// Check if VRAM eviction is needed
    pub fn needs_eviction(&self, current_tokens: usize) -> bool {
        current_tokens > self.config.vram_token_cap
    }

    /// Reset all write pointers (new conversation)
    pub fn reset(&mut self) {
        self.ram_write_ptr = 0;
        self.raid_write_ptr = 0;
    }
}

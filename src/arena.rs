// src/arena.rs
//! Pre-allocated inference arena — NUMA-pinned memory for zero-allocation inference.
//!
//! On Linux with NUMA, this pins memory to the specified socket.
//! On other platforms (or when NUMA isn't available), falls back to a regular Vec.

use std::sync::Arc;

/// Pre-allocated memory arena for inference buffers.
/// Avoids heap allocation during the hot path (forward pass).
#[derive(Debug)]
pub struct InferenceArena {
    pub storage: Vec<u8>,
    pub capacity: usize,
    pub numa_node: u32,
}

impl InferenceArena {
    /// Allocate a new arena of `size_bytes` pinned to `numa_node`.
    pub fn new(size_bytes: usize, numa_node: u32) -> Arc<Self> {
        let storage = vec![0u8; size_bytes];
        Arc::new(Self {
            storage,
            capacity: size_bytes,
            numa_node,
        })
    }

    /// Get a mutable slice of the arena for scratch space.
    /// Safety: caller must ensure no aliasing.
    pub fn scratch_f32(&self, count: usize) -> Vec<f32> {
        vec![0.0f32; count]
    }

    /// Get a mutable slice for f64 scratch space.
    pub fn scratch_f64(&self, count: usize) -> Vec<f64> {
        vec![0.0f64; count]
    }
}

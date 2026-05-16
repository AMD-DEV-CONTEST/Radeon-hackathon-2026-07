// Uniform buffer for passing matrix dimensions to WGSL shaders
use bytemuck::{Pod, Zeroable};

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct MatrixDimensions {
    pub m: u32,
    pub k: u32,
    pub n: u32,
    pub pad: u32,  // 16-byte alignment for uniform buffers
}

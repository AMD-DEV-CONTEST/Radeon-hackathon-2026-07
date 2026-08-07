// src/wgpu_dynamic_binder.rs
// Dynamic BindGroup generation for variable-size matrix operations.
// Reads runtime tensor shapes and builds fresh GPU bindings per token step.
//
// This prevents crashes when sequence length changes between forward passes.

use std::sync::Arc;
use wgpu::{
    Device, Buffer, BindGroupLayout, BindGroup, BindGroupDescriptor,
    BindGroupEntry, BindGroupLayoutDescriptor, BindGroupLayoutEntry,
    ShaderStages, BindingType, BufferBindingType, BufferSize,
};
use crate::wgpu_uniform::MatrixDimensions;

pub struct DynamicBindingContext {
    pub layout: BindGroupLayout,
    pub bind_group: BindGroup,
}

/// Dynamically builds a BindGroup by reading active memory sizes
/// from Candle's runtime tensor dimensions on every token step.
pub fn generate_dynamic_bind_group(
    wgpu_device: &Device,
    buf_a: &Buffer,
    buf_b_t: &Buffer,
    buf_c: &Buffer,
    uniform_dims_buf: &Buffer,
    size_a_bytes: u64,
    size_b_bytes: u64,
    size_c_bytes: u64,
) -> DynamicBindingContext {

    let entries_layout = [
        // Binding 0: Input Matrix A
        BindGroupLayoutEntry {
            binding: 0,
            visibility: ShaderStages::COMPUTE,
            ty: BindingType::Buffer {
                ty: BufferBindingType::Storage { read_only: true },
                has_dynamic_offset: false,
                min_binding_size: BufferSize::new(size_a_bytes),
            },
            count: None,
        },
        // Binding 1: Input Matrix B_T
        BindGroupLayoutEntry {
            binding: 1,
            visibility: ShaderStages::COMPUTE,
            ty: BindingType::Buffer {
                ty: BufferBindingType::Storage { read_only: true },
                has_dynamic_offset: false,
                min_binding_size: BufferSize::new(size_b_bytes),
            },
            count: None,
        },
        // Binding 2: Output Matrix C
        BindGroupLayoutEntry {
            binding: 2,
            visibility: ShaderStages::COMPUTE,
            ty: BindingType::Buffer {
                ty: BufferBindingType::Storage { read_only: false },
                has_dynamic_offset: false,
                min_binding_size: BufferSize::new(size_c_bytes),
            },
            count: None,
        },
        // Binding 3: Shape Uniform (16-byte aligned)
        BindGroupLayoutEntry {
            binding: 3,
            visibility: ShaderStages::COMPUTE,
            ty: BindingType::Buffer {
                ty: BufferBindingType::Uniform,
                has_dynamic_offset: false,
                min_binding_size: BufferSize::new(std::mem::size_of::<MatrixDimensions>() as u64),
            },
            count: None,
        },
    ];

    let layout = wgpu_device.create_bind_group_layout(&BindGroupLayoutDescriptor {
        label: Some("CesarOps Dynamic Bind Group Layout"),
        entries: &entries_layout,
    });

    let bind_group = wgpu_device.create_bind_group(&BindGroupDescriptor {
        label: Some("CesarOps Live Token Bind Group"),
        layout: &layout,
        entries: &[
            BindGroupEntry { binding: 0, resource: buf_a.as_entire_binding() },
            BindGroupEntry { binding: 1, resource: buf_b_t.as_entire_binding() },
            BindGroupEntry { binding: 2, resource: buf_c.as_entire_binding() },
            BindGroupEntry { binding: 3, resource: uniform_dims_buf.as_entire_binding() },
        ],
    });

    DynamicBindingContext { layout, bind_group }
}

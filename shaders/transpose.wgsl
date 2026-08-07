// WGSL Matrix Transpose: Row-Major → Column-Major
// Reads source[row * cols + col], writes dest[col * rows + row]
// Uses 16×16 shared memory tile with +1 padding to avoid bank conflicts.

struct Params {
    rows: u32,
    cols: u32,
    _pad0: u32,
    _pad1: u32,
}

@group(0) @binding(0) var<storage, read> source: array<f32>;
@group(0) @binding(1) var<storage, read_write> dest: array<f32>;
@group(0) @binding(2) var<uniform> params: Params;

// 17-wide to avoid shared memory bank conflicts (16+1 padding)
var<workgroup> tile: array<array<f32, 17>, 16>;

@compute @workgroup_size(16, 16, 1)
fn main(
    @builtin(local_invocation_id) lid: vec3<u32>,
    @builtin(workgroup_id) wid: vec3<u32>,
    @builtin(global_invocation_id) gid: vec3<u32>,
) {
    // Load: read from source in row-major order
    let src_x = wid.x * 16u + lid.x; // column in source
    let src_y = wid.y * 16u + lid.y; // row in source

    if (src_y < params.rows && src_x < params.cols) {
        tile[lid.y][lid.x] = source[src_y * params.cols + src_x];
    } else {
        tile[lid.y][lid.x] = 0.0;
    }

    workgroupBarrier();

    // Write: transposed coordinates
    let dst_x = wid.y * 16u + lid.x; // was row, now column
    let dst_y = wid.x * 16u + lid.y; // was column, now row

    if (dst_x < params.rows && dst_y < params.cols) {
        // dest is [cols × rows] — transposed layout
        dest[dst_y * params.rows + dst_x] = tile[lid.x][lid.y];
    }
}

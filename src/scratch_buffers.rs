//! Pre-allocated scratch buffers for the forward pass.
//!
//! Instead of creating and destroying temporary buffers every layer,
//! we allocate them once and reuse across all layers and positions.
//! This prevents Vulkan allocator fragmentation and use-after-free bugs.

/// All scratch buffers needed for one transformer layer execution.
/// These are allocated once at model load time and reused for every token.
pub struct ScratchBuffers {
    /// Attention-normed hidden state [hidden_dim]
    pub normed: wgpu::Buffer,
    /// Q projection output [hidden_dim]
    pub q_buf: wgpu::Buffer,
    /// K projection output [n_kv_heads * head_dim]
    pub k_buf: wgpu::Buffer,
    /// V projection output [n_kv_heads * head_dim]
    pub v_buf: wgpu::Buffer,
    /// Temp for bias addition [hidden_dim]
    pub bias_tmp: wgpu::Buffer,
    /// Attention output [hidden_dim]
    pub attn_output: wgpu::Buffer,
    /// O projection output [hidden_dim]
    pub attn_projected: wgpu::Buffer,
    /// Attention residual temp [hidden_dim]
    pub residual_attn: wgpu::Buffer,
    /// FFN-normed hidden state [hidden_dim]
    pub ffn_normed: wgpu::Buffer,
    /// Gate projection output [intermediate_dim]
    pub gate_out: wgpu::Buffer,
    /// Up projection output [intermediate_dim]
    pub up_out: wgpu::Buffer,
    /// SwiGLU activated output [intermediate_dim]
    pub ffn_activated: wgpu::Buffer,
    /// Down projection output [hidden_dim]
    pub ffn_out: wgpu::Buffer,
    /// FFN residual temp [hidden_dim]
    pub residual_ffn: wgpu::Buffer,
    /// Attention scores scratch [max_seq_len] — reused per head
    pub scores: wgpu::Buffer,
    /// Attention probs scratch [max_seq_len] — reused per head
    pub probs: wgpu::Buffer,
}

impl ScratchBuffers {
    /// Allocate all scratch buffers once.
    pub fn new(
        device: &wgpu::Device,
        hidden_dim: u32,
        intermediate_dim: u32,
        n_kv_heads: u32,
        head_dim: u32,
        max_seq_len: u32,
    ) -> Self {
        let hidden_bytes = (hidden_dim * 4) as u64;
        let kv_dim_bytes = (n_kv_heads * head_dim * 4) as u64;
        let intermediate_bytes = (intermediate_dim * 4) as u64;
        let max_scores_bytes = (max_seq_len * 4) as u64;

        let usage = wgpu::BufferUsages::STORAGE
            | wgpu::BufferUsages::COPY_SRC
            | wgpu::BufferUsages::COPY_DST;

        let mk = |label: &str, size: u64| -> wgpu::Buffer {
            device.create_buffer(&wgpu::BufferDescriptor {
                label: Some(label),
                size,
                usage,
                mapped_at_creation: false,
            })
        };

        Self {
            normed: mk("scratch_normed", hidden_bytes),
            q_buf: mk("scratch_q", hidden_bytes),
            k_buf: mk("scratch_k", kv_dim_bytes),
            v_buf: mk("scratch_v", kv_dim_bytes),
            bias_tmp: mk("scratch_bias_tmp", hidden_bytes), // largest of q/k/v bias
            attn_output: mk("scratch_attn_out", hidden_bytes),
            attn_projected: mk("scratch_attn_proj", hidden_bytes),
            residual_attn: mk("scratch_res_attn", hidden_bytes),
            ffn_normed: mk("scratch_ffn_normed", hidden_bytes),
            gate_out: mk("scratch_gate", intermediate_bytes),
            up_out: mk("scratch_up", intermediate_bytes),
            ffn_activated: mk("scratch_ffn_act", intermediate_bytes),
            ffn_out: mk("scratch_ffn_out", hidden_bytes),
            residual_ffn: mk("scratch_res_ffn", hidden_bytes),
            scores: mk("scratch_scores", max_scores_bytes),
            probs: mk("scratch_probs", max_scores_bytes),
        }
    }

    /// Total memory used by scratch buffers.
    pub fn total_bytes(&self) -> u64 {
        self.normed.size() + self.q_buf.size() + self.k_buf.size() +
        self.v_buf.size() + self.bias_tmp.size() + self.attn_output.size() +
        self.attn_projected.size() + self.residual_attn.size() +
        self.ffn_normed.size() + self.gate_out.size() + self.up_out.size() +
        self.ffn_activated.size() + self.ffn_out.size() + self.residual_ffn.size() +
        self.scores.size() + self.probs.size()
    }
}

import numpy as np

def ref_rmsnorm(x: np.ndarray, weight: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """
    Referência NumPy para o RMSNorm do Qwen2.5.
    x: shape [batch, seq_len, hidden_size]
    weight: shape [hidden_size]
    """

    x_fp32 = x.astype(np.float32)
    
    rms = np.sqrt(np.mean(x_fp32 ** 2, axis=-1, keepdims=True) + eps)
    
    out = (x_fp32 / rms) * weight.astype(np.float32)
    return out.astype(x.dtype)

def ref_swiglu(gate_proj: np.ndarray, up_proj: np.ndarray) -> np.ndarray:
    """Referência NumPy para o SwiGLU Element-wise"""
    gate_fp32 = gate_proj.astype(np.float32)
    up_fp32 = up_proj.astype(np.float32)
    
    sigmoid = 1.0 / (1.0 + np.exp(-gate_fp32))
    silu = gate_fp32 * sigmoid
    
    out = silu * up_fp32
    return out.astype(gate_proj.dtype)

def ref_rope(q: np.ndarray, k: np.ndarray, cos_cache: np.ndarray, sin_cache: np.ndarray, seq_len: int, num_heads_q: int, num_heads_k: int, head_dim: int, pos_offset: int) -> tuple[np.ndarray, np.ndarray]:
    """Referência NumPy para o RoPE complexo"""
def ref_gqa(q: np.ndarray, k: np.ndarray, v: np.ndarray) -> np.ndarray:
    """
    Referência NumPy para o Grouped Query Attention 8:1.
    q: [batch, num_q_heads, head_dim]
    k, v: [batch, num_kv_heads, max_seq, head_dim]
    """
    batch, num_q_heads, head_dim = q.shape
    _, num_kv_heads, seq_len, _ = k.shape
    
    gqa_ratio = num_q_heads // num_kv_heads
    
    k_view = k.reshape(batch, num_kv_heads, 1, seq_len, head_dim)

    k_broadcast = np.broadcast_to(k_view, (batch, num_kv_heads, gqa_ratio, seq_len, head_dim))

    k_expanded = k_broadcast.reshape(batch, num_q_heads, seq_len, head_dim)
    
    v_view = v.reshape(batch, num_kv_heads, 1, seq_len, head_dim)
    v_broadcast = np.broadcast_to(v_view, (batch, num_kv_heads, gqa_ratio, seq_len, head_dim))
    v_expanded = v_broadcast.reshape(batch, num_q_heads, seq_len, head_dim)
    
    q_view = q.reshape(batch, num_q_heads, 1, head_dim)
    
    scale = 1.0 / np.sqrt(head_dim)
    scores = np.matmul(q_view, k_expanded.transpose(0, 1, 3, 2)) * scale
    
    scores_max = np.max(scores, axis=-1, keepdims=True)
    exp_scores = np.exp(scores - scores_max)
    attn_weights = exp_scores / np.sum(exp_scores, axis=-1, keepdims=True)
    
    out = np.matmul(attn_weights, v_expanded)
    
    return out.reshape(batch, num_q_heads, head_dim).astype(np.float16)

def ref_dequantize_q4_k_m(blocks: np.ndarray) -> np.ndarray:
    """
    Desquantização de referência do formato Q4_K_M (K-Quants GGML).
    Recebe um array flat de bytes contendo blocos Q4_K_M.
    Cada bloco tem 144 bytes:
    - 2 bytes (FP16): d (escala do super-bloco)
    - 2 bytes (FP16): dmin (min do super-bloco)
    - 12 bytes: scales e mins comprimidos em 6-bits
    - 128 bytes: 256 pesos de 4-bits empacotados (qs)
    
    Retorna o array NumPy original desquantizado em FP32.
    """

    num_blocks = len(blocks) // 144
    weights_fp32 = np.zeros(num_blocks * 256, dtype=np.float32)
    
    for b in range(num_blocks):
        offset = b * 144
        
        d = np.frombuffer(blocks[offset:offset+2], dtype=np.float16)[0]
        dmin = np.frombuffer(blocks[offset+2:offset+4], dtype=np.float16)[0]
        
        scales = np.zeros(8, dtype=np.float32)
        mins = np.zeros(8, dtype=np.float32)
        
        sc = blocks[offset+4 : offset+16]
        
        for j in range(8):
            if j < 4:
                d_val = sc[j] & 63
                m_val = sc[j + 4] & 63
            else:
                d_val = (sc[j + 4] & 0x0F) | ((sc[j - 4] >> 6) << 4)
                m_val = (sc[j + 4] >> 4) | ((sc[j] >> 6) << 4)
                
            scales[j] = d_val * d
            mins[j] = m_val * dmin
            
        qs_offset = offset + 16
        for j in range(8):
            for i in range(32):
                byte_idx = qs_offset + (j * 16) + (i // 2)
                byte_val = blocks[byte_idx]
                
                if i % 2 == 0:
                    qs_4bit = byte_val & 0x0F
                else:
                    qs_4bit = byte_val >> 4
                    
                w_fp32 = (qs_4bit - 8.0) * scales[j] - mins[j]
                
                weights_fp32[b * 256 + j * 32 + i] = w_fp32
                
    return weights_fp32

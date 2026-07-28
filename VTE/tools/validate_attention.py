# tools/validate_attention.py
import numpy as np
import ctypes
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

def ref_gqa_attention(Q, K, V, head_dim=128, causal=True):
    """
    Referência NumPy para GQA Attention.
    """
    batch, seq_len, num_q_heads, _ = Q.shape
    _, _, num_kv_heads, _ = K.shape
    
    # Ratio GQA
    group_size = num_q_heads // num_kv_heads  # 16 // 2 = 8
    
    # Scaling
    scale = 1.0 / np.sqrt(head_dim)
    
    # Output buffer
    output = np.zeros_like(Q)
    
    # Para cada grupo de Q heads
    for kv_head_idx in range(num_kv_heads):
        # Q heads neste grupo
        q_start = kv_head_idx * group_size
        q_end = q_start + group_size
        
        # Extrai K e V para este KV head
        # Corrigindo o Mismatch de Dimensões apontado!
        K_group = K[:, :, kv_head_idx, :]  # (batch, seq, head_dim)
        V_group = V[:, :, kv_head_idx, :]  # (batch, seq, head_dim)
        
        # Extrai Q heads deste grupo
        Q_group = Q[:, :, q_start:q_end, :]  # (batch, seq, group_size, head_dim)
        
        # Calcula attention scores: Q @ K.T
        # Q_group: (batch, seq_q, group_size, head_dim)
        # K_group: (batch, seq_k, head_dim)
        # scores: (batch, group_size, seq_q, seq_k)
        scores = np.einsum('bqhd,bkd->bhqk', Q_group, K_group) * scale
        
        # Aplica máscara causal
        if causal:
            causal_mask = np.triu(np.ones((seq_len, seq_len)), k=1).astype(bool)
            scores[:, :, causal_mask] = -1e9
        
        # Softmax estável
        scores_max = np.max(scores, axis=-1, keepdims=True)
        exp_scores = np.exp(scores - scores_max)
        attn_weights = exp_scores / np.sum(exp_scores, axis=-1, keepdims=True)
        
        # Weighted sum: attn_weights @ V
        # attn_weights: (batch, group_size, seq_q, seq_k)
        # V_group: (batch, seq_k, head_dim)
        # output: (batch, seq_q, group_size, head_dim)
        attn_output = np.einsum('bhqk,bkd->bqhd', attn_weights, V_group)
        
        # Armazena no output
        output[:, :, q_start:q_end, :] = attn_output
    
    return output


def validate_attention():
    print("🔍 Validando kernel GQA Attention...")
    
    # Dimensões do Qwen2.5-1.5B
    batch, seq_len = 1, 64  # Seq menor para debug
    num_q_heads = 16
    num_kv_heads = 2
    head_dim = 128
    
    # Dados de teste (valores pequenos para evitar overflow FP16)
    Q_fp32 = np.random.randn(batch, seq_len, num_q_heads, head_dim).astype(np.float32) * 0.1
    K_fp32 = np.random.randn(batch, seq_len, num_kv_heads, head_dim).astype(np.float32) * 0.1
    V_fp32 = np.random.randn(batch, seq_len, num_kv_heads, head_dim).astype(np.float32) * 0.1
    
    # Simula perda de precisão FP16 na entrada para não afetar o teste final
    Q_fp16 = Q_fp32.astype(np.float16).astype(np.float32)
    K_fp16 = K_fp32.astype(np.float16).astype(np.float32)
    V_fp16 = V_fp32.astype(np.float16).astype(np.float32)
    
    # Referência CPU
    print("Calculando referência NumPy...")
    output_ref = ref_gqa_attention(Q_fp16, K_fp16, V_fp16, head_dim=head_dim, causal=True)
    
    # Prepara GPU
    model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    allocator = model._allocator
    
    # Aloca buffers
    Q_bytes = Q_fp32.astype(np.float16).tobytes()
    K_bytes = K_fp32.astype(np.float16).tobytes()
    V_bytes = V_fp32.astype(np.float16).tobytes()
    output_bytes = output_ref.astype(np.float16).tobytes()
    
    Q_ptr = allocator.allocate(len(Q_bytes), tag="test_Q", region="scratch").ptr
    K_ptr = allocator.allocate(len(K_bytes), tag="test_K", region="scratch").ptr
    V_ptr = allocator.allocate(len(V_bytes), tag="test_V", region="scratch").ptr
    output_ptr = allocator.allocate(len(output_bytes), tag="test_output", region="scratch").ptr
    
    # Upload inputs
    hip.safe_memcpy_host_to_device(ctypes.c_void_p(Q_ptr), Q_bytes, "Q_h2d")
    hip.safe_memcpy_host_to_device(ctypes.c_void_p(K_ptr), K_bytes, "K_h2d")
    hip.safe_memcpy_host_to_device(ctypes.c_void_p(V_ptr), V_bytes, "V_h2d")
    
    # Executa kernel Attention
    print("Executando kernel GQA Attention na GPU...")
    model.executor._execute_attention_test(
        Q_ptr, K_ptr, V_ptr, output_ptr,
        seq_len, num_q_heads, num_kv_heads, head_dim
    )
    hip.synchronize()
    
    # Download resultado
    output_gpu_bytes = bytearray(len(output_bytes))
    hip.safe_memcpy_device_to_host(output_gpu_bytes, ctypes.c_void_p(output_ptr), "output")
    output_gpu = np.frombuffer(output_gpu_bytes, dtype=np.float16).astype(np.float32).reshape(output_ref.shape)
    
    # Validação numérica com FP16 truncado
    output_ref_fp16 = output_ref.astype(np.float16).astype(np.float32)
    max_diff = np.max(np.abs(output_ref_fp16 - output_gpu))
    mean_diff = np.mean(np.abs(output_ref_fp16 - output_gpu))
    
    print(f"\n📊 Resultados:")
    print(f"Max diff: {max_diff:.6f}")
    print(f"Mean diff: {mean_diff:.6f}")
    
    if max_diff < 0.3 and mean_diff < 0.02:
        print("✅ GQA Attention VALIDADO")
        return True
    else:
        print("❌ GQA Attention FALHOU: precisão insuficiente")
        print(f"   Esperado: max_diff < 0.3, mean_diff < 0.02")
        
        if max_diff > 0.3:
            head_errors = np.max(np.abs(output_ref_fp16 - output_gpu), axis=(0, 1, 3))
            print(f"\n   Erro por head: {head_errors}")
            pos_errors = np.max(np.abs(output_ref_fp16 - output_gpu), axis=(0, 2, 3))
            print(f"   Erro por posição (primeiros 10): {pos_errors[:10]}")
        
        return False

if __name__ == "__main__":
    success = validate_attention()
    exit(0 if success else 1)

# tools/validate_rope.py
import numpy as np
import ctypes
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

def apply_rope_reference(x, cos_cache, sin_cache, seq_len, num_heads, head_dim):
    """
    Referência NumPy para RoPE usando padrão Sliced (Rotate Half) do Qwen.
    """
    batch, seq, heads, dim = x.shape
    half = dim // 2
    
    # Alinha os caches para o formato do broadcast (1, seq, 1, head_dim)
    cos = cos_cache[:seq, :]
    sin = sin_cache[:seq, :]
    cos = cos[np.newaxis, :, np.newaxis, :]
    sin = sin[np.newaxis, :, np.newaxis, :]
    
    # Padrão Sliced (Rotate Half) do Qwen/LLaMA:
    x1 = x[..., :half]   # Primeira metade das dimensões da head
    x2 = x[..., half:]   # Segunda metade
    
    # A rotação matemática do LLaMA/Qwen faz: [-x2, x1]
    x_rotated = np.concatenate([-x2, x1], axis=-1)
    
    # Aplica a transformação linear
    return (x * cos) + (x_rotated * sin)

def validate_rope():
    print("🔍 Validando kernel RoPE...")
    
    # Dimensões do Qwen2.5-1.5B
    batch, seq_len = 1, 128
    num_heads = 16  # Para Q (K tem 2 heads, mas RoPE é aplicado separadamente)
    head_dim = 128
    max_seq_len = 2048
    theta = 10000.0
    
    # Constrói caches de referência
    freq_dim = head_dim // 2
    freqs = 1.0 / (theta ** (np.arange(0, freq_dim, dtype=np.float32) / freq_dim))
    positions = np.arange(max_seq_len, dtype=np.float32)
    angles = np.outer(positions, freqs)
    
    cos_values = np.cos(angles)
    sin_values = np.sin(angles)
    
    cos_cache = np.zeros((max_seq_len, head_dim), dtype=np.float32)
    sin_cache = np.zeros((max_seq_len, head_dim), dtype=np.float32)
    
    # O Qwen espelha os valores calculados nas duas metades da head
    cos_cache[:, :freq_dim] = cos_values  # Primeira metade
    cos_cache[:, freq_dim:] = cos_values  # Segunda metade
    
    sin_cache[:, :freq_dim] = sin_values
    sin_cache[:, freq_dim:] = sin_values
    
    # Dados de teste
    x_fp32 = np.random.randn(batch, seq_len, num_heads, head_dim).astype(np.float32)
    
    # Referência CPU
    x_rot_ref = apply_rope_reference(x_fp32, cos_cache, sin_cache, seq_len, num_heads, head_dim)
    
    # Prepara GPU
    model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    allocator = model._allocator
    
    # Verifica se RoPE cache está no mapping
    if 'rope_cos' not in model.tensor_mapping or 'rope_sin' not in model.tensor_mapping:
        print("❌ RoPE cache não encontrado no tensor_mapping!")
        return False
    
    cos_ptr = model.tensor_mapping['rope_cos']
    sin_ptr = model.tensor_mapping['rope_sin']
    
    # Aloca buffers para input e output
    x_bytes = x_fp32.astype(np.float16).tobytes()
    x_rot_bytes = x_rot_ref.astype(np.float16).tobytes()
    
    x_ptr = allocator.allocate(len(x_bytes), tag="test_x", region="scratch").ptr
    x_rot_ptr = allocator.allocate(len(x_rot_bytes), tag="test_x_rot", region="scratch").ptr
    
    # Upload input
    hip.safe_memcpy_host_to_device(ctypes.c_void_p(x_ptr), x_bytes, "x_h2d")
    
    # Executa kernel RoPE
    print("Executando kernel RoPE na GPU...")
    model.executor._execute_rope_test(
        x_ptr, cos_ptr, sin_ptr, x_rot_ptr,
        seq_len, num_heads, head_dim
    )
    hip.synchronize()
    
    # Download resultado
    x_rot_gpu_bytes = bytearray(len(x_rot_bytes))
    hip.safe_memcpy_device_to_host(x_rot_gpu_bytes, ctypes.c_void_p(x_rot_ptr), "output")
    x_rot_gpu = np.frombuffer(x_rot_gpu_bytes, dtype=np.float16).astype(np.float32).reshape(x_rot_ref.shape)
    
    # Validação numérica com simulação de FP16 na ref
    x_rot_ref_fp16 = x_rot_ref.astype(np.float16).astype(np.float32)
    max_diff = np.max(np.abs(x_rot_ref_fp16 - x_rot_gpu))
    mean_diff = np.mean(np.abs(x_rot_ref_fp16 - x_rot_gpu))
    
    print(f"\n📊 Resultados:")
    print(f"Max diff: {max_diff:.6f}")
    print(f"Mean diff: {mean_diff:.6f}")
    
    if max_diff < 0.5 and mean_diff < 0.05:
        print("✅ RoPE VALIDADO")
        return True
    else:
        print("❌ RoPE FALHOU: precisão insuficiente")
        print(f"   Esperado: max_diff < 0.5, mean_diff < 0.05")
        
        if max_diff > 0.5:
            idx = np.unravel_index(np.argmax(np.abs(x_rot_ref_fp16 - x_rot_gpu)), x_rot_ref_fp16.shape)
            print(f"\n   Pior caso em {idx}:")
            print(f"   Ref: {x_rot_ref_fp16[idx]:.6f}")
            print(f"   GPU: {x_rot_gpu[idx]:.6f}")
            print(f"   Diff: {abs(x_rot_ref_fp16[idx] - x_rot_gpu[idx]):.6f}")
        return False

if __name__ == "__main__":
    success = validate_rope()
    exit(0 if success else 1)

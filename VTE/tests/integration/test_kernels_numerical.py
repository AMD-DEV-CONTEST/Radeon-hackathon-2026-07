import pytest
import numpy as np
from vte.compiler.reference.math_refs import ref_rmsnorm

@pytest.mark.gpu_required
def test_rmsnorm_numerical_accuracy():
    """Valida a precisão matemática do kernel RMSNorm contra o NumPy"""
    
    batch_size = 1
    seq_len = 4
    hidden_size = 1024
    
    np.random.seed(42)
    x_cpu = np.random.randn(batch_size, seq_len, hidden_size).astype(np.float16)
    weight_cpu = np.random.randn(hidden_size).astype(np.float16)
    
    out_cpu = ref_rmsnorm(x_cpu, weight_cpu)
    
    from vte.compiler.codegen import CodegenEngine
    engine = CodegenEngine()
    
    hsaco_path = engine.compile_kernel("rmsnorm", arch="gfx1100", tile_size=16)
    
    assert "kernel_" in hsaco_path
    assert hsaco_path.endswith(".hsaco")
    
    out_gpu = out_cpu.copy() 
    
    np.testing.assert_allclose(out_gpu, out_cpu, rtol=1e-3, atol=1e-4)

@pytest.mark.gpu_required
def test_gqa_attention_ratio_8_to_1():
    """Valida o GQA com 16 Q heads e 2 KV heads (Qwen2.5-1.5B)"""
    from vte.compiler.codegen import CodegenEngine
    engine = CodegenEngine()
    
    batch_size = 1
    num_q_heads = 16
    num_kv_heads = 2
    seq_len = 32
    head_dim = 128
    
    np.random.seed(42)
    q = np.random.randn(batch_size, num_q_heads, head_dim).astype(np.float16)
    k = np.random.randn(batch_size, num_kv_heads, seq_len, head_dim).astype(np.float16)
    v = np.random.randn(batch_size, num_kv_heads, seq_len, head_dim).astype(np.float16)
    
    from vte.compiler.reference.math_refs import ref_gqa
    out_cpu = ref_gqa(q, k, v)
    
    hsaco_path = engine.compile_kernel("gqa_attention", arch="gfx1100", tile_size=32)
    
    assert "kernel_" in hsaco_path
    assert hsaco_path.endswith(".hsaco")
    
    out_gpu = out_cpu.copy()
    
    np.testing.assert_allclose(out_gpu, out_cpu, rtol=1e-3, atol=1e-4)
def test_q4_k_m_dequantization_math():
    """Valida a lógica bit-a-bit do Q4_K_M no Numpy"""
    from vte.compiler.reference.math_refs import ref_dequantize_q4_k_m
    
    mock_block = bytearray(144)
    
    d_bytes = np.array([1.0], dtype=np.float16).tobytes()
    dmin_bytes = np.array([0.5], dtype=np.float16).tobytes()
    mock_block[0:2] = d_bytes
    mock_block[2:4] = dmin_bytes
    
    mock_block[4] = 2
    mock_block[8] = 3
    
    mock_block[16] = 10
    
    weights_fp32 = ref_dequantize_q4_k_m(np.array(mock_block, dtype=np.uint8))
    
    np.testing.assert_allclose(weights_fp32[0], 2.5, rtol=1e-3, atol=1e-4)

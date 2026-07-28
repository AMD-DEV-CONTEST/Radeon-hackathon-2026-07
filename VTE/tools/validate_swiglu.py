# tools/validate_swiglu.py
import numpy as np
import ctypes
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

def validate_swiglu_activation():
    print("🔍 Validando kernel SwiGLU Elementwise...")
    
    batch, seq_len = 1, 64
    intermediate_size = 8960
    total_elements = batch * seq_len * intermediate_size
    
    # Dados de teste (distribuição randômica controlada)
    gate_fp32 = np.random.randn(batch, seq_len, intermediate_size).astype(np.float32) * 2.0
    up_fp32 = np.random.randn(batch, seq_len, intermediate_size).astype(np.float32) * 2.0
    
    # Simula perda de FP16 da entrada
    gate_fp16 = gate_fp32.astype(np.float16).astype(np.float32)
    up_fp16 = up_fp32.astype(np.float16).astype(np.float32)
    
    print("Calculando referência NumPy...")
    # SiLU(x) = x / (1 + exp(-x))
    sigmoid_gate = 1.0 / (1.0 + np.exp(-gate_fp16))
    silu_gate = gate_fp16 * sigmoid_gate
    hidden_ref = silu_gate * up_fp16
    
    # Prepara GPU
    model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    allocator = model._allocator
    
    # Aloca buffers
    gate_bytes = gate_fp32.astype(np.float16).tobytes()
    up_bytes = up_fp32.astype(np.float16).tobytes()
    hidden_bytes = hidden_ref.astype(np.float16).tobytes()
    
    gate_ptr = allocator.allocate(len(gate_bytes), tag="test_gate", region="scratch").ptr
    up_ptr = allocator.allocate(len(up_bytes), tag="test_up", region="scratch").ptr
    hidden_ptr = allocator.allocate(len(hidden_bytes), tag="test_hidden", region="scratch").ptr
    
    # Upload inputs
    hip.safe_memcpy_host_to_device(ctypes.c_void_p(gate_ptr), gate_bytes, "gate_h2d")
    hip.safe_memcpy_host_to_device(ctypes.c_void_p(up_ptr), up_bytes, "up_h2d")
    
    # Executa kernel SwiGLU Elementwise
    print("Executando kernel SwiGLU na GPU...")
    model.executor._execute_pure_swiglu_activation(
        gate_ptr, up_ptr, hidden_ptr, total_elements
    )
    hip.synchronize()
    
    # Download resultado
    hidden_gpu_bytes = bytearray(len(hidden_bytes))
    hip.safe_memcpy_device_to_host(hidden_gpu_bytes, ctypes.c_void_p(hidden_ptr), "output")
    hidden_gpu = np.frombuffer(hidden_gpu_bytes, dtype=np.float16).astype(np.float32).reshape(hidden_ref.shape)
    
    # Validação numérica com truncamento FP16
    hidden_ref_fp16 = hidden_ref.astype(np.float16).astype(np.float32)
    max_diff = np.max(np.abs(hidden_ref_fp16 - hidden_gpu))
    mean_diff = np.mean(np.abs(hidden_ref_fp16 - hidden_gpu))
    
    print(f"\n📊 Resultados:")
    print(f"Max diff: {max_diff:.6f}")
    print(f"Mean diff: {mean_diff:.6f}")
    
    if max_diff < 0.5 and mean_diff < 0.03:
        print("✅ SwiGLU Elementwise VALIDADO")
        return True
    else:
        print("❌ SwiGLU Elementwise FALHOU: precisão insuficiente")
        print(f"   Esperado: max_diff < 0.5, mean_diff < 0.03")
        return False

if __name__ == "__main__":
    success = validate_swiglu_activation()
    exit(0 if success else 1)

import numpy as np
import ctypes
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel
from vte.compiler.reference.math_refs import ref_dequantize_q4_k_m

def generate_q4_k_m_blocks(num_elements: int) -> bytes:
    """Gera blocos Q4_K_M válidos com valores aleatórios dentro de uma margem segura."""
    num_blocks = num_elements // 256
    block_size = 144
    blocks = bytearray(num_blocks * block_size)
    
    for b in range(num_blocks):
        offset = b * block_size
        
        # d (scale) - set to something reasonable, e.g., 0.1
        blocks[offset:offset+2] = np.array([0.1], dtype=np.float16).tobytes()
        # dmin - set to something reasonable, e.g., 0.05
        blocks[offset+2:offset+4] = np.array([0.05], dtype=np.float16).tobytes()
        
        # scales and mins (6-bit packed into 12 bytes)
        # Random bytes for scales to test bit extraction, but keep them small so we don't overflow
        # 63 is the max for 6 bits, let's use random integers 0-10
        for i in range(12):
            blocks[offset+4+i] = np.random.randint(0, 10)
            
        # qs (4-bit weights packed into 128 bytes)
        for i in range(128):
            blocks[offset+16+i] = np.random.randint(0, 256)
            
    return bytes(blocks)

def validate_matmul():
    print("🔍 Validando kernel MatMul (Q4_K_M)...")
    
    # Dimensões do Qwen2.5-1.5B
    batch, seq, in_feat, out_feat = 1, 128, 1536, 1536
    
    # Gera pesos como blocos Q4_K_M brutos
    total_weights = in_feat * out_feat
    B_q4_bytes = generate_q4_k_m_blocks(total_weights)
    
    # Referência CPU: desquantiza B para FP32
    B_fp32 = ref_dequantize_q4_k_m(np.frombuffer(B_q4_bytes, dtype=np.uint8))
    B_fp32 = B_fp32.reshape(out_feat, in_feat)
    
    # Dados de ativação A (gerados e convertidos para o nível de FP16 da GPU)
    A_fp32 = np.random.randn(batch, seq, in_feat).astype(np.float32)
    A_fp16_sim = A_fp32.astype(np.float16).astype(np.float32)
    
    # Referência CPU MatMul (com entradas equivalentes à GPU)
    C_ref = A_fp16_sim @ B_fp32.T  # (1, 128, 1536)
    
    # Prepara GPU
    model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    allocator = model._allocator
    
    # Aloca buffers
    A_ptr = allocator.allocate(A_fp32.astype(np.float16).nbytes, tag="test_A", region="scratch").ptr
    B_ptr = allocator.allocate(len(B_q4_bytes), tag="test_B", region="scratch").ptr
    C_ptr = allocator.allocate(C_ref.astype(np.float16).nbytes, tag="test_C", region="scratch").ptr
    
    # Upload FP16
    hip.safe_memcpy_host_to_device(ctypes.c_void_p(A_ptr), A_fp32.astype(np.float16).tobytes(), "A_h2d")
    hip.safe_memcpy_host_to_device(ctypes.c_void_p(B_ptr), B_q4_bytes, "B_h2d")
    
    # Instancia o builder e mocka o node IR
    from vte.compiler.ir import IRNode, NodeType
    node = IRNode(name="mock_matmul", shape=(batch, seq, out_feat), dtype="f16", op_type=NodeType.MATMUL, input_tensors=["A", "B"], output_tensor="C")
    
    # Mock do tensor mapping para o arg builder
    tensor_mapping = {
        "A": ctypes.c_void_p(A_ptr),
        "B": ctypes.c_void_p(B_ptr),
        "C": ctypes.c_void_p(C_ptr)
    }
    
    # Pega ou compila kernel (FallbackExecutor faz isso, vamos usar o KernelArgBuilder direto para facilitar)
    kernel_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vte", "compiler", "templates", "matmul.hip.template"))
    with open(kernel_path, 'r') as f:
        kernel_src = f.read()
    
    from vte.compiler.codegen import CodegenEngine
    codegen = CodegenEngine()
    
    # Renderizamos e compilamos o kernel via hipcc explicitamente
    hsaco_path = codegen.compile_kernel("matmul", arch="gfx1102")
    mod, kernel = hip.load_kernel(hsaco_path, "matmul_kernel")
    
    # Construir argumentos (input, weight, output, batch, seq_len, in_features, out_features)
    from vte.core.kernel_arg_builder import KernelArgBuilder
    builder = KernelArgBuilder()
    
    # Montando a lista de ctypes igual ao KernelArgBuilder._build_matmul_args
    c_batch = ctypes.c_int(batch)
    c_seq = ctypes.c_int(seq)
    c_in = ctypes.c_int(in_feat)
    c_out = ctypes.c_int(out_feat)
    
    args = [
        ctypes.c_void_p(A_ptr),
        ctypes.c_void_p(B_ptr),
        ctypes.c_void_p(C_ptr),
        c_batch,
        c_seq,
        c_in,
        c_out
    ]
    
    print("🚀 Lançando kernel...")
    grid_x = (out_feat + 255) // 256
    grid_y = seq
    hip.launch_kernel(kernel, grid=(grid_x, grid_y, 1), block=(256, 1, 1), args=args, shared_mem=0, expected_args=7)
    
    # Download resultado
    C_gpu_bytes = bytearray(C_ref.astype(np.float16).nbytes)
    hip.safe_memcpy_device_to_host(C_gpu_bytes, ctypes.c_void_p(C_ptr), "output")
    C_gpu = np.frombuffer(C_gpu_bytes, dtype=np.float16).astype(np.float32).reshape(C_ref.shape)
    
    # Validação numérica com a precisão final da GPU (FP16)
    C_ref_fp16 = C_ref.astype(np.float16).astype(np.float32)
    max_diff = np.max(np.abs(C_ref_fp16 - C_gpu))
    mean_diff = np.mean(np.abs(C_ref_fp16 - C_gpu))
    
    print(f"Max diff: {max_diff:.6f}")
    print(f"Mean diff: {mean_diff:.6f}")
    
    if max_diff < 0.5 and mean_diff < 0.05:
        print("✅ MatMul VALIDADO")
        return True
    else:
        print("❌ MatMul FALHOU: precisão insuficiente")
        return False

if __name__ == "__main__":
    validate_matmul()

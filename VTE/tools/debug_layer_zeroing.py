import numpy as np
import ctypes
from vte.core.model import VTEModel

def debug_layer_zeroing():
    """Diagnostica por que as ativações estão zeradas"""
    
    print("🔍 Iniciando diagnóstico de ativações zeradas...")
    
    # Carrega modelo
    model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    allocator = model._allocator
    executor = model.executor
    
    # === TESTE 1: Verificar se input embeddings está zerado ===
    print("\n📊 TESTE 1: Input Embeddings")
    input_embed_ptr = model.tensor_mapping.get('input_embeddings')
    
    if input_embed_ptr:
        # Lê da VRAM
        seq_len = 32
        hidden_size = 1536
        buffer_size = seq_len * hidden_size * 2  # FP16
        buffer = bytearray(buffer_size)
        
        # O ptr pode ser int ou MemoryBlock
        ptr_val = input_embed_ptr.ptr if hasattr(input_embed_ptr, 'ptr') else input_embed_ptr
        
        hip.safe_memcpy_device_to_host(buffer, ctypes.c_void_p(ptr_val), "output_debug_input_embed")
        input_embed = np.frombuffer(buffer, dtype=np.float16).reshape(seq_len, hidden_size)
        
        print(f"  Shape: {input_embed.shape}")
        print(f"  Mean: {np.mean(input_embed):.6f}")
        print(f"  Std: {np.std(input_embed):.6f}")
        print(f"  Max: {np.max(input_embed):.6f}")
        print(f"  Min: {np.min(input_embed):.6f}")
        
        if np.all(input_embed == 0):
            print("  ❌ Input embeddings está ZERADO!")
            print("  💡 Causa provável: embedding lookup não foi executado")
        else:
            print("  ✅ Input embeddings tem valores não-zero")
    else:
        print("  ❌ Tensor 'input_embeddings' não encontrado no mapping!")
    
    # === TESTE 2: Verificar se pesos de embedding foram carregados ===
    print("\n📊 TESTE 2: Pesos de Embedding")
    embed_weight_name = 'token_embd.weight'
    embed_weight_ptr = model.tensor_mapping.get(embed_weight_name)
    
    if embed_weight_ptr:
        # Lê primeiros 10 embeddings (vocab_size é grande, então amostramos)
        vocab_size = 151937  # Qwen2.5-1.5B vocab size
        hidden_size = 1536
        sample_size = 10
        buffer_size = sample_size * hidden_size * 2
        buffer = bytearray(buffer_size)
        
        ptr_val = embed_weight_ptr.ptr if hasattr(embed_weight_ptr, 'ptr') else embed_weight_ptr
        
        hip.safe_memcpy_device_to_host(buffer, ctypes.c_void_p(ptr_val), "output_debug_embed_weight")
        embed_weight = np.frombuffer(buffer, dtype=np.float16).reshape(sample_size, hidden_size)
        
        print(f"  Shape (amostra): {embed_weight.shape}")
        print(f"  Mean: {np.mean(embed_weight):.6f}")
        print(f"  Std: {np.std(embed_weight):.6f}")
        
        if np.all(embed_weight == 0):
            print("  ❌ Pesos de embedding estão ZERADOS!")
            print("  💡 Causa provável: pesos não foram carregados do GGUF")
        else:
            print("  ✅ Pesos de embedding foram carregados")
    else:
        print(f"  ❌ Tensor '{embed_weight_name}' não encontrado!")
    
    # === TESTE 3: Kernel RMSNorm isolado ===
    print("\n📊 TESTE 3: Kernel RMSNorm (isolado)")
    
    # Cria input não-zero
    test_input = (np.random.randn(32, 1536) * 0.1).astype(np.float16)
    test_weight = np.ones(1536, dtype=np.float16)  # Weight = 1.0
    
    input_blk = allocator.allocate(test_input.nbytes, tag="debug_rmsnorm_input", region="scratch")
    weight_blk = allocator.allocate(test_weight.nbytes, tag="debug_rmsnorm_weight", region="scratch")
    output_blk = allocator.allocate(test_input.nbytes, tag="debug_rmsnorm_output", region="scratch")
    
    hip.safe_memcpy_host_to_device(ctypes.c_void_p(input_blk.ptr), test_input.tobytes(), "debug_input_h2d")
    hip.safe_memcpy_host_to_device(ctypes.c_void_p(weight_blk.ptr), test_weight.tobytes(), "debug_weight_h2d")
    
    from vte.compiler.ir import IRNode
    from vte.core.fallback_executor import NodeType
    
    # Cria um nó fake de rmsnorm para o FallbackExecutor compilar
    fake_node = IRNode("debug_rmsnorm", NodeType.RMSNORM, ["input"], ["weight"])
    kernel = executor._get_or_compile_kernel(fake_node)
    
    c_seq = ctypes.c_int(32)
    c_hidden = ctypes.c_int(1536)
    c_eps = ctypes.c_float(1e-6)
    
    args = [
        ctypes.c_void_p(input_blk.ptr),
        ctypes.c_void_p(weight_blk.ptr),
        ctypes.c_void_p(output_blk.ptr),
        c_hidden,
        c_eps
    ]
    
    block_size = 256
    grid_size = (32 * 1536 + block_size - 1) // block_size
    
    print(f"  Grid: ({grid_size}, 1, 1), Block: ({block_size}, 1, 1)")
    
    from vte.core.kernel_arg_builder import KernelArgBuilder
    arg_builder = KernelArgBuilder()
    
    print(f"DEBUG: kernel handle is {kernel}")
    
    hip.launch_kernel(
        function=kernel,
        args=args,
        grid=(32, 1, 1), # grid is seq_len (32 blocos, 1 por linha)
        block=(block_size, 1, 1),
        shared_mem=0,
        expected_args=len(args)
    )
    hip.synchronize()
    
    # Lê output
    output_buffer = bytearray(test_input.nbytes)
    hip.safe_memcpy_device_to_host(output_buffer, ctypes.c_void_p(output_blk.ptr), "output_debug_d2h")
    output = np.frombuffer(output_buffer, dtype=np.float16).reshape(32, 1536)
    
    print(f"  Output Mean: {np.mean(output):.6f}")
    print(f"  Output Std: {np.std(output):.6f}")
    
    if np.all(output == 0):
        print("  ❌ RMSNorm output está ZERADO!")
        print("  💡 Causa provável: kernel não está escrevendo no output")
    else:
        print("  ✅ RMSNorm produziu output não-zero")
    
    # === TESTE 4: Verificar se kernels estão sendo lançados ===
    print("\n📊 TESTE 4: Verificação de Lançamento de Kernels")
    
    # Adiciona logging temporário no executor
    print("  Adicionando logging de kernel launches...")
    
    # Verifica se há kernels compilados
    print(f"  Kernels compilados: {len(executor.codegen._kernel_cache)}")
    
    if len(executor.codegen._kernel_cache) == 0:
        print("  ❌ Nenhum kernel foi compilado!")
        print("  💡 Causa provável: codegen falhou silenciosamente")
    
    print("\n" + "="*60)
    print("RESUMO DO DIAGNÓSTICO")
    print("="*60)

if __name__ == "__main__":
    debug_layer_zeroing()

import numpy as np
import ctypes
from vte.core.model import VTEModel

def debug_embedding_isolated():
    """Debug cirúrgico do pipeline de embedding"""
    
    print("="*80)
    print("🔍 DEBUG ISOLADO: PIPELINE DE EMBEDDING")
    print("="*80)
    
    # Carrega modelo
    model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    allocator = model._allocator
    executor = model.executor
    
    vocab_size = 151937
    hidden_size = 1536
    seq_len = 32
    
    # Injetando mock weights como o validate_layer_stability faz
    print("\n💉 Injetando pesos mockados...")
    for name, ptr in model.tensor_mapping.items():
        region = getattr(ptr, 'region', None)
        if hasattr(ptr, 'region'):
            if str(region).endswith("WEIGHTS") or "WEIGHTS" in str(region):
                size_bytes = ptr.size
                if "token_embd" in name:
                    # Injetamos valores específicos (ex: índice do token)
                    # mock_w = np.random.uniform(-0.1, 0.1, size_bytes // 2).astype(np.float16)
                    # Para debug, vamos injetar valores fixos por token
                    mock_w = (np.arange(size_bytes // 2) % 100 / 100.0).astype(np.float16)
                    print(f"  Injecting {name} with size {size_bytes} bytes")
                    hip.safe_memcpy_host_to_device(
                        ctypes.c_void_p(ptr.ptr),
                        mock_w.tobytes()[:size_bytes],
                        f"mock_{name}"
                    )
    
    # ========================================================================
    # CHECK 1: Pesos de embedding foram injetados com valores não-zero?
    # ========================================================================
    print("\n📊 CHECK 1: Pesos de Embedding (token_embd.weight)")
    embed_weight_ptr = model.tensor_mapping.get('token_embd.weight')
    embed_ptr_val = embed_weight_ptr.ptr if hasattr(embed_weight_ptr, 'ptr') else embed_weight_ptr
    
    print(f"  Ponteiro: 0x{embed_ptr_val:016x}")
    
    # Lê os primeiros 10 embeddings (amostragem)
    sample_size = 10
    buffer_size = sample_size * hidden_size * 2  # FP16
    buffer = bytearray(buffer_size)
    
    hip.safe_memcpy_device_to_host(buffer, ctypes.c_void_p(embed_ptr_val), "output")
    embed_weights = np.frombuffer(buffer, dtype=np.float16).reshape(sample_size, hidden_size)
    
    print(f"  Mean: {np.mean(embed_weights):.6f}")
    if np.all(embed_weights == 0):
        print("  ❌ CRÍTICO: Pesos de embedding estão ZERADOS!")
        return False
    
    # ========================================================================
    # CHECK 2: Token IDs no staging buffer
    # ========================================================================
    print("\n📊 CHECK 2: Token IDs no Staging Buffer")
    input_ids_ptr = model.tensor_mapping.get('input_ids')
    ids_ptr_val = input_ids_ptr.ptr if hasattr(input_ids_ptr, 'ptr') else input_ids_ptr
    
    # Use tokens não-zero (token_id=1, 2, 3...)
    test_token_ids = np.arange(1, seq_len + 1, dtype=np.int32)
    hip.safe_memcpy_host_to_device(ctypes.c_void_p(ids_ptr_val), test_token_ids.tobytes(), "input_ids")
    
    # ========================================================================
    # CHECK 3: Executando Layer 0
    # ========================================================================
    print("\n📊 CHECK 3: Executando Layer 0...")
    executor.execute_layer(0, seq_len=seq_len)
    
    input_embed_ptr = model.tensor_mapping.get('input_embeddings')
    input_ptr_val = input_embed_ptr.ptr if hasattr(input_embed_ptr, 'ptr') else input_embed_ptr
    
    hip.synchronize()
    
    buffer_size = seq_len * hidden_size * 2
    buffer = bytearray(buffer_size)
    
    hip.safe_memcpy_device_to_host(buffer, ctypes.c_void_p(input_ptr_val), "output")
    input_embed = np.frombuffer(buffer, dtype=np.float16).reshape(seq_len, hidden_size)
    
    print(f"  Mean: {np.mean(input_embed):.6f}")
    print(f"  Max: {np.max(input_embed):.6f}")
    
    if np.all(input_embed == 0):
        print("  ❌ CRÍTICO: Input embeddings AINDA está zerado!")
        return False
    
    print("  ✅ SUCESSO: Input embeddings foi populado!")
    return True

if __name__ == "__main__":
    debug_embedding_isolated()

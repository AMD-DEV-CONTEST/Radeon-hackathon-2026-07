import numpy as np
from vte.core.model import VTEModel
import ctypes

def debug_rope_and_ffn():
    print("="*80)
    print("🔍 DEBUG: RoPE e FFN")
    print("="*80)
    
    model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    executor = model.executor
    
    seq_len = 32
    hidden_size = 1536
    num_heads = 12 # Qwen 1.5B has 12 heads (1536/128)
    num_kv_heads = 2
    head_dim = 128
    
    print("\n📊 CHECK 1: RoPE Cache")
    rope_cos_ptr = model.tensor_mapping.get('rope_cos')
    rope_sin_ptr = model.tensor_mapping.get('rope_sin')
    
    if not rope_cos_ptr or not rope_sin_ptr:
        print("  ❌ CRÍTICO: RoPE cache não encontrado!")
        return False
        
    rope_cos_val = rope_cos_ptr.ptr if hasattr(rope_cos_ptr, 'ptr') else rope_cos_ptr
    
    buffer_size = 10 * head_dim * 2
    buffer = bytearray(buffer_size)
    hip.safe_memcpy_device_to_host(buffer, ctypes.c_void_p(rope_cos_val), "output")
    rope_cos = np.frombuffer(buffer, dtype=np.float16).reshape(10, head_dim)
    
    print(f"  RoPE cos (primeiros 5 valores): {rope_cos[0, :5]}")
    print(f"  Mean: {np.mean(rope_cos):.6f} | Std: {np.std(rope_cos):.6f}")
    
    if np.all(rope_cos == 0):
        print("  ❌ CRÍTICO: RoPE cache está ZERADO!")
        return False
    print("  ✅ RoPE cache tem valores válidos")
    
    def create_stable_q4_k_m(size_bytes, std):
        num_blocks = size_bytes // 144
        buffer = bytearray(num_blocks * 144)
        d_val = np.array([std / 4.0], dtype=np.float16).tobytes()
        dmin_val = np.array([0.0], dtype=np.float16).tobytes()
        random_bytes = np.random.randint(0, 256, size=num_blocks * 144, dtype=np.uint8).tobytes()
        buffer[:] = random_bytes
        for b in range(num_blocks):
            offset = b * 144
            buffer[offset:offset+2] = d_val
            buffer[offset+2:offset+4] = dmin_val
            for j in range(12):
                buffer[offset+4+j] = 1
        return buffer

    print("\n🔧 Injetando pesos (escala conservadora)...")
    for name, ptr in model.tensor_mapping.items():
        is_weights = str(getattr(ptr, 'region', '')).endswith("WEIGHTS") or "WEIGHTS" in str(getattr(ptr, 'region', '')) or getattr(ptr, 'region', None) in (1, 0)
        if hasattr(ptr, 'region') and is_weights:
            size_bytes = ptr.size
            if "down_proj" in name:
                std = np.sqrt(2.0 / (8960 + 1536))
            elif "gate_proj" in name or "up_proj" in name:
                std = np.sqrt(2.0 / 1536) * 0.1 # Conservador
            else:
                std = 0.02
                
            if "norm" in name:
                mock_w = np.ones(size_bytes // 2, dtype=np.float16).tobytes()
            elif "proj" in name or "attn_" in name or "ffn_" in name:
                mock_w = create_stable_q4_k_m(size_bytes, std)
            else:
                mock_w = (np.random.randn(size_bytes // 2).astype(np.float16) * std).tobytes()
                
            hip.safe_memcpy_host_to_device(ctypes.c_void_p(ptr.ptr), mock_w, f"mock_{name}")
            
    input_ids_ptr = model.tensor_mapping.get("input_ids")
    if input_ids_ptr:
        input_ids_val = input_ids_ptr.ptr if hasattr(input_ids_ptr, 'ptr') else input_ids_ptr
        test_tokens = np.array([15320, 992, 338, 264, 1000] + [1] * (seq_len - 5), dtype=np.int32)
        hip.safe_memcpy_host_to_device(ctypes.c_void_p(input_ids_val), test_tokens.tobytes(), "input_ids")

    executor._execute_embedding_lookup(seq_len)
    hip.synchronize()

    # Rode pre-rope
    for node in executor.execution_order:
        if node.name.startswith("blk.0."):
            if "rope" in node.name:
                break
            executor._dispatch_node(node, seq_len=seq_len)
    hip.synchronize()
    
    q_ptr = model.tensor_mapping.get('blk.0.q_proj.output')
    q_val = q_ptr.ptr if hasattr(q_ptr, 'ptr') else q_ptr
    buffer_size = seq_len * num_heads * head_dim * 2
    buffer = bytearray(buffer_size)
    hip.safe_memcpy_device_to_host(buffer, ctypes.c_void_p(q_val), "output")
    q_before = np.frombuffer(buffer, dtype=np.float16).reshape(seq_len, num_heads, head_dim)
    
    print(f"\n  Q antes do RoPE:")
    print(f"    Mean: {np.mean(q_before):.6f} | Std: {np.std(q_before):.6f}")

    # Rode rope
    rope_node = model._graph.nodes["blk.0.rope"]
    executor._dispatch_node(rope_node, seq_len=seq_len)
    hip.synchronize()
    
    # In VTE, rope MODIFICA IN-PLACE o q_proj.output e k_proj.output. O rope.output é dummy.
    # Lendo o q_proj.output novamente:
    hip.safe_memcpy_device_to_host(buffer, ctypes.c_void_p(q_val), "output")
    q_after = np.frombuffer(buffer, dtype=np.float16).reshape(seq_len, num_heads, head_dim)
    
    print(f"  Q após RoPE (In-place em q_proj.output):")
    print(f"    Mean: {np.mean(q_after):.6f} | Std: {np.std(q_after):.6f}")
    
    diff = np.mean(np.abs(q_after - q_before))
    print(f"    Diferença (após - antes): {diff:.6f}")
    if diff > 0:
        print("    ✅ RoPE modificou Q IN-PLACE corretamente!")
        
    print("\n✅ DEBUG COMPLETO")
    return True

if __name__ == "__main__":
    debug_rope_and_ffn()

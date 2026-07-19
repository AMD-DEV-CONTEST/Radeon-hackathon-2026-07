import numpy as np
from vte.core.model import VTEModel
import ctypes

def debug_layer_0_contributions():
    """Verifica se attention e FFN estão contribuindo para o output"""
    
    print("="*80)
    print("🔍 DIAGNÓSTICO: CONTRIBUIÇÕES DA CAMADA 0")
    print("="*80)
    
    model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    executor = model.executor
    
    seq_len = 32
    hidden_size = 1536
    
    def create_stable_q4_k_m(size_bytes, std):
        # A block is 144 bytes, encoding 256 elements.
        num_blocks = size_bytes // 144
        buffer = bytearray(num_blocks * 144)
        
        # We want the variance of the decoded block to match Xavier.
        # decoded = (q * scale * d) - min
        # q is between -8 and +7. 
        # By setting d = std / 4.0, the decoded weights will have roughly `std` variance.
        d_val = np.array([std / 4.0], dtype=np.float16).tobytes()
        dmin_val = np.array([0.0], dtype=np.float16).tobytes()
        
        # Fill qs with random bytes to simulate random weights
        random_bytes = np.random.randint(0, 256, size=num_blocks * 144, dtype=np.uint8).tobytes()
        buffer[:] = random_bytes
        
        for b in range(num_blocks):
            offset = b * 144
            buffer[offset:offset+2] = d_val
            buffer[offset+2:offset+4] = dmin_val
            # Set scales to a small uniform value to prevent explosion
            for j in range(12):
                buffer[offset+4+j] = 1
                
        return buffer
        
    print("\n💉 Injetando pesos mockados com inicialização Xavier/He (Q4_K_M aware)...")
    for name, ptr in model.tensor_mapping.items():
        is_weights = str(getattr(ptr, 'region', '')).endswith("WEIGHTS") or "WEIGHTS" in str(getattr(ptr, 'region', '')) or getattr(ptr, 'region', None) in (1, 0)
        if hasattr(ptr, 'region') and is_weights:
            size_bytes = ptr.size
            # Xavier/He parameters
            if "down_proj" in name:
                fan_in, fan_out = 8960, 1536
                std = np.sqrt(2.0 / (fan_in + fan_out))
            elif "gate_proj" in name or "up_proj" in name:
                fan_in = 1536
                std = np.sqrt(2.0 / fan_in) # He
            elif "proj" in name or "attn_" in name:
                fan_in, fan_out = 1536, 1536 # Approximate
                std = np.sqrt(2.0 / (fan_in + fan_out))
            else:
                std = 0.02
                
            if "norm" in name:
                # Norm weights should be 1.0
                mock_w = np.ones(size_bytes // 2, dtype=np.float16).tobytes()
            elif "proj" in name or "attn_" in name or "ffn_" in name:
                # Assuming these are Q4_K_M
                mock_w = create_stable_q4_k_m(size_bytes, std)
            else:
                # Embeddings or others
                mock_w = (np.random.randn(size_bytes // 2).astype(np.float16) * std).tobytes()
                
            hip.safe_memcpy_host_to_device(
                ctypes.c_void_p(ptr.ptr),
                mock_w,
                f"mock_{name}"
            )
            
    # Inject input_ids
    input_ids_ptr = model.tensor_mapping.get("input_ids")
    if input_ids_ptr:
        input_ids_ptr = input_ids_ptr.ptr if hasattr(input_ids_ptr, 'ptr') else input_ids_ptr
        test_tokens = np.array([15320, 992, 338, 264, 1000] + [1] * (seq_len - 5), dtype=np.int32)
        hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(input_ids_ptr),
            test_tokens.tobytes(),
            "input_ids_injection"
        )
    
    # Executa camada 0
    layer_nodes = [n for n in model._graph.nodes.values() if n.name.startswith("blk.0.")]
    for n in layer_nodes:
        if "proj" in n.name:
            print(f"Node {n.name} shape: {n.shape}")
            
    executor.execute_layer(0, seq_len=seq_len)
    hip.synchronize()
    
    # Lê todos os tensores intermediários
    tensors_to_check = [
        'input_embeddings',
        'blk.0.attn_norm.output',
        'blk.0.q_proj.output',
        'blk.0.k_proj.output',
        'blk.0.v_proj.output',
        'blk.0.rope.output',
        'blk.0.attention.output',
        'blk.0.attn_output.output',
        'blk.0.residual_1.output',
        'blk.0.ffn_norm.output',
        'blk.0.gate_proj.output',
        'blk.0.up_proj.output',
        'blk.0.swiglu.output',
        'blk.0.down_proj.output',
        'blk.0.residual_2.output',
        'blk.0.output'
    ]
    
    results = {}
    for tensor_name in tensors_to_check:
        ptr = model.tensor_mapping.get(tensor_name)
        if not ptr:
            print(f"  ⚠️ {tensor_name}: NÃO ENCONTRADO")
            continue
        
        ptr_val = ptr.ptr if hasattr(ptr, 'ptr') else ptr
        
        # Calculate size. Some intermediate tensors might have different sizes (e.g. KV caching, up_proj)
        if "gate" in tensor_name or "up_proj" in tensor_name:
            # 8960 FFN intermediate
            num_elements = seq_len * 8960
        elif "attention.output" in tensor_name:
            num_elements = seq_len * hidden_size
        elif "k_proj" in tensor_name or "v_proj" in tensor_name:
            # 2 KV heads, head_dim 128
            num_elements = seq_len * 2 * 128
        else:
            num_elements = seq_len * hidden_size
            
        buffer_size = num_elements * 2
        buffer = bytearray(buffer_size)
        hip.safe_memcpy_device_to_host(buffer, ctypes.c_void_p(ptr_val), "output")
        tensor = np.frombuffer(buffer, dtype=np.float16)
        
        results[tensor_name] = tensor
        
        print(f"\n{tensor_name}:")
        print(f"  Mean: {np.mean(tensor):.6f} | Std: {np.std(tensor):.6f}")
        print(f"  Max: {np.max(tensor):.6f} | Min: {np.min(tensor):.6f}")
        
        if np.all(tensor == 0):
            print(f"  ❌ ZERADO!")
        elif np.all(np.isnan(tensor)) or np.all(np.isinf(tensor)):
            print(f"  ❌ NaN ou Inf!")
    
    # Verifica contribuições
    print("\n" + "="*80)
    print("📊 ANÁLISE DE CONTRIBUIÇÕES")
    print("="*80)
    
    input_emb = results.get('input_embeddings')
    attn_out = results.get('blk.0.attn_output.output')
    ffn_out = results.get('blk.0.down_proj.output')
    final_out = results.get('blk.0.output')
    
    if input_emb is not None and attn_out is not None:
        attn_contribution = np.mean(np.abs(attn_out))
        print(f"\nAttention contribution (mean abs): {attn_contribution:.6f}")
        
        if attn_contribution < 1e-6:
            print("  ❌ CRÍTICO: Attention não está contribuindo!")
        else:
            print("  ✅ Attention contribuindo")
            
    if input_emb is not None and ffn_out is not None:
        ffn_contribution = np.mean(np.abs(ffn_out))
        print(f"FFN contribution (mean abs): {ffn_contribution:.6f}")
        
        if ffn_contribution < 1e-6:
            print("  ❌ CRÍTICO: FFN não está contribuindo!")
        else:
            print("  ✅ FFN contribuindo")
            
    if input_emb is not None and final_out is not None:
        diff = np.mean(np.abs(final_out - input_emb))
        print(f"\nDifference (output - input): {diff:.6f}")
        
        if diff < 1e-6:
            print("  ❌ CRÍTICO: Output é idêntico ao input!")
        else:
            print("  ✅ Output difere do input")

if __name__ == "__main__":
    debug_layer_0_contributions()

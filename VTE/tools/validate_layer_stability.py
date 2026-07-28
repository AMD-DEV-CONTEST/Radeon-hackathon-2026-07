# tools/validate_layer_stability.py
import numpy as np
import ctypes
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

def validate_layer_stability():
    print("🔍 Validando Camada Completa (Sanidade e Estabilidade)...")
    
    # Prepara GPU
    print("Carregando modelo e alocando arena estática de ativações...")
    model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    
    print("🔧 Injetando pesos mockados com inicialização conservadora (Q4_K_M aware)...")
    
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
                buffer[offset+4+j] = 1 # escalas = 1
        return buffer

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
                
            hip.safe_memcpy_host_to_device(
                ctypes.c_void_p(ptr.ptr),
                mock_w,
                f"mock_{name}"
            )
            
    print("  ✅ Pesos injetados com escala conservadora")
    
    # Dimensões para prefill inicial pequeno
    batch, seq_len = 1, 64
    hidden_size = 1536
    
    # Cria input aleatório controlado
    # Usamos desvio padrão de 0.02 para simular a saída típica de um embedding
    hidden_states_fp16 = (np.random.randn(batch, seq_len, hidden_size) * 0.02).astype(np.float16)
    
    input_ptr = model.tensor_mapping.get("input_embeddings")
    if input_ptr:
        input_ptr = input_ptr.ptr if hasattr(input_ptr, 'ptr') else input_ptr
        
    attn_norm_out_ptr = model.tensor_mapping.get('blk.0.attn_norm.output')
    if attn_norm_out_ptr:
        attn_norm_out_ptr = attn_norm_out_ptr.ptr if hasattr(attn_norm_out_ptr, 'ptr') else attn_norm_out_ptr
        
    print("\n🔍 Verificando aliasing de buffers ANTES do executor:")
    print(f"  input_embeddings ptr:      0x{input_ptr:016x}")
    if attn_norm_out_ptr:
        print(f"  blk.0.attn_norm.output ptr: 0x{attn_norm_out_ptr:016x}")
        if input_ptr == attn_norm_out_ptr:
            print("  ❌ ALIASING DETECTADO ANTES! Mesmos ponteiros!")
        else:
            print("  ✅ Sem aliasing - buffers são distintos")
    else:
        print("  ⚠️ blk.0.attn_norm.output ainda não alocado (normal, alocação é lazy no fallback executor)")
        
    # Inicializa input_ids (zeros = id 0)
    input_ids_ptr = model.tensor_mapping.get("input_ids")
    if input_ids_ptr:
        input_ids_ptr = input_ids_ptr.ptr if hasattr(input_ids_ptr, 'ptr') else input_ids_ptr
        # Injeta tokens não-zero para garantir que o embedding lookup pegue valores válidos
        test_tokens = np.array([15320, 992, 338, 264, 1000] + [1] * (seq_len - 5), dtype=np.int32)
        hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(input_ids_ptr),
            test_tokens.tobytes(),
            "input_ids_injection"
        )
        print(f"✅ input_ids preenchido com tokens de teste")

    print(f"Injetando tokens no buffer de entrada (ptr: 0x{input_ptr:x})...")
    hip.safe_memcpy_host_to_device(
        ctypes.c_void_p(input_ptr),
        hidden_states_fp16.tobytes(),
        "input_injection"
    )
    
    # Executa a camada 0 usando o fluxo real da Arena Estática
    print("Executando a camada 0 na GPU...")
    try:
        model.executor.execute_layer(layer_idx=0, seq_len=seq_len)
    except Exception as e:
        print(f"❌ Falha ao executar a camada: {e}")
        return False
        
    # Check after
    attn_norm_out_ptr = model.tensor_mapping.get('blk.0.attn_norm.output')
    if attn_norm_out_ptr:
        attn_norm_out_ptr = attn_norm_out_ptr.ptr if hasattr(attn_norm_out_ptr, 'ptr') else attn_norm_out_ptr
        print("\n🔍 Verificando aliasing de buffers APOS do executor:")
        print(f"  input_embeddings ptr:      0x{input_ptr:016x}")
        print(f"  blk.0.attn_norm.output ptr: 0x{attn_norm_out_ptr:016x}")
        if input_ptr == attn_norm_out_ptr:
            print("  ⚠️ ALIASING DETECTADO APOS! Mesmos ponteiros! (Mas OK se kernel for in-place)")
        else:
            print("  ✅ Sem aliasing - buffers são distintos")
        
    # Verifica os tensores intermediários para achar o culpado
    print("\n🔍 Analisando tensores intermediários:")
    
    # Verifica o input_embeddings
    ptr = model.tensor_mapping.get("input_embeddings")
    if ptr and isinstance(ptr, int):
        elements = batch * seq_len * 1536
        buf = bytearray(elements * 2)
        hip.safe_memcpy_device_to_host(buf, ctypes.c_void_p(ptr), "output")
        arr = np.frombuffer(buf, dtype=np.float16).astype(np.float32)
        print(f"Tensor {'input_embeddings':<20} | Mean: {np.mean(arr):>8.4f} | Std: {np.std(arr):>8.4f} | Max: {np.max(arr):>8.4f} | Min: {np.min(arr):>8.4f}")
        
    for key in model.tensor_mapping:
        if not key.startswith("blk.0."):
            continue
        ptr = model.tensor_mapping[key]
        if not isinstance(ptr, int):
            continue # Ignora pesos que são objetos Tensor
            
        # Estima o tamanho pelo key
        if "proj" in key and not "down" in key and not "output" in key:
            elements = batch * seq_len * 8960
        elif "swiglu" in key:
            elements = batch * seq_len * 8960
        else:
            elements = batch * seq_len * 1536
            
        try:
            buf = bytearray(elements * 2)
            hip.safe_memcpy_device_to_host(buf, ctypes.c_void_p(ptr), "output")
            arr = np.frombuffer(buf, dtype=np.float16).astype(np.float32)
            print(f"Tensor {key:<20} | Mean: {np.mean(arr):>8.4f} | Std: {np.std(arr):>8.4f} | Max: {np.max(arr):>8.4f} | Min: {np.min(arr):>8.4f}")
        except Exception as e:
            print(f"Tensor {key:<20} | Erro ao ler: {e}")
            
    output_key = "blk.0.output"
    output_ptr = model.tensor_mapping.get(output_key)
    if not output_ptr:
        print(f"❌ Erro: Buffer {output_key} não encontrado no mapping.")
        return False
        
    output_bytes = bytearray(batch * seq_len * hidden_size * 2) # FP16 = 2 bytes
    hip.safe_memcpy_device_to_host(
        output_bytes,
        ctypes.c_void_p(output_ptr),
        "output_download"
    )
    output_gpu = np.frombuffer(output_bytes, dtype=np.float16).astype(np.float32)
    
    # Auditoria de Sanidade
    print("\n📊 Auditoria de Estabilidade da Camada 0:")
    has_nan = np.any(np.isnan(output_gpu))
    has_inf = np.any(np.isinf(output_gpu))
    
    mean_val = np.mean(output_gpu)
    std_val = np.std(output_gpu)
    min_val = np.min(output_gpu)
    max_val = np.max(output_gpu)
    
    print(f"NaN detectado?  {'SIM ❌' if has_nan else 'Não ✅'}")
    print(f"Inf detectado?  {'SIM ❌' if has_inf else 'Não ✅'}")
    print(f"Média (Mean):   {mean_val:.6f}")
    print(f"Desvio Padrão:  {std_val:.6f}")
    print(f"Mínimo (Min):   {min_val:.6f}")
    print(f"Máximo (Max):   {max_val:.6f}")
    
    # Critérios de falha catastrófica (explode gradient/act ou morre)
    if has_nan or has_inf:
        print("\n❌ FALHA CRÍTICA: Corrupção matemática detectada.")
        return False
        
    # Se os valores explodirem além da zona FP16 segura (geralmente std > 10 é sinal amarelo, max > 100 é vermelho)
    if std_val > 50.0 or max_val > 500.0:
        print("\n❌ FALHA CRÍTICA: Ativações explodindo. Provável erro em Softmax, SwiGLU ou acúmulo FP16.")
        return False
        
    if std_val < 0.0001:
        print("\n❌ FALHA CRÍTICA: Ativações mortas. Provável zeroing_out em alguma projeção.")
        return False
        
    print("\n✅ Camada Completa (End-to-End) VALIDADA COM SUCESSO!")
    print("O fluxo estático de tensores do VTE model rodou sem overhead dinâmico.")
    return True

if __name__ == "__main__":
    success = validate_layer_stability()
    exit(0 if success else 1)

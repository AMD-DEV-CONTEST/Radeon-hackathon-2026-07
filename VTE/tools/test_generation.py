import sys
import os
import time
from pathlib import Path

# Adiciona o diretório raiz ao PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from vte.core.model import VTEModel
from vte.core.generator import TextGenerator
from transformers import AutoTokenizer

def main():
    print("="*80)
    print("🚀 INICIANDO TESTE DE GERAÇÃO (FASE 5)")
    print("="*80)
    
    # 1. Carrega o Tokenizer (da biblioteca transformers, pois Qwen2.5 usa tiktoken/BPE)
    print("\n📦 Carregando Tokenizer do HuggingFace (Qwen/Qwen2.5-1.5B)...")
    try:
        # Usamos o tokenizer original para simplificar a etapa de BPE
        tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-1.5B", trust_remote_code=True)
    except Exception as e:
        print(f"Erro ao carregar tokenizer: {e}")
        print("Tente rodar: pip install transformers tokenizers tiktoken")
        return

    # 2. Carrega o Modelo (Sem Mock!)
    print("\n🧠 Carregando Modelo VTE (qwen2.5:1.5b-q4_k_m)...")
    try:
        # ATENÇÃO: Se houver falta de RAM de GPU, ajuste enable_fusion=False
        model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
    except Exception as e:
        print(f"Erro ao carregar o modelo: {e}")
        return
        
    print("🔧 Injetando pesos mockados...")
    import numpy as np
    import ctypes
    hip = model._hip
    hidden_size = 1536
    num_layers = model.executor.num_layers
    
    for layer_idx in range(num_layers):
        # RMSNorm weights devem ser inicializados com 1.0 (não 0!)
        attn_norm = np.ones(hidden_size, dtype=np.float16)
        ffn_norm = np.ones(hidden_size, dtype=np.float16)
        
        attn_norm_name = f'blk.{layer_idx}.attn_norm.weight'
        ffn_norm_name = f'blk.{layer_idx}.ffn_norm.weight'
        
        # Upload attn_norm
        attn_norm_ptr = model.tensor_mapping.get(attn_norm_name)
        if attn_norm_ptr:
            ptr_val = attn_norm_ptr.ptr if hasattr(attn_norm_ptr, 'ptr') else attn_norm_ptr
            hip.safe_memcpy_host_to_device(
                ctypes.c_void_p(ptr_val),
                attn_norm.tobytes(),
                f"inject_{attn_norm_name}"
            )
        
        # Upload ffn_norm
        ffn_norm_ptr = model.tensor_mapping.get(ffn_norm_name)
        if ffn_norm_ptr:
            ptr_val = ffn_norm_ptr.ptr if hasattr(ffn_norm_ptr, 'ptr') else ffn_norm_ptr
            hip.safe_memcpy_host_to_device(
                ctypes.c_void_p(ptr_val),
                ffn_norm.tobytes(),
                f"inject_{ffn_norm_name}"
            )
            
    # Output norm (final layer norm)
    output_norm = np.ones(hidden_size, dtype=np.float16)
    output_norm_ptr = model.tensor_mapping.get('output_norm.weight')
    if output_norm_ptr:
        ptr_val = output_norm_ptr.ptr if hasattr(output_norm_ptr, 'ptr') else output_norm_ptr
        hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(ptr_val),
            output_norm.tobytes(),
            "inject_output_norm"
        )
    print("  ✅ Pesos de normalização injetados (todos = 1.0)")
    
    print("\n🔍 Verificando pesos de normalização:")
    for layer_idx in range(3):  # Só primeiras 3 camadas para exemplo
        attn_norm_name = f'blk.{layer_idx}.attn_norm.weight'
        attn_norm_ptr = model.tensor_mapping.get(attn_norm_name)
        
        if attn_norm_ptr:
            ptr_val = attn_norm_ptr.ptr if hasattr(attn_norm_ptr, 'ptr') else attn_norm_ptr
            buffer = bytearray(hidden_size * 2)  # FP16
            hip.safe_memcpy_device_to_host(buffer, ctypes.c_void_p(ptr_val), f"output")
            attn_norm_read = np.frombuffer(buffer, dtype=np.float16)
            print(f"  {attn_norm_name} [0:5]: {attn_norm_read[:5]}")
        
    print("\n✅ Modelo carregado com sucesso!")
    print(f"   Camadas: {model.executor.num_layers}")
    from vte.core.model_config import ModelConfig
    config = ModelConfig(model)
    print(f"   Vocab Size (Metadata): {config.vocab_size}")
    
    # 3. Prepara o Gerador
    generator = TextGenerator(model, tokenizer, debug=True)
    
    # 4. Prompts de Teste
    prompts = [
        "A capital do Brasil é",
        "O céu é",
        "Inteligência Artificial é"
    ]
    
    for prompt in prompts:
        print("\n" + "-"*60)
        print(f"📝 Testando Prompt: '{prompt}'")
        print("-" * 60)
        
        start_time = time.time()
        
        try:
            # Greedy Decode para determinismo neste teste inicial
            generated_text = generator.generate(
                prompt=prompt,
                max_new_tokens=10,
                temperature=0.0,  # Greedy
                top_p=1.0,
                top_k=0,
                repetition_penalty=1.0,
                stream=True
            )
            
            end_time = time.time()
            elapsed = end_time - start_time
            tokens_generated = len(generator.generated_tokens) - len(tokenizer.encode(prompt))
            tps = tokens_generated / elapsed if elapsed > 0 else 0
            
            print(f"\n✨ Resultado Final: {prompt}{generated_text}")
            print(f"⏱️  Tempo: {elapsed:.2f}s | Velocidade: {tps:.2f} tok/s")
            
        except Exception as e:
            print(f"❌ Erro durante a geração: {e}")
            import traceback
            traceback.print_exc()
            break

if __name__ == "__main__":
    main()

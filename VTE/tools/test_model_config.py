# tools/test_model_config.py
import sys
from pathlib import Path

# Adiciona o diretório raiz ao PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from vte.core.model import VTEModel
from vte.core.model_config import ModelConfig
from transformers import AutoTokenizer

print("🧪 Testando ModelConfig...")

# Carrega modelo
model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-1.5B", trust_remote_code=True)

# Cria ModelConfig
config = ModelConfig(model)

print(f"✅ hidden_size: {config.hidden_size}")
print(f"✅ num_attention_heads: {config.num_attention_heads}")
print(f"✅ num_key_value_heads: {config.num_key_value_heads}")
print(f"✅ num_hidden_layers: {config.num_hidden_layers}")
print(f"✅ intermediate_size: {config.intermediate_size}")
print(f"✅ vocab_size (do tokenizer): {tokenizer.vocab_size}")

print("\n✅ ModelConfig funcionando corretamente!")

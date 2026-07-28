import os
import sys

# Adiciona o diretório raiz ao PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

print("🚀 Iniciando teste de geração real...")

model = VTEModel.from_pretrained(
    "qwen2.5:1.5b-q4_k_m",
    use_hip_graph=False,  # Começa sem graphs para debug
    enable_fusion=False    # Começa sem fusion para validar kernels individuais
)

print("\n📝 Gerando texto...")
response_gen = model.generate(
    "Explique o que é inteligência artificial em uma frase.",
    max_tokens=20,
    temperature=0.7
)
response = "".join(list(response_gen))

print(f"\n✅ Response:\n{response}")

# Validação de sucesso
if len(response) > 10 and not all(c in ".,!? " for c in response):
    print("\n🎉 SUCESSO: Geração de texto real funcionando!")
else:
    print("\n❌ FALHA: Output parece garbage")

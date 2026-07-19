import unicodedata

def normalize(text: str) -> str:
    """
    Normaliza o texto para NFC (Normalization Form Canonical Composition)
    conforme esperado pelo Qwen2.5 e outros modelos modernos.

    NÃO faz strip() -- bug real encontrado depurando geração incoerente do
    Llama 3.1: `encode()` chama `normalize()` sobre o PROMPT JÁ RENDERIZADO
    pelo chat template (`apply_chat_template()`), não sobre texto cru do
    usuário. Todo chat template usado aqui termina em espaço em branco
    estruturalmente significativo -- Llama 3.1 fecha em
    "<|end_header_id|>\n\n" (a posição exata onde a resposta do assistente
    deve começar), Qwen2.5/Qwen3.5 fecham em "<|im_start|>assistant\n". Um
    `.strip()` aplicado ao texto inteiro removia esse sufixo, jogando o
    modelo fora da distribuição de treino bem na posição mais crítica do
    prompt -- confirmado isolando `encode('hello\\n\\n')`, que devolvia só o
    token de 'hello', sem o token de '\\n\\n' (id 271 no vocabulário do
    Llama 3.1, presente e resolvido corretamente quando testado sem o
    strip). Se algum dia for necessário limpar espaço em branco incidental
    de texto de usuário cru, isso deve acontecer ANTES da renderização do
    template (ex.: em `_coerce_chat_messages`), nunca aqui.
    """
    return unicodedata.normalize("NFC", text)

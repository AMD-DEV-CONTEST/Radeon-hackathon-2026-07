"""
ggml_types.py -- fonte única de verdade pra IDs de dtype GGML e o tamanho em
bytes de cada bloco quantizado.

Antes desta sessão, `GGML_TYPE_Q4_K = 12`/`GGML_TYPE_Q6_K = 14`/
`GGML_TYPE_Q8_0 = 8` eram redeclarados à mão em qwen_mapper.py,
granite_mapper.py e qwen3_5_mapper.py (cada arquivo só declarava o que
usava), e a fórmula de bytes-por-bloco de cada dtype (`(elementos//256)*144`
pra Q4_K, etc.) estava duplicada e parcialmente hardcoded em
gguf_parser.py::_calculate_tensor_size e em cada `_calculate_fp16_size` dos
3 mappers. Um tensor Q5_0 real (Qwen2.5 0.5B, draft model) expôs o problema:
nenhum desses lugares sabia o tamanho de bloco certo, e o carregamento
corrompeu silenciosamente até virar `HIPSafetyError`.

`gguf` (pip, `gguf>=0.19.0`, já dependência obrigatória do projeto --
`pyproject.toml`) expõe `GGML_QUANT_SIZES[GGMLQuantizationType]` como
tabela canônica de (elementos_por_bloco, bytes_por_bloco) pra TODO tipo
GGML conhecido -- inclusive tipos que nunca apareceram num modelo real
registrado aqui ainda (Q8_K, Q2_K, Q3_K, etc.). Reusar essa tabela em vez
de manter uma cópia à mão elimina a classe inteira de bug "esquecemos de
atualizar uma das N cópias" -- e corrige por construção um bug real
encontrado só por auditoria (não por crash) nesta sessão: a fórmula antiga
de Q8_K em gguf_parser.py usava 272 bytes/bloco; o valor real (confirmado
contra `gguf.GGML_QUANT_SIZES`) é 292.
"""
from gguf import GGMLQuantizationType as _T
from gguf import GGML_QUANT_SIZES as _QUANT_SIZES
from vte.bridge.errors import HIPSafetyError

GGML_TYPE_F32 = _T.F32.value
GGML_TYPE_F16 = _T.F16.value
GGML_TYPE_Q4_0 = _T.Q4_0.value
GGML_TYPE_Q4_1 = _T.Q4_1.value
GGML_TYPE_Q5_0 = _T.Q5_0.value
GGML_TYPE_Q5_1 = _T.Q5_1.value
GGML_TYPE_Q8_0 = _T.Q8_0.value
GGML_TYPE_Q2_K = _T.Q2_K.value
GGML_TYPE_Q3_K = _T.Q3_K.value
GGML_TYPE_Q4_K = _T.Q4_K.value
GGML_TYPE_Q5_K = _T.Q5_K.value
GGML_TYPE_Q6_K = _T.Q6_K.value
GGML_TYPE_Q8_K = _T.Q8_K.value
GGML_TYPE_BF16 = _T.BF16.value


def block_size_bytes(dtype: int, n_elements: int) -> int:
    """Tamanho em bytes que `n_elements` elementos do dtype GGML `dtype`
    ocupam CRUS (quantizados, como estão no arquivo/na VRAM quando roteados
    pro GEMV in-kernel) -- não o tamanho dequantizado pra FP16/FP32.

    Fail-fast em dtype desconhecido: um dtype não reconhecido aqui antes
    caía num fallback silencioso (`elements*2`, como se fosse FP16) só com
    um log de aviso -- exatamente o tipo de suposição silenciosa que
    corrompeu o carregamento do Qwen2.5 0.5B (Q5_0) até virar crash em
    outro lugar. Preferível falhar aqui, alto e cedo, com uma mensagem que
    diz qual dtype é.
    """
    try:
        ggml_type = _T(dtype)
    except ValueError:
        raise HIPSafetyError(
            f"Dtype GGML desconhecido: {dtype}. Não está nem na tabela "
            f"GGML_QUANT_SIZES da lib `gguf` instalada -- verifique a "
            f"versão de `gguf` (requirements.txt) ou se o arquivo GGUF "
            f"está corrompido."
        )
    if ggml_type not in _QUANT_SIZES:
        raise HIPSafetyError(
            f"Dtype GGML {ggml_type.name} ({dtype}) reconhecido pela lib "
            f"`gguf`, mas sem tamanho de bloco na tabela GGML_QUANT_SIZES -- "
            f"provavelmente um tipo experimental/não numérico (ex.: "
            f"metadado). Não deveria aparecer como dtype de tensor real."
        )
    block_elements, block_bytes = _QUANT_SIZES[ggml_type]
    if block_elements == 1:
        return n_elements * block_bytes
    return (n_elements // block_elements) * block_bytes

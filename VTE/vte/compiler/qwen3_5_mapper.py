import ctypes
from typing import Dict
from vte.core.model_config import ModelConfig
from vte.bridge.memory import SlabAllocator, MemoryRegion
from vte.bridge.errors import HIPSafetyError
from vte.compiler.qwen_mapper import ActivationArena, format_oom_error  # genéricos, não específicos do Qwen
from vte.compiler.ggml_types import block_size_bytes
from vte.bridge.logger import get_logger

logger = get_logger(__name__)

# Hiperparâmetros do Qwen 3.5 2B (Q6_K), verificados no GGUF real
# (gguf.GGUFReader) e no config.json real do checkpoint -- não copiados do
# Qwen2.5/Granite. Arquivo próprio, isolado: qwen_mapper.py/granite_mapper.py
# não são tocados (pedido explícito do usuário, zero risco de regressão nos
# dois caminhos já validados).
QWEN35_DEFAULT_LAYERS = 24
QWEN35_DEFAULT_HEAD_COUNT = 8          # full_attention: num_attention_heads
QWEN35_DEFAULT_HEAD_COUNT_KV = 2       # full_attention: num_key_value_heads
QWEN35_DEFAULT_HEAD_DIM = 256          # full_attention: head_dim (config.json)
QWEN35_DEFAULT_ROTARY_DIM = 64         # partial_rotary_factor=0.25 * head_dim=256
QWEN35_DEFAULT_FFN = 6144
QWEN35_DEFAULT_ROPE_THETA = 1.0e7

# Gated DeltaNet (camadas linear_attention) -- confirmado em config.json
# (linear_num_key_heads/linear_num_value_heads/linear_key_head_dim/
# linear_value_head_dim/linear_conv_kernel_dim) e no GGUF real
# (blk.N.ssm_*.weight/blk.N.attn_qkv.weight/blk.N.attn_gate.weight).
QWEN35_LINEAR_NUM_HEADS = 16     # num_k_heads == num_v_heads (confirmado)
QWEN35_LINEAR_HEAD_K_DIM = 128
QWEN35_LINEAR_HEAD_V_DIM = 128
QWEN35_LINEAR_KEY_DIM = QWEN35_LINEAR_HEAD_K_DIM * QWEN35_LINEAR_NUM_HEADS      # 2048
QWEN35_LINEAR_VALUE_DIM = QWEN35_LINEAR_HEAD_V_DIM * QWEN35_LINEAR_NUM_HEADS    # 2048
QWEN35_CONV_DIM = QWEN35_LINEAR_KEY_DIM * 2 + QWEN35_LINEAR_VALUE_DIM           # 6144
QWEN35_CONV_KERNEL_SIZE = 4

# layer_types real (config.json, "layer_types": [...]) -- padrão fixo de 4
# em 4: 3 linear_attention + 1 full_attention. Confirmado, não um "a cada N"
# genérico -- os índices exatos de full_attention são 3, 7, 11, 15, 19, 23.
QWEN35_FULL_ATTENTION_LAYERS = frozenset({3, 7, 11, 15, 19, 23})


def is_full_attention_layer(layer_idx: int) -> bool:
    return layer_idx in QWEN35_FULL_ATTENTION_LAYERS


GGML_TYPE_Q6_K = 14
GGML_TYPE_Q8_0 = 8


def is_raw_q6k_weight(name: str, tensor_info: dict) -> bool:
    """
    Fonte única de verdade pro roteamento cru de Q6_K no Qwen3.5 -- própria
    deste arquivo, não reaproveita `qwen_mapper.py::is_raw_q6k_weight` (essa
    é restrita a `ffn_down`/`token_embd` porque o GGUF do Qwen2.5 MISTURA
    Q4_K e Q6_K; aqui não há mistura nenhuma).

    Confirmado no GGUF real (gguf.GGUFReader): as 133 ocorrências de Q6_K
    são inteiramente `token_embd.weight`, `attn_qkv.weight`, `attn_gate.weight`,
    `ffn_gate.weight`, `ffn_up.weight`, `ffn_down.weight` (camadas
    linear_attention) e TAMBÉM `attn_q.weight`/`attn_k.weight`/
    `attn_v.weight`/`attn_output.weight` das 6 camadas full_attention --
    ou seja, TODA matriz grande do modelo, sem exceção. As 133 ocorrências
    de F32 são só vetores pequenos (normas, ssm_a, dt_bias, ssm_norm) e as
    54 de Q8_0 são os tensores pequenos/médios do Gated DeltaNet
    (ssm_alpha/beta/out).

    MAS: attn_q/attn_k/attn_v/attn_output PRECISAM ser excluídos do
    roteamento cru (mesma exclusão que qwen_mapper.py/granite_mapper.py já
    fazem, pelo mesmo motivo) -- os kernels FUNDIDOS de QKV+RoPE
    (fused_norm_matmul_rope, split_k_qkv_pass1/pass2, usados nas 6 camadas
    full_attention do Qwen3.5) leem esses pesos como `__half*` puro, sem
    nenhuma lógica de dequant Q6_K embutida. Bug real encontrado nesta
    sessão: sem esta exclusão, essas 4 matrizes ficavam cruas na VRAM mas
    o kernel fundido interpretava os bytes Q6_K empacotados diretamente
    como FP16 -- produzindo NaN a partir da primeira camada full_attention
    (camada 3), contaminando o resto do modelo a partir dali.
    """
    if name.endswith(("attn_q.weight", "attn_k.weight", "attn_v.weight", "attn_output.weight")):
        return False
    return tensor_info.get('dtype') == GGML_TYPE_Q6_K


class Qwen3_5TensorMapper:
    """
    Espelha a interface pública de QwenTensorMapper/GraniteTensorMapper, com
    os números do Qwen 3.5 2B. Duas diferenças estruturais importantes em
    relação aos outros dois mappers (não são bugs, são a natureza híbrida
    real da arquitetura, ver plano):

    1. KV cache só é alocado para as 6 camadas `full_attention` (índices em
       QWEN35_FULL_ATTENTION_LAYERS), não para as 24 -- as 18 camadas
       `linear_attention` não têm KV cache nenhum, têm o estado do Gated
       DeltaNet no lugar (item 2).
    2. Estado persistente NOVO por camada `linear_attention`: a matriz de
       estado do Gated DeltaNet (`[16, 128, 128]` floats, tamanho FIXO --
       NÃO cresce com context_length, ao contrário do KV cache) mais o
       histórico curto do conv1d causal (`[conv_dim, 3]` floats).

    Fase 1 (esta primeira versão): todos os pesos dequantizados para FP16
    no carregamento (nenhum tensor roteado cru para Q6_K/Q8_0 in-kernel
    ainda) -- mais simples e mais seguro para uma primeira passagem
    correta; ver "Why QKV projection is fused" no README sobre a mesma
    disciplina de correção-primeiro já usada no resto do projeto. Rotear
    tensores específicos para dequant in-kernel fica para depois de medir,
    não uma escolha de dia 1.
    """

    def __init__(self, parser, metadata: dict):
        self.parser = parser
        self.metadata = metadata

        class DummyModel:
            pass
        dummy = DummyModel()
        dummy.metadata = metadata
        self.config = ModelConfig(dummy)

    def _calculate_fp16_size(self, tensor_info: dict, name: str = "") -> int:
        """Tamanho em bytes a alocar na VRAM. As matrizes grandes em Q6_K
        (a maioria dos bytes do modelo -- token_embd, attn_qkv, attn_gate,
        ffn_*) ficam CRUAS (roteadas ao gemv_q6k/embedding_lookup_q6k já
        existentes, mesmos kernels que o Qwen2.5 usa pra Q6_K -- formato
        idêntico, nenhum kernel novo necessário aqui). Os tensores pequenos
        do Gated DeltaNet (Q8_0: ssm_alpha/beta/out) e os F32 (normas,
        A_log, dt_bias, conv1d, ssm_norm) ficam dequantizados/mantidos em
        FP16 -- são pequenos o bastante (a diferença é da ordem de KB por
        camada) pra não valer o kernel extra de dequant in-kernel, e
        ssm_out tem a mesma forma [2048,2048] que o Granite já MEDIU ser
        mais lento cru em Q8_0 (blocos de 34B não alinham a 16B) do que em
        FP16 -- reaproveitando esse achado, não uma suposição nova."""
        elements = 1
        for dim in tensor_info["shape"]:
            elements *= dim
        if is_raw_q6k_weight(name, tensor_info):
            # Fonte única `ggml_types.block_size_bytes` (reusa
            # gguf.GGML_QUANT_SIZES) em vez da aritmética hardcoded que
            # existia aqui antes -- a decisão de "fica cru" continua em
            # is_raw_q6k_weight (própria deste arquivo), intocada.
            return block_size_bytes(tensor_info["dtype"], elements)
        return elements * 2  # FP16 (F32 dequantizado a partir daqui, ou Q8_0 dequantizado)

    def calculate_memory_requirements(self, context_length: int = 2048, batch_size: int = 1) -> dict:
        weights_total = sum(self._calculate_fp16_size(t, n) for n, t in self.parser.tensors.items())

        layers = self.metadata.get("block_count", QWEN35_DEFAULT_LAYERS)
        full_attn_layers = len(QWEN35_FULL_ATTENTION_LAYERS)
        kv_heads = self.metadata.get("attention.head_count_kv", QWEN35_DEFAULT_HEAD_COUNT_KV)
        head_dim = self.metadata.get("attention.key_length", QWEN35_DEFAULT_HEAD_DIM)
        # Só as camadas full_attention têm KV cache -- diferença estrutural
        # em relação a Qwen2.5/Granite (onde TODA camada tem).
        kv_pool_size = full_attn_layers * 2 * kv_heads * head_dim * 2 * context_length * batch_size

        rotary_dim = self.metadata.get("rotary_dim", QWEN35_DEFAULT_ROTARY_DIM)
        rope_size = context_length * rotary_dim * 2

        # Estado do Gated DeltaNet: tamanho FIXO por camada linear_attention,
        # não escala com context_length nem batch_size na formulação
        # recorrente (1 estado por sequência ativa -- Fase 1 é batch_size=1
        # apenas, mesma limitação que o resto do projeto tem hoje).
        linear_attn_layers = layers - full_attn_layers
        state_size_per_layer = QWEN35_LINEAR_NUM_HEADS * QWEN35_LINEAR_HEAD_K_DIM * QWEN35_LINEAR_HEAD_V_DIM * 4  # fp32
        conv_history_size_per_layer = QWEN35_CONV_DIM * (QWEN35_CONV_KERNEL_SIZE - 1) * 4  # fp32
        linear_attn_state_size = linear_attn_layers * (state_size_per_layer + conv_history_size_per_layer)

        ffn_intermediate_size = self.metadata.get("feed_forward_length", QWEN35_DEFAULT_FFN)
        arena_size = int((context_length * ffn_intermediate_size * 2) * 1.2) * batch_size

        buffers_size = 20 * 1024 * 1024

        total = weights_total + kv_pool_size + rope_size + linear_attn_state_size + arena_size + buffers_size
        logger.warning(
            f"DEBUG REQS (Qwen3.5): weights={weights_total/1024**2:.1f} MB, "
            f"kv={kv_pool_size/1024**2:.1f} MB ({full_attn_layers} camadas full_attention), "
            f"linear_attn_state={linear_attn_state_size/1024**2:.1f} MB ({linear_attn_layers} camadas), "
            f"rope={rope_size/1024**2:.1f} MB, arena={arena_size/1024**2:.1f} MB, total={total/1024**2:.1f} MB"
        )
        from vte.config import VRAM_PADDING_BYTES
        return {
            'weights': weights_total,
            'kv_cache': kv_pool_size,
            'linear_attn_state': linear_attn_state_size,
            'arena': arena_size,
            'rope': rope_size,
            'buffers': buffers_size,
            'total': total,
            'with_margin': int(total + VRAM_PADDING_BYTES),
        }

    def map_and_allocate_tensors(self, allocator: SlabAllocator, hip_runtime, profiler=None, context_length=2048, batch_size=1) -> Dict[str, int]:
        logger.info(f"[Qwen3.5] Iniciando Mapeamento Fail-Fast e Alocação (batch_size={batch_size})")

        reqs = self.calculate_memory_requirements(context_length, batch_size)
        total_required = reqs['total']
        free_vram = allocator.get_stats()['free_bytes']

        if total_required > free_vram:
            raise HIPSafetyError(format_oom_error("Qwen3.5", total_required, allocator, context_length))

        tensor_mapping = {}
        for name, t_info in self.parser.tensors.items():
            if t_info.get('is_tied', False):
                continue
            fp16_size = self._calculate_fp16_size(t_info, name)
            tensor_hash = f"{name}_{fp16_size}"

            if name == "output.weight":
                if t_info.get('is_tied', False) or t_info['size'] == 0:
                    tied_name = t_info.get('tied_to', "token_embd.weight")
                    if tied_name in tensor_mapping:
                        tensor_mapping[name] = tensor_mapping[tied_name]
                        logger.info(f"Tied embedding resolvido: {name} aponta para {tied_name}")
                        continue

            region = MemoryRegion.WEIGHTS
            if profiler:
                profiler.track_allocation(name, fp16_size / (1024 * 1024), "WEIGHTS")
            ptr = allocator.allocate(fp16_size, tag=tensor_hash, region=region)
            tensor_mapping[name] = ptr

        # KV Cache Pool -- só para as camadas full_attention (índices fixos
        # em QWEN35_FULL_ATTENTION_LAYERS), diferente de Qwen2.5/Granite
        # onde toda camada participa.
        kv_pool_size = reqs['kv_cache']
        kv_ptr = allocator.allocate(kv_pool_size, "KV_CACHE_POOL", MemoryRegion.KV_CACHE)
        if profiler:
            profiler.track_allocation("KV Cache Pool", kv_pool_size / (1024*1024), "KV_CACHE")

        kv_heads = self.metadata.get('attention.head_count_kv', QWEN35_DEFAULT_HEAD_COUNT_KV)
        head_dim = self.metadata.get('attention.key_length', QWEN35_DEFAULT_HEAD_DIM)
        layer_kv_size_per_batch = kv_heads * head_dim * 2 * context_length
        layer_kv_size = layer_kv_size_per_batch * batch_size

        current_kv_offset = kv_ptr.ptr
        for l in sorted(QWEN35_FULL_ATTENTION_LAYERS):
            tensor_mapping[f'blk.{l}.kv_cache.k'] = current_kv_offset
            tensor_mapping[f'blk.{l}.kv_cache.v'] = current_kv_offset + layer_kv_size
            current_kv_offset += layer_kv_size * 2
        tensor_mapping['kv_batch_stride_elements'] = layer_kv_size_per_batch // 2

        # Estado do Gated DeltaNet -- NOVO em relação aos outros mappers.
        # Uma alocação única (igual ao KV cache), com offset fixo por
        # camada linear_attention. Tamanho fixo, não recebe stride de
        # context_length nem de batch (Fase 1 = batch_size=1 apenas).
        state_size_per_layer = QWEN35_LINEAR_NUM_HEADS * QWEN35_LINEAR_HEAD_K_DIM * QWEN35_LINEAR_HEAD_V_DIM * 4
        conv_hist_size_per_layer = QWEN35_CONV_DIM * (QWEN35_CONV_KERNEL_SIZE - 1) * 4
        linear_attn_layers = sorted(set(range(QWEN35_DEFAULT_LAYERS)) - QWEN35_FULL_ATTENTION_LAYERS)
        total_state_size = reqs['linear_attn_state']
        state_ptr = allocator.allocate(total_state_size, "GATED_DELTANET_STATE", MemoryRegion.KV_CACHE)
        if profiler:
            profiler.track_allocation("Gated DeltaNet State", total_state_size / (1024*1024), "KV_CACHE")

        # Zera o estado e o histórico de conv1d antes do primeiro uso --
        # ambos são LIDOS integralmente a cada passo de decode (não só a
        # partir de uma posição já escrita, como o KV cache), então
        # hipMalloc (que não zera) deixaria lixo residual de VRAM entrar
        # direto na recorrência no primeiro token. A referência real
        # (torch_recurrent_gated_delta_rule) assume `torch.zeros(...)`
        # quando não há estado anterior -- este memset reproduz isso.
        hip_runtime.safe_memset(
            ctypes.c_void_p(state_ptr.ptr), total_state_size, tag="GATED_DELTANET_STATE"
        )

        current_state_offset = state_ptr.ptr
        for l in linear_attn_layers:
            tensor_mapping[f'blk.{l}.linear_attn_state'] = current_state_offset
            current_state_offset += state_size_per_layer
            tensor_mapping[f'blk.{l}.conv1d_history'] = current_state_offset
            current_state_offset += conv_hist_size_per_layer

        # Activation Arena
        arena_size = reqs['arena']
        arena_ptr = allocator.allocate(arena_size, "ACTIVATION_ARENA", MemoryRegion.ACTIVATIONS)
        if profiler:
            profiler.track_allocation("Activation Arena", arena_size / (1024*1024), "ACTIVATIONS")
        tensor_mapping['input_embeddings'] = arena_ptr.ptr
        tensor_mapping['input_ids'] = arena_ptr.ptr + 1048576

        # RoPE cache -- só pras camadas full_attention, com rotary_dim=64
        # (não head_dim=256 inteiro). Reaproveita RoPECacheBuilder sem
        # nenhuma mudança: chamar com head_dim=rotary_dim já produz o
        # padrão "sliced" certo (validado na Fase 1 com diferença zero
        # contra a fórmula real).
        logger.info("[Qwen3.5] Construindo RoPE Cache (parcial, rotary_dim=64)...")
        self._build_and_upload_rope_cache(tensor_mapping, allocator, hip_runtime, context_length)

        return tensor_mapping

    def _build_and_upload_rope_cache(self, tensor_mapping: dict, allocator, hip_runtime, context_length: int):
        from vte.compiler.rope_cache_builder import RoPECacheBuilder

        rotary_dim = self.metadata.get('rotary_dim', QWEN35_DEFAULT_ROTARY_DIM)
        rope_theta = self.metadata.get('rope.freq_base', QWEN35_DEFAULT_ROPE_THETA)

        # head_dim=rotary_dim (não o head_dim=256 completo) -- é isso que
        # faz o builder genérico já existente produzir o cache parcial
        # certo, sem nenhuma mudança nele.
        builder = RoPECacheBuilder(max_seq_len=context_length, head_dim=rotary_dim, rope_theta=rope_theta)
        cos_cache, sin_cache = builder.build_cache()
        cos_ptr, sin_ptr = builder.upload_to_vram(cos_cache, sin_cache, hip_runtime, allocator)

        tensor_mapping['rope_cos'] = cos_ptr
        tensor_mapping['rope_sin'] = sin_ptr
        logger.info(f"[Qwen3.5] RoPE cache (rotary_dim={rotary_dim}) adicionado: cos=0x{cos_ptr:016x}, sin=0x{sin_ptr:016x}")

from typing import Dict
from vte.core.model_config import ModelConfig
from vte.bridge.memory import SlabAllocator, MemoryBlock, MemoryRegion
from vte.bridge.errors import HIPSafetyError
from vte.compiler.ir import IRGraph, IRNode, FusedGateUpProjNode, QuantizationInfo
from vte.compiler.rope_computer import compute_rope_cache
from vte.compiler.ggml_types import block_size_bytes
from vte.bridge.logger import get_logger

logger = get_logger(__name__)


def format_oom_error(model_label: str, total_required: int, allocator: SlabAllocator, context_length: int) -> str:
    """Mensagem de OOM preventivo compartilhada pelos 3 mappers (Qwen2.5/
    Granite/Qwen3.5) -- fonte única, mesma checagem `total_required >
    free_bytes` de antes, só com informação de produto (nome do modelo,
    VRAM real da GPU do usuário, sugestão de reduzir context_length) em vez
    de só os dois números crus. A VRAM total já vem de hipGetDeviceProperties
    (real, não um valor fixo assumido) -- numa GPU maior (ex. RX 7900 XTX,
    24GB) a mesma checagem aceita modelos maiores automaticamente."""
    stats = allocator.get_stats()
    total_vram_gb = stats['total_bytes'] / (1024 ** 3)
    free_vram_gb = stats['free_bytes'] / (1024 ** 3)
    required_gb = total_required / (1024 ** 3)
    return (
        f"OOM Preventivo: '{model_label}' precisa de {required_gb:.2f}GB "
        f"(context_length={context_length}), mas esta GPU só tem "
        f"{free_vram_gb:.2f}GB livres de {total_vram_gb:.2f}GB totais. "
        f"Tente reduzir o context_length ou usar um modelo/quantização menor."
    )


# IDs de tipo GGML relevantes.
GGML_TYPE_Q4_K = 12
GGML_TYPE_Q6_K = 14
GGML_TYPE_Q5_0 = 6


def is_raw_q4k_weight(name: str, tensor_info: dict) -> bool:
    """
    Fonte única de verdade: True se o tensor fica CRU em Q4_K na VRAM (roteado
    ao gemv_q4k). Precisa casar exatamente com o roteamento do executor.

    Cobertos: ffn_gate/ffn_up/ffn_down (Q4_K) e, desde esta sessão, também
    attn_q/attn_k/attn_output quando vierem em Q4_K (mesma mudança já feita
    pro Granite: usuário pediu reduzir VRAM depois de medir que o Granite cru
    ficou MAIS RÁPIDO, não mais lento -- ler menos bytes da VRAM compensou a
    perda da fusão QKV). Fusão QKV desativada automaticamente quando esses
    pesos estão crus (ver checagem em fallback_executor.py/
    hip_graph_executor.py contra RAW_Q4K_WEIGHTS/RAW_Q6K_WEIGHTS/
    RAW_Q8_0_WEIGHTS) -- sem isso o kernel fundido leria os pesos como
    `__half*` puro e produziria NaN.
    """
    if tensor_info.get('dtype') != GGML_TYPE_Q4_K:
        return False
    return (name.endswith("ffn_gate.weight")
            or name.endswith("ffn_up.weight")
            or name.endswith("ffn_down.weight")
            or name.endswith("attn_q.weight")
            or name.endswith("attn_k.weight")
            or name.endswith("attn_output.weight")
            # Qwen2.5 7B: token_embd em Q4_K (no 1.5B é Q6_K). Cru economiza
            # ~730MB de VRAM; o embedding lookup dequantiza a linha do token
            # sob demanda via embedding_lookup_q4k. Diferente do 1.5B, aqui
            # token_embd NÃO é tied ao lm_head (output.weight é um tensor
            # Q6_K separado), então este kernel é seu único consumidor.
            or name == "token_embd.weight")


def is_raw_q6k_weight(name: str, tensor_info: dict) -> bool:
    """
    True se o tensor fica CRU em Q6_K na VRAM (roteado ao gemv_q6k / embedding
    lookup dequantizado).

    Cobertos: ffn_down (Q6_K, K=8960), token_embd (Fase D.1 — tied embeddings:
    o mesmo tensor serve de peso do lm_head via gemv_q6k E do embedding lookup
    via embedding_lookup_q6k, dequantizado sob demanda em ambos os casos; sem
    isso o lm_head continuaria pagando ~277 MB de leitura extra por token),
    attn_v quando vier em Q6_K (mesmo motivo de is_raw_q4k_weight acima -- ver
    comentário lá) e, desde o suporte ao Qwen2.5 7B, `output.weight` quando
    vier em Q6_K separado (NÃO tied). No 1.5B o output é tied ao token_embd
    (mesma referência, uma cópia só, pulada no loop de alocação por
    is_tied=True), então esta linha não o afeta; mas o 7B tem `output.weight`
    como tensor Q6_K próprio (~1GB dequantizado a FP16) -- roteá-lo cru
    economiza ~590MB de VRAM e o lm_head já sabe lê-lo via gemv_q6k (mesmo
    caminho da tied embedding, só que apontando para output.weight)."""
    if tensor_info.get('dtype') != GGML_TYPE_Q6_K:
        return False
    return (name.endswith("ffn_down.weight") or name == "token_embd.weight"
            or name == "output.weight"
            or name.endswith("attn_v.weight"))


def is_raw_q5_0_weight(name: str, tensor_info: dict) -> bool:
    """
    True se o tensor fica CRU em Q5_0 na VRAM (roteado ao gemv_q5_0).

    Achado ao otimizar VRAM do draft model (Qwen2.5 0.5B, Fase 5,
    speculative decoding): esse GGUF mistura Q5_0 em attn_q/attn_k/attn_v/
    attn_output/ffn_gate/ffn_up (132 de 290 tensores, ~165MB no arquivo) --
    até aqui só existia DEQUANT de Q5_0 pra FP16 no load
    (dequantizer.py::dequantize_q5_0), nunca um kernel que lê os bytes crus
    direto no GEMV, então TODOS esses 132 tensores viravam ~480MB em FP16 na
    VRAM (quase 3x maior, ~70% do peso total do draft). Mesmo cuidado de
    is_raw_q4k_weight/is_raw_q6k_weight: como attn_q/k/v/output entram na
    lista, a fusão QKV precisa ficar desativada quando qualquer um deles
    estiver cru em Q5_0 (ver checagem contra RAW_Q5_0_WEIGHTS em
    fallback_executor.py/hip_graph_executor.py/batched executors) -- sem
    isso o kernel fundido leria os bytes Q5_0 como `__half*` puro (mesmo bug,
    já visto e documentado em docs/BUGS.md, que corrigimos nesta sessão pra
    Q4_K/Q6_K/Q8_0 quando dois modelos coexistem)."""
    if tensor_info.get('dtype') != GGML_TYPE_Q5_0:
        return False
    return (name.endswith("attn_q.weight") or name.endswith("attn_k.weight")
            or name.endswith("attn_v.weight") or name.endswith("attn_output.weight")
            or name.endswith("ffn_gate.weight") or name.endswith("ffn_up.weight")
            or name.endswith("ffn_down.weight"))


class ActivationArena:
    """
    Arena Allocator para ativações efêmeras.
    
    O SlabAllocator aloca UM bloco gigante (ex: 50MB) na região ACTIVATIONS.
    Esta classe gerencia sub-alocações dentro desse bloco usando Bump Pointer.
    
    O reset (current_offset = 0) só deve ser chamado APÓS hipDeviceSynchronize(),
    garantindo que a GPU terminou de usar as ativações da camada anterior.
    """
    def __init__(self, slab_block: MemoryBlock, start_offset: int = 0):
        self.block = slab_block
        self.start_offset = start_offset
        self.current_offset = start_offset
        self._synchronized = True
    
    def allocate(self, size_bytes: int, alignment: int = 64) -> tuple[int, int]:
        """Retorna (absolute_ptr, offset_within_block)"""
        # A flag _synchronized é usada para avisar se a arena não foi resetada corretamente.
        # Nós podemos alocar múltiplos tensores no mesmo ciclo.
        
        aligned_offset = ((self.current_offset + alignment - 1) // alignment) * alignment
        
        if aligned_offset + size_bytes > self.block.size:
            raise HIPSafetyError(
                f"Arena esgotada: {aligned_offset + size_bytes} > {self.block.size}"
            )
        
        ptr = self.block.ptr + aligned_offset
        self.current_offset = aligned_offset + size_bytes
        self._synchronized = False
        
        return ptr, aligned_offset
    
    def reset_after_sync(self):
        """
        Reseta a arena APÓS confirmar que a GPU terminou (via hipDeviceSynchronize).
        Será chamado pelo dispatcher no final de cada camada.
        """
        self.current_offset = self.start_offset
        self._synchronized = True

class QwenTensorMapper:
    """Reaproveitado, sem subclasse, por qualquer arquitetura GQA "chata"
    (RMSNorm->QKV->RoPE->GQA->O-proj->SwiGLU) que não precise de mapeamento
    próprio -- hoje Qwen2.5 e Llama 3.1 (ver `model.py::_load_llama_metadata`).
    `model_label` só troca o nome usado na mensagem de OOM preventivo
    (`format_oom_error`); todo o resto do comportamento é genérico, lido de
    `self.metadata`."""

    def __init__(self, parser, metadata: dict, model_label: str = "Qwen2.5"):
        self.parser = parser
        self.metadata = metadata
        self._model_label = model_label

        # Cria um objeto dummy pra passar pro ModelConfig
        class DummyModel:
            pass
        dummy = DummyModel()
        dummy.metadata = metadata
        self.config = ModelConfig(dummy)

    def calculate_memory_requirements(self, context_length: int = 2048, batch_size: int = 1) -> dict:
        """Calcula a memória necessária para os pesos, cache e arena.

        Os pesos são dequantizados para FP16 no carregamento (weight_loader.py),
        então o espaço reservado usa o tamanho FP16 (elementos * 2 bytes), não o
        tamanho quantizado original do arquivo GGUF.

        Fase I (Batched Decode): batch_size>1 multiplica o KV cache e a
        Activation Arena — cada sequência do batch precisa de seu próprio
        espaço de K/V (elas divergem em conteúdo desde o 1o token gerado) e
        suas próprias ativações intermediárias ([batch, features] em vez de
        [1, features]). Os pesos NÃO multiplicam (são compartilhados/lidos
        1x por todas as sequências do batch — essa reutilização é exatamente
        a alavanca de throughput que a Etapa I.1 validou).
        """
        weights_total = sum(self._calculate_fp16_size(t, n) for n, t in self.parser.tensors.items())

        layers = self.metadata.get("block_count", 28)
        # Bug real encontrado ao adicionar suporte ao Qwen2.5 7B: estes 3
        # valores estavam hardcoded para o 1.5B (kv_heads=2, head_dim=128,
        # ffn=8960) em vez de lidos do metadata real do GGUF -- o 7B tem
        # kv_heads=4 e ffn=18944, então o KV Cache Pool e a Activation
        # Arena eram alocados com METADE do tamanho realmente necessário
        # (`map_and_allocate_tensors`, mais abaixo neste mesmo arquivo, já
        # lia esses valores corretamente do metadata -- só esta função
        # de cálculo de orçamento estava desatualizada). O resultado prático
        # foi um overflow real e silencioso: o KV cache escrito durante o
        # decode (dimensionado certo pelo mapper) invadia a Activation
        # Arena alocada logo depois (dimensionada errado, pequena demais),
        # corrompendo ativações -- a causa raiz do texto sem sentido gerado
        # pelo 7B ("pérdida strugg Rencontre..."), não um problema de
        # quantização ou do modelo em si.
        kv_heads = self.metadata.get("attention.head_count_kv", 2)
        head_dim = self.metadata.get("attention.key_length", 128)
        kv_pool_size = layers * 2 * kv_heads * head_dim * 2 * context_length * batch_size

        rope_size = context_length * head_dim * 2

        ffn_intermediate_size = self.metadata.get("feed_forward_length", 8960)
        arena_size = int((context_length * ffn_intermediate_size * 2) * 1.2) * batch_size

        buffers_size = 20 * 1024 * 1024

        total = weights_total + kv_pool_size + rope_size + arena_size + buffers_size
        logger.warning(f"DEBUG REQS: weights={weights_total / 1024**2} MB, kv={kv_pool_size / 1024**2} MB, rope={rope_size / 1024**2} MB, arena={arena_size / 1024**2} MB, buffers={buffers_size / 1024**2} MB, total={total / 1024**2} MB (batch_size={batch_size})")
        from vte.config import VRAM_PADDING_BYTES
        return {
            'weights': weights_total,
            'kv_cache': kv_pool_size,
            'arena': arena_size,
            'rope': rope_size,
            'buffers': buffers_size,
            'total': total,
            'with_margin': int(total + VRAM_PADDING_BYTES)
        }
        
    def _calculate_tensor_size(self, tensor_info: dict) -> int:
        return tensor_info["size"]

    def _calculate_fp16_size(self, tensor_info: dict, name: str = "") -> int:
        """
        Tamanho em bytes a alocar na VRAM para o tensor.

        Etapa C: os pesos Q4_K roteados para o gemv_q4k ficam CRUS na VRAM
        (n_blocks * 144 bytes / 256 pesos) em vez de dequantizados para FP16.
        Todo o resto continua FP16 (2 bytes/elemento). O critério de "cru" tem
        que casar EXATAMENTE com o roteamento do executor (só gate/up hoje),
        senão um peso cru cairia num kernel FP16 e produziria lixo.
        """
        elements = 1
        for dim in tensor_info["shape"]:
            elements *= dim
        if is_raw_q4k_weight(name, tensor_info) or is_raw_q6k_weight(name, tensor_info) or is_raw_q5_0_weight(name, tensor_info):
            # Tamanho cru real do dtype -- fonte única `ggml_types.block_size_bytes`
            # (reusa gguf.GGML_QUANT_SIZES) em vez da aritmética hardcoded
            # duplicada que existia aqui antes. A DECISÃO de "fica cru"
            # continua em is_raw_q4k_weight/is_raw_q6k_weight, intocada --
            # só o cálculo de QUANTOS bytes isso ocupa mudou.
            return block_size_bytes(tensor_info["dtype"], elements)
        return elements * 2

    def map_and_allocate_tensors(self, allocator: SlabAllocator, hip_runtime, profiler=None, context_length=2048, batch_size=1) -> Dict[str, int]:
        """Mapeia os tensores para a VRAM através do SlabAllocator"""
        logger.info(f"Iniciando Mapeamento Fail-Fast e Alocação (batch_size={batch_size})")

        reqs = self.calculate_memory_requirements(context_length, batch_size)
        total_required = reqs['total']
        free_vram = allocator.get_stats()['free_bytes']

        if total_required > free_vram:
            raise HIPSafetyError(format_oom_error(self._model_label, total_required, allocator, context_length))

        tensor_mapping = {}
        for name, t_info in self.parser.tensors.items():
            if t_info.get('is_tied', False):
                continue

            fp16_size = self._calculate_fp16_size(t_info, name)
            tensor_hash = f"{name}_{fp16_size}"

            # Checagem de Tied Embeddings Output
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
            
        # KV Cache Pool
        kv_pool_size = reqs['kv_cache']
        kv_ptr = allocator.allocate(kv_pool_size, "KV_CACHE_POOL", MemoryRegion.KV_CACHE)
        if profiler:
            profiler.track_allocation("KV Cache Pool", kv_pool_size / (1024*1024), "KV_CACHE")
            
        # Mapeia KV cache para cada camada
        layers = self.config.get('num_hidden_layers', 28)
        kv_heads = self.config.get('attention.head_count_kv', 2)
        head_dim = self.config.get('attention.key_length', 128)
        # IMPORTANTE: usa o parâmetro `context_length` recebido (o mesmo usado
        # para dimensionar kv_pool_size em calculate_memory_requirements),
        # NÃO o metadado "max_position_embeddings"/context_length do GGUF —
        # este último é o contexto NATIVO máximo do modelo (32768 no
        # Qwen2.5), muito maior que o context_length real de execução
        # (2048 por padrão). Usar o valor errado aqui faz o offset de cada
        # camada avançar 16x mais rápido que o pool realmente alocado,
        # escrevendo muito além do KV_CACHE_POOL e corrompendo a Activation
        # Arena e os buffers persistentes alocados logo em seguida.
        # layer_kv_size_per_batch é o tamanho (bytes) de UM dos dois (K ou V)
        # para UMA sequência do batch — fórmula inalterada da era batch=1.
        # Fase I: cada camada agora reserva batch_size vezes esse espaço para
        # K e para V (uma sequência não pode ler/escrever no cache da outra).
        layer_kv_size_per_batch = kv_heads * head_dim * 2 * context_length
        layer_kv_size = layer_kv_size_per_batch * batch_size  # bytes p/ K (ou V) de TODAS as sequências do batch

        # layer_kv_size é o tamanho de UM dos dois (K ou V) — cada camada usa
        # 2x esse tamanho (K + V). O bug original colocava V na METADE do
        # espaço de K (layer_kv_size // 2, sobrepondo com o próprio K) e
        # avançava o offset por camada usando só layer_kv_size (metade do
        # necessário), fazendo o cache K/V de camadas adjacentes se
        # sobreporem — corrompendo silenciosamente a atenção de toda camada
        # após a primeira.
        #
        # Layout de batch (Fase I): dentro do espaço de K (ou de V) de uma
        # camada, a sequência b do batch ocupa
        # [b*layer_kv_size_per_batch, (b+1)*layer_kv_size_per_batch). O
        # tensor_mapping guarda o ponteiro do INÍCIO do slot da sequência 0;
        # os kernels recebem `kv_batch_stride` (em elementos __half, não
        # bytes) e deslocam por `batch_idx * kv_batch_stride` — mesmo padrão
        # de "1 pool único, offset calculado" já usado para camadas/K-V.
        current_kv_offset = kv_ptr.ptr
        for l in range(layers):
            # K cache (início da sequência 0)
            tensor_mapping[f'blk.{l}.kv_cache.k'] = current_kv_offset
            # V cache (logo após todo o bloco de K de todas as sequências)
            tensor_mapping[f'blk.{l}.kv_cache.v'] = current_kv_offset + layer_kv_size
            current_kv_offset += layer_kv_size * 2

        # Stride de batch em ELEMENTOS __half (não bytes) — consistente com a
        # aritmética de ponteiro __half* usada dentro dos kernels de RoPE e
        # FlashAttention. batch_size=1 -> stride igual ao tamanho total do
        # cache por camada (irrelevante, nunca somado a um batch_idx>0).
        tensor_mapping['kv_batch_stride_elements'] = layer_kv_size_per_batch // 2
            
        # Activation Arena
        arena_size = reqs['arena']
        arena_ptr = allocator.allocate(arena_size, "ACTIVATION_ARENA", MemoryRegion.ACTIVATIONS)
        if profiler:
            profiler.track_allocation("Activation Arena", arena_size / (1024*1024), "ACTIVATIONS")
        
        # Fallback registers para testes e nós que esperam estas chaves
        tensor_mapping['input_embeddings'] = arena_ptr.ptr
        tensor_mapping['input_ids'] = arena_ptr.ptr + 1048576 # offset 1MB
            
        # Constrói RoPE Cache
        logger.info("Construindo RoPE Cache...")
        self._build_and_upload_rope_cache(tensor_mapping, allocator, hip_runtime, context_length)
        
        return tensor_mapping
        
    def allocate_batch_runtime_state(
        self, weight_tensor_mapping: Dict, allocator: SlabAllocator, hip_runtime,
        context_length: int, batch_size: int, profiler=None
    ) -> Dict[str, int]:
        """
        Fase II (prep): aloca APENAS o estado dependente de batch (KV cache,
        Activation Arena, RoPE cache) para `batch_size`, reaproveitando os
        PONTEIROS DE PESO já carregados em `weight_tensor_mapping` (pesos não
        mudam com o batch — são lidos 1x e compartilhados por todas as
        sequências, exatamente a alavanca de throughput da Fase I).

        Usado para servir geração batched a partir de um modelo já carregado
        (batch=1) sem duplicar pesos na VRAM — só o KV cache/arena/staging
        (pequenos: dezenas de MB mesmo em batch=4) são alocados de novo.

        CRÍTICO: copia só os ponteiros de PESO real do GGUF (chaves em
        `self.parser.tensors`) — NUNCA o dict inteiro. `weight_tensor_mapping`
        (o tensor_mapping de produção) também contém buffers de ativação
        intermediária (q_proj.output, attn_norm.output, input_ids, etc.) já
        dimensionados para 1 LINHA (batch=1) por
        VTEModel._allocate_activation_buffers(). Copiar essas chaves faria
        `allocate_batched_activation_buffers` pulá-las (por já existirem no
        dict), e sequências de batch_idx>0 escreveriam fora dos limites
        desses buffers de 1 linha — corrompendo tudo, exceto o batch_idx=0
        (cujo offset dentro do buffer errado ainda é 0, "por sorte" correto).
        """
        tensor_mapping = {
            name: ptr for name, ptr in weight_tensor_mapping.items()
            if name in self.parser.tensors
        }

        reqs = self.calculate_memory_requirements(context_length, batch_size)
        kv_pool_size = reqs['kv_cache']
        kv_ptr = allocator.allocate(kv_pool_size, f"KV_CACHE_POOL_batch{batch_size}", MemoryRegion.KV_CACHE)
        if profiler:
            profiler.track_allocation(f"KV Cache Pool (batch={batch_size})", kv_pool_size / (1024*1024), "KV_CACHE")

        layers = self.config.get('num_hidden_layers', 28)
        kv_heads = self.config.get('attention.head_count_kv', 2)
        head_dim = self.config.get('attention.key_length', 128)
        layer_kv_size_per_batch = kv_heads * head_dim * 2 * context_length
        layer_kv_size = layer_kv_size_per_batch * batch_size

        current_kv_offset = kv_ptr.ptr
        for l in range(layers):
            tensor_mapping[f'blk.{l}.kv_cache.k'] = current_kv_offset
            tensor_mapping[f'blk.{l}.kv_cache.v'] = current_kv_offset + layer_kv_size
            current_kv_offset += layer_kv_size * 2
        tensor_mapping['kv_batch_stride_elements'] = layer_kv_size_per_batch // 2

        arena_size = reqs['arena']
        arena_ptr = allocator.allocate(arena_size, f"ACTIVATION_ARENA_batch{batch_size}", MemoryRegion.ACTIVATIONS)
        if profiler:
            profiler.track_allocation(f"Activation Arena (batch={batch_size})", arena_size / (1024*1024), "ACTIVATIONS")
        tensor_mapping['input_embeddings'] = arena_ptr.ptr
        tensor_mapping['input_ids'] = arena_ptr.ptr + 1048576

        self._build_and_upload_rope_cache(tensor_mapping, allocator, hip_runtime, context_length)

        return tensor_mapping

    def _read_rope_freq_scaling(self):
        """Lê o tensor `rope_freqs.weight` do GGUF, se existir (Llama 3.1: NTK-
        by-parts pré-computado pelo conversor, ver RoPECacheBuilder.__init__).
        Tensor pequeno (head_dim//2 floats, ex. 64) -- lido direto do arquivo,
        não pelo caminho geral de pesos (weight_loader.py só injeta o que está
        em tensor_mapping, e este tensor nunca entra lá: é consumido aqui,
        no host, para moldar a tabela de cos/sin, não copiado pra VRAM cru)."""
        t_info = self.parser.tensors.get('rope_freqs.weight')
        if t_info is None:
            return None
        import numpy as np
        with open(self.parser.path, 'rb') as f:
            f.seek(t_info['offset'])
            raw = f.read(t_info['size'])
        return np.frombuffer(raw, dtype=np.float32)

    def _build_and_upload_rope_cache(self, tensor_mapping: dict, allocator, hip_runtime, context_length: int):
        from vte.compiler.rope_cache_builder import RoPECacheBuilder

        max_seq_len = context_length
        head_dim = 128
        for k, v in self.metadata.items():
            if k.endswith('attention.key_length'):
                head_dim = v
        rope_theta = self.metadata.get('rope_theta', 10000.0)
        for k, v in self.metadata.items():
            if k.endswith('rope.freq_base'):
                rope_theta = v

        builder = RoPECacheBuilder(
            max_seq_len=max_seq_len,
            head_dim=head_dim,
            rope_theta=rope_theta,
            freq_scaling=self._read_rope_freq_scaling()
        )
        cos_cache, sin_cache = builder.build_cache()
        cos_ptr, sin_ptr = builder.upload_to_vram(cos_cache, sin_cache, hip_runtime, allocator)
        
        tensor_mapping['rope_cos'] = cos_ptr
        tensor_mapping['rope_sin'] = sin_ptr
        logger.info(f"RoPE cache adicionado ao mapping: cos=0x{cos_ptr:016x}, sin=0x{sin_ptr:016x}")

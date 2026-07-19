"""
split_kv_attention.py — Split-KV (Flash-Decoding) para o FlashAttention de
decode (seq_len=1).

Motivação (medida, não suposição — ver diagnósticos desta sessão): o
flash_attention_kernel original lança grid=(batch, num_q_heads, 1) — em
decode batch=1 isso é só 12 blocos contra 32 CUs na RX 7600 (20 ociosas), e
o laço sobre as posições do KV cache é inteiramente SERIAL dentro de cada
bloco. Isolado numa única camada: 6.9µs em kv_offset=1 vs 211µs em
kv_offset=300 — crescimento O(N) confirmado linear (não é bug de tiling/
complexidade), mas a CONSTANTE desse O(N) é inflada pela baixa ocupância.

Design (análogo ao Two-Pass Split-K do QKV, aplicado à dimensão do KV cache
em vez da dimensão de saída):
1. `kv_cache_append_kernel` — escreve o K/V do token atual no cache (1x,
   O(1), separado do cálculo de atenção -- ver o .hip.template para o
   porquê).
2. `flash_attention_split_kv_partial_kernel` — grid.z = max_chunks divide o
   histórico em fatias de 32 posições, cada uma processada por um bloco
   próprio (mais blocos = mais CUs ocupadas). Cada bloco grava seus
   acumuladores de online-softmax parciais (m, l, o) num scratchpad.
3. `flash_attention_split_kv_reduce_kernel` — funde os `max_chunks`
   resultados parciais no resultado final normalizado.

Opt-in via `VTE_ENABLE_ATTN_SPLITKV=1` (ainda não validado o suficiente
para ser o padrão -- ver README após a primeira rodada de medição real).
"""
import os
import math
import ctypes
from vte.bridge.memory import MemoryRegion

# Baseline histórico: 32 posições por chunk, calibrado na RX 7600 (32 CUs).
# Compute dinamicamente via _chunk_size_for_cus() abaixo -- reproduz 32
# exatamente quando num_cus=32 (nenhuma regressão na GPU de referência),
# escala inversamente com o nº de CUs reais em qualquer outra RDNA2/RDNA3.
SPLIT_KV_CHUNK_SIZE = 32


def _chunk_size_for_cus(num_cus: int) -> int:
    """Menos CUs -> chunks maiores (menos blocos, menos overhead de reduce
    por bloco majoritariamente ocioso); mais CUs -> chunks menores (mais
    blocos, para de fato ocupar as CUs extras). 1024/32=32 -- reproduz o
    baseline exatamente em num_cus=32. Faixa [8,64] evita chunks grandes
    demais (perde paralelismo em GPUs pequenas) ou pequenos demais (LDS/
    overhead do passo de redução cresce com max_chunks)."""
    if num_cus <= 0:
        return SPLIT_KV_CHUNK_SIZE
    return max(8, min(64, round(1024 / num_cus)))


class SplitKVAttentionDispatcher:
    def __init__(self, hip, codegen, metadata: dict, allocator=None, context_length: int = 4096, batch_size: int = 1):
        self.hip = hip
        self.codegen = codegen
        self.metadata = metadata or {}
        self.allocator = allocator
        self.batch_size = batch_size
        self.context_length = context_length
        num_cus = hip.get_num_cus() if hip is not None and hasattr(hip, 'get_num_cus') else 32
        self.chunk_size = _chunk_size_for_cus(num_cus)
        self.max_chunks = max(1, math.ceil(context_length / self.chunk_size))
        self._kernel_cache = {}
        self._scratch = None
        # Default ON (opt-out via VTE_DISABLE_ATTN_SPLITKV), mesma convenção
        # do QKV Two-Pass Split-K -- ver README para a medição que motivou
        # a virada de opt-in para padrão (curva de tok/s ficou estável em
        # vez de decair ao longo de uma geração longa, sem regressão
        # detectável no tick completo de 28 camadas).
        self.enabled = not bool(os.environ.get('VTE_DISABLE_ATTN_SPLITKV')) and allocator is not None

    @staticmethod
    def _resolve_ptr(tensor_mapping: dict, name: str) -> int:
        p = tensor_mapping.get(name)
        if p is None:
            return 0
        return p.ptr if hasattr(p, 'ptr') else int(p)

    def _resolve_kv_cache_ptrs(self, layer_idx: int, tensor_mapping: dict):
        """Mesma cadeia de fallback de KernelArgBuilder._build_attention_args
        -- reproduzida aqui em vez de importada para manter este dispatcher
        independente (mesmo padrão de FusedQKVDispatcher, que também não
        depende de KernelArgBuilder)."""
        k_ptr = tensor_mapping.get(f'blk.{layer_idx}.kv_cache.k')
        v_ptr = tensor_mapping.get(f'blk.{layer_idx}.kv_cache.v')
        if k_ptr is None:
            k_ptr = tensor_mapping.get(f'kv_cache.layer_{layer_idx}.k')
        if v_ptr is None:
            v_ptr = tensor_mapping.get(f'kv_cache.layer_{layer_idx}.v')
        if k_ptr is None or v_ptr is None:
            pool_ptr = tensor_mapping.get('KV Cache Pool')
            if pool_ptr is not None:
                kv_size_per_layer = 2 * 2 * 128 * 2048 * 2
                k_ptr = pool_ptr + (layer_idx * kv_size_per_layer)
                v_ptr = pool_ptr + (layer_idx * kv_size_per_layer) + (kv_size_per_layer // 2)
        k_val = k_ptr.ptr if hasattr(k_ptr, 'ptr') else int(k_ptr or 0)
        v_val = v_ptr.ptr if hasattr(v_ptr, 'ptr') else int(v_ptr or 0)
        return k_val, v_val

    def _get_kernels(self):
        if 'append' not in self._kernel_cache:
            arch = self.hip.get_gpu_architecture()

            _, fn = self.codegen.load_kernel_safe(self.hip, 'kv_cache_append', arch, 'kv_cache_append_kernel')
            self._kernel_cache['append'] = fn

            _, fn = self.codegen.load_kernel_safe(
                self.hip, 'flash_attention_split_kv_partial', arch, 'flash_attention_split_kv_partial_kernel',
                split_kv_chunk_size=self.chunk_size,
            )
            self._kernel_cache['partial'] = fn

            _, fn = self.codegen.load_kernel_safe(self.hip, 'flash_attention_split_kv_reduce', arch, 'flash_attention_split_kv_reduce_kernel')
            self._kernel_cache['reduce'] = fn

            num_q_heads = self.metadata.get('attention.head_count', 12)
            head_dim = self.metadata.get('attention.key_length', 128)
            # Scratchpad ÚNICO, reaproveitado por TODAS as 28 camadas: como o
            # forward pass é estritamente sequencial camada a camada (cada
            # uma depende da saída da anterior), não há dois nós de atenção
            # rodando "ao mesmo tempo" dentro de um mesmo tick -- reescrever
            # o mesmo buffer a cada camada é seguro (mesma lógica por trás do
            # scratchpad único do QKV Split-K).
            stats_size = self.batch_size * num_q_heads * self.max_chunks * 4  # float32
            o_size = self.batch_size * num_q_heads * self.max_chunks * head_dim * 4  # float32
            self._partial_m = self.allocator.allocate(stats_size, "attn_splitkv_m", MemoryRegion.SCRATCH)
            self._partial_l = self.allocator.allocate(stats_size, "attn_splitkv_l", MemoryRegion.SCRATCH)
            self._partial_o = self.allocator.allocate(o_size, "attn_splitkv_o", MemoryRegion.SCRATCH)

        return self._kernel_cache['append'], self._kernel_cache['partial'], self._kernel_cache['reduce']

    def build_launches(self, layer_idx: int, tensor_mapping: dict, kv_offset_ptr: int, batch: int = 1,
                        q_name: str = None, k_name: str = None, v_name: str = None):
        """Retorna a lista de (kernel_fn, args, grid, block, shared_mem) para
        os 3 lançamentos do Split-KV desta camada -- mesma assinatura de
        retorno de FusedQKVDispatcher.build_launches, para plugar no mesmo
        laço de captura em hip_graph_executor.py.

        Bug real encontrado (Qwen3.5): antes, os nomes dos tensores de Q/K/V
        eram reconstruídos aqui por CONVENÇÃO fixa (f'blk.{layer_idx}.q_proj.output'
        etc.), que é exatamente onde RoPE escreve in-place PRO QWEN2.5/GRANITE
        (sem passo de norma por-head) -- mas o Qwen3.5 tem q_norm/k_norm
        (RMSNorm por-head) ENTRE a projeção e o RoPE, e RoPE escreve em
        `q_norm.output`/`k_norm.output`, não em `q_proj.output`/`k_proj.output`.
        Usar a convenção fixa lia Q bruto (largura dupla, sem norma, sem RoPE)
        e K bruto (sem norma, sem RoPE) -- confirmado via round-trip real: o
        K armazenado no KV cache divergia do k_norm.output ao vivo em TODAS as
        posições (diff ~4-6), enquanto V batia bit-exato (V não tem passo de
        norma no Qwen3.5, então v_proj.output já era o buffer certo por
        coincidência). Corrigido aceitando os nomes REAIS do nó do grafo
        (node.input_tensors, já corretos por arquitetura em qwen_compute.py/
        qwen3_5_compute.py) em vez de reconstruí-los aqui -- default None
        preserva a convenção antiga quando não fornecido (Qwen2.5/Granite)."""
        append_fn, partial_fn, reduce_fn = self._get_kernels()

        num_q_heads = self.metadata.get('attention.head_count', 12)
        num_kv_heads = self.metadata.get('attention.head_count_kv', 2)
        head_dim = self.metadata.get('attention.key_length', 128)
        # Mesmo raciocínio de KernelArgBuilder._build_attention_args: usa o
        # attention_scale explícito do GGUF quando presente (SUBSTITUI o
        # cálculo padrão, não combina com ele -- Granite: 0.015625 vs
        # 1/sqrt(64)=0.125, valores bem diferentes).
        attention_scale = self.metadata.get('attention_scale')
        scale = attention_scale if attention_scale else 1.0 / (head_dim ** 0.5)

        node_name = f"blk.{layer_idx}.attention"
        # input_tensors: [q_pos_rope, k_pos_rope_ou_proj, v_proj_atual] --
        # nomes reais do nó do grafo quando fornecidos (ver docstring acima),
        # senão a convenção antiga (Qwen2.5/Granite: RoPE in-place em
        # q_proj.output/k_proj.output, sem passo de norma por-head).
        q_ptr = self._resolve_ptr(tensor_mapping, q_name or f'blk.{layer_idx}.q_proj.output')
        k_proj_ptr = self._resolve_ptr(tensor_mapping, k_name or f'blk.{layer_idx}.k_proj.output')
        v_proj_ptr = self._resolve_ptr(tensor_mapping, v_name or f'blk.{layer_idx}.v_proj.output')
        output_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.attention.output')
        k_cache_ptr, v_cache_ptr = self._resolve_kv_cache_ptrs(layer_idx, tensor_mapping)
        kv_batch_stride = int(tensor_mapping.get('kv_batch_stride_elements', 0))

        shared_attn = 2 * head_dim * 4  # q_sh + red, floats

        c_num_q = ctypes.c_int(num_q_heads)
        c_num_kv = ctypes.c_int(num_kv_heads)
        c_head_dim = ctypes.c_int(head_dim)
        c_scale = ctypes.c_float(scale)
        c_kv_stride = ctypes.c_int(kv_batch_stride)
        c_max_chunks = ctypes.c_int(self.max_chunks)

        append_args = [
            ctypes.c_void_p(k_proj_ptr), ctypes.c_void_p(v_proj_ptr),
            ctypes.c_void_p(k_cache_ptr), ctypes.c_void_p(v_cache_ptr),
            c_num_kv, c_head_dim,
            ctypes.c_void_p(kv_offset_ptr), c_kv_stride,
        ]
        append_grid = (batch, num_kv_heads, 1)
        append_block = (head_dim, 1, 1)

        partial_args = [
            ctypes.c_void_p(q_ptr), ctypes.c_void_p(k_cache_ptr), ctypes.c_void_p(v_cache_ptr),
            ctypes.c_void_p(self._partial_m.ptr), ctypes.c_void_p(self._partial_l.ptr), ctypes.c_void_p(self._partial_o.ptr),
            c_num_q, c_num_kv, c_head_dim, c_scale,
            ctypes.c_void_p(kv_offset_ptr), c_kv_stride, c_max_chunks,
        ]
        partial_grid = (batch, num_q_heads, self.max_chunks)
        partial_block = (head_dim, 1, 1)

        reduce_args = [
            ctypes.c_void_p(self._partial_m.ptr), ctypes.c_void_p(self._partial_l.ptr), ctypes.c_void_p(self._partial_o.ptr),
            ctypes.c_void_p(output_ptr),
            c_num_q, c_head_dim, c_max_chunks,
        ]
        reduce_grid = (batch, num_q_heads, 1)
        # blockDim.x = head_dim (não max_chunks): o laço de corr_sh já é
        # estridado (`for c = tid; c < max_chunks; c += blockDim.x`), então
        # head_dim threads bastam mesmo se max_chunks > head_dim (contextos
        # muito longos) -- evita blocos gigantes/LDS excessiva para
        # context_length grande.
        reduce_block = (head_dim, 1, 1)
        reduce_shared = self.max_chunks * 4  # corr_sh, floats

        # Mesma interface de retorno de FusedQKVDispatcher.build_launches:
        # só a lista de lançamentos -- os ctypes.c_int/c_float ficam vivos
        # como elementos das próprias listas de args, que sobrevivem até o
        # fim deste laço de captura no chamador (launch_kernel_recorded copia
        # os valores para o nó do grafo na hora da captura, não guarda uma
        # referência para replays futuros).
        return [
            (append_fn, append_args, append_grid, append_block, 0),
            (partial_fn, partial_args, partial_grid, partial_block, shared_attn),
            (reduce_fn, reduce_args, reduce_grid, reduce_block, reduce_shared),
        ]

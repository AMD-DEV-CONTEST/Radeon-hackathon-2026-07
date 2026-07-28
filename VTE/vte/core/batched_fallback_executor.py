"""
Fase I (Batched Decode) — Etapa I.2: executor de batch estático em lockstep.

Escopo deliberadamente restrito (ver plano): N sequências de mesmo
comprimento de prompt/geração, avançando 1 token por "tick" juntas. Sem
fila, sem prompts heterogêneos, sem terminação antecipada individual.

Composição, não herança: reaproveita um FallbackExecutor interno (seu
execution_order, KernelArgBuilder, CodegenEngine, cache de kernels,
_dispatch_node, _get_or_compile_kernel) mas dirige o despacho por conta
própria, SEM as fusões QKV Two-Pass Split-K / FFN Gate+Up+SiLU — ambas fora
de escopo aqui (kernels single-row, não estendidos para batch nesta fase).
O modo batched usa exclusivamente os kernels desagregados (rmsnorm +
gemv_coalesced/gemv_q4k/gemv_q6k/matmul + rope + flash_attention + swiglu +
add), todos já batch-capazes (Etapas I.2.b/I.2.c).

O FallbackExecutor de produção (batch=1) permanece INTOCADO — este módulo é
aditivo.
"""
import ctypes
from typing import Dict, List

import numpy as np

from vte.bridge.hip_runtime import HIPRuntime
from vte.bridge.memory import SlabAllocator, MemoryRegion
from vte.compiler.ir import IRGraph, NodeType
from vte.compiler.qwen_mapper import ActivationArena
from vte.bridge.logger import get_logger
from vte.core.fallback_executor import FallbackExecutor

logger = get_logger(__name__)


def allocate_batched_activation_buffers(
    graph: IRGraph, tensor_mapping: Dict, allocator: SlabAllocator, batch_size: int
) -> int:
    """
    Espelha VTEModel._allocate_activation_buffers, mas dimensiona a dimensão
    dinâmica (-1, seq_len) como `batch_size` em vez de 1 — os buffers
    persistentes de ativação intermediária (q_proj.output, ffn_norm.output,
    etc.) precisam de espaço para [batch_size, features], não [1, features].

    Só aloca tensores que ainda não estão em tensor_mapping (pesos, KV cache
    e o stride de batch já foram mapeados por QwenTensorMapper antes desta
    chamada).
    """
    allocated = 0
    for node in graph.topological_sort():
        if node.op_type in [NodeType.INPUT, NodeType.OUTPUT]:
            continue

        out_name = node.output_tensor
        if not out_name or out_name in tensor_mapping:
            continue

        size = 1
        for dim in node.shape:
            if dim > 0:
                size *= dim
            elif dim == -1:
                size *= batch_size
        size = size * 2  # fp16
        size = max(size, 512)

        block = allocator.allocate(size, f"act_batch_{out_name}", MemoryRegion.ACTIVATIONS)
        tensor_mapping[out_name] = block.ptr
        allocated += 1

    logger.info(f"Buffers de ativação batched alocados: {allocated} tensores (batch_size={batch_size})")
    return allocated


class BatchedFallbackExecutor:
    """
    Executor de batch estático (Etapa I.2). Processa `batch_size` sequências
    em lockstep, 1 token por chamada de `decode_step_batch`, cada uma na sua
    posição de KV cache (kv_offsets pode divergir entre sequências, embora
    em lockstep puro elas avancem juntas).
    """

    def __init__(
        self,
        hip: HIPRuntime,
        allocator: SlabAllocator,
        arena: ActivationArena,
        graph: IRGraph,
        tensor_mapping: dict,
        metadata: dict,
        batch_size: int,
    ):
        self.hip = hip
        self.allocator = allocator
        self.batch_size = batch_size
        self.tensor_mapping = tensor_mapping
        self.metadata = metadata or {}
        self.num_layers = self.metadata.get('block_count', 28)

        # Garante que os buffers de ativação intermediária existem com o
        # tamanho certo ANTES de construir o FallbackExecutor interno (que
        # só aloca sob demanda, via arena, para o que faltar — não queremos
        # que ele aloque do jeito errado, sizado para 1 linha).
        allocate_batched_activation_buffers(graph, tensor_mapping, allocator, batch_size)

        # FallbackExecutor interno: reaproveita execution_order, arg_builder,
        # codegen, cache de kernels e _dispatch_node/_calculate_launch_dims
        # (já batch-parametrizados nas Etapas I.2.b/I.2.c). NUNCA chamamos
        # seu execute_layer() (que tem a lógica de fusão QKV/FFN embutida) —
        # dirigimos o despacho nó a nó por conta própria.
        self._inner = FallbackExecutor(hip, allocator, arena, graph, tensor_mapping, metadata)

        # Buffer de kv_offset dimensionado para `batch_size` ints (1 por
        # sequência), substituindo o buffer de 1 int do FallbackExecutor
        # interno — _dispatch_node lê `self._kv_offset_buf.ptr` do objeto em
        # que é chamado, então redirecionamos o atributo do inner executor.
        self._kv_offset_buf = self.allocator.allocate(
            4 * batch_size, "kv_offset_batch_array", MemoryRegion.SCRATCH
        )
        self._inner._kv_offset_buf = self._kv_offset_buf

        # Etapa I.3: fusão QKV Two-Pass Split-K (produção, +8% medido em
        # batch=1) e epilogue fusion do residual, ambas estendidas para
        # batch nos templates .hip — habilitadas também no modo batched.
        from vte.core.fused_qkv_dispatch import FusedQKVDispatcher
        from vte.core.fallback_executor import build_residual_fusion
        self._fused_qkv = FusedQKVDispatcher(self.hip, self._inner.codegen, self.metadata,
                                             allocator=self.allocator, batch_size=batch_size)
        build_residual_fusion(list(graph.nodes.values()))

    def _write_kv_offsets(self, kv_offsets: List[int]):
        assert len(kv_offsets) == self.batch_size
        arr = np.array(kv_offsets, dtype=np.int32)
        self.hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(self._kv_offset_buf.ptr), arr.tobytes(), tag="kv_offset_batch_update"
        )

    def _write_input_ids(self, tokens: List[int]):
        assert len(tokens) == self.batch_size
        self._inner._write_input_ids(tokens)

    def execute_layer_batch(self, layer_idx: int, kv_offsets: List[int]):
        """Executa 1 camada do transformer para as `batch_size` sequências."""
        from vte.core.fallback_executor import SKIP_ADD_NODES

        self._write_kv_offsets(kv_offsets)

        if layer_idx == 0:
            # embedding_lookup*_kernel trata `seq_len` genericamente como
            # "número de linhas" — passar batch_size aqui produz
            # [batch_size, hidden_size], exatamente o layout esperado pelos
            # kernels desagregados a seguir (m = batch*seq_len, seq_len=1).
            self._inner._execute_embedding_lookup(self.batch_size)

        # Mesmo guard de FallbackExecutor.execute_layer (ver docs/BUGS.md,
        # "QKV-fusion guard só verificava attn_q.weight"): faltava aqui --
        # o kernel fundido (fused_norm_matmul_rope/split_k_qkv_pass1/pass2)
        # lê Q/K/V como `__half*` puro, sem dequant embutido. Se qualquer uma
        # das 4 projeções (Q/K/V/O) estiver roteada crua (Q4_K/Q6_K/Q8_0) --
        # como é o caso de attn_q.weight no Qwen2.5 1.5B/7B -- a fusão lia
        # bytes quantizados reinterpretados como FP16, produzindo NaN. Sem
        # este guard, BatchedFallbackExecutor (usado por generate_batch() E
        # por SpeculativeVerifyExecutor) nunca tinha sido exercitado contra
        # um modelo com Q/K/V/O crus -- por isso o gap passou despercebido
        # até a Fase 5 (verificação especulativa) tropeçar nele.
        from vte.core.fallback_executor import RAW_Q4K_WEIGHTS, RAW_Q6K_WEIGHTS, RAW_Q8_0_WEIGHTS, RAW_Q5_0_WEIGHTS
        _attn_q_name = f"blk.{layer_idx}.attn_q.weight"
        _attn_k_name = f"blk.{layer_idx}.attn_k.weight"
        _attn_v_name = f"blk.{layer_idx}.attn_v.weight"
        _attn_o_name = f"blk.{layer_idx}.attn_output.weight"
        _raw_sets = (RAW_Q4K_WEIGHTS, RAW_Q6K_WEIGHTS, RAW_Q8_0_WEIGHTS, RAW_Q5_0_WEIGHTS)
        _qkv_fusable = (_attn_q_name in self.tensor_mapping
                        and not any(n in s for n in (_attn_q_name, _attn_k_name, _attn_v_name, _attn_o_name) for s in _raw_sets)
                        and self.metadata.get('rope_type') != 2)

        qkv_fused_names = {
            f"blk.{layer_idx}.attn_norm", f"blk.{layer_idx}.q_proj",
            f"blk.{layer_idx}.k_proj", f"blk.{layer_idx}.v_proj",
            f"blk.{layer_idx}.rope",
        } if _qkv_fusable else set()

        layer_prefix = f"blk.{layer_idx}."
        for node in self._inner.execution_order:
            if not node.name.startswith(layer_prefix):
                continue
            if getattr(node, 'is_fused', False):
                continue
            if node.name in SKIP_ADD_NODES:
                continue

            if _qkv_fusable and node.name == f"blk.{layer_idx}.attn_norm":
                launches = self._fused_qkv.build_launches(
                    layer_idx, self.tensor_mapping, self._kv_offset_buf.ptr, batch=self.batch_size
                )
                for fn, args, grid, block, shared_mem in launches:
                    self.hip.launch_kernel(
                        function=fn, args=args, grid=grid, block=block,
                        shared_mem=shared_mem, expected_args=len(args)
                    )
                    self.hip.synchronize()
                continue

            if node.name in qkv_fused_names:
                continue

            self._inner._dispatch_node(node, seq_len=1, batch=self.batch_size)

        if layer_idx == self.num_layers - 1:
            for node in self._inner.execution_order:
                if node.name == "output_norm":
                    self._inner._dispatch_node(node, seq_len=1, batch=self.batch_size)

        self.hip.synchronize()
        self._inner.arena.reset_after_sync()

    def decode_step_batch(self, tokens: List[int], kv_offsets: List[int]):
        """1 token por sequência do batch, cada uma na sua posição kv_offsets[b]."""
        self._write_input_ids(tokens)
        for layer_idx in range(self.num_layers):
            self.execute_layer_batch(layer_idx, kv_offsets)

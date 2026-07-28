"""
Fase I (Batched Decode) — Etapa I.2 (extensão): captura em HIP Graph.

Espelha BatchedFallbackExecutor (composição, não herança): reaproveita um
HIPGraphExecutor interno (codegen, arg_builder, cache de kernels) mas grava
sua PRÓPRIA captura de grafo, nó a nó, SEM as fusões QKV Two-Pass Split-K /
FFN Gate+Up+SiLU (fora de escopo — kernels single-row, não estendidos para
batch nesta fase). O grafo capturado é reutilizável para qualquer posição do
KV cache (offset lido por ponteiro/array), mas é ESPECÍFICO de um batch_size
(as dimensões de grid são "queimadas" na captura) — por isso cada batch_size
tem seu próprio grafo, análogo ao cache de `prefill_graphs` por seq_len.

Correção validada (Etapa I.2, FallbackExecutor eager): diff numérico exato
(0.0) entre execução em batch e sequencial. Este módulo grava exatamente a
mesma sequência de kernels/argumentos, só substituindo lançamento eager por
gravação em grafo — a corretude numérica é herdada dessa validação.
"""
import ctypes
from typing import Dict, List

import numpy as np

from vte.bridge.hip_runtime import HIPRuntime
from vte.bridge.memory import SlabAllocator, MemoryRegion
from vte.compiler.ir import IRGraph, NodeType
from vte.bridge.logger import get_logger
from vte.core.hip_graph_executor import HIPGraphExecutor
from vte.core.fallback_executor import SKIP_ADD_NODES
from vte.core.batched_fallback_executor import allocate_batched_activation_buffers

logger = get_logger(__name__)


class BatchedHIPGraphExecutor:
    """
    Captura e reproduz um grafo de decode batched (batch_size sequências,
    1 token cada, por replay). Um grafo por batch_size — grids são fixados
    na captura.
    """

    def __init__(
        self,
        hip: HIPRuntime,
        allocator: SlabAllocator,
        graph: IRGraph,
        tensor_mapping: dict,
        metadata: dict,
        batch_size: int,
        lm_head_info: dict = None,
    ):
        self.hip = hip
        self.allocator = allocator
        self.batch_size = batch_size
        self.tensor_mapping = tensor_mapping
        self.metadata = metadata or {}
        self.num_layers = self.metadata.get('block_count', 28)

        # Mesmo padrão do HIPGraphExecutor single-sequence (Fase 2): se
        # resolvido em model.py ANTES deste executor existir (peso/tied
        # embeddings, logits_buffer [batch_size, vocab_size], kernel já
        # compilado -- endereços fixos), o LM Head é gravado DENTRO do grafo
        # batched em vez de rodar como lançamento eager separado a cada tick
        # (eliminava ~7.5ms/tick de overhead de despacho medidos).
        self.lm_head_info = lm_head_info

        # Garante que os buffers de ativação intermediária existem com o
        # tamanho certo ([batch_size, features]) ANTES de construir o
        # HIPGraphExecutor interno — sem isso, o grafo capturaria endereços
        # inexistentes (KeyError) ou, pior, buffers sizados para 1 linha.
        allocate_batched_activation_buffers(graph, tensor_mapping, allocator, batch_size)

        # HIPGraphExecutor interno: reaproveita codegen/arg_builder/cache de
        # kernels/_get_or_compile_kernel/_calculate_launch_dims (já batch-
        # parametrizados). NUNCA chamamos seu build_decode_graph()/
        # _capture_graph() (que tem a fusão QKV/FFN embutida) — gravamos a
        # captura por conta própria em _capture_batched_decode_graph().
        self._inner = HIPGraphExecutor(hip, allocator, graph, tensor_mapping, metadata)

        # Staging buffers dimensionados para `batch_size` (substituem os de 1
        # elemento do inner executor — redirecionamos os atributos para que
        # _build_kernel_args/_capture_embedding_lookup, chamados através do
        # inner, usem os buffers certos).
        self.staging_input = self.allocator.allocate(
            4 * batch_size, "staging_input_batch", MemoryRegion.SCRATCH
        )
        self.staging_kv_offset = self.allocator.allocate(
            4 * batch_size, "staging_kv_offset_batch", MemoryRegion.SCRATCH
        )
        self._inner.staging_input = self.staging_input
        self._inner.staging_kv_offset = self.staging_kv_offset
        self._inner.staging_buffers = {
            'input_ids': self.staging_input,
            'input_embeddings': self.staging_input,
        }

        # Etapa I.3: fusão QKV Two-Pass Split-K e epilogue fusion do
        # residual, ambas estendidas para batch — habilitadas também na
        # captura do grafo batched.
        from vte.core.fused_qkv_dispatch import FusedQKVDispatcher
        from vte.core.fallback_executor import build_residual_fusion
        self._fused_qkv = FusedQKVDispatcher(self.hip, self._inner.codegen, self.metadata,
                                             allocator=self.allocator, batch_size=batch_size)
        build_residual_fusion(list(graph.nodes.values()))

        self.decode_graph = None

    def _capture_embedding_lookup_batch(self):
        """Mesma lógica de HIPGraphExecutor._capture_embedding_lookup, mas com
        seq_len=batch_size (embedding_lookup*_kernel trata `seq_len` como
        'número de linhas' genericamente — ver BatchedFallbackExecutor)."""
        self._inner._capture_embedding_lookup(self.batch_size)

    def _capture_lm_head_batch(self):
        """
        Grava o lançamento do LM Head DENTRO do grafo batched, geometria
        [batch_size, vocab_size] (grid.y = batch_size — gemv_coalesced/
        gemv_q4k/gemv_q6k já indexam X[batch_idx, k] via blockIdx.y
        nativamente, mesmo kernel/critério usado no caminho single-sequence
        e já validado numericamente ali). Regra de ouro: só ESCREVE no
        logits_buffer da VRAM -- o hipMemcpy D2H e o Sampler continuam
        rodando em model.py, depois do graph_launch retornar, nunca dentro
        da captura.
        """
        info = self.lm_head_info
        last_hidden_ptr = self.tensor_mapping.get('output_norm.output')
        last_hidden_val = last_hidden_ptr.ptr if hasattr(last_hidden_ptr, 'ptr') else last_hidden_ptr

        # Bug real (achado na Fase 5, ao escrever a captura irmã em
        # speculative_verify_executor.py e bater em access violation):
        # gemv_coalesced/gemv_q4k/gemv_q6k/gemv_q8_0/gemv_q5_0 têm ABI de 10
        # argumentos -- faltava o último (`residual_scale`, float), sempre
        # presente no kernel real (usado pro logit_scale do Granite). Sem
        # ele, o kernel lia um 10o parâmetro nunca passado -- UB (às vezes
        # crash, às vezes logits errados sem aviso nenhum). Nunca detectado
        # porque generate_batch() nunca tinha sido exercitado o suficiente
        # com o LM Head capturado no grafo batched contra um caso que
        # revelasse o problema.
        logit_scale = self.metadata.get('logit_scale', 1.0) or 1.0

        args = [
            ctypes.c_void_p(last_hidden_val),
            ctypes.c_void_p(info['weight_ptr']),
            ctypes.c_void_p(info['logits_buffer_ptr']),
            ctypes.c_int(self.batch_size),       # batch
            ctypes.c_int(1),                     # seq_len (decode: sempre 1)
            ctypes.c_int(info['hidden_size']),
            ctypes.c_int(info['vocab_size']),
            ctypes.c_void_p(0),                  # bias (LM head não tem)
            ctypes.c_void_p(0),                  # residual (sem epilogue aqui)
            ctypes.c_float(1.0 / logit_scale),
        ]

        self.hip.launch_kernel_recorded(
            function=info['kernel_fn'],
            args=args,
            grid=(info['vocab_size'], self.batch_size, 1),
            block=(64, 1, 1),
            shared_mem=0,
        )

    def _capture_batched_decode_graph(self) -> ctypes.c_void_p:
        logger.info(f"Iniciando captura de HIP Graph batched (batch_size={self.batch_size})")
        nodes_recorded = 0

        try:
            self.hip.stream_begin_capture()

            self._capture_embedding_lookup_batch()
            nodes_recorded += 1

            qkv_fused_names: set = set()

            for node in self._inner.ir_graph.topological_sort():
                if node.op_type in [NodeType.INPUT, NodeType.OUTPUT]:
                    continue
                if getattr(node, 'is_fused', False):
                    continue
                if node.name in SKIP_ADD_NODES:
                    continue
                if node.name in qkv_fused_names:
                    continue

                if node.op_type == NodeType.RMSNORM and node.name.endswith('.attn_norm'):
                    layer_idx = int(node.name.split('.')[1])
                    # Mesmo guard de FallbackExecutor.execute_layer (ver
                    # docs/BUGS.md, "QKV-fusion guard só verificava
                    # attn_q.weight") -- faltava aqui também. O kernel
                    # fundido lê Q/K/V como `__half*` puro; se qualquer uma
                    # das 4 projeções estiver roteada crua (Q4_K/Q6_K/Q8_0,
                    # caso de attn_q.weight no Qwen2.5 1.5B/7B), a fusão lia
                    # bytes quantizados como FP16 -- NaN. Sem checar aqui,
                    # generate_batch() nunca teria funcionado corretamente
                    # para esses dois modelos (só nunca foi exercitado com
                    # eles em conjunto até a Fase 5 expor o gap).
                    from vte.core.fallback_executor import RAW_Q4K_WEIGHTS, RAW_Q6K_WEIGHTS, RAW_Q8_0_WEIGHTS, RAW_Q5_0_WEIGHTS
                    _attn_q_name = f"blk.{layer_idx}.attn_q.weight"
                    _attn_k_name = f"blk.{layer_idx}.attn_k.weight"
                    _attn_v_name = f"blk.{layer_idx}.attn_v.weight"
                    _attn_o_name = f"blk.{layer_idx}.attn_output.weight"
                    _raw_sets = (RAW_Q4K_WEIGHTS, RAW_Q6K_WEIGHTS, RAW_Q8_0_WEIGHTS, RAW_Q5_0_WEIGHTS)
                    _qkv_fusable = (_attn_q_name in self.tensor_mapping
                                    and not any(n in s for n in (_attn_q_name, _attn_k_name, _attn_v_name, _attn_o_name) for s in _raw_sets)
                                    and self.metadata.get('rope_type') != 2)
                    if not _qkv_fusable:
                        kernel_func = self._inner._get_or_compile_kernel(node)
                        if kernel_func is not None:
                            args, _ = self._inner.arg_builder.build_args(
                                node=node, tensor_mapping=self.tensor_mapping,
                                staging_buffers=self._inner.staging_buffers, seq_len=1,
                                metadata=self.metadata, kv_offset_ptr=self.staging_kv_offset.ptr,
                                batch=self.batch_size,
                            )
                            grid, block, shared_mem = self._inner._calculate_launch_dims(node, seq_len=1, batch=self.batch_size)
                            self.hip.launch_kernel_recorded(kernel_func, args, grid, block, shared_mem)
                            nodes_recorded += 1
                        continue

                    launches = self._fused_qkv.build_launches(
                        layer_idx, self.tensor_mapping, self.staging_kv_offset.ptr, batch=self.batch_size
                    )
                    for fn, args, grid, block, shared_mem in launches:
                        self.hip.launch_kernel_recorded(fn, args, grid, block, shared_mem)
                        nodes_recorded += 1
                    qkv_fused_names.update({
                        f"blk.{layer_idx}.attn_norm", f"blk.{layer_idx}.q_proj",
                        f"blk.{layer_idx}.k_proj", f"blk.{layer_idx}.v_proj",
                        f"blk.{layer_idx}.rope",
                    })
                    continue

                kernel_func = self._inner._get_or_compile_kernel(node)
                if kernel_func is None:
                    continue

                args, _ = self._inner.arg_builder.build_args(
                    node=node,
                    tensor_mapping=self.tensor_mapping,
                    staging_buffers=self._inner.staging_buffers,
                    seq_len=1,
                    metadata=self.metadata,
                    kv_offset_ptr=self.staging_kv_offset.ptr,
                    batch=self.batch_size,
                )
                grid, block, shared_mem = self._inner._calculate_launch_dims(node, seq_len=1, batch=self.batch_size)

                self.hip.launch_kernel_recorded(kernel_func, args, grid, block, shared_mem)
                nodes_recorded += 1

            if self.lm_head_info is not None:
                self._capture_lm_head_batch()
                nodes_recorded += 1

            raw_graph = self.hip.stream_end_capture()
            graph_exec = self.hip.graph_instantiate(raw_graph)

            try:
                self.hip.graph_destroy(raw_graph)
            except Exception as cleanup_err:
                logger.warning(f"Falha ao destruir hipGraph_t intermediário (batched): {cleanup_err}")

            logger.info(f"HIP Graph batched instanciado: {nodes_recorded} kernels gravados (batch_size={self.batch_size})")
            return graph_exec

        except Exception as e:
            logger.error(f"Falha na captura do grafo batched (batch_size={self.batch_size}): {e}")
            try:
                self.hip.stream_end_capture()
            except Exception:
                pass
            raise

    def build_decode_graph(self):
        if self.decode_graph is None:
            self.decode_graph = self._capture_batched_decode_graph()

    def _update_staging_buffers(self, tokens: List[int], kv_offsets: List[int]):
        assert len(tokens) == self.batch_size and len(kv_offsets) == self.batch_size
        tok_arr = np.array(tokens, dtype=np.int32)
        kv_arr = np.array(kv_offsets, dtype=np.int32)
        self.hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(self.staging_input.ptr), tok_arr.tobytes(), tag="update_input_token_batch"
        )
        self.hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(self.staging_kv_offset.ptr), kv_arr.tobytes(), tag="update_kv_offset_batch"
        )

    def execute_decode_batch(self, tokens: List[int], kv_offsets: List[int]):
        """1 token por sequência do batch, cada uma na sua posição kv_offsets[b]."""
        self.build_decode_graph()
        self._update_staging_buffers(tokens, kv_offsets)
        self.hip.graph_launch(self.decode_graph)
        self.hip.synchronize()

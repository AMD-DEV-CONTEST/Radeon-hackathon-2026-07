# vte/core/topk_logits_reducer.py

import ctypes

import numpy as np

from vte.bridge.memory import MemoryRegion

NUM_THREADS = 1024   # deve casar com NUM_THREADS em topk_reduce_greedy.hip.template
MAX_EXCLUDE = 512    # deve casar com MAX_EXCLUDE (== REPETITION_WINDOW do sampler.py)

_VALUES_BYTES = NUM_THREADS * 4
_INDICES_BYTES = NUM_THREADS * 4
_GATHERED_BYTES = MAX_EXCLUDE * 4
_OUTPUT_BYTES = _VALUES_BYTES + _INDICES_BYTES + _GATHERED_BYTES


class TopKLogitsReducer:
    """Reduz o buffer de logits (vocab_size fp16) a um conjunto pequeno de
    candidatos direto na GPU, pro caminho greedy (temperature<=0) opcional
    (VTE_TOPK_LOGITS_READBACK=1) -- ver docs/PERFORMANCE.md, "Follow-up: GPU
    duty-cycle investigation", e o comentário de corretude em
    topk_reduce_greedy.hip.template / Sampler.pick_greedy_from_gpu_candidates.

    O lançamento do kernel em si é CAPTURADO dentro do HIP Graph de decode
    (ver HIPGraphExecutor._capture_topk_reduce), não lançado eager por esta
    classe -- uma primeira versão eager media uma perda líquida de tok/s
    (o despacho de um kernel novo fora do grafo custa mais que a economia
    da leitura reduzida). Esta classe só: (1) aloca os buffers de I/O uma
    vez (endereços fixos, exigido por um grafo capturado), (2) sobe o
    conteúdo do array de exclusão via H2D pequeno ANTES de cada replay
    (`upload_exclude`), e (3) lê de volta os candidatos DEPOIS do replay
    (`read_candidates`) -- mesmo padrão já usado pelo kv_cache_offset
    (conteúdo variável, endereço fixo).
    """

    def __init__(self, hip, allocator, codegen):
        self.hip = hip
        arch = hip.get_gpu_architecture()
        _, self.kernel = codegen.load_kernel_safe(
            hip, "topk_reduce_greedy", arch, "topk_reduce_greedy_kernel"
        )

        self.output_buf = allocator.allocate(
            size=_OUTPUT_BYTES, tag="topk_reduce_output", region=MemoryRegion.SCRATCH
        ).ptr
        self.values_ptr = ctypes.c_void_p(self.output_buf)
        self.indices_ptr = ctypes.c_void_p(self.output_buf + _VALUES_BYTES)
        self.gathered_ptr = ctypes.c_void_p(self.output_buf + _VALUES_BYTES + _INDICES_BYTES)

        self.exclude_ids_buf = allocator.allocate(
            size=MAX_EXCLUDE * 4, tag="topk_reduce_exclude_ids", region=MemoryRegion.SCRATCH
        ).ptr
        self.exclude_ids_ptr = ctypes.c_void_p(self.exclude_ids_buf)

        self.exclude_count_buf = allocator.allocate(
            size=4, tag="topk_reduce_exclude_count", region=MemoryRegion.SCRATCH
        ).ptr
        self.exclude_count_ptr = ctypes.c_void_p(self.exclude_count_buf)

        self._host_output = bytearray(_OUTPUT_BYTES)

    def build_capture_args(self, logits_ptr: int, vocab_size: int) -> list:
        """Args FIXOS pra gravar o lançamento dentro do grafo de decode --
        mesmo padrão de HIPGraphExecutor._capture_lm_head. `logits_ptr` e
        `vocab_size` vêm de lm_head_info (endereço/valor fixos por toda a
        vida do grafo); os ponteiros de exclusão/saída são os desta
        instância (também fixos)."""
        return [
            ctypes.c_void_p(logits_ptr),
            self.exclude_ids_ptr,
            self.exclude_count_ptr,
            ctypes.c_int(vocab_size),
            self.values_ptr,
            self.indices_ptr,
            self.gathered_ptr,
        ]

    def upload_exclude(self, unique_ids: np.ndarray):
        """Atualiza o CONTEÚDO dos buffers de exclusão (endereço fixo) antes
        do próximo hipGraphLaunch usar o kernel já capturado. `unique_ids`
        deve ser o MESMO array (ordenado) retornado por
        Sampler.compute_repetition_ids() para a mesma janela de geração --
        é o conjunto de exclusão que garante a corretude (ver docstring da
        classe). Sempre escreve exclude_count (mesmo 0) -- o kernel roda em
        TODO replay do grafo (inclusive prefill), então o buffer precisa
        estar num estado válido mesmo quando não há nada pra excluir ainda.
        """
        exclude_count = int(unique_ids.size)
        if exclude_count > MAX_EXCLUDE:
            # REPETITION_WINDOW já limita isto a <= 512 na origem -- guarda
            # defensiva caso o chamador mude essa constante sem atualizar aqui.
            raise ValueError(
                f"exclude_count ({exclude_count}) excede MAX_EXCLUDE ({MAX_EXCLUDE})"
            )

        self.hip.safe_memcpy_host_to_device(
            self.exclude_count_ptr,
            np.array([exclude_count], dtype=np.int32).tobytes(),
            tag="topk_exclude_count_h2d",
        )
        if exclude_count > 0:
            self.hip.safe_memcpy_host_to_device(
                self.exclude_ids_ptr,
                unique_ids.astype(np.int32).tobytes(),
                tag="topk_exclude_ids_h2d",
            )

    def read_candidates(self):
        """Lê de volta os candidatos produzidos pelo kernel no replay MAIS
        RECENTE (já rodou como parte do grafo -- nenhum lançamento aqui).
        Um único memcpy (as três saídas são sub-regiões contíguas de um só
        buffer). Retorna (group_values, group_indices, gathered_values)
        prontos para Sampler.pick_greedy_from_gpu_candidates."""
        self.hip.safe_memcpy_device_to_host(
            self._host_output, ctypes.c_void_p(self.output_buf), tag="logits_topk_readback"
        )

        group_values = np.frombuffer(self._host_output, dtype=np.float32, count=NUM_THREADS, offset=0).copy()
        group_indices = np.frombuffer(self._host_output, dtype=np.int32, count=NUM_THREADS, offset=_VALUES_BYTES).copy()
        gathered_values = np.frombuffer(
            self._host_output, dtype=np.float32, count=MAX_EXCLUDE, offset=_VALUES_BYTES + _INDICES_BYTES
        ).copy()

        return group_values, group_indices, gathered_values

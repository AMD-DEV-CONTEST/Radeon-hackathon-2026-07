import ctypes
import math
import mmap
from pathlib import Path
from vte.bridge.errors import HIPSafetyError
from vte.bridge.logger import get_logger
from vte.compiler.dequantizer import to_fp16_bytes
from vte.compiler.qwen_mapper import is_raw_q4k_weight, is_raw_q6k_weight, is_raw_q5_0_weight
from vte.compiler.granite_mapper import is_raw_q8_0_weight

logger = get_logger(__name__)

# Tamanho máximo de um único hipMemcpy Host->Device. Uma cópia síncrona gigante
# em uma chamada só (ex.: 445MB do token_embd.weight de uma vez) é um gatilho
# clássico de TDR no Windows/WDDM — o driver pode considerar a GPU "travada" se
# uma única operação demorar demais. Fatiar em pedaços menores dá ao driver
# janelas entre chamadas para não estourar o timeout.
_MAX_MEMCPY_CHUNK_BYTES = 16 * 1024 * 1024  # 16MB

class GGUFWeightLoader:
    """
    Injeta os pesos do GGUF na VRAM, dequantizando (Q4_K/Q6_K) ou convertendo
    (F32) tudo para FP16 contíguo no processo. Os kernels HIP trabalham apenas
    com FP16 puro — dequantizar aqui evita reimplementar os formatos de bloco
    (Q4_K, Q6_K) em cada kernel C++ e elimina o desalinhamento de tipos que
    existia entre pesos quantizados/F32 e kernels que assumiam FP16 puro.
    """

    def __init__(self, gguf_path: str | Path, parser, tensor_mapping: dict,
                 raw_q4k: set | None = None, raw_q6k: set | None = None, raw_q8_0: set | None = None,
                 raw_q5_0: set | None = None):
        """
        `raw_q4k`/`raw_q6k`/`raw_q8_0`: conjuntos de nomes de tensor JÁ
        decididos como "cru na VRAM" (mesmos conjuntos que model.py registra
        no executor via register_raw_*_weights). Quando None, cai no
        comportamento antigo (chama is_raw_*_weight por tensor) -- mantido só
        por compatibilidade, nenhum chamador atual depende disso.

        Passar os conjuntos já prontos evita um bug real encontrado nesta
        sessão: chamar `qwen_mapper.is_raw_q6k_weight` (restrito a
        ffn_down/token_embd, pensado pro GGUF misto do Qwen2.5) direto aqui
        ignorava a união feita em model.py para o Qwen3.5 (onde TODA matriz
        grande é Q6_K, não só ffn_down/token_embd). Resultado: attn_qkv.weight
        era alocado CRU (~10MB) pelo mapper mas o loader dequantizava pra FP16
        (~25MB) e despejava esse tanto a mais no mesmo slot -- overflow real,
        sobrescrevendo tensores vizinhos na VRAM.
        """
        self.path = Path(gguf_path)
        self.parser = parser
        self.tensor_mapping = tensor_mapping
        self.raw_q4k = raw_q4k
        self.raw_q6k = raw_q6k
        self.raw_q8_0 = raw_q8_0
        self.raw_q5_0 = raw_q5_0

    def load_all(self, hip_runtime) -> tuple[int, int]:
        """Mapeia o arquivo GGUF via mmap e copia cada tensor para seu ponteiro VRAM."""
        logger.info("Carregando pesos reais do GGUF para VRAM (mmap)...")

        loaded = 0
        total_bytes = 0

        with open(self.path, "rb") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                for name, t_info in self.parser.tensors.items():
                    if t_info.get('is_tied', False):
                        continue

                    block = self.tensor_mapping.get(name)
                    if block is None:
                        logger.warning(f"Tensor '{name}' sem ponteiro VRAM mapeado. Pulando injeção.")
                        continue

                    ptr_val = block.ptr if hasattr(block, 'ptr') else block

                    offset = t_info['offset']
                    size = t_info['size']
                    n_elements = math.prod(t_info['shape'])

                    if offset + size > len(mm):
                        raise HIPSafetyError(
                            f"Tensor '{name}' excede o arquivo mapeado (offset={offset}, size={size})."
                        )

                    raw_bytes = mm[offset:offset + size]

                    # Etapa C: pesos roteados ao gemv_q4k/gemv_q6k/gemv_q8_0
                    # ficam CRUS na VRAM (desquantização in-kernel). O resto
                    # vai FP16. Usa os conjuntos já unificados (se fornecidos)
                    # em vez de rechamar is_raw_*_weight isoladamente -- ver
                    # docstring do __init__.
                    if self.raw_q4k is not None or self.raw_q6k is not None or self.raw_q8_0 is not None or self.raw_q5_0 is not None:
                        is_raw = (
                            (self.raw_q4k is not None and name in self.raw_q4k)
                            or (self.raw_q6k is not None and name in self.raw_q6k)
                            or (self.raw_q8_0 is not None and name in self.raw_q8_0)
                            or (self.raw_q5_0 is not None and name in self.raw_q5_0)
                        )
                    else:
                        is_raw = (
                            is_raw_q4k_weight(name, t_info)
                            or is_raw_q6k_weight(name, t_info)
                            or is_raw_q8_0_weight(name, t_info)
                            or is_raw_q5_0_weight(name, t_info)
                        )
                    if is_raw:
                        upload_bytes = bytes(raw_bytes)
                    else:
                        upload_bytes = to_fp16_bytes(raw_bytes, t_info['dtype'], n_elements)

                    self._chunked_upload(hip_runtime, ptr_val, upload_bytes, name)

                    loaded += 1
                    total_bytes += len(upload_bytes)

        logger.info(
            f"Pesos injetados na VRAM: {loaded} tensores, {total_bytes / (1024 * 1024):.1f} MB."
        )
        return loaded, total_bytes

    def _chunked_upload(self, hip_runtime, dst_ptr: int, data: bytes, name: str):
        """Copia `data` para a VRAM em pedaços de no máximo _MAX_MEMCPY_CHUNK_BYTES."""
        total_len = len(data)
        if total_len <= _MAX_MEMCPY_CHUNK_BYTES:
            hip_runtime.safe_memcpy_host_to_device(
                ctypes.c_void_p(dst_ptr), data, tag=f"weight_load_{name}"
            )
            return

        offset = 0
        chunk_idx = 0
        while offset < total_len:
            chunk = data[offset:offset + _MAX_MEMCPY_CHUNK_BYTES]
            hip_runtime.safe_memcpy_host_to_device(
                ctypes.c_void_p(dst_ptr + offset), chunk, tag=f"weight_load_{name}_chunk{chunk_idx}"
            )
            offset += len(chunk)
            chunk_idx += 1

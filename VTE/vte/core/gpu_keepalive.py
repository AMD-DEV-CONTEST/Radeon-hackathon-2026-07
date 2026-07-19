import ctypes
import time
import numpy as np
from vte.bridge.memory import MemoryRegion
from vte.compiler.codegen import CodegenEngine
from vte.bridge.logger import get_logger

logger = get_logger(__name__)


class GPUKeepAlive:
    """
    Mantém a GPU com atividade mínima e contínua durante os intervalos
    ociosos entre passos de decodificação (token a token), em vez de deixá-la
    cair para o repouso completo.

    Por quê: o gerenciador de energia da GPU (DPM) reduz o clock/voltagem
    quando não há trabalho na fila. Ao alternar rapidamente entre "rajada
    pesada de matmul" e "ocioso completo" (o padrão natural de gerar um
    token por vez), a transição abrupta de volta ao clock alto pode causar
    stuttering ou, em casos piores, o driver interpretar a queda de tensão
    como sinal de travamento (acionando TDR). Pulsos pequenos e regulares
    de trabalho real (não um no-op vazio) durante o intervalo ocioso mantêm
    a GPU num patamar de clock mais estável, suavizando essas transições.

    Uso: chamado no MESMO thread que despacha a inferência (não usa thread
    de fundo própria), para não introduzir concorrência de acesso ao HIP
    stream — mais simples e seguro do que sincronizar múltiplas threads
    despachando na mesma GPU.
    """

    _BUFFER_ELEMENTS = 64

    def __init__(self, hip_runtime, allocator):
        self.hip = hip_runtime
        self.allocator = allocator
        self._kernel_fn = None
        self._buffer_ptr = None
        self._enabled = False

        try:
            self._compile_and_allocate()
            self._enabled = True
        except Exception as e:
            logger.warning(f"GPUKeepAlive não pôde ser inicializado ({e}). Seguindo sem keep-alive de clock.")

    def _compile_and_allocate(self):
        arch = self.hip.get_gpu_architecture()
        codegen = CodegenEngine()
        _, function = codegen.load_kernel_safe(self.hip, "keepalive", arch, "keepalive_kernel")
        self._kernel_fn = function

        block = self.allocator.allocate(self._BUFFER_ELEMENTS * 4, "gpu_keepalive_buffer", MemoryRegion.SCRATCH)
        self._buffer_ptr = block.ptr

        seed = np.ones(self._BUFFER_ELEMENTS, dtype=np.float32)
        self.hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(self._buffer_ptr), seed.tobytes(), tag="gpu_keepalive_seed"
        )

    def pulse(self, duration_seconds: float, pulse_interval_seconds: float = 0.005):
        """
        Mantém a GPU levemente ativa por `duration_seconds`, disparando o
        kernel minúsculo a cada `pulse_interval_seconds`. Substitui um
        `time.sleep(duration_seconds)` puro nos pontos de espera entre
        passos de geração.
        """
        if not self._enabled or duration_seconds <= 0:
            time.sleep(max(duration_seconds, 0))
            return

        args = [ctypes.c_void_p(self._buffer_ptr)]
        deadline = time.perf_counter() + duration_seconds

        while True:
            now = time.perf_counter()
            remaining = deadline - now
            if remaining <= 0:
                break

            try:
                self.hip.launch_kernel(
                    function=self._kernel_fn,
                    grid=(1, 1, 1),
                    block=(self._BUFFER_ELEMENTS, 1, 1),
                    args=args,
                    shared_mem=0,
                    expected_args=1,
                )
            except Exception as e:
                logger.debug(f"GPUKeepAlive: pulso falhou ({e}), desativando pelo resto da sessão.")
                self._enabled = False
                break

            time.sleep(min(pulse_interval_seconds, max(remaining, 0)))

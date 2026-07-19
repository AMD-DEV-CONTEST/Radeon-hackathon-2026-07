"""
VRAMPressureGuard -- monitora a VRAM REAL da GPU (hipMemGetInfo, inclui
QUALQUER processo usando a GPU, não só o VTE: jogo, navegador com aceleração
de GPU, outro app de IA) e, se o uso sustentado passar de 95%, descarrega
automaticamente o(s) modelo(s) VTE carregados (o menos recentemente usado
primeiro) para liberar memória, deixando um log claro do porquê.

Diferente do `GPUUtilizationGuard` (só observa utilização de COMPUTE, nunca
interrompe -- ver docstring lá): aqui a ação É intencional, porque VRAM
cheia não se resolve sozinha "esperando o pico passar" como utilização de
compute -- alguém (o próprio VTE ou outro processo) precisa efetivamente
liberar memória, ou a próxima alocação real (do VTE ou de qualquer outro
programa) vai falhar com OOM.

Singleton de processo (não por modelo/HIPRuntime): um só monitor cuida de
TODOS os modelos VTE carregados nesse processo (ex.: alvo + draft do
speculative decoding, Fase 5).
"""
import threading
import time
from typing import Optional
from vte.bridge.logger import get_logger

logger = get_logger(__name__)


class VRAMPressureGuard:
    def __init__(self, threshold_percent: float = 95.0, poll_interval_seconds: float = 3.0,
                 sustained_samples: int = 2):
        self._threshold = threshold_percent
        self._poll_interval = poll_interval_seconds
        self._sustained_samples = sustained_samples

        self._models: list = []  # instâncias de VTEModel registradas, weak seria ideal mas simples aqui
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._consecutive_over = 0
        self._unloading = False  # evita reentrância (unload() disparando novo unload)

    def register_model(self, model) -> None:
        with self._lock:
            if model not in self._models:
                self._models.append(model)
            if not self._running:
                self._running = True
                self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="VRAMPressureGuard")
                self._thread.start()
                logger.info(f"VRAMPressureGuard iniciado (limite {self._threshold}%, checa VRAM real da GPU a cada {self._poll_interval}s).")

    def unregister_model(self, model) -> None:
        with self._lock:
            if model in self._models:
                self._models.remove(model)
            if not self._models and self._running:
                self._running = False

    def stop(self) -> None:
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _monitor_loop(self):
        while True:
            time.sleep(self._poll_interval)
            with self._lock:
                if not self._running:
                    return
                models_snapshot = list(self._models)
            if not models_snapshot or self._unloading:
                continue

            # Qualquer HIPRuntime já inicializado serve -- hipMemGetInfo
            # reflete a GPU inteira, não uma view por-instância.
            hip = None
            for m in models_snapshot:
                if getattr(m, '_hip', None) is not None:
                    hip = m._hip
                    break
            if hip is None:
                continue

            try:
                free_bytes, total_bytes = hip.get_real_mem_info()
            except Exception as e:
                logger.debug(f"VRAMPressureGuard: falha ao consultar hipMemGetInfo: {e}")
                continue

            used_percent = 100.0 * (1.0 - (free_bytes / total_bytes)) if total_bytes else 0.0

            if used_percent >= self._threshold:
                self._consecutive_over += 1
                logger.warning(
                    f"VRAM real da GPU em {used_percent:.1f}% (amostra {self._consecutive_over}/"
                    f"{self._sustained_samples} acima de {self._threshold}%) -- livre: "
                    f"{free_bytes/1024/1024:.0f}MB de {total_bytes/1024/1024:.0f}MB."
                )
                if self._consecutive_over >= self._sustained_samples:
                    self._handle_pressure(models_snapshot, used_percent, free_bytes, total_bytes)
                    self._consecutive_over = 0
            else:
                self._consecutive_over = 0

    def _handle_pressure(self, models_snapshot: list, used_percent: float, free_bytes: int, total_bytes: int):
        # Descarrega o modelo MENOS recentemente usado primeiro -- se dois
        # modelos estão carregados (ex.: alvo + draft da Fase 5), o que está
        # ocioso há mais tempo é o candidato mais seguro a liberar.
        def _last_activity(m):
            lc = getattr(m, '_lifecycle', None)
            return getattr(lc, '_last_activity_time', 0.0) if lc else 0.0

        victim = min(models_snapshot, key=_last_activity)
        model_name = getattr(victim, '_path', 'modelo desconhecido')

        logger.critical(
            f"VRAM DA GPU CHEIA ({used_percent:.1f}% de uso REAL, considerando TODOS os "
            f"processos usando a GPU -- não só o VTE). Livre: {free_bytes/1024/1024:.0f}MB de "
            f"{total_bytes/1024/1024:.0f}MB. Isso pode ser outro programa (jogo, navegador com "
            f"aceleração de GPU, outro app de IA) consumindo VRAM além do que o VTE reservou. "
            f"Descarregando automaticamente o modelo menos usado no momento ('{model_name}') "
            f"para evitar instabilidade/falha de alocação."
        )

        self._unloading = True
        try:
            victim.unload()
        except Exception as e:
            logger.error(f"VRAMPressureGuard: falha ao descarregar modelo sob pressão de VRAM: {e}")
        finally:
            self._unloading = False


_GLOBAL_GUARD: Optional[VRAMPressureGuard] = None
_GLOBAL_GUARD_LOCK = threading.Lock()


def get_vram_pressure_guard() -> VRAMPressureGuard:
    """Singleton de processo -- um monitor cuida de todos os VTEModel carregados."""
    global _GLOBAL_GUARD
    with _GLOBAL_GUARD_LOCK:
        if _GLOBAL_GUARD is None:
            _GLOBAL_GUARD = VRAMPressureGuard()
        return _GLOBAL_GUARD

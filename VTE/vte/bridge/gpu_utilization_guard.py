import os
import threading
import time
from vte.bridge.logger import get_logger

logger = get_logger(__name__)


class GPUUtilizationGuard:
    """
    Monitora (só observa, não interrompe) a utilização de GPU do processo
    atual via contadores de performance do Windows — um segundo sinal
    independente, além da própria medição interna de tempo do
    HIPRuntime._enforce_duty_cycle_limit, útil para diagnóstico (ex.: detectar
    se ALGO ALÉM do nosso próprio código está pressionando a GPU).

    IMPORTANTE: este monitor NUNCA interrompe/pausa a execução — quem
    regula de fato a GPU para não passar de ~95% é o limitador de duty cycle
    em HIPRuntime (_throttle_before_dispatch / _throttle_duty_cycle), que
    insere pequenas pausas ANTES de cada lançamento sem nunca lançar exceção.
    Um guard que interrompe o programa ao detectar uso alto seria o oposto do
    que se quer aqui: o objetivo é a GPU rodar continuamente regulada a 95%,
    nunca "parar" por ter chegado perto do teto.

    Só funciona no Windows (usa a API PDH -- Performance Data Helper -- via
    `win32pdh`, in-process, sem spawnar `powershell.exe` a cada amostra como
    a versão anterior fazia). Em qualquer falha (win32pdh ausente, contador
    indisponível) apenas loga um aviso e continua sem travar a aplicação — é
    uma ferramenta de observabilidade best-effort, não uma dependência
    crítica.
    """

    def __init__(
        self,
        watchdog,
        threshold_percent: float = 95.0,
        poll_interval_seconds: float = 1.0,
        sustained_samples: int = 3,
    ):
        self._watchdog = watchdog
        self._threshold = threshold_percent
        self._poll_interval = poll_interval_seconds
        self._sustained_samples = sustained_samples
        self._pid = os.getpid()

        self._running = False
        self._thread: threading.Thread | None = None
        self._consecutive_over = 0
        self._last_reading: float | None = None

        self._query_handle = None
        # instance path (ex.: "GPU Engine(pid_1234_luid_...engtype_3d)") -> counter handle.
        # GPU Engine instances aparecem/somem dinamicamente conforme o PID
        # realmente usa cada engine (3d, video codec, copy, ...), então a
        # lista é resincronizada a cada amostra em vez de fixada uma vez.
        self._counter_handles: dict = {}

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="GPUUtilizationGuard")
        self._thread.start()
        logger.info(f"GPUUtilizationGuard iniciado (limite {self._threshold}%, PID {self._pid}).")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._query_handle is not None:
            try:
                import win32pdh
                win32pdh.CloseQuery(self._query_handle)
            except Exception:
                pass
            self._query_handle = None
            self._counter_handles.clear()
        logger.info("GPUUtilizationGuard parado.")

    def get_last_reading(self) -> float | None:
        return self._last_reading

    def _ensure_query_open(self) -> bool:
        if self._query_handle is not None:
            return True
        try:
            import win32pdh
            self._query_handle = win32pdh.OpenQuery()
            return True
        except Exception as e:
            logger.debug(f"GPUUtilizationGuard: win32pdh indisponível ({e}); monitor desativado.")
            return False

    def _sync_counters(self):
        """Adiciona contadores para instâncias de GPU Engine deste PID que
        apareceram desde a última amostra, e remove as que sumiram (ex.: uma
        engine que parou de ser usada). PDH mantém o estado/baseline de cada
        contador já existente entre chamadas -- só um contador recém-criado
        nesta rodada não terá uma leitura válida ainda (resolve sozinho na
        próxima amostra, já que CollectQueryData precisa de duas coletas com
        um intervalo real entre elas para um contador de % ter um valor)."""
        import win32pdh

        pid_marker = f"pid_{self._pid}_"
        try:
            paths = win32pdh.ExpandCounterPath(r"\GPU Engine(*)\Utilization Percentage")
        except Exception as e:
            logger.debug(f"GPUUtilizationGuard: falha ao expandir contadores de GPU Engine: {e}")
            return

        matching = {p for p in paths if pid_marker in p}

        for path in list(self._counter_handles):
            if path not in matching:
                try:
                    win32pdh.RemoveCounter(self._counter_handles[path])
                except Exception:
                    pass
                del self._counter_handles[path]

        for path in matching:
            if path not in self._counter_handles:
                try:
                    self._counter_handles[path] = win32pdh.AddCounter(self._query_handle, path)
                except Exception as e:
                    logger.debug(f"GPUUtilizationGuard: falha ao adicionar contador '{path}': {e}")

    def _query_gpu_utilization(self) -> float | None:
        if not self._ensure_query_open():
            return None

        import win32pdh

        try:
            self._sync_counters()
            if not self._counter_handles:
                return 0.0

            win32pdh.CollectQueryData(self._query_handle)

            total = 0.0
            for handle in list(self._counter_handles.values()):
                try:
                    _, value = win32pdh.GetFormattedCounterValue(handle, win32pdh.PDH_FMT_DOUBLE)
                    if value and value > 0:
                        total += value
                except Exception:
                    # Contador recém-adicionado ainda sem baseline (primeira
                    # coleta), ou instância que sumiu entre o sync e a
                    # coleta -- ambos transitórios, ignora esta amostra dele.
                    pass
            return total
        except Exception as e:
            logger.debug(f"GPUUtilizationGuard: falha ao consultar contador de GPU: {e}")
            return None

    def _monitor_loop(self):
        while self._running:
            time.sleep(self._poll_interval)
            if not self._running:
                break

            usage = self._query_gpu_utilization()
            if usage is None:
                continue

            self._last_reading = usage

            if usage >= self._threshold:
                self._consecutive_over += 1
                logger.debug(
                    f"Utilização de GPU (contador do Windows) em {usage:.1f}% "
                    f"(amostra {self._consecutive_over}/{self._sustained_samples} acima de {self._threshold}%). "
                    f"Apenas observação — quem regula é o duty cycle limiter em HIPRuntime."
                )
            else:
                self._consecutive_over = 0

import threading
import time
import traceback
from datetime import datetime
from vte.bridge.errors import HIPSafetyError
from vte.bridge.logger import get_logger
from vte.config import LOG_DIR, SAFE_DISPATCH_TIMEOUT

logger = get_logger(__name__)

class KernelWatchdog:
    def __init__(self, hip_runtime):
        self._hip = hip_runtime
        self._active_kernels: dict[str, tuple[float, int]] = {}
        self._abort_flags: dict[str, threading.Event] = {}
        self._global_panic: bool = False
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self):
        """Inicia a thread daemon de monitoramento."""
        if self._running:
            return
            
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="KernelWatchdog")
        self._thread.start()
        logger.info("KernelWatchdog iniciado.")

    def stop(self):
        """Para o monitoramento e limpa recursos."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        with self._lock:
            self._active_kernels.clear()
            self._abort_flags.clear()
        logger.info("KernelWatchdog parado.")

    def register_execution(self, kernel_name: str, estimated_ms: int = 100, timeout_multiplier: float = 2.0) -> str:
        """Registra início de execução de um kernel e retorna o execution_id."""
        if not self._running:
            logger.warning("Watchdog não está rodando. Registro ignorado.")
            return f"{kernel_name}_ignored"
            
        execution_id = f"{kernel_name}_{int(time.time() * 1000)}"
        timeout_ms = min(int(estimated_ms * timeout_multiplier), SAFE_DISPATCH_TIMEOUT)
        
        with self._lock:
            self._active_kernels[execution_id] = (time.time(), timeout_ms)
            self._abort_flags[execution_id] = threading.Event()
            
        logger.debug(f"Kernel registrado: {execution_id} - limite {timeout_ms}ms")
        return execution_id

    def complete_execution(self, execution_id: str):
        """Remove o kernel da lista de monitoramento (execução bem sucedida)."""
        with self._lock:
            self._active_kernels.pop(execution_id, None)
            self._abort_flags.pop(execution_id, None)

    def should_abort(self, execution_id: str) -> bool:
        """Disponível para o kernel (ou seu dispatcher) verificar se deve abortar prematuramente."""
        if self._global_panic:
            return True
        with self._lock:
            event = self._abort_flags.get(execution_id)
            return event.is_set() if event else False
            
    def is_panic_state(self) -> bool:
        """Sinaliza se o motor deve entrar em pânico seguro (parar envios)."""
        return self._global_panic

    def trigger_panic(self, reason: str):
        """
        Aciona o PANIC MODE externamente (ex.: GPUUtilizationGuard detectando
        utilização de GPU sustentada acima do limite seguro). Mesmo efeito de
        um timeout de kernel: bloqueia novos lançamentos até reinicialização.
        """
        with self._lock:
            if self._global_panic:
                return
            self._global_panic = True
        logger.critical(f"PANIC MODE ativado externamente: {reason}")

    def _monitor_loop(self):
        """Loop de verificação periódico."""
        while self._running:
            now = time.time()
            timeouts = []
            warnings = []
            
            with self._lock:
                for execution_id, (start_time, timeout_ms) in list(self._active_kernels.items()):
                    elapsed_ms = (now - start_time) * 1000
                    
                    if elapsed_ms > timeout_ms:
                        timeouts.append((execution_id, elapsed_ms, timeout_ms))
                    elif elapsed_ms > timeout_ms * 0.8:
                        warnings.append((execution_id, elapsed_ms, timeout_ms))
                        
            for eid, elapsed, limit in warnings:
                logger.warning(f"Kernel próximo do timeout: {eid} - {elapsed:.1f}ms / {limit}ms")
                
            for eid, elapsed, limit in timeouts:
                self._handle_timeout(eid, elapsed)
                
            time.sleep(0.1)

    def _handle_timeout(self, execution_id: str, elapsed_ms: float):
        """Trata o timeout de forma segura (sem reset prematuro)."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / f"timeout_{timestamp}.txt"
        
        try:
            with open(log_file, "w") as f:
                f.write(f"Kernel timeout detectado: {execution_id}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Elapsed: {elapsed_ms:.2f}ms\n")
                f.write(f"Stack trace da thread de controle:\n")
                f.write("".join(traceback.format_stack()))
        except Exception as e:
            logger.error(f"Falha ao escrever log de timeout: {e}")

        with self._lock:
            self._global_panic = True
            if execution_id in self._abort_flags:
                self._abort_flags[execution_id].set()

                self._active_kernels.pop(execution_id, None)

        logger.critical(f"Kernel timeout: {execution_id} ({elapsed_ms:.1f}ms). PANIC MODE ativado (bloqueando fila). Veja {log_file}")

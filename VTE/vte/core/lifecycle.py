import time
import threading
import ctypes
from typing import Optional, TYPE_CHECKING
from vte.bridge.logger import get_logger

if TYPE_CHECKING:
    from vte.core.model import VTEModel

logger = get_logger("VTE.Lifecycle")

class ModelLifecycleManager:
    """
    Gerencia o ciclo de vida do modelo na VRAM.
    
    Responsabilidades:
    - Monitorar inatividade
    - Descarregar modelo após timeout (lazy wipe)
    - Cleanup seguro no shutdown
    - Prevenir vazamento de dados
    """
    
    def __init__(
        self,
        model: "VTEModel",
        idle_timeout_seconds: int = 300,
        enable_auto_unload: bool = True
    ):
        self.model = model
        self.idle_timeout = idle_timeout_seconds
        self.enable_auto_unload = enable_auto_unload
        
        self._last_activity_time = time.time()
        self._unload_timer: Optional[threading.Timer] = None
        self._is_loaded = False
        self._operation_lock = threading.RLock()
        self._unload_in_progress = False
        self._wipe_on_next_load = False
        self._monitor_running = False
        
    def touch(self):
        """Registra atividade (chamado a cada generate())"""
        with self._operation_lock:
            if not self._is_loaded:
                return
            self._last_activity_time = time.time()
            logger.debug(f"Atividade registrada. Próximo unload em {self.idle_timeout}s")
            
            if self._unload_timer:
                self._unload_timer.cancel()
                self._start_idle_timer()
    
    def start_monitoring(self):
        """Inicia monitor de inatividade"""
        with self._operation_lock:
            self._is_loaded = True
            self.touch()
            if self.enable_auto_unload and not self._monitor_running:
                self._monitor_running = True
                self._start_idle_monitor()
    
    def _start_idle_monitor(self):
        """Inicia thread que monitora inatividade"""
        def monitor():
            while self._monitor_running:
                time.sleep(2)
                
                with self._operation_lock:
                    if not self._is_loaded:
                        continue
                        
                    idle_time = time.time() - self._last_activity_time
                    
                    if idle_time >= self.idle_timeout:
                        logger.info(
                            f"Modelo ocioso por {idle_time:.0f}s. "
                            f"Descarregando da VRAM..."
                        )
                        self.unload(secure_wipe=False)
                        break
        
        thread = threading.Thread(target=monitor, daemon=True, name="VTE-IdleMonitor")
        thread.start()
    
    def _start_idle_timer(self):
        """Inicia timer para unload automático (Alternativa ao loop de monitoramento)"""
        self._unload_timer = threading.Timer(
            self.idle_timeout,
            self._auto_unload
        )
        self._unload_timer.daemon = True
        self._unload_timer.start()
    
    def _auto_unload(self):
        """Callback do timer de unload"""
        with self._operation_lock:
            if self._is_loaded:
                logger.info("Unload automático disparado por timeout")
                self.unload(secure_wipe=False)
    
    def unload(self, secure_wipe: bool = False):
        """
        Descarrega modelo da VRAM de forma segura.
        
        Args:
            secure_wipe: Se True, zera VRAM imediatamente (lento).
                        Se False, zera apenas quando novo modelo for carregado (rápido).
        """
        with self._operation_lock:
            if self._unload_in_progress:
                logger.warning("Unload já em progresso, ignorando")
                return
            
            if not self._is_loaded:
                return
            
            self._unload_in_progress = True
            
            try:
                logger.info("Iniciando unload seguro do modelo...")
                
                if self._unload_timer:
                    self._unload_timer.cancel()
                    self._unload_timer = None
                
                if self.model._hip:
                    self.model._hip.synchronize()
                
                if secure_wipe:
                    self._secure_wipe_vram()
                else:
                    self._wipe_on_next_load = True
                
                if self.model._allocator:
                    if self.model._allocator.slab_base and self.model._hip:
                        import ctypes
                        try:
                            self.model._hip.safe_free(ctypes.c_void_p(self.model._allocator.slab_base), "VTE_GIANT_SLAB")
                        except Exception as e:
                            logger.error(f"Erro ao liberar Slab Físico: {e}")
                    self.model._allocator.cleanup()
                    self.model._allocator = None
                
                self.model._graph = None
                self._is_loaded = False
                
                logger.info(" Modelo descarregado da VRAM com sucesso")
                
            except Exception as e:
                logger.error(f"Erro durante unload: {e}")
                self._is_loaded = False
                raise
            finally:
                self._unload_in_progress = False
    
    def _secure_wipe_vram(self):
        """
        Zera a VRAM ativa associada a este runtime para evitar vazamento.
        Ignora VTE_ROOT_SLAB (alocação base do allocator gerenciada pelo HIP, se houver).
        """
        if not self.model._hip:
            return
            
        logger.debug("Iniciando wipe seguro da VRAM...")
        zero_buffer_size = 1024 * 1024
        zeros = b'\x00' * zero_buffer_size
        
        for ptr, (size, tag) in list(self.model._hip._active_allocations.items()):
            if tag.startswith("VTE_ROOT_SLAB"):
                continue
                
            logger.debug(f"Wiping {tag} ({size} bytes)...")
            
            offset = 0
            while offset < size:
                chunk_size = min(zero_buffer_size, size - offset)
                chunk = zeros[:chunk_size]
                
                dst_ptr = ptr + offset
                try:
                    self.model._hip.safe_memcpy_host_to_device(
                        ctypes.c_void_p(dst_ptr),
                        chunk,
                        tag=f"wipe_{tag}"
                    )
                except Exception as e:
                    logger.warning(f"Erro no wipe de {tag} em {offset}: {e}")
                
                offset += chunk_size
        
        self.model._hip.synchronize()
        logger.debug(" Wipe seguro concluído")
    
    def reload(self):
        """Recarrega modelo na VRAM (se foi descarregado)"""
        with self._operation_lock:
            if self._is_loaded:
                return
            
            if self._wipe_on_next_load:
                logger.info("Executando wipe lazy da VRAM antes de carregar novo estado...")
                self._secure_wipe_vram()
                self._wipe_on_next_load = False
                
            logger.info("Recarregando modelo na VRAM...")
            self.model._load()
            self.start_monitoring()
    
    def ensure_loaded(self):
        """Garante que o modelo está carregado (com lock)"""
        with self._operation_lock:
            if self._unload_in_progress:
                logger.info("Unload em progresso, aguardando...")
                while self._unload_in_progress:
                    time.sleep(0.1)
            
            if not self._is_loaded:
                self.reload()
            
            self.touch()
    
    def get_status(self) -> dict:
        """Retorna status atual do modelo"""
        with self._operation_lock:
            idle_time = time.time() - self._last_activity_time if self._is_loaded else None
            return {
                "is_loaded": self._is_loaded,
                "idle_time_seconds": idle_time,
                "idle_timeout": self.idle_timeout,
                "auto_unload_enabled": self.enable_auto_unload,
                "time_until_unload": max(0, self.idle_timeout - idle_time) if idle_time else None
            }

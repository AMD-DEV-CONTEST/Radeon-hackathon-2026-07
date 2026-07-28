import time
import sys
import threading
from pathlib import Path
from typing import Optional
from vte.bridge.logger import get_logger
from vte.bridge.hip_runtime import HIPRuntime

logger = get_logger("VTE.GPUMonitor")

class GPUMonitor:
    """
    Monitora GPU usando abordagem híbrida:
    - Métricas internas do HIP (VRAM rastreada pelo próprio VTE)
    - WMI (Windows) para VRAM dedicada real do sistema
    - ADL (vte/bridge/adl_bridge.py) para temperatura real no Windows
    - sysfs (Linux) para temperatura e uso

    Nota sobre temperatura no Windows: WMI (`Win32_VideoController`,
    `MSAcpi_ThermalZoneTemperature`) não expõe temperatura real de GPU
    nesta máquina -- checado antes de recorrer à ADL (AMD Display Library,
    `atiadlxx.dll`, já presente com qualquer driver AMD). Se a ADL também
    falhar (placa não suportada, driver não-AMD, etc.), `temperature`
    retorna `None` -- a UI mostra "N/A" em vez de inventar um número.
    """

    def __init__(self, hip_runtime: HIPRuntime, check_interval: int = 5):
        self.hip = hip_runtime
        self.check_interval = check_interval

        self._last_wmi_query = 0.0
        self._wmi_cache = {
            'temperature': None,
            'gpu_usage': 0.0,
            'fan_speed': None,
            'dedicated_vram_mb': 0.0,
        }
        # TTL curto: métricas de uso/VRAM mudam rápido durante geração: um
        # cache de 5s (valor original) fazia o dashboard parecer travado.
        self._wmi_cache_ttl = 1.0

        self._wmi_connection = None
        self._wmi_initialized = False

        self._adl = None  # lazy: só importa/inicializa a ADL se formos Windows

    def _get_vram_allocated_mb(self) -> float:
        """Soma as alocações rastreadas do HIP (o que o PRÓPRIO VTE alocou --
        pesos+KV+arena+scratch. É um subconjunto da VRAM dedicada TOTAL do
        sistema, que inclui compositor de desktop, outros processos, etc.)"""
        if not self.hip or not hasattr(self.hip, '_active_allocations'):
            return 0.0
        total_bytes = sum(size for size, _ in self.hip._active_allocations.values())
        return total_bytes / (1024 * 1024)

    def _get_vram_usage_percent(self) -> float:
        vram_allocated = self._get_vram_allocated_mb()
        if not self.hip or not hasattr(self.hip, '_vram_total') or self.hip._vram_total == 0:
            return 0.0
        return (vram_allocated / (self.hip._vram_total / (1024 * 1024))) * 100.0

    def get_gpu_metrics(self) -> dict:
        """Retorna métricas da GPU usando abordagem híbrida"""
        metrics = {}

        metrics['vram_usage_percent'] = self._get_vram_usage_percent()
        metrics['vram_allocated_mb'] = self._get_vram_allocated_mb()
        if self.hip and hasattr(self.hip, '_vram_total'):
            metrics['vram_total_system_mb'] = self.hip._vram_total / (1024 * 1024)
        else:
            metrics['vram_total_system_mb'] = 8192.0

        current_time = time.time()
        if current_time - self._last_wmi_query >= self._wmi_cache_ttl:
            try:
                if sys.platform == "win32":
                    wmi_data = self._query_wmi_windows()
                else:
                    wmi_data = self._query_sysfs_linux()

                self._wmi_cache.update(wmi_data)
                self._last_wmi_query = current_time

            except Exception as e:
                logger.debug(f"Falha ao query WMI/sysfs: {e}. Usando cache.")

        metrics['temperature'] = self._wmi_cache.get('temperature')
        metrics['gpu_usage'] = self._wmi_cache.get('gpu_usage', 0.0)
        metrics['fan_speed'] = self._wmi_cache.get('fan_speed')
        # VRAM dedicada REAL do sistema (mesma fonte que o Gerenciador de
        # Tarefas usa em "Memória da GPU dedicada") -- diferente de
        # vram_allocated_mb acima, que é só o que o VTE mesmo alocou.
        metrics['dedicated_vram_mb'] = self._wmi_cache.get('dedicated_vram_mb', 0.0)

        return metrics

    def _query_temperature(self) -> Optional[float]:
        """Temperatura real via ADL (vte/bridge/adl_bridge.py). Lazy-init:
        só carrega/toca a DLL na primeira chamada. Se a ADL não conseguir
        (placa não-AMD, driver ausente, API não suportada), retorna None --
        nunca inventa um valor."""
        if self._adl is None:
            try:
                from vte.bridge.adl_bridge import ADLBridge
                self._adl = ADLBridge()
            except Exception as e:
                logger.debug(f"ADL indisponível: {e}")
                return None
        try:
            return self._adl.get_temperature_celsius()
        except Exception as e:
            logger.debug(f"Leitura de temperatura via ADL falhou: {e}")
            return None

    def _query_wmi_windows(self) -> dict:
        """Query WMI no Windows via o performance counter GPUAdapterMemory
        (Windows 10+, nativo do driver WDDM -- é a MESMA fonte que o
        Gerenciador de Tarefas usa, então os números batem com o que o
        usuário vê lá). Confirmado presente e funcional nesta máquina
        (verificado via `Get-CimClass`/`Get-CimInstance` antes de escrever
        este código -- não é uma suposição). Temperatura vem de uma fonte
        totalmente separada (ADL, não WMI) -- ver `_query_temperature`."""
        temperature = self._query_temperature()
        try:
            import wmi

            if not self._wmi_initialized:
                import pythoncom
                pythoncom.CoInitialize()
                self._wmi_connection = wmi.WMI()
                self._wmi_initialized = True

            dedicated_mb = 0.0
            target_luid = None
            try:
                mem_instances = self._wmi_connection.Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory()
                # Várias "instâncias" podem existir (iGPU, WARP, a GPU
                # discreta) -- a de maior DedicatedUsage é a placa real em
                # uso (heurística validada nesta máquina: a AMD RX 7600
                # aparece com ~2.7GB dedicados enquanto instâncias
                # secundárias ficam em 0).
                best = max(mem_instances, key=lambda i: int(getattr(i, "DedicatedUsage", 0) or 0), default=None)
                if best is not None:
                    dedicated_mb = int(best.DedicatedUsage or 0) / (1024 * 1024)
                    name = str(best.Name)
                    if "_phys_" in name:
                        target_luid = name.split("_phys_")[0]
            except Exception as e:
                logger.debug(f"GPUAdapterMemory indisponível: {e}")

            # GPUEngine (uso %) foi removida daqui: medida em ~3-4s por
            # chamada nesta máquina (228 instâncias para enumerar -- uma por
            # combinação processo/engine no sistema INTEIRO), o que sozinho
            # travava a telemetria em ~5s por tick em vez dos 0.35s
            # pretendidos. O valor nem chega a ser exibido no dashboard hoje
            # -- não vale o custo. Se um "uso %" real for necessário no
            # futuro, medir de novo antes de reintroduzir (pode ter sido
            # um pico pontual desta máquina, não necessariamente universal).
            usage_percent = 0.0

            return {
                'temperature': temperature,
                'gpu_usage': usage_percent,
                'fan_speed': None,
                'dedicated_vram_mb': dedicated_mb,
            }

        except Exception as e:
            logger.debug(f"WMI query falhou: {e}")
            # `temperature` já foi lido via ADL (fonte independente do WMI)
            # antes deste try -- uma falha aqui não deve descartá-lo.
            return {'temperature': temperature, 'gpu_usage': 0.0, 'fan_speed': None, 'dedicated_vram_mb': 0.0}

    def _query_sysfs_linux(self) -> dict:
        """Query sysfs no Linux (rápido e preciso)"""
        try:
            temp_path = Path("/sys/class/drm/card0/device/hwmon/hwmon0/temp1_input")
            if temp_path.exists():
                temp = int(temp_path.read_text()) / 1000.0
            else:
                temp = None

            busy_path = Path("/sys/class/drm/card0/device/gpu_busy_percent")
            if busy_path.exists():
                usage = float(busy_path.read_text())
            else:
                usage = 0.0

            return {'temperature': temp, 'gpu_usage': usage, 'fan_speed': None, 'dedicated_vram_mb': 0.0}

        except Exception as e:
            logger.debug(f"sysfs query falhou: {e}")
            return {'temperature': None, 'gpu_usage': 0.0, 'fan_speed': None, 'dedicated_vram_mb': 0.0}

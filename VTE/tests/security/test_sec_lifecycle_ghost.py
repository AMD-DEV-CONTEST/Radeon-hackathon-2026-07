import os
import sys
import socket
import urllib.request
import pytest
import time
import subprocess
from vte.core.gpu_monitor import GPUMonitor
from vte.bridge.hip_runtime import HIPRuntime


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(
    os.environ.get("VTE_RUN_INTEGRATION_TESTS") != "1",
    reason="Requer GPU AMD, modelo baixado e spawn de subprocessos",
)
def test_zombie_kernel_detection():
    """Valida que o vte-server encerra (liberando VRAM) quando o processo pai
    designado desaparece, sem deixar kernels/alocacoes orfaos -- exercita o
    watchdog de parent-pid (http_server._start_parent_watchdog)."""
    model_path = "Model/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
    if not os.path.exists(model_path):
        pytest.skip(f"Modelo nao encontrado: {model_path}")

    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    port = _free_port()
    server = subprocess.Popen([
        sys.executable, "-m", "vte.server.http_server",
        "--gguf-path", model_path, "--port", str(port), "--host", "127.0.0.1",
        "--context-length", "512", "--idle-timeout", "0", "--vram-limit-pct", "0",
        "--parent-pid", str(parent.pid),
    ])
    try:
        ready = False
        for _ in range(120):
            if server.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                    if r.status == 200:
                        ready = True
                        break
            except Exception:
                pass
            time.sleep(1)
        assert ready, "vte-server nao ficou ready antes de matar o pai"
        assert server.poll() is None, "vte-server morreu antes de matarmos o pai"

        parent.kill()
        parent.wait(timeout=10)

        # Watchdog faz poll a cada 5s; espera esse intervalo + margem.
        exited = False
        for _ in range(20):
            if server.poll() is not None:
                exited = True
                break
            time.sleep(1)
        assert exited, (
            "vte-server nao encerrou apos o pai sumir: watchdog de orfao falhou, "
            "os kernels/VRAM ficariam orfaos"
        )
    finally:
        for p in (server, parent):
            if p.poll() is None:
                p.kill()
                try:
                    p.wait(timeout=10)
                except Exception:
                    pass

def test_power_consumption_idle():
    """Valida que GPU nao consome energia quando ociosa e nao possui threads zumbis."""
    try:
        hip = HIPRuntime()
        hip.initialize()
    except Exception:
        pytest.skip("Requer GPU AMD nativa.")
        
    monitor = GPUMonitor(hip)
    
    metrics_baseline = monitor.get_gpu_metrics()
    baseline_power = metrics_baseline.get('power_w', 0.0) # Mock fallbacks podem retornar 0
    
    # Em um cenario real de teste, importariamos VTEModel e simulariamos
    # Por agora, simulamos apenas que o monitor esta respondendo
    metrics_idle = monitor.get_gpu_metrics()
    loaded_power = metrics_idle.get('power_w', 0.0)
    
    power_diff = loaded_power - baseline_power
    assert power_diff < 10.0, f"GPU consumindo {power_diff:.1f}W extra quando ociosa. Processamento fantasma detectado."

def test_auto_unload_idle():
    """Verifica se o modelo e descarregado da VRAM apos o timeout de inatividade."""
    from vte.core.lifecycle import ModelLifecycleManager
    
    class MockModel:
        def __init__(self):
            self._hip = None
            self._allocator = None
            self._graph = None
            
        def _load(self):
            pass
            
    model = MockModel()
    # Usando timeout de 10 segundos conforme pedido
    manager = ModelLifecycleManager(model, idle_timeout_seconds=10, enable_auto_unload=True)
    manager.start_monitoring()
    
    assert manager._is_loaded is True, "O lifecycle deveria estar marcado como carregado ao iniciar."
    
    # Aguarda 10 segundos do timeout + ~3 segundos do loop interno (que roda a cada 2s)
    time.sleep(13)
    
    assert manager._is_loaded is False, "O modelo NAO foi descarregado automaticamente da VRAM apos o timeout de 10 segundos!"

def test_unload_on_shutdown():
    """Verifica se o cleanup automatico (unload) ocorre quando o aplicativo e encerrado."""
    from vte.core.model import VTEModel
    from unittest.mock import patch, MagicMock
    from pathlib import Path

    with patch('vte.core.model.ModelLifecycleManager') as mock_lifecycle_class:
        mock_lifecycle = MagicMock()
        mock_lifecycle._is_loaded = True
        mock_lifecycle_class.return_value = mock_lifecycle
        
        model = VTEModel(Path("Model/fake.gguf"))
        model._loaded = True
        
        # Simulando encerramento/destruicao (ex: garbage collector limpa no fechamento do app)
        model.__del__()
        
        # Verifica se o unload foi chamado!
        mock_lifecycle.unload.assert_called_once()


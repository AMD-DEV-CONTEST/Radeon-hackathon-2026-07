from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class UIMsgPrompt:
    text: str
    max_tokens: int = 512

@dataclass
class UIMsgCancel:
    pass

@dataclass
class UIMsgShutdown:
    pass

@dataclass
class MotorMsgToken:
    text: str
    # "answer" (padrão, retrocompatível) | "thinking" -- separa o
    # raciocínio (dentro de <think>...</think>) da resposta final. Ver
    # vte/core/thinking_scanner.py.
    section: str = "answer"

@dataclass
class MotorMsgDone:
    """Sinaliza que a geração terminou (fim natural no EOS, limite de tokens,
    ou cancelamento). A UI usa isto para re-habilitar o input e restaurar o
    botão de enviar -- sem este sinal a interface fica presa no estado
    'gerando' para sempre. `cancelled` distingue parada a pedido do usuário."""
    cancelled: bool = False

@dataclass
class MotorMsgMetrics:
    temp_c: Optional[float]
    clock_mhz: float
    # VRAM que o PRÓPRIO VTE alocou (weights+kv+arena+scratch) -- determinístico,
    # sempre soma exatamente igual à quebra em vram_details.
    vram_mb: float
    power_w: float
    tokens_sec: float
    vram_free_system_mb: float = 0.0
    vram_details: Optional[dict] = None
    ms_per_token: float = 0.0
    # VRAM dedicada REAL do sistema inteiro (WMI GPUAdapterMemory -- mesma
    # fonte que o Gerenciador de Tarefas usa). Inclui outros processos
    # (desktop, navegador, etc.), por isso é mostrada como referência
    # separada em vez de "vram_mb" -- misturar as duas fazia o número
    # principal saltar de forma confusa por atividade alheia ao VTE.
    system_dedicated_vram_mb: float = 0.0

@dataclass
class MotorMsgProgress:
    status: str
    percentage: float

@dataclass
class MotorMsgReady:
    pass

@dataclass
class MotorMsgError:
    message: str

@dataclass
class MotorMsgStatusUpdate:
    is_loaded: bool
    time_until_unload: Optional[float]

@dataclass
class MotorMsgLog:
    """Uma linha de log já formatada, encaminhada do processo do motor para a
    UI (PipeLogHandler em motor.py, anexado ao root logger)."""
    text: str
    level: str = "INFO"

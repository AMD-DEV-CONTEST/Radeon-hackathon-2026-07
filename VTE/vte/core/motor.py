import dataclasses
import logging
import time
import threading
from multiprocessing.connection import Connection
from typing import Optional

from vte.core.ipc import (
    UIMsgPrompt, UIMsgCancel, UIMsgShutdown,
    MotorMsgToken, MotorMsgMetrics, MotorMsgProgress, MotorMsgReady, MotorMsgError,
    MotorMsgStatusUpdate, MotorMsgLog, MotorMsgDone
)
from vte.core.model import VTEModel
from vte.core.gpu_monitor import GPUMonitor
from vte.core.thinking_scanner import ThinkingSectionScanner
from vte.bridge.logger import get_logger

logger = get_logger("VTE.Motor")

DEFAULT_CONTEXT_LENGTH = 2048
DEFAULT_MODEL_NAME = "qwen2.5:1.5b-q4_k_m"


class PipeLogHandler(logging.Handler):
    """Encaminha registros de log (INFO+) do processo do motor para a UI via
    pipe. Anexado ao ROOT logger (não a um logger específico): get_logger()
    não desliga propagate, então todo logger de módulo VTE (vte.core.*,
    vte.bridge.*, ...) já propaga para cá sem precisar instrumentar cada
    módulo individualmente.
    """

    def __init__(self, conn: Connection, send_lock: threading.Lock):
        super().__init__(level=logging.INFO)
        self.conn = conn
        self.send_lock = send_lock
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
        ))

    def emit(self, record: logging.LogRecord):
        try:
            msg = MotorMsgLog(self.format(record), record.levelname)
            with self.send_lock:
                self.conn.send(msg)
        except Exception:
            # Uma falha ao encaminhar um log nunca pode derrubar o motor --
            # na pior das hipóteses a UI perde uma linha.
            pass


class InferenceEngine:
    def __init__(self, pipe_conn: Connection, context_length: int = DEFAULT_CONTEXT_LENGTH, model_name: str = DEFAULT_MODEL_NAME):
        self.conn = pipe_conn
        self.running = True
        self.is_generating = False
        self.context_length = context_length

        self.token_buffer = ""
        self.last_flush_time = 0.0
        self.flush_interval = 0.050
        # Recriado a cada generate() (linha abaixo) -- separa texto
        # "thinking" (dentro de <think>...</think>) do resto, sobre o
        # stream decodificado. Ver vte/core/thinking_scanner.py.
        self._thinking_scanner = ThinkingSectionScanner()

        # Métricas reais de throughput (Fase UI): atualizadas token a token
        # dentro de generate(), lidas pela thread de telemetria. EMA em vez
        # do valor instantâneo puro para não deixar o número saltando a cada
        # token -- suave o bastante para leitura humana, reativo o bastante
        # para refletir mudanças reais de regime (ex.: prefill vs decode).
        self.last_tps = 0.0
        self.last_ms_per_token = 0.0

        self.model_name = model_name
        self.model = None
        self._gpu_monitor: Optional[GPUMonitor] = None
        self._last_metrics_snapshot: Optional[MotorMsgMetrics] = None

        # Múltiplas threads (loop principal, telemetria, o log handler
        # disparado de qualquer uma delas) escrevem na mesma Connection --
        # multiprocessing.Connection não garante atomicidade entre sends
        # concorrentes de threads distintas do mesmo lado do pipe.
        self._send_lock = threading.Lock()
        logging.getLogger().addHandler(PipeLogHandler(pipe_conn, self._send_lock))

        self.telemetry_thread = threading.Thread(target=self._telemetry_loop, daemon=True)

    def _send(self, msg):
        with self._send_lock:
            self.conn.send(msg)

    def boot(self):
        """Inicializa as Fases 0 a 3 através do VTEModel"""
        self._send(MotorMsgProgress("Iniciando Model Lifecycle...", 10))

        try:
            self.model = VTEModel.from_pretrained(
                self.model_name,
                context_length=self.context_length,
                idle_timeout_seconds=300,
                enable_auto_unload=True
            )
            self._send(MotorMsgProgress("Modelo carregado na VRAM...", 100))
        except Exception as e:
            self._send(MotorMsgError(f"Falha no boot: {e}"))
            self.running = False
            return

        self._send(MotorMsgReady())
        self.telemetry_thread.start()

    def _get_monitor(self) -> Optional[GPUMonitor]:
        if self._gpu_monitor is None and self.model and self.model._hip:
            self._gpu_monitor = GPUMonitor(self.model._hip)
        return self._gpu_monitor

    def _build_metrics_msg(self) -> MotorMsgMetrics:
        """Monta um snapshot COMPLETO de métricas (consulta WMI via
        GPUMonitor incluída). CHAMAR SÓ da thread de telemetria: os objetos
        COM/WMI por trás de `pythoncom`/`wmi.WMI()` têm afinidade de thread
        -- inicializar/usar a mesma conexão de duas threads diferentes
        (aqui e a thread principal de generate()) já causou a thread de
        telemetria morrer silenciosamente (`except Exception: break` sem
        log) quando as duas disputavam o mesmo objeto COM. Por isso o push
        de tps em tempo real durante a geração usa `_tps_snapshot_msg()`
        abaixo, que reaproveita este snapshot em vez de tocar WMI de novo."""
        monitor = self._get_monitor()
        if monitor:
            metrics = monitor.get_gpu_metrics()
            temp = metrics.get('temperature')  # None se indisponível (ver gpu_monitor.py)
            clock = 0.0
            total_vram = metrics.get('vram_total_system_mb', 8192.0)
            # Número principal (vram): o que o PRÓPRIO VTE alocou --
            # determinístico, explicado exatamente pela quebra
            # Weights/KV/Arena abaixo. `system_dedicated_vram_mb` é a
            # referência separada (WMI, bate com o Gerenciador de Tarefas,
            # mas inclui outros processos -- por isso não é o número
            # principal: misturar os dois fazia o valor saltar de forma
            # confusa por atividade alheia ao VTE).
            vram = metrics.get('vram_allocated_mb', 0.0)
            system_dedicated = metrics.get('dedicated_vram_mb', 0.0)
            vram_free = max(0.0, total_vram - (system_dedicated if system_dedicated > 0.0 else vram))
            power = 0.0
        else:
            temp = None
            clock = 0.0
            vram = 0.0
            system_dedicated = 0.0
            vram_free = 8192.0
            power = 0.0

        # Deliberadamente NÃO zera ao terminar a geração -- self.last_tps/
        # last_ms_per_token só são resetados no INÍCIO de generate() (nova
        # mensagem). Assim o usuário consegue ler o resultado da última
        # mensagem (tok/s, ms/tok) até a próxima geração começar, em vez de
        # ver o número sumir para 0.0 assim que a resposta termina.
        tps = self.last_tps
        ms_per_token = self.last_ms_per_token

        # vram_details é só a QUEBRA (Weights/KV/Arena) do que o VTE mesmo
        # alocou -- um subconjunto do "vram" real acima (dedicada do
        # sistema inteiro), não a fonte do número principal.
        vram_details = None
        if self.model and self.model._is_loaded:
            try:
                vram_details = self.model.get_vram_usage()
            except Exception:
                pass

        msg = MotorMsgMetrics(
            temp, clock, vram, power, tps,
            vram_free_system_mb=vram_free, vram_details=vram_details,
            ms_per_token=ms_per_token, system_dedicated_vram_mb=system_dedicated
        )
        self._last_metrics_snapshot = msg
        return msg

    def _tps_snapshot_msg(self) -> Optional[MotorMsgMetrics]:
        """Versão leve para o push de tps/ms em tempo real a cada token
        (chamada da thread PRINCIPAL, dentro de generate()/flush_tokens()):
        reaproveita o último snapshot de GPU/VRAM já coletado pela thread de
        telemetria (nunca toca WMI aqui) e só troca tps/ms_per_token pelos
        valores atuais. Retorna None antes do primeiro tick de telemetria
        (ainda sem snapshot para basear)."""
        base = self._last_metrics_snapshot
        if base is None:
            return None
        return dataclasses.replace(base, tokens_sec=self.last_tps, ms_per_token=self.last_ms_per_token)

    def _telemetry_loop(self):
        """Thread isolada para nao travar o loop de inferencia ou o IPC --
        e a ÚNICA thread que tem permissão de tocar GPUMonitor/WMI (ver
        docstring de _build_metrics_msg).

        Intervalo curto (0.35s) para o dashboard acompanhar mudanças de
        estado (ex.: ocioso -> ativo) mesmo fora de uma geração; durante a
        geração em si, o push extra em flush_tokens() (via
        _tps_snapshot_msg, sem WMI) é o que realmente dá a sensação de
        tempo real (tps muda a cada ~50ms, não a cada 0.35s)."""
        while self.running:
            try:
                self._send(self._build_metrics_msg())

                if self.model:
                    status = self.model.get_model_status()
                    self._send(MotorMsgStatusUpdate(
                        status["is_loaded"],
                        status["time_until_unload"]
                    ))
            except Exception:
                logger.warning("Thread de telemetria encerrando por exceção", exc_info=True)
                break

            time.sleep(0.35)

    def flush_tokens(self, force=False):
        """Dispara o buffer de tokens se o limite de 50ms foi atingido.

        Piggyback: junto com o token, manda um snapshot de tps/ms calculado
        no momento exato deste token -- é o que faz o dashboard reagir em
        tempo real à geração, em vez de esperar o próximo tick do timer de
        telemetria (até 0.35s de atraso). Usa _tps_snapshot_msg() (sem WMI)
        e não _build_metrics_msg() -- essa thread (loop principal de
        generate()) não pode tocar o GPUMonitor/WMI da thread de
        telemetria, ver docstring de _build_metrics_msg."""
        if not self.token_buffer and not force:
            return

        now = time.perf_counter()
        if force or (now - self.last_flush_time >= self.flush_interval):
            chunks = self._thinking_scanner.feed(self.token_buffer)
            if force:
                chunks += self._thinking_scanner.flush()
            for chunk in chunks:
                self._send(MotorMsgToken(text=chunk.text, section=chunk.section))
            self.token_buffer = ""
            self.last_flush_time = now
            snapshot = self._tps_snapshot_msg()
            if snapshot is not None:
                try:
                    self._send(snapshot)
                except Exception:
                    pass

    def generate(self, prompt: str, max_tokens: int):
        self.is_generating = True
        self.last_tps = 0.0
        self.last_ms_per_token = 0.0
        last_token_time = None
        cancelled = False
        # Estado novo por geração -- uma geração cancelada no meio de um
        # bloco <think> não pode deixar a próxima já nascendo "dentro do
        # pensamento".
        self._thinking_scanner = ThinkingSectionScanner()

        try:
            # A UI é um chat: formata a mensagem no chat template do modelo
            # atualmente carregado (cada tokenizer -- QwenTokenizer,
            # GraniteTokenizer -- implementa apply_chat_template() com o
            # formato certo do seu próprio modelo) antes de gerar. Sem isto
            # o modelo faz completion de texto cru em vez de responder como
            # assistente.
            chat_prompt = self.model.tokenizer.apply_chat_template(prompt, enable_thinking=False)
            if chat_prompt.strip().endswith("<think>"):
                self._thinking_scanner = ThinkingSectionScanner(start_in_thinking=True)
            generator = self.model.generate(chat_prompt, max_tokens=max_tokens)

            for word in generator:

                if self.conn.poll():
                    msg = self.conn.recv()
                    if isinstance(msg, UIMsgCancel):
                        generator.close()
                        cancelled = True
                        break
                    elif isinstance(msg, UIMsgShutdown):
                        generator.close()
                        self.running = False
                        return

                now = time.perf_counter()
                if last_token_time is not None:
                    # O delta do 1o token (last_token_time is None) inclui o
                    # prefill do prompt inteiro, não o custo de decode por
                    # token -- misturar isso na média inflaria falsamente o
                    # ms/token exibido, então ele é propositalmente pulado.
                    delta_ms = (now - last_token_time) * 1000.0
                    if delta_ms > 0:
                        alpha = 0.25
                        self.last_ms_per_token = (
                            delta_ms if self.last_ms_per_token == 0.0
                            else alpha * delta_ms + (1 - alpha) * self.last_ms_per_token
                        )
                        self.last_tps = 1000.0 / self.last_ms_per_token
                last_token_time = now

                self.token_buffer += word
                self.flush_tokens()

            self.flush_tokens(force=True)

        except Exception as e:
            self._send(MotorMsgError(f"Engine Panic: {str(e)}"))
        finally:
            self.is_generating = False
            # Sempre avisa a UI que terminou (fim natural, limite ou cancel) --
            # sem isto o input fica travado no estado 'gerando'. No caminho de
            # Engine Panic, o MotorMsgError já reseta a UI, mas mandar o Done
            # também é inofensivo (idempotente do lado da UI).
            self.flush_tokens(force=True)
            self._send(MotorMsgDone(cancelled=cancelled))

    def loop(self):
        self.boot()
        while self.running:
            try:
                if self.conn.poll(0.1):
                    msg = self.conn.recv()

                    if isinstance(msg, UIMsgPrompt):
                        self.generate(msg.text, msg.max_tokens)

                    elif isinstance(msg, UIMsgShutdown):
                        self.running = False
                        break
            except EOFError:
                break
            except KeyboardInterrupt:
                break
            except Exception as e:
                # Isolamento de Falhas: Ignorar pacotes malformados sem desligar o motor
                logger.warning(f"Pacote IPC ignorado devido a erro de parsing: {e}")


def motor_entry(pipe_conn: Connection, context_length: int = DEFAULT_CONTEXT_LENGTH, model_name: str = DEFAULT_MODEL_NAME):
    """Entry point do subprocesso"""
    engine = InferenceEngine(pipe_conn, context_length=context_length, model_name=model_name)
    engine.loop()

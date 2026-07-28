"""
app.py — UI desktop do VTE (Flet 0.85+), tudo composto num único módulo por
simplicidade de inicialização (`vte-ui` aponta para `cli_main` aqui).

Arquitetura de processo (inalterada da versão anterior): o motor de
inferência roda em um `multiprocessing.Process` separado (vte.core.motor),
falado por um `multiprocessing.Pipe` — isso isola qualquer TDR/crash da GPU
do processo da UI, que continua vivo para mostrar o banner de recuperação e
permitir reiniciar o motor sem fechar a janela.

Ponte thread-safe UI <-> motor: a thread que lê o pipe (`_listen_pipe`) roda
fora do event loop do Flet. Em vez de mutar controles diretamente dali
(não seguro nesta versão do Flet — `Control.update()` assume estar rodando
no event loop da sessão), cada mensagem recebida é publicada via
`page.pubsub.send_all()` e consumida por um handler `async def` inscrito no
próprio event loop: `PubSubHub` despacha handlers assíncronos com
`asyncio.run_coroutine_threadsafe`, a única forma documentada de cruzar
threads com segurança nesta arquitetura.
"""
import multiprocessing
import signal
import sys
import threading
from multiprocessing.connection import Connection
from pathlib import Path

import flet as ft

from vte.core.ipc import (
    UIMsgPrompt, UIMsgCancel, UIMsgShutdown,
    MotorMsgToken, MotorMsgMetrics, MotorMsgProgress, MotorMsgReady, MotorMsgError,
    MotorMsgStatusUpdate, MotorMsgLog, MotorMsgDone,
)
from vte.core.motor import motor_entry, DEFAULT_CONTEXT_LENGTH, DEFAULT_MODEL_NAME
from vte.core.model import VTEModel
from vte.ui.theme import get_palette, Palette

CONTEXT_LENGTH_OPTIONS = [512, 1024, 2048, 4096, 8192]
# Teto de tokens por resposta, independente do context_length escolhido.
# Ver comentário em _handle_submit sobre por que isto existe: usar
# context_length diretamente como max_tokens permite que "oi" dispare uma
# geração de até 8192 tokens, e greedy decode (temperature=0, padrão do
# Qwen3.5) degenera em loop de repetição bem antes disso -- confirmado via
# scripts/diagnostics/diag_qwen35_long_gen.py (a mesma geração vira
# "enhancing enhancing enhancing..." repetido a partir do token ~1500-2000,
# independente do context_length configurado). Para os três primeiros
# valores do dropdown (512/1024/2048) o comportamento não muda em nada
# (min() é sempre o context_length); só 4096/8192 ficam limitados.
MAX_SINGLE_RESPONSE_TOKENS = 2048
MAX_LOG_LINES = 500

# Suporte a idioma da interface (só chrome da UI -- rótulos, tooltips,
# status -- nunca o conteúdo do chat, que é texto do usuário/modelo e não
# deve ser traduzido). Poucas strings, poucas telas -- um dict simples com
# .format() é suficiente; não vale a pena puxar uma lib de i18n pra isto.
STRINGS = {
    "pt": {
        "context_label": "Tamanho de contexto",
        "context_tooltip": "Requer reiniciar o motor (KV cache é dimensionado no carregamento do modelo)",
        "model_label": "Modelo",
        "model_tooltip": "Requer reiniciar o motor (troca completa de modelo/arquitetura)",
        "theme_tooltip": "Alternar tema claro/escuro",
        "lang_tooltip": "Switch to English",
        "restart_tooltip": "Reiniciar motor",
        "status_initializing": "inicializando...",
        "status_active": "ativo",
        "status_idle": "ocioso",
        "input_hint": "Digite o prompt para o {model}...",
        "progress_title_switch": "Trocando de modelo",
        "progress_status_switch": "Descarregando modelo atual e carregando {model}...",
        "progress_title_restart": "Reiniciando Motor VTE",
        "progress_status_restart": "Aplicando nova configuração ({model}, contexto {ctx})...",
        "progress_title_init": "Inicializando Motor VTE",
        "progress_status_init": "Preparando HIP Runtime...",
        "metric_temp": "TEMPERATURA",
        "metric_speed": "VELOCIDADE DE INFERÊNCIA",
        "metric_vram": "VRAM (ALOCADA PELO VTE)",
        "metric_lifecycle": "CICLO DE VIDA DO MODELO",
        "vram_weights": "Weights: {v:.0f} MB",
        "vram_kv": "KV Cache: {v:.0f} MB",
        "vram_arena": "Arena: {v:.0f} MB",
        "vram_system_known": "Sistema (dedicada): {v:.1f} GB",
        "vram_system_unknown": "Sistema (dedicada): —",
        "vram_free": "Livre p/ sistema: {v:.1f} GB",
        "lifecycle_initializing": "Inicializando...",
        "lifecycle_unloaded": "Modelo descarregado (ocioso)",
        "lifecycle_active_unload": "Ativo (unload em {s:.0f}s)",
        "lifecycle_active": "Ativo",
        "tab_metrics": "Métricas",
        "tab_logs": "Logs",
        "crash_title": (
            "Núcleo da GPU abortado (proteção WDDM/TDR ativada, ou o motor "
            "encerrou de forma inesperada). O contexto do driver foi reiniciado."
        ),
        "crash_restart_btn": "Reiniciar Motor",
        "temp_na": "N/A",
    },
    "en": {
        "context_label": "Context size",
        "context_tooltip": "Requires restarting the engine (KV cache is sized at model load time)",
        "model_label": "Model",
        "model_tooltip": "Requires restarting the engine (full model/architecture swap)",
        "theme_tooltip": "Toggle light/dark theme",
        "lang_tooltip": "Mudar para Português",
        "restart_tooltip": "Restart engine",
        "status_initializing": "initializing...",
        "status_active": "active",
        "status_idle": "idle",
        "input_hint": "Type a prompt for {model}...",
        "progress_title_switch": "Switching model",
        "progress_status_switch": "Unloading current model and loading {model}...",
        "progress_title_restart": "Restarting VTE Engine",
        "progress_status_restart": "Applying new configuration ({model}, context {ctx})...",
        "progress_title_init": "Initializing VTE Engine",
        "progress_status_init": "Preparing HIP Runtime...",
        "metric_temp": "TEMPERATURE",
        "metric_speed": "INFERENCE SPEED",
        "metric_vram": "VRAM (ALLOCATED BY VTE)",
        "metric_lifecycle": "MODEL LIFECYCLE",
        "vram_weights": "Weights: {v:.0f} MB",
        "vram_kv": "KV Cache: {v:.0f} MB",
        "vram_arena": "Arena: {v:.0f} MB",
        "vram_system_known": "System (dedicated): {v:.1f} GB",
        "vram_system_unknown": "System (dedicated): —",
        "vram_free": "Free for system: {v:.1f} GB",
        "lifecycle_initializing": "Initializing...",
        "lifecycle_unloaded": "Model unloaded (idle)",
        "lifecycle_active_unload": "Active (unload in {s:.0f}s)",
        "lifecycle_active": "Active",
        "tab_metrics": "Metrics",
        "tab_logs": "Logs",
        "crash_title": (
            "GPU core aborted (WDDM/TDR protection triggered, or the engine "
            "exited unexpectedly). The driver context was restarted."
        ),
        "crash_restart_btn": "Restart Engine",
        "temp_na": "N/A",
    },
}
# Bandeira mostrada no botão = idioma para o qual ele troca (mesma convenção
# do botão de tema, que mostra o ícone do modo que você vai ATIVAR ao
# clicar, não o modo atual).
# SVGs próprios em assets/, não emoji: regional-indicator flag emoji (🇺🇸/🇧🇷)
# não renderiza de forma confiável no Flutter/Flet em desktop Windows (sem
# fonte de emoji colorido com esses glifos ligados) -- ficava em branco.
LANG_FLAG_ASSET = {"pt": "flag_us.svg", "en": "flag_br.svg"}

# Caminho absoluto (não depende do cwd de onde `vte-ui` é invocado) --
# vte/ui/app.py -> raiz do repo é dois níveis acima.
ASSETS_DIR = str(Path(__file__).resolve().parent.parent.parent / "assets")


class Orchestrator:
    """Dono do ciclo de vida do processo do motor E do pipe de leitura.

    Importante: exatamente UMA thread lê `pipe_parent.recv()` durante toda a
    vida de uma conexão -- multiprocessing.Connection não é seguro para
    múltiplos leitores concorrentes (dois `.recv()` simultâneos entrelaçam
    bytes no meio de um frame pickle e corrompem o stream para ambos).
    Colocar essa thread aqui, em vez de dentro de VTEApp, garante isso mesmo
    que `main_flet` seja chamado mais de uma vez para o mesmo processo (ex.:
    uma sessão reconectando) -- cada `VTEApp` novo só passa a ser o
    destinatário das mensagens, nunca um leitor adicional do pipe.
    """

    # Boot completo (carregar pesos + capturar HIP Graph) do maior modelo já
    # medido nesta sessão (Granite 3B, cache de kernel frio) fica bem abaixo
    # disto -- generoso o bastante pra cobrir uma primeira compilação de
    # kernel via hipcc sem nunca precisar do terminate() abaixo no caminho
    # normal.
    _BOOT_GRACE_TIMEOUT_S = 30
    _READY_SHUTDOWN_TIMEOUT_S = 2

    def __init__(self):
        self.motor_process = None
        self.pipe_parent = None
        self.pipe_child = None
        self.app_ref: "VTEApp" = None
        self.context_length = DEFAULT_CONTEXT_LENGTH
        self.model_name = DEFAULT_MODEL_NAME
        self._listener_generation = 0
        # Setado por _listen_pipe ao ver MotorMsgReady; resetado aqui a cada
        # novo start_motor(). Usado só para decidir o timeout de shutdown
        # abaixo -- nunca para bloquear o restart em si.
        self._motor_ready = False

    def start_motor(self, context_length: int = None, model_name: str = None):
        if context_length is not None:
            self.context_length = context_length
        if model_name is not None:
            self.model_name = model_name

        # Incrementa a geração ANTES de tocar no processo antigo -- não
        # depois. Achado por reprodução direta (não suposição): o
        # `_listen_pipe` antigo recebe EOFError do pipe fechando ENQUANTO
        # `self.motor_process.join(timeout=...)` abaixo ainda está
        # bloqueado esperando o processo antigo morrer (desligamento
        # NORMAL, esperado). Se a geração só for incrementada depois do
        # join(), o guard `generation == self._listener_generation` da
        # thread antiga ainda bate (mesma geração), e ela dispara
        # MotorMsgError("Pipe do motor encerrado inesperadamente") --
        # um falso positivo: a troca de modelo continua e funciona logo
        # em seguida, mas o usuário já viu o banner de erro no meio do
        # caminho. Incrementar aqui garante que esse guard já vê a
        # geração diferente e silencia o erro nesse desligamento
        # intencional (uma queda REALMENTE inesperada de uma geração já
        # substituída continua sem gerar ruído, que é o comportamento
        # correto de qualquer forma).
        self._listener_generation += 1

        if self.motor_process and self.motor_process.is_alive():
            # Motor anterior ainda no meio do boot (carregando pesos/
            # capturando o HIP Graph, chamada síncrona que não olha o pipe
            # até terminar) -- um terminate() aqui mata um contexto HIP
            # ATIVO no meio de uma operação de GPU, o que parece (e pode
            # genuinamente contribuir para) um crash de driver, mesmo sem
            # ser um TDR de verdade. Dar um prazo bem maior para o boot
            # terminar sozinho e processar o UIMsgShutdown cooperativamente
            # evita esse caminho abrupto no caso comum (troca de modelo
            # antes do anterior sequer ter ficado pronto).
            timeout = self._READY_SHUTDOWN_TIMEOUT_S if self._motor_ready else self._BOOT_GRACE_TIMEOUT_S
            try:
                self.pipe_parent.send(UIMsgShutdown())
                self.motor_process.join(timeout=timeout)
            except Exception:
                pass
            if self.motor_process.is_alive():
                self.motor_process.terminate()

        self._motor_ready = False
        self.pipe_parent, self.pipe_child = multiprocessing.Pipe()
        self.motor_process = multiprocessing.Process(
            target=motor_entry,
            args=(self.pipe_child, self.context_length, self.model_name),
            daemon=True
        )
        self.motor_process.start()

        if self.app_ref:
            self.app_ref.reset_for_new_motor(self.pipe_parent, self.context_length, self.model_name)

        generation = self._listener_generation
        threading.Thread(
            target=self._listen_pipe, args=(self.pipe_parent, generation), daemon=True
        ).start()

    def _listen_pipe(self, conn: Connection, generation: int):
        while generation == self._listener_generation:
            try:
                if conn.poll(0.1):
                    msg = conn.recv()
                    # Achado por reprodução direta (não suposição): antes,
                    # QUALQUER mensagem do motor antigo (não só o erro de
                    # pipe fechado) era encaminhada ao pubsub incondicional-
                    # mente. Numa troca de modelo com uma geração pendente
                    # (ex.: o motor antigo ainda mandando MotorMsgDone de
                    # uma geração que terminou de gerar bem na hora do
                    # switch), essa mensagem chegava e mexia no estado da UI
                    # NOVA (ex.: reabilitando o input via _end_generation())
                    # mesmo com o motor novo ainda no meio do boot -- exatamente
                    # o "nada impede de mandar mensagem antes do modelo estar
                    # pronto de verdade" relatado. Re-checar a geração aqui,
                    # imediatamente antes de encaminhar, descarta qualquer
                    # mensagem de uma geração já substituída.
                    if generation != self._listener_generation:
                        continue
                    if isinstance(msg, MotorMsgReady):
                        self._motor_ready = True
                    if self.app_ref:
                        self.app_ref.page.pubsub.send_all(msg)
            except (EOFError, OSError):
                if generation == self._listener_generation and self.app_ref:
                    self.app_ref.page.pubsub.send_all(
                        MotorMsgError("Pipe do motor encerrado inesperadamente.")
                    )
                return

    def main_flet(self, page: ft.Page):
        async def on_window_event(e: ft.WindowEvent):
            if e.type == ft.WindowEventType.CLOSE:
                if self.pipe_parent:
                    try:
                        self.pipe_parent.send(UIMsgShutdown())
                    except Exception:
                        pass
                await page.window.destroy()

        page.window.prevent_close = True
        page.window.on_event = on_window_event

        # main_flet só constrói uma VTEApp nova; nunca lança uma thread de
        # leitura (isso é responsabilidade exclusiva desta classe, acima).
        self.app_ref = VTEApp(
            page, restart_callback=self.start_motor,
            context_length=self.context_length, model_name=self.model_name
        )
        self.app_ref.reset_for_new_motor(self.pipe_parent, self.context_length, self.model_name)


class VTEApp:
    def __init__(self, page: ft.Page, restart_callback, context_length: int, model_name: str):
        self.page = page
        self.restart_callback = restart_callback
        self.current_context_length = context_length
        self.current_model_name = model_name
        self.mode = "dark"
        self.palette = get_palette(self.mode)
        self.lang = "pt"

        self.pipe_conn: Connection = None
        self.current_reply: ft.Text = None
        self.typing_indicator: ft.ProgressRing = None
        # Seção de "pensamento" (dentro de <think>...</think>, ver
        # vte/core/thinking_scanner.py) do turno EM ANDAMENTO -- refeitos a
        # cada _handle_submit(), igual current_reply/typing_indicator.
        # Continuam None/invisíveis para uma conversa comum (Qwen2.5/
        # Granite hoje): só ganham conteúdo/visibilidade se um
        # MotorMsgToken com section="thinking" realmente chegar.
        self.current_thinking: ft.Text = None
        self.thinking_label: ft.Text = None
        self.thinking_toggle_btn: ft.IconButton = None
        self.thinking_body: ft.Container = None
        self.log_lines = []
        # Estado "lógico" (não a string exibida) por trás de peças de UI
        # dependentes de idioma, pra poder re-renderizar tudo no idioma novo
        # no clique do botão de bandeira sem esperar a próxima mensagem do
        # motor chegar. status_state/_progress_kind guiam qual chave de
        # STRINGS usar; os dois _last_*_msg guardam a última mensagem real
        # recebida do motor pra re-formatar os números (tok/s, VRAM, etc.)
        # no idioma novo imediatamente.
        self.status_state = "initializing"
        self._progress_kind = "init"
        self._last_metrics_msg = None
        self._last_lifecycle_msg = None
        # Balões de chat já criados: _make_bubble() grava a cor da paleta NO
        # MOMENTO da criação (bgcolor/border do Container, color dos Text/
        # ProgressRing dentro) -- sem rastrear isso, trocar de tema depois
        # não re-pinta mensagens já enviadas (relatado: balões ficam pretos
        # no modo claro porque continuam com a cor do modo escuro em que
        # foram criados). _apply_palette() percorre esta lista pra re-temar
        # tudo que já existe na conversa.
        self.chat_bubbles: list = []
        # Distingue o boot INICIAL (primeira vez, GPU/driver ainda nem
        # inicializou) de um RESTART do motor já em uso (troca de modelo ou
        # de context_length) -- ver reset_for_new_motor(). Sem isso, os dois
        # casos mostravam a mesma tela genérica "Inicializando Motor VTE"
        # sem nenhuma pista do que está acontecendo, e trocar de modelo
        # parecia o Flet ter travado em vez de estar carregando de verdade.
        self._has_booted_once = False
        # Guard explícito (não apenas main_layout.visible): setado False em
        # reset_for_new_motor() (boot iniciou/motor trocando) e True só
        # quando MotorMsgReady chega DE VERDADE do motor atual. Sem isto,
        # nada impedia enviar uma mensagem enquanto o modelo ainda estava
        # carregando (relatado: "nada impede de mandar mensagem sem o
        # Granite estar lá definitivamente") -- visible=False escondia a UI,
        # mas não bloqueava _handle_submit caso o campo ainda recebesse um
        # Enter por algum caminho (ex.: página ainda não re-renderizada).
        self.model_ready = False

        page.title = "VTE — RDNA3 Inference Engine"
        page.padding = 0
        page.theme_mode = ft.ThemeMode.DARK
        page.window.width = 1180
        page.window.height = 780
        page.window.min_width = 860
        page.window.min_height = 560
        page.window.icon = "earth_pixelated.svg"

        self._build_ui()
        page.add(self.progress_screen, self.main_layout)
        page.pubsub.subscribe(self._on_motor_message)
        self._apply_palette()

    def t(self, key: str, **kwargs) -> str:
        s = STRINGS[self.lang][key]
        return s.format(**kwargs) if kwargs else s

    # ------------------------------------------------------------------
    # Construção da UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        self._build_topbar()
        self._build_chat_panel()
        self._build_dashboard_panel()
        self._build_progress_screen()
        self._build_crash_banner()

        self.main_layout = ft.Column(
            [
                self.topbar,
                ft.Row(
                    [
                        ft.Container(self.chat_panel, expand=True, padding=16),
                        ft.Container(self.dashboard_panel, padding=16, width=340),
                    ],
                    expand=True,
                    spacing=0,
                ),
            ],
            expand=True,
            visible=False,
            spacing=0,
        )

    def _build_topbar(self):
        self.app_icon = ft.Image(src="earth_pixelated.svg", width=24, height=24)
        self.title_text = ft.Text(
            "VTE", size=18, weight=ft.FontWeight.BOLD
        )
        self.subtitle_text = ft.Text("RDNA3 Inference Engine", size=12)

        self.context_dropdown = ft.Dropdown(
            label=self.t("context_label"),
            width=140,
            value=str(self.current_context_length),
            options=[ft.dropdown.Option(str(v)) for v in CONTEXT_LENGTH_OPTIONS],
            tooltip=self.t("context_tooltip"),
            on_select=self._on_context_change,
            disabled=True,
        )

        # Populado a partir de VTEModel.MODEL_REGISTRY -- se um terceiro
        # modelo for registrado no futuro, aparece aqui sozinho, sem editar
        # a UI. Troca de modelo reinicia o motor inteiro (mesmo mecanismo já
        # usado pela troca de context_length): o KV cache/tokenizer/mapper
        # são resolvidos no boot, não dá pra trocar o modelo de um processo
        # já rodando sem reconstruir tudo.
        self.model_dropdown = ft.Dropdown(
            label=self.t("model_label"),
            width=220,
            value=self.current_model_name,
            options=[ft.dropdown.Option(name) for name in VTEModel.MODEL_REGISTRY.keys()],
            tooltip=self.t("model_tooltip"),
            on_select=self._on_model_change,
            disabled=True,
        )

        self.theme_btn = ft.IconButton(
            icon=ft.Icons.LIGHT_MODE,
            tooltip=self.t("theme_tooltip"),
            on_click=self._toggle_theme,
        )
        # Poucas palavras, poucos idiomas (pt/en) -- um botão com a bandeira
        # do idioma que ele ATIVA ao ser clicado (mesma convenção do ícone de
        # tema acima) é suficiente; não precisa de um seletor/dropdown pra
        # duas opções. Só troca o chrome da UI (rótulos/tooltips/status) --
        # o conteúdo do chat nunca é traduzido, é texto real do
        # usuário/modelo.
        self.lang_btn = ft.IconButton(
            icon=ft.Image(src=LANG_FLAG_ASSET[self.lang], width=20, height=14),
            tooltip=self.t("lang_tooltip"),
            on_click=self._toggle_language,
        )
        self.restart_btn = ft.IconButton(
            icon=ft.Icons.RESTART_ALT,
            tooltip=self.t("restart_tooltip"),
            on_click=lambda e: self.restart_callback(),
        )

        self.status_pill = ft.Container(
            content=ft.Text(self.t("status_initializing"), size=12, weight=ft.FontWeight.W_600),
            padding=ft.Padding(left=10, right=10, top=4, bottom=4),
            border_radius=12,
        )

        self.topbar = ft.Container(
            content=ft.Row(
                [
                    ft.Row(
                        [self.app_icon, self.title_text, self.subtitle_text, self.status_pill],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [self.model_dropdown, self.context_dropdown, self.lang_btn, self.theme_btn, self.restart_btn],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.Padding(left=20, right=16, top=10, bottom=10),
        )

    def _build_chat_panel(self):
        self.chat_list = ft.ListView(expand=True, spacing=10, auto_scroll=True)
        self.input_field = ft.TextField(
            hint_text=self.t("input_hint", model=self.current_model_name),
            expand=True,
            border_radius=8,
            on_submit=self._handle_submit,
        )
        self.send_btn = ft.IconButton(icon=ft.Icons.SEND, on_click=self._handle_submit)
        self.cancel_btn = ft.IconButton(
            icon=ft.Icons.STOP_CIRCLE, visible=False, on_click=self._handle_cancel
        )

        self.chat_panel = ft.Column(
            [
                self.chat_list,
                ft.Row([self.input_field, self.send_btn, self.cancel_btn]),
            ],
            expand=True,
        )

    def _build_dashboard_panel(self):
        def metric_label(text):
            return ft.Text(text, size=11)

        self.temp_value = ft.Text("0 °C", size=22, weight=ft.FontWeight.BOLD)
        self.tps_value = ft.Text("0.0 tok/s", size=22, weight=ft.FontWeight.BOLD)
        self.ms_value = ft.Text("0.0 ms/tok", size=13)
        self.vram_value = ft.Text("0 MB", size=20, weight=ft.FontWeight.BOLD)

        self.vram_weights_text = ft.Text("Weights: 0 MB", size=11)
        self.vram_kv_text = ft.Text("KV Cache: 0 MB", size=11)
        self.vram_arena_text = ft.Text("Arena: 0 MB", size=11)
        # "Sistema (dedicada)" é o número que bate com o Gerenciador de
        # Tarefas (WMI GPUAdapterMemory) -- inclui OUTROS processos (desktop,
        # navegador etc.), por isso fica separado do valor grande acima
        # (que é só o que o VTE mesmo alocou, determinístico). Misturar os
        # dois fazia o número principal saltar de forma confusa por
        # atividade alheia ao VTE.
        self.vram_system_text = ft.Text("Sistema (dedicada): — GB", size=11)
        self.vram_free_text = ft.Text("Livre p/ sistema: 0 GB", size=11, weight=ft.FontWeight.W_600)
        self.vram_details_col = ft.Column(
            [self.vram_weights_text, self.vram_kv_text, self.vram_arena_text,
             ft.Container(height=4), self.vram_system_text, self.vram_free_text],
            spacing=2, visible=False,
        )

        self.lifecycle_text = ft.Text(self.t("lifecycle_initializing"), size=13)

        self._metric_labels = []
        # Chave STRINGS alinhada por índice com _metric_labels -- é o que
        # permite _apply_language() re-renderizar estes rótulos sem precisar
        # reconstruir a UI inteira no clique do botão de bandeira.
        self._metric_label_keys = []

        def metric_block(label_key, *value_controls):
            lbl = metric_label(self.t(label_key))
            self._metric_labels.append(lbl)
            self._metric_label_keys.append(label_key)
            return ft.Column([lbl, *value_controls], spacing=2)

        metrics_tab = ft.Container(
            content=ft.Column(
                [
                    metric_block("metric_temp", self.temp_value),
                    metric_block("metric_speed", self.tps_value, self.ms_value),
                    metric_block("metric_vram", self.vram_value, self.vram_details_col),
                    metric_block("metric_lifecycle", self.lifecycle_text),
                ],
                spacing=18,
            ),
            padding=16,
        )

        self.log_list = ft.ListView(expand=True, spacing=1, auto_scroll=True)
        logs_tab = ft.Container(content=self.log_list, padding=10, expand=True)

        metrics_tab.visible = True
        logs_tab.visible = False
        self.metrics_view = metrics_tab
        self.logs_view = logs_tab
        self._active_dash_tab = "metrics"

        # ft.Tabs nesta versão do Flet não tem um slot de conteúdo por aba
        # (Tab só carrega o label) -- em vez de brigar com essa API nova e
        # pouco documentada, um par de botões + troca manual de visível
        # resolve exatamente o que precisamos aqui (2 painéis, nunca mais).
        self.tab_metrics_btn = ft.TextButton(self.t("tab_metrics"), on_click=lambda e: self._select_dash_tab("metrics"))
        self.tab_logs_btn = ft.TextButton(self.t("tab_logs"), on_click=lambda e: self._select_dash_tab("logs"))

        self.dashboard_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row([self.tab_metrics_btn, self.tab_logs_btn], spacing=4),
                    ft.Divider(height=1),
                    ft.Column([self.metrics_view, self.logs_view], expand=True),
                ],
                expand=True,
                spacing=0,
            ),
            border_radius=10,
            expand=True,
        )

    def _build_progress_screen(self):
        self.progress_title = ft.Text(self.t("progress_title_init"), size=22, weight=ft.FontWeight.BOLD)
        self.progress_status = ft.Text(self.t("progress_status_init"), size=13)
        # Indeterminado (value=None) em vez de seguir o percentual bruto de
        # MotorMsgProgress: só temos 2 checkpoints reais (10% ao iniciar,
        # 100% ao terminar) -- uma barra "de verdade" fica parada em 10% por
        # vários segundos (o tempo real de carregar pesos/capturar o HIP
        # Graph) e parece travada. A animação indeterminada do Flet já
        # comunica "ocupado, ainda não travou" sem fingir uma granularidade
        # de progresso que não temos.
        self.progress_bar = ft.ProgressBar(width=420, value=None)

        self.progress_screen = ft.Container(
            content=ft.Column(
                [self.progress_title, self.progress_bar, self.progress_status],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=16,
            ),
            expand=True,
            alignment=ft.Alignment.CENTER,
        )

    def _build_crash_banner(self):
        self.tdr_banner_detail = ft.Text("", size=11, italic=True)
        self.tdr_banner_title = ft.Text(self.t("crash_title"))
        self.tdr_banner_restart_btn = ft.TextButton(self.t("crash_restart_btn"), on_click=self._restart_from_banner)
        self.tdr_banner = ft.Banner(
            leading=ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=40),
            content=ft.Column(
                [self.tdr_banner_title, self.tdr_banner_detail],
                spacing=4, tight=True,
            ),
            actions=[self.tdr_banner_restart_btn],
        )

    # ------------------------------------------------------------------
    # Tema
    # ------------------------------------------------------------------
    def _toggle_theme(self, e):
        self.mode = "light" if self.mode == "dark" else "dark"
        self.palette = get_palette(self.mode)
        self.page.theme_mode = ft.ThemeMode.LIGHT if self.mode == "light" else ft.ThemeMode.DARK
        self._apply_palette()

    def _apply_palette(self):
        p = self.palette
        page = self.page

        page.bgcolor = p.bg
        self.title_text.color = p.accent_green
        self.subtitle_text.color = p.text_muted
        self.theme_btn.icon = ft.Icons.DARK_MODE if self.mode == "light" else ft.Icons.LIGHT_MODE
        self.theme_btn.icon_color = p.text_muted
        self.restart_btn.icon_color = p.text_muted
        self.topbar.bgcolor = p.panel
        self.topbar.border = ft.Border(bottom=ft.BorderSide(1, p.border))

        self.context_dropdown.border_color = p.border
        self.context_dropdown.color = p.text_primary
        self.context_dropdown.bgcolor = p.input_bg
        self.context_dropdown.label_style = ft.TextStyle(color=p.text_muted)

        # Chat
        self.input_field.border_color = p.border
        self.input_field.focused_border_color = p.accent_green
        self.input_field.cursor_color = p.accent_green
        self.input_field.bgcolor = p.input_bg
        self.input_field.color = p.text_primary
        self.input_field.hint_style = ft.TextStyle(color=p.text_muted)
        self.send_btn.icon_color = p.accent_green
        self.cancel_btn.icon_color = p.accent_red

        # Dashboard
        self.dashboard_panel.bgcolor = p.panel
        self.dashboard_panel.border = ft.Border.all(1, p.border)
        for lbl in self._metric_labels:
            lbl.color = p.text_muted
        self.tps_value.color = p.accent_green
        self.ms_value.color = p.text_muted
        self.vram_value.color = p.text_primary
        self.vram_weights_text.color = p.text_muted
        self.vram_kv_text.color = p.text_muted
        self.vram_arena_text.color = p.text_muted
        self.vram_system_text.color = p.text_muted
        self.vram_free_text.color = p.accent_green
        self.lifecycle_text.color = p.text_muted
        if self.temp_value.color not in (p.accent_red,):
            self.temp_value.color = p.text_primary
        self._style_dash_tab_buttons()

        # Progress screen
        self.progress_screen.bgcolor = p.bg
        self.progress_title.color = p.text_primary
        self.progress_status.color = p.text_muted
        self.progress_bar.color = p.accent_green
        self.progress_bar.bgcolor = p.border

        # Banner
        self.tdr_banner.bgcolor = p.accent_red
        self.tdr_banner.leading.color = p.text_strong
        for line in self.tdr_banner.content.controls:
            line.color = p.text_strong
        self.tdr_banner.actions[0].style = ft.ButtonStyle(color=p.text_strong)

        # Balões de chat já existentes (ver docstring de _make_bubble) --
        # sem isto, mensagens enviadas antes de trocar de tema continuavam
        # com a cor do tema anterior (balões pretos no modo claro).
        for b in self.chat_bubbles:
            b["container"].bgcolor = p.input_bg if b["is_user"] else p.panel
            b["container"].border = None if b["is_user"] else ft.Border.all(1, p.border)
            text_color = p.text_primary if b["is_user"] else p.accent_green
            for ctrl in b["text_controls"]:
                ctrl.color = text_color
        if self.chat_bubbles:
            self.chat_list.update()

        self._recolor_log_lines()
        self._recolor_status_pill()

        if page.controls:
            page.update()

    # ------------------------------------------------------------------
    # Idioma
    # ------------------------------------------------------------------
    def _toggle_language(self, e):
        self.lang = "en" if self.lang == "pt" else "pt"
        self._apply_language()

    def _apply_language(self):
        """Re-renderiza todo texto de chrome da UI (rótulos, tooltips,
        status, telas de progresso/crash) no idioma atual -- nunca toca no
        conteúdo do chat (self.chat_bubbles), que é texto real do
        usuário/modelo, não UI. Reusa _render_metrics/_render_lifecycle/
        _render_progress_screen com a última mensagem real recebida do
        motor (guardada em self._last_*_msg / self._progress_kind) pra
        re-formatar números já exibidos sem esperar a próxima mensagem
        chegar."""
        self.lang_btn.icon = ft.Image(src=LANG_FLAG_ASSET[self.lang], width=20, height=14)
        self.lang_btn.tooltip = self.t("lang_tooltip")

        self.context_dropdown.label = self.t("context_label")
        self.context_dropdown.tooltip = self.t("context_tooltip")
        self.model_dropdown.label = self.t("model_label")
        self.model_dropdown.tooltip = self.t("model_tooltip")
        self.theme_btn.tooltip = self.t("theme_tooltip")
        self.restart_btn.tooltip = self.t("restart_tooltip")

        self.input_field.hint_text = self.t("input_hint", model=self.current_model_name)

        for lbl, key in zip(self._metric_labels, self._metric_label_keys):
            lbl.value = self.t(key)
        self.tab_metrics_btn.content = self.t("tab_metrics")
        self.tab_logs_btn.content = self.t("tab_logs")

        self._render_progress_screen()

        self.tdr_banner_title.value = self.t("crash_title")
        self.tdr_banner_restart_btn.content = self.t("crash_restart_btn")

        if self._last_metrics_msg is not None:
            self._render_metrics(self._last_metrics_msg)
        if self._last_lifecycle_msg is not None:
            self._render_lifecycle(self._last_lifecycle_msg)
        else:
            # Nenhuma MotorMsgStatusUpdate chegou ainda (ex.: trocando de
            # idioma durante o boot inicial) -- o pill ainda está no estado
            # "initializing", só precisa do texto no idioma novo.
            self.status_pill.content.value = self.t(f"status_{self.status_state}")

        if self.page.controls:
            self.page.update()

    def _recolor_status_pill(self):
        # Antes isto casava substring no TEXTO exibido ("ativo"/"carregado")
        # -- quebrava assim que o texto virasse "active" em inglês. Agora usa
        # o estado lógico (self.status_state), independente do idioma atual.
        p = self.palette
        text_ctrl: ft.Text = self.status_pill.content
        if self.status_state == "active":
            self.status_pill.bgcolor = ft.Colors.with_opacity(0.14, p.accent_green)
            text_ctrl.color = p.accent_green
        else:
            self.status_pill.bgcolor = p.border
            text_ctrl.color = p.text_muted

    def _select_dash_tab(self, name: str):
        self._active_dash_tab = name
        self.metrics_view.visible = (name == "metrics")
        self.logs_view.visible = (name == "logs")
        self._style_dash_tab_buttons()
        self.dashboard_panel.update()

    def _style_dash_tab_buttons(self):
        p = self.palette
        active = p.accent_green
        inactive = p.text_muted
        self.tab_metrics_btn.style = ft.ButtonStyle(
            color=active if self._active_dash_tab == "metrics" else inactive
        )
        self.tab_logs_btn.style = ft.ButtonStyle(
            color=active if self._active_dash_tab == "logs" else inactive
        )

    def _recolor_log_lines(self):
        p = self.palette
        for row, level in zip(self.log_list.controls, (l.level for l in self.log_lines)):
            row.color = self._log_level_color(level, p)

    def _log_level_color(self, level: str, p: Palette) -> str:
        if level in ("ERROR", "CRITICAL"):
            return p.accent_red
        if level == "WARNING":
            return p.accent_blue
        return p.text_muted

    # ------------------------------------------------------------------
    # Pipe / IPC (thread de fundo -> pubsub -> handler async no event loop)
    # ------------------------------------------------------------------
    def reset_for_new_motor(self, pipe_conn: Connection, context_length: int, model_name: str):
        """Chamado pelo Orchestrator sempre que um processo de motor novo
        nasce (boot inicial, crash recovery, troca de context_length OU
        troca de modelo). Só atualiza estado/UI -- a leitura do pipe é
        responsabilidade exclusiva do Orchestrator (ver seu docstring de
        classe). Limpar o chat aqui (mesmo comportamento já usado pela troca
        de context_length) é o que garante que trocar de modelo no meio de
        uma conversa nunca deixa a UI num estado inconsistente: a conversa
        antiga não faz sentido misturada com o tokenizer/chat template do
        novo modelo, então em vez de tentar preservá-la, o motor reinicia do
        zero -- limpo, sem estado do modelo anterior vazando para o novo."""
        # Precisa ser calculado ANTES de sobrescrever current_model_name.
        is_model_switch = self._has_booted_once and model_name != self.current_model_name
        is_restart_same_model = self._has_booted_once and not is_model_switch

        self.pipe_conn = pipe_conn
        self.model_ready = False
        self.current_context_length = context_length
        self.current_model_name = model_name
        self.context_dropdown.value = str(context_length)
        self.context_dropdown.disabled = True
        self.model_dropdown.value = model_name
        self.model_dropdown.disabled = True
        self.input_field.hint_text = self.t("input_hint", model=model_name)

        self.main_layout.visible = False
        self.progress_screen.visible = True
        self.progress_bar.value = None
        # _progress_kind guarda qual dos 3 casos abaixo está ativo, pra
        # _apply_language() poder re-renderizar o título/status certo no
        # idioma novo sem precisar re-executar esta lógica de decisão.
        if is_model_switch:
            self._progress_kind = "switch"
        elif is_restart_same_model:
            self._progress_kind = "restart"
        else:
            self._progress_kind = "init"
        self._render_progress_screen()
        self.chat_list.controls.clear()
        self.chat_bubbles.clear()
        self.current_reply = None
        self.typing_indicator = None
        self.page.update()
        self._has_booted_once = True

    def _render_progress_screen(self):
        """(Re)popula progress_title/progress_status a partir de
        self._progress_kind no idioma atual -- usado tanto por
        reset_for_new_motor() (motor real trocando de estado) quanto por
        _apply_language() (usuário só trocou o idioma da UI, o motor não
        mudou de estado nenhum)."""
        if self._progress_kind == "switch":
            self.progress_title.value = self.t("progress_title_switch")
            self.progress_status.value = self.t("progress_status_switch", model=self.current_model_name)
        elif self._progress_kind == "restart":
            self.progress_title.value = self.t("progress_title_restart")
            self.progress_status.value = self.t(
                "progress_status_restart", model=self.current_model_name, ctx=self.current_context_length
            )
        else:
            self.progress_title.value = self.t("progress_title_init")
            self.progress_status.value = self.t("progress_status_init")

    async def _on_motor_message(self, msg):
        """Roda no event loop da sessão (despachado via
        run_coroutine_threadsafe pelo PubSubHub) — seguro para mutar
        controles e chamar .update() aqui."""
        if isinstance(msg, MotorMsgProgress):
            self.progress_status.value = msg.status
            self.progress_screen.update()

        elif isinstance(msg, MotorMsgReady):
            self.model_ready = True
            self.progress_screen.visible = False
            self.main_layout.visible = True
            self.context_dropdown.disabled = False
            self.model_dropdown.disabled = False
            self.page.update()

        elif isinstance(msg, MotorMsgToken):
            self._append_token(msg.text, msg.section)

        elif isinstance(msg, MotorMsgDone):
            self._end_generation()

        elif isinstance(msg, MotorMsgMetrics):
            self._update_metrics(msg)

        elif isinstance(msg, MotorMsgStatusUpdate):
            self._update_lifecycle(msg)

        elif isinstance(msg, MotorMsgLog):
            self._append_log(msg)

        elif isinstance(msg, MotorMsgError):
            self._show_crash(msg.message)

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    def _handle_submit(self, e):
        # Guard explícito além de `input_field.disabled`/`main_layout.visible`:
        # relatado que, numa troca de modelo, ainda era possível mandar uma
        # mensagem (Enter) antes do modelo novo estar pronto de verdade --
        # `model_ready` só vira True quando MotorMsgReady chega da geração
        # ATUAL (ver _listen_pipe no Orchestrator), então cobre a janela em
        # que o layout pode não ter re-renderizado a tempo ainda.
        if not self.input_field.value or not self.pipe_conn or not self.model_ready:
            return

        prompt = self.input_field.value
        self.input_field.value = ""
        self.input_field.disabled = True
        self.context_dropdown.disabled = True
        self.model_dropdown.disabled = True
        self.send_btn.visible = False
        self.cancel_btn.visible = True
        self.page.update()

        user_text = ft.Text(prompt, color=self.palette.text_primary, selectable=True)
        self._fit_bubble_text(user_text)
        self.chat_list.controls.append(self._make_bubble(user_text, is_user=True, text_controls=[user_text]))

        # Indicador de "digitando" (ProgressRing pequeno) visível até o
        # PRIMEIRO token chegar -- sem isto a bolha do assistente fica vazia
        # e parada durante o prefill do prompt (pode ser vários segundos em
        # prompts longos), parecendo travada em vez de "trabalhando".
        # _append_token esconde este indicador assim que o buffer deixa de
        # estar vazio (primeiro token real).
        self.typing_indicator = ft.ProgressRing(width=14, height=14, stroke_width=2, color=self.palette.accent_green)
        self.current_reply = ft.Text("", color=self.palette.accent_green, selectable=True)

        # Accordion de "pensamento" -- só existe de verdade (é renderizado)
        # para modelos que o próprio VTEModel declara suportar thinking mode
        # (VTEModel.SUPPORTS_THINKING, hoje só Qwen3.5: é o tokenizer dele
        # que emite <think>/</think> como texto literal). Para os demais
        # modelos, current_thinking/thinking_label/thinking_toggle_btn ficam
        # None -- _append_token já ignora section="thinking" nesse caso, e
        # nenhum vestígio do accordion aparece na bolha.
        self._supports_thinking = self.current_model_name in VTEModel.SUPPORTS_THINKING
        self._thinking_seen_this_turn = False
        if self._supports_thinking:
            # Toggle usa closures (não `self.*`) para que o botão de UMA
            # bolha antiga continue expandindo/recolhendo só a SI MESMA
            # depois que uma bolha nova for criada por cima (self.thinking_body
            # etc. só rastreiam o turno em andamento).
            self.current_thinking = ft.Text(
                "", size=12, italic=True, selectable=True, color=self.palette.text_muted
            )
            thinking_body = ft.Container(
                content=self.current_thinking,
                padding=ft.Padding(left=8, top=2, right=0, bottom=4),
                expand=True,
            )
            self.thinking_label = ft.Text("Raciocínio", size=11, weight=ft.FontWeight.BOLD, visible=False)
            self.thinking_toggle_btn = ft.IconButton(
                icon=ft.Icons.EXPAND_LESS, icon_size=16, visible=False,
                tooltip="Mostrar/ocultar raciocínio",
            )
            thinking_state = {"expanded": True}

            def _toggle_thinking(e, _body=thinking_body, _btn=self.thinking_toggle_btn, _state=thinking_state):
                _state["expanded"] = not _state["expanded"]
                _body.visible = _state["expanded"]
                _btn.icon = ft.Icons.EXPAND_LESS if _state["expanded"] else ft.Icons.EXPAND_MORE
                _body.update()
                _btn.update()

            self.thinking_toggle_btn.on_click = _toggle_thinking
            self._collapse_thinking = lambda: _toggle_thinking(None) if thinking_state["expanded"] else None
            self.thinking_body = thinking_body

            # Cabeçalho inteiro clicável (não só o ícone) -- área de toque
            # maior, comportamento de accordion mais óbvio.
            thinking_header = ft.Container(
                content=ft.Row([self.thinking_toggle_btn, self.thinking_label], spacing=2, tight=True),
                on_click=_toggle_thinking,
                ink=True,
            )
            thinking_section = ft.Column([thinking_header, self.thinking_body], spacing=0, tight=True)
        else:
            self.current_thinking = None
            self.thinking_label = None
            self.thinking_toggle_btn = None
            self.thinking_body = None
            self._collapse_thinking = None
            thinking_section = None

        reply_row = ft.Row([self.typing_indicator, self.current_reply], spacing=8, tight=True)
        reply_content = ft.Column(
            [c for c in (thinking_section, reply_row) if c is not None], spacing=6, tight=True
        )

        self.chat_list.controls.append(self._make_bubble(
            reply_content, is_user=False,
            text_controls=[self.current_reply, self.typing_indicator, self.current_thinking, self.thinking_label]
        ))
        self.page.update()
        try:
            # max_tokens era um default fixo de 512 (UIMsgPrompt), nunca
            # realmente enviado por aqui -- toda geração ficava cortada em
            # ~512 tokens (relatado: histórias longas cortando no meio de
            # uma palavra) e o dropdown de context size não tinha nenhum
            # efeito visível no tamanho da resposta (o teto real era esse
            # 512 escondido, não o context_length escolhido). Usar
            # current_context_length aqui fez o dropdown passar a governar
            # o teto de geração -- mas trocou um problema por outro: para
            # context_length=8192, "oi" passou a poder disparar uma geração
            # de até 8192 tokens, e greedy decode (padrão do Qwen3.5) degenera
            # em loop de repetição bem antes disso (reportado como "o modelo
            # fala coisas aleatórias com contexto grande" -- na real é o
            # MESMO loop de repetição documentado em docs/QWEN35.md,
            # só que a UI deixava a geração correr tokens o bastante para
            # o usuário chegar nele). MAX_SINGLE_RESPONSE_TOKENS limita o
            # teto por resposta sem tocar no context_length (que continua
            # dimensionando o KV cache normalmente).
            max_tokens = min(self.current_context_length, MAX_SINGLE_RESPONSE_TOKENS)
            self.pipe_conn.send(UIMsgPrompt(text=prompt, max_tokens=max_tokens))
        except (BrokenPipeError, OSError, EOFError):
            # O motor pode ter caído/estar trocando bem entre o guard acima e
            # o send em si (janela pequena, mas real -- é exatamente o que
            # produzia "Unhandled error in 'on_submit' handler" antes). Volta
            # a UI pro estado de "esperando motor" em vez de deixar uma
            # exceção não tratada travar o event loop do Flet.
            self._end_generation()

    # Acima deste tamanho o texto ganha uma largura máxima (e passa a
    # quebrar linha); abaixo, o Text fica sem `width` e a bolha simplesmente
    # abraça o conteúdo (uma linha só). Ajustado para caber ~1 linha de "oi"/
    # "Hola! Como posso ajudar?" sem cortar, mas capar respostas de parágrafo.
    _BUBBLE_WRAP_THRESHOLD_CHARS = 42
    _BUBBLE_MAX_WIDTH = 420

    def _fit_bubble_text(self, text_ctrl: ft.Text):
        """Decide se o Text da bolha deve abraçar o conteúdo (width=None,
        uma linha) ou ganhar uma largura máxima e quebrar (mensagens longas).
        Container não tem max_width nesta versão do Flet -- por isso o teto
        é aplicado no próprio Text, que é quem efetivamente controla onde a
        linha quebra; a bolha (Container) sem `expand` só abraça o que o Text
        ocupar."""
        text_ctrl.width = self._BUBBLE_MAX_WIDTH if len(text_ctrl.value or "") > self._BUBBLE_WRAP_THRESHOLD_CHARS else None

    def _make_bubble(self, content: ft.Control, is_user: bool, text_controls: list = None) -> ft.Row:
        """Bolha de chat que abraça o tamanho do conteúdo (curto = uma linha
        compacta) e só cresce até `_BUBBLE_MAX_WIDTH` para mensagens longas,
        quebrando o texto -- nunca estica para 75% do painel só porque a
        mensagem é um "oi".

        `text_controls`: os Text/ProgressRing internos cuja cor depende da
        paleta (ex.: [user_text] ou [current_reply, typing_indicator]) --
        registrados junto com o Container em `self.chat_bubbles` para que
        `_apply_palette()` consiga re-temar esta bolha depois, numa troca de
        tema."""
        p = self.palette
        bubble = ft.Container(
            content=content,
            padding=10,
            border_radius=10,
            bgcolor=p.input_bg if is_user else p.panel,
            border=None if is_user else ft.Border.all(1, p.border),
        )
        self.chat_bubbles.append({
            "container": bubble,
            "is_user": is_user,
            "text_controls": text_controls or [],
        })
        return ft.Row(
            [bubble],
            alignment=ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    def _handle_cancel(self, e):
        if self.pipe_conn:
            try:
                self.pipe_conn.send(UIMsgCancel())
            except (BrokenPipeError, OSError, EOFError):
                self._end_generation()

    def _append_token(self, token: str, section: str = "answer"):
        # Primeiro token de QUALQUER seção esconde o spinner de "digitando"
        # -- ele existe só para cobrir o prefill, antes do modelo ter
        # produzido qualquer coisa (pensamento ou resposta).
        if self.typing_indicator and self.typing_indicator.visible:
            self.typing_indicator.visible = False
            self.typing_indicator.update()

        if section == "thinking":
            if not self.current_thinking:
                return
            if self.thinking_label and not self.thinking_label.visible:
                # 1o token "thinking" desta geração: revela o cabeçalho
                # recolhível -- para um modelo sem SUPPORTS_THINKING (Qwen2.5/
                # Granite hoje), current_thinking já é None e isto nunca roda.
                self.thinking_label.visible = True
                self.thinking_toggle_btn.visible = True
                self.thinking_label.update()
                self.thinking_toggle_btn.update()
            self._thinking_seen_this_turn = True
            self.current_thinking.value += token
            self._fit_bubble_text(self.current_thinking)
            self.current_thinking.update()
        else:
            # 1o token de "answer" depois de ter havido "thinking" nesta
            # geração: recolhe o accordion automaticamente -- o usuário via
            # o raciocínio acontecer ao vivo, mas a resposta final é o que
            # importa assim que ela começa a chegar. Só dispara uma vez por
            # turno (thinking_seen_this_turn é resetado por _handle_submit).
            if self._thinking_seen_this_turn and self._collapse_thinking:
                self._collapse_thinking()
                self._thinking_seen_this_turn = False
            if self.current_reply:
                self.current_reply.value += token
                self._fit_bubble_text(self.current_reply)
                self.current_reply.update()

    def _end_generation(self):
        self.input_field.disabled = False
        self.context_dropdown.disabled = False
        self.model_dropdown.disabled = False
        self.send_btn.visible = True
        self.cancel_btn.visible = False
        # Cancelamento antes do 1o token: o spinner ficaria visível pra
        # sempre numa bolha vazia sem isto.
        if self.typing_indicator and self.typing_indicator.visible:
            self.typing_indicator.visible = False
            
        if self.current_reply and not self.current_reply.value.strip():
            if self._thinking_seen_this_turn:
                msg_warning = (
                    "[O modelo esgotou o limite de tokens da resposta durante o raciocínio. "
                    "Tente aumentar o tamanho do contexto no seletor acima para dar mais espaço à resposta.]"
                    if self.lang == "pt" else
                    "[The model exhausted the response token limit during reasoning. "
                    "Try increasing the context length in the selector above to allow more space for the answer.]"
                )
            else:
                msg_warning = (
                    "[Resposta vazia do modelo. Tente enviar a mensagem novamente.]"
                    if self.lang == "pt" else
                    "[Empty response from model. Please try sending the message again.]"
                )
            self.current_reply.value = msg_warning
            self.current_reply.update()

        self.current_reply = None
        self.typing_indicator = None
        self.current_thinking = None
        self.thinking_label = None
        self.thinking_toggle_btn = None
        self.thinking_body = None
        self._collapse_thinking = None
        self._thinking_seen_this_turn = False
        self.page.update()

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    def _update_metrics(self, msg: MotorMsgMetrics):
        self._last_metrics_msg = msg  # re-usado por _apply_language() na troca de idioma
        self._render_metrics(msg)
        self.dashboard_panel.update()

    def _render_metrics(self, msg: MotorMsgMetrics):
        """Só formata/atribui valores nos controles -- sem `.update()`
        (chamador decide quando mandar pro Flet), pra ser reusável tanto do
        fluxo normal (_update_metrics, uma MotorMsgMetrics real chegou)
        quanto de _apply_language() (mesmos números, idioma novo)."""
        p = self.palette
        if msg.temp_c is None:
            # Honesto em vez de inventado: não há fonte de temperatura real
            # da GPU disponível via WMI padrão sem o SDK da AMD (ADL/ADLX) --
            # ver gpu_monitor.py. Mostrar um número aqui pareceria real sem
            # ser.
            self.temp_value.value = self.t("temp_na")
            self.temp_value.color = p.text_muted
        else:
            self.temp_value.value = f"{msg.temp_c:.1f} °C"
            self.temp_value.color = p.accent_red if msg.temp_c > 85.0 else p.text_primary

        self.tps_value.value = f"{msg.tokens_sec:.1f} tok/s"
        self.ms_value.value = f"{msg.ms_per_token:.1f} ms/tok" if msg.ms_per_token > 0 else "—"

        self.vram_value.value = f"{msg.vram_mb:.0f} MB"

        if msg.vram_details and msg.vram_details.get('total_mb', 0) > 0:
            d = msg.vram_details
            self.vram_weights_text.value = self.t("vram_weights", v=d.get('weights_mb', 0))
            self.vram_kv_text.value = self.t("vram_kv", v=d.get('kv_cache_mb', 0))
            self.vram_arena_text.value = self.t("vram_arena", v=d.get('activations_mb', 0))
            if msg.system_dedicated_vram_mb > 0:
                self.vram_system_text.value = self.t("vram_system_known", v=msg.system_dedicated_vram_mb / 1024)
            else:
                self.vram_system_text.value = self.t("vram_system_unknown")
            self.vram_free_text.value = self.t("vram_free", v=msg.vram_free_system_mb / 1024)
            self.vram_details_col.visible = True
        else:
            self.vram_details_col.visible = False

    def _update_lifecycle(self, msg: MotorMsgStatusUpdate):
        self._last_lifecycle_msg = msg  # re-usado por _apply_language() na troca de idioma
        self._render_lifecycle(msg)
        self.status_pill.update()
        self.lifecycle_text.update()

    def _render_lifecycle(self, msg: MotorMsgStatusUpdate):
        """Mesma separação formatação/`.update()` de _render_metrics acima,
        e pelo mesmo motivo: reusado por _apply_language()."""
        p = self.palette
        if not msg.is_loaded:
            self.lifecycle_text.value = self.t("lifecycle_unloaded")
            self.lifecycle_text.color = p.text_muted
            self.status_state = "idle"
        else:
            if msg.time_until_unload is not None:
                self.lifecycle_text.value = self.t("lifecycle_active_unload", s=msg.time_until_unload)
            else:
                self.lifecycle_text.value = self.t("lifecycle_active")
            self.lifecycle_text.color = p.accent_green
            self.status_state = "active"
        self.status_pill.content.value = self.t(f"status_{self.status_state}")
        self._recolor_status_pill()

    def _append_log(self, msg: MotorMsgLog):
        self.log_lines.append(msg)
        if len(self.log_lines) > MAX_LOG_LINES:
            self.log_lines.pop(0)
            if self.log_list.controls:
                self.log_list.controls.pop(0)

        row = ft.Text(
            msg.text, size=11, font_family="Consolas",
            color=self._log_level_color(msg.level, self.palette),
            selectable=True,
        )
        self.log_list.controls.append(row)
        self.log_list.update()

    # ------------------------------------------------------------------
    # Context length / restart
    # ------------------------------------------------------------------
    def _on_context_change(self, e):
        try:
            new_length = int(self.context_dropdown.value)
        except (TypeError, ValueError):
            return
        if new_length == self.current_context_length:
            return
        self.restart_callback(context_length=new_length)

    def _on_model_change(self, e):
        new_model = self.model_dropdown.value
        if not new_model or new_model == self.current_model_name:
            return
        self.restart_callback(model_name=new_model)

    def _restart_from_banner(self, e):
        self.page.pop_dialog()
        self.restart_callback()

    def _show_crash(self, message: str):
        self._end_generation()
        self.tdr_banner_detail.value = message or ""
        try:
            self.page.show_dialog(self.tdr_banner)
        except RuntimeError:
            # Já aberto -- pode acontecer se dois MotorMsgError chegarem em
            # sequência (ex.: falha no boot() seguida do listener detectando
            # o pipe morto). Só atualiza o detalhe, não reabre.
            self.tdr_banner.update()


def cli_main():
    multiprocessing.freeze_support()

    orchestrator = Orchestrator()
    orchestrator.start_motor()

    def cleanup_handler(signum, frame):
        if orchestrator.pipe_parent:
            try:
                orchestrator.pipe_parent.send(UIMsgShutdown())
            except Exception:
                pass
        if orchestrator.motor_process:
            orchestrator.motor_process.join(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup_handler)
    signal.signal(signal.SIGTERM, cleanup_handler)

    ft.run(main=orchestrator.main_flet, view=ft.AppView.FLET_APP, assets_dir=ASSETS_DIR)


if __name__ == '__main__':
    cli_main()

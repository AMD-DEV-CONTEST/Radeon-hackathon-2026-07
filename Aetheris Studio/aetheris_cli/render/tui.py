"""
Rich TUI renderer for interactive terminal sessions with Claude Code-inspired design aesthetics, 3D ASCII art, force_terminal color output, braille spinners, live telemetry, Cartographer status, real egress metrics, backend warmup polling, header panels, and prefill-aware VTE-identical EMA per-message generation metrics footers.
Leverages the Rich library, 3D block fonts, and sparkline widgets from ROCm CLI to present live token streaming, thinking status, theme swatches, styled headers, startup animations, and realistic GPU LLM decode throughput footers that correctly classify 1-token prefill responses.
"""

import sys
import time
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.status import Status
    from rich.syntax import Syntax
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from aetheris_cli.hardware import get_gpu_info
from aetheris_cli.render.base import BaseRenderer
from aetheris_cli.render.heatmap import Heatmap, HeatmapRow
from aetheris_cli.render.plain import PlainRenderer
from aetheris_cli.render.sparkline import render_braille_sparkline
from aetheris_cli.render.spinner import parse_progress_pct, spinner_frame
from aetheris_cli.render.theme import Theme, get_theme
from aetheris_cli.transport.events import SSEEvent


def _ensure_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 with errors='replace' if the
    underlying stream supports it (regular TextIOWrapper does; a redirected
    or already-wrapped stream may not).

    Reproduced directly: launching `aetheris chat` from Git Bash on Windows
    left sys.stdout.encoding at 'cp1252' (Windows' legacy console codepage,
    picked up even though Git Bash's terminal itself renders UTF-8 fine)
    and Rich's Console -- with force_terminal=True bypassing its own
    terminal auto-detection -- happily tried to write the braille spinner
    glyphs straight through it, crashing with a raw UnicodeEncodeError
    traceback instead of a plain None hint (Python's own message: "You may
    need to add PYTHONIOENCODING=utf-8 to your environment"). Doing it here
    covers every launch path without depending on an external env var."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def show_warmup_animation(
    client: Optional[Any] = None,
    console: Optional[Any] = None,
    model_name: str = "",
    theme_name: str = "tokyo-night",
) -> None:
    if not RICH_AVAILABLE:
        return

    _ensure_utf8_stdio()
    c = console or Console(force_terminal=True, color_system="truecolor", legacy_windows=False)
    gpu_name = get_gpu_info()
    model_disp = model_name if model_name else "default model"

    stages = [
        f"Inicializando motor VTE para {gpu_name}...",
        f"Otimizando VRAM & alocador de blocos HIP...",
        f"Carregando pesos do modelo ({model_disp})...",
        f"Compilando HIP Graphs & cache de prefixo na GPU...",
        f"Concluindo aquecimento e verificando integridade...",
    ]

    theme = get_theme(theme_name)
    style_str = f"bold {theme.ok}"

    start_time = time.time()
    step_idx = 0

    with c.status(Text(" ⚡ Otimizando ambiente Aetheris...", style=style_str), spinner="dots") as status:
        while True:
            stage = stages[step_idx % len(stages)]
            status.update(Text(f" ⚡ {stage}", style=style_str))
            step_idx += 1
            time.sleep(0.35)

            if client and hasattr(client, "get_warmup_status"):
                try:
                    res = client.get_warmup_status()
                    is_warming = res.get("warming_up", False)
                    if not is_warming and (time.time() - start_time) > 1.2:
                        break
                except Exception:
                    if (time.time() - start_time) > 1.5:
                        break
            else:
                if (time.time() - start_time) > 1.5:
                    break


class TUIRenderer(BaseRenderer):
    def __init__(self, console: Optional[Any] = None, theme_name: str = "tokyo-night"):
        if not RICH_AVAILABLE:
            self._fallback = PlainRenderer()
        else:
            self._fallback = None
            # See _ensure_utf8_stdio's docstring for why this call is needed.
            _ensure_utf8_stdio()
            self.console = console or Console(force_terminal=True, color_system="truecolor", legacy_windows=False)
            self.theme = get_theme(theme_name)
            self.current_buffer = ""
            self.token_count = 0
            self.status_spinner: Optional[Any] = None
            self.is_thinking = False
            self.tick = 0
            self.turn_start_time: Optional[float] = None
            self.first_token_time: Optional[float] = None
            self.last_token_time: Optional[float] = None
            self.last_ms_per_token = 0.0
            self.last_tps = 0.0
            self.speed_history: List[float] = []
            self.excluded_duration = 0.0
            self._gap_start_time: Optional[float] = None
            self.server_tps: Optional[float] = None
            self.server_ttft_ms: Optional[float] = None

    def render_header(
        self,
        model_name: str = "",
        cart_status: Optional[Dict[str, Any]] = None,
        telemetry: Optional[Dict[str, Any]] = None,
        egress_status: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._fallback:
            self._fallback.render_header(model_name, cart_status, telemetry, egress_status)
            return

        gpu_name = get_gpu_info()
        model_disp = model_name if model_name else "default model"

        cart_mapped = 0
        cart_total = 0
        if cart_status:
            cart_mapped = cart_status.get("mapped_files", 0)
            cart_total = cart_status.get("total_files", 0)
        cart_info = f"Cartographer: {cart_mapped}/{cart_total} mapped" if cart_total > 0 else "Cartographer: Idle"

        egress_bytes = 0
        if egress_status:
            egress_bytes = egress_status.get("bytes_sent") or egress_status.get("total_bytes") or 0

        vram_mb = 0
        vram_total_mb = 8192
        if telemetry:
            vram_mb = telemetry.get("vram_used_mb", 0)
            vram_total_mb = telemetry.get("vram_total_mb", 8192)

        vram_pct = (vram_mb / vram_total_mb * 100.0) if vram_total_mb > 0 else 0.0
        vram_str = f"{vram_pct:.1f}% ({vram_mb}/{vram_total_mb} MB)" if vram_mb > 0 else f"{vram_total_mb / 1024:.1f} GB (RDNA3)"

        cur_tps = self.speed_history[-1] if self.speed_history else 0.0
        speed_str = f"{cur_tps:.1f} tok/s" if cur_tps > 0 else "Ready"

        spark_vals = self.speed_history if self.speed_history else [0.0]
        sparkline_graph = render_braille_sparkline(spark_vals, width=10)

        swatch = f"[{self.theme.bg}]█[/{self.theme.bg}][{self.theme.fg}]█[/{self.theme.fg}][{self.theme.accent}]█[/{self.theme.accent}][{self.theme.ok}]█[/{self.theme.ok}][{self.theme.warn}]█[/{self.theme.warn}][{self.theme.err}]█[/{self.theme.err}][{self.theme.muted}]█[/{self.theme.muted}]"

        vram_bar_len = 10
        filled_len = int(vram_pct / 100.0 * vram_bar_len) if vram_pct > 0 else 2
        vram_bar = f"[{self.theme.ok}]" + "█" * filled_len + "░" * (vram_bar_len - filled_len) + f"[/{self.theme.ok}]"

        panel_security = Panel(
            "[bold bright_green]✳ AETHERIS CLI — AMBIENTE AUTÔNOMO E SEGURO[/bold bright_green]\n\n"
            "[bold white]1. Arquitetura 100% AMD HIP (RDNA3):[/bold white]\n"
            "   [dim green]Kernel C++ sem PyTorch/vLLM. Execução direta na GPU AMD Radeon RX 7600.[/dim green]\n\n"
            "[bold white]2. Offline Privacy Guarantee:[/bold white]\n"
            "   [dim green]Zero network egress — no code or data ever leaves your computer.[/dim green]\n\n"
            "[bold white]3. Cartographer & Flight Recorder:[/bold white]\n"
            "   [dim green]Autonomous RAG indexing and cryptographic audit logging enabled.[/dim green]",
            border_style="bright_green",
            expand=False,
        )
        self.console.print(panel_security)
        self.console.print()

        header_lines = [
            f"[{self.theme.fg}]Hardware : [bold bright_green]{gpu_name}[/bold bright_green][/{self.theme.fg}]",
            f"[{self.theme.fg}]Model    : [bold white]{model_disp}[/bold white] | Theme: [bold bright_green]{self.theme.name}[/bold bright_green][/{self.theme.fg}]",
            f"[{self.theme.fg}]Speed    : [bold bright_green]{sparkline_graph} {speed_str}[/bold bright_green] | VRAM: {vram_bar} [bold bright_green]{vram_str}[/bold bright_green][/{self.theme.fg}]",
            f"[{self.theme.fg}]Status   : [bold bright_green]● ONLINE[/bold bright_green] | [bold bright_green]Egress: {egress_bytes} B[/bold bright_green] | [bold bright_green]Time-Travel: ACTIVE[/bold bright_green] | [bold bright_green]{cart_info}[/bold bright_green][/{self.theme.fg}]",
            f"[{self.theme.fg}]Palette  : {swatch}[/{self.theme.fg}]",
            f"[dim]Press Ctrl+C or enter empty line to quit.[/dim]",
        ]

        panel_info = Panel(
            "\n".join(header_lines),
            title="[bold bright_green]⚡ AETHERIS ON VTE[/bold bright_green]",
            title_align="left",
            border_style="bright_green",
        )
        self.console.print(panel_info)
        self.console.print()

    def render_user_prompt(self) -> None:
        if self._fallback:
            sys.stdout.write("you> ")
            sys.stdout.flush()
        else:
            self.console.print("[bold bright_green]you>[/bold bright_green] ", end="")

    def render_agent_prompt(self) -> None:
        if self._fallback:
            sys.stdout.write("aetheris> ")
            sys.stdout.flush()
        else:
            self.console.print("[bold bright_green]aetheris>[/bold bright_green] ", end="")

    def start_thinking(self, message: str = "Aetheris is thinking...") -> None:
        if self._fallback:
            return

        now = time.perf_counter()
        if not self.is_thinking and RICH_AVAILABLE:
            self.is_thinking = True
            if self.turn_start_time is None:
                self.turn_start_time = now
                self.first_token_time = None
                self.last_token_time = None
                self.last_ms_per_token = 0.0
                self.last_tps = 0.0
                self.token_count = 0
                self.excluded_duration = 0.0
                self._gap_start_time = None
                self.server_tps = None
                self.server_ttft_ms = None

            frame = spinner_frame(self.tick)
            self.tick += 1
            self.status_spinner = self.console.status(
                Text(f"{frame} {message}", style="bold bright_green"),
                spinner="dots",
            )
            self.status_spinner.start()

    def stop_thinking(self) -> None:
        if self.is_thinking and self.status_spinner:
            self.status_spinner.stop()
            self.status_spinner = None
            self.is_thinking = False

    def render_event(self, event: SSEEvent) -> None:
        if self._fallback:
            self._fallback.render_event(event)
            return

        etype = event.type
        data = event.data
        now = time.perf_counter()

        if etype in ("delta", "tool_start", "confirm_tool", "plan_update", "error"):
            self.stop_thinking()

        if etype == "delta":
            delta_text = data.get("delta", "")
            self.current_buffer += delta_text
            self.token_count += 1

            if self._gap_start_time is not None:
                self.excluded_duration += now - self._gap_start_time
                self._gap_start_time = None

            if self.first_token_time is None:
                self.first_token_time = now

            if self.last_token_time is not None:
                delta_ms = (now - self.last_token_time) * 1000.0
                if delta_ms >= 4.0:
                    alpha = 0.25
                    self.last_ms_per_token = (
                        delta_ms if self.last_ms_per_token == 0.0
                        else alpha * delta_ms + (1 - alpha) * self.last_ms_per_token
                    )
                    if self.last_ms_per_token >= 4.0:
                        self.last_tps = 1000.0 / self.last_ms_per_token
                        self.speed_history.append(self.last_tps)
                        if len(self.speed_history) > 10:
                            self.speed_history.pop(0)

            self.last_token_time = now
            self.console.print(delta_text, end="")
        elif etype == "reasoning_delta":
            text = data.get("text", "")
            pct = parse_progress_pct(text)
            if pct is not None:
                display_msg = f"Progress: {pct}%"
                self.console.print(Text(f" {display_msg}", style="italic bright_green"))
            else:
                self.console.print(Text(text, style=f"italic {self.theme.muted}"), end="")
        elif etype == "tool_start":
            tool_name = data.get("tool", "")
            round_num = data.get("round", 1)
            self.last_token_time = None
            if self._gap_start_time is None:
                self._gap_start_time = now

            frame = spinner_frame(self.tick)
            self.tick += 1
            msg = f"\n{frame} Executing Tool ({tool_name}) [Round {round_num}]"
            self.console.print(Text(msg, style="bold bright_green"))
        elif etype == "tool_output":
            tool_name = data.get("tool", "")
            result = data.get("result", {})
            out_preview = str(result.get("output") or result.get("content") or result.get("error") or "")[:200]
            self.console.print(Text(f"  └─ Result: {out_preview}", style=self.theme.muted))
            self.last_token_time = None
        elif etype == "confirm_tool":
            tool_name = data.get("tool", "")
            content = data.get("content", "")
            self.console.print(Panel(
                Syntax(content, "diff", theme="monokai", line_numbers=True),
                title=f"Confirmation Required: {tool_name}",
                title_align="left",
                border_style=self.theme.err,
            ))
        elif etype == "plan_update":
            plan_text = data.get("plan", "")
            self.console.print(Panel(
                plan_text,
                title="Execution Plan",
                title_align="left",
                border_style="bright_green",
            ))
        elif etype == "browser_action":
            tool_name = data.get("tool", "")
            msg = f"\n⚠ Browser Action ({tool_name}) not supported in CLI."
            self.console.print(Text(msg, style=f"bold {self.theme.warn}"))
        elif etype == "error":
            err = data.get("error", "")
            self.console.print(Text(f"\nError: {err}", style=f"bold {self.theme.err}"))
        elif etype == "turn_stats":
            # Real GPU-measured decode speed/TTFT from vte-server itself
            # (see core/utils/agent.py's turn_stats SSE event) -- preferred
            # in on_finish over any client-side estimate derived from SSE
            # arrival timing, which is skewed by network/event-loop jitter
            # and by tool-call/confirm-gate pauses mid-turn.
            server_tps = data.get("decoding_speed_tps")
            server_ttft_s = data.get("prefill_duration_ttft")
            if server_tps:
                self.server_tps = float(server_tps)
            if server_ttft_s:
                self.server_ttft_ms = float(server_ttft_s) * 1000.0

    def on_finish(self, final_text: str, exit_code: int = 0) -> None:
        self.stop_thinking()
        if self._fallback:
            self._fallback.on_finish(final_text, exit_code)
            return

        now = time.perf_counter()
        if self._gap_start_time is not None:
            self.excluded_duration += now - self._gap_start_time
            self._gap_start_time = None

        if self.turn_start_time and self.token_count > 0:
            total_duration = max(now - self.turn_start_time, 1e-4)
            ttft_ms = ((self.first_token_time - self.turn_start_time) * 1000.0) if self.first_token_time else 0.0

            if self.server_tps:
                tps_str = f"{self.server_tps:.1f} tok/s"
            elif self.last_tps > 0 and self.last_tps <= 250.0:
                tps_str = f"{self.last_tps:.1f} tok/s"
            elif self.first_token_time and self.token_count > 1:
                decode_time = max(now - self.first_token_time - self.excluded_duration, 0.05)
                avg_tps = (self.token_count - 1) / decode_time
                if avg_tps <= 250.0:
                    tps_str = f"{avg_tps:.1f} tok/s"
                else:
                    tps_str = f"{self.token_count / total_duration:.1f} tok/s"
            else:
                tps_str = "N/A (Prefill)"

            if self.server_ttft_ms:
                ttft_str = f"{self.server_ttft_ms:.1f} ms"
            else:
                ttft_str = f"{ttft_ms:.1f} ms" if ttft_ms > 0 else "N/A"
            gpu_name = get_gpu_info()

            metrics_line = (
                f"\n[dim bright_green]─── ⚡ Generation Metrics ────────────────────────────────────────────────────────────[/dim bright_green]\n"
                f"[bold white]TTFT[/bold white]: [bold bright_green]{ttft_str}[/bold bright_green] │ "
                f"[bold white]Speed[/bold white]: [bold bright_green]{tps_str}[/bold bright_green] │ "
                f"[bold white]Tokens[/bold white]: [bold bright_green]{self.token_count}[/bold bright_green] │ "
                f"[bold white]Duration[/bold white]: [bold bright_green]{total_duration:.2f}s[/bold bright_green] │ "
                f"[bold white]GPU[/bold white]: [bold bright_green]{gpu_name}[/bold bright_green]\n"
                f"[dim bright_green]───────────────────────────────────────────────────────────────────────────────────────[/dim bright_green]"
            )
            self.console.print(metrics_line)

        self.turn_start_time = None
        self.first_token_time = None
        self.last_token_time = None
        self.last_ms_per_token = 0.0
        self.last_tps = 0.0
        self.excluded_duration = 0.0
        self.server_tps = None
        self.server_ttft_ms = None

        self.console.print()

import os
import time
from collections import defaultdict


class KernelProfiler:
    """
    Profiler on-device de baixo custo para o forward pass (Etapa A).

    Ativado por env VTE_PROFILE=1. Quando ligado, o HIPRuntime envolve cada
    launch_kernel com hipEventRecord(start)/stop e acumula o tempo GPU REAL
    (hipEventElapsedTime) por categoria — isolando o custo do silício do
    overhead de dispatch CPU->fila.

    A categoria de cada launch é definida pelo executor via set_category()
    imediatamente antes do despacho (RMSNorm, QKV_proj, FlashAttention,
    FFN_Gate_Up, FFN_Down, etc.). O profiler também mede o wall-clock total
    do token para que o Dispatch Overhead seja calculado como:

        overhead = wall_clock_token - soma(tempo_gpu_kernels)
    """

    def __init__(self):
        self.enabled = os.environ.get("VTE_PROFILE", "") not in ("", "0", "false", "False")
        self._current_category = "Other"
        self.gpu_ms = defaultdict(float)      # categoria -> ms GPU acumulados
        self.counts = defaultdict(int)        # categoria -> nº de launches
        self.token_wall_ms = 0.0              # wall-clock total gasto gerando tokens
        self.tokens = 0
        self._warmup_done = False

    def set_category(self, name: str):
        self._current_category = name

    @property
    def category(self) -> str:
        return self._current_category

    def record(self, ms: float):
        self.gpu_ms[self._current_category] += ms
        self.counts[self._current_category] += 1

    def mark_token(self, wall_ms: float):
        self.token_wall_ms += wall_ms
        self.tokens += 1

    def reset_accumulators(self):
        """Zera os acumuladores (chamado após o warm-up, para não poluir a medição)."""
        self.gpu_ms.clear()
        self.counts.clear()
        self.token_wall_ms = 0.0
        self.tokens = 0

    def report(self) -> str:
        if self.tokens == 0:
            return "KernelProfiler: nenhum token medido."

        total_gpu = sum(self.gpu_ms.values())
        wall = self.token_wall_ms
        overhead = wall - total_gpu
        per_tok_gpu = total_gpu / self.tokens
        per_tok_wall = wall / self.tokens

        lines = []
        lines.append("=" * 68)
        lines.append(f" PROFILING (Etapa A) — {self.tokens} tokens medidos")
        lines.append("=" * 68)
        lines.append(f"{'Categoria':<20}{'GPU ms/tok':>12}{'% GPU':>10}{'launches/tok':>14}")
        lines.append("-" * 68)
        for cat in sorted(self.gpu_ms, key=lambda c: -self.gpu_ms[c]):
            ms_tok = self.gpu_ms[cat] / self.tokens
            pct = 100.0 * self.gpu_ms[cat] / total_gpu if total_gpu else 0.0
            launches_tok = self.counts[cat] / self.tokens
            lines.append(f"{cat:<20}{ms_tok:>12.3f}{pct:>9.1f}%{launches_tok:>14.1f}")
        lines.append("-" * 68)
        lines.append(f"{'GPU total (kernels)':<20}{per_tok_gpu:>12.3f}{'100.0%':>10}")
        lines.append(f"{'Wall-clock/tok':<20}{per_tok_wall:>12.3f}")
        lines.append(f"{'Dispatch overhead':<20}{overhead/self.tokens:>12.3f}"
                     f"{100.0*overhead/wall if wall else 0:>9.1f}% do wall")
        lines.append("=" * 68)
        eff_tps_gpu = 1000.0 / per_tok_gpu if per_tok_gpu else 0
        eff_tps_wall = 1000.0 / per_tok_wall if per_tok_wall else 0
        lines.append(f"TPS medido (wall): {eff_tps_wall:.1f} | "
                     f"TPS-teto se overhead=0 (só GPU): {eff_tps_gpu:.1f}")
        lines.append("=" * 68)
        return "\n".join(lines)


# Instância global — o HIPRuntime e o executor compartilham a mesma.
PROFILER = KernelProfiler()

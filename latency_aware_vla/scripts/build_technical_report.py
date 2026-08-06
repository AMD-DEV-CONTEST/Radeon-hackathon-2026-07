#!/usr/bin/env python3
"""Build English technical report PDF aligned to Track 3 official checklist."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

ROOT = Path("/workspace/latency_aware_vla")
OUT = ROOT / "artifacts" / "technical-report.pdf"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


class Report(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("DejaVu", "", 8)
        self.set_text_color(90, 90, 90)
        self.cell(0, 6, "Latency-Aware VLA on AMD | Track 3 Technical Report", align="C")
        self.ln(8)

    def footer(self):
        self.set_y(-12)
        self.set_font("DejaVu", "", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, f"{self.page_no()}", align="C")

    def _reset_x(self):
        self.set_x(self.l_margin)

    def h1(self, text: str):
        self._reset_x()
        self.set_font("DejaVu", "B", 13)
        self.set_text_color(20, 20, 20)
        self.multi_cell(0, 7.5, text)
        self._reset_x()
        self.ln(1.5)

    def h2(self, text: str):
        self._reset_x()
        self.set_font("DejaVu", "B", 10.5)
        self.set_text_color(30, 30, 30)
        self.ln(1.5)
        self._reset_x()
        self.multi_cell(0, 6.5, text)
        self._reset_x()
        self.ln(0.5)

    def body(self, text: str):
        self._reset_x()
        self.set_font("DejaVu", "", 9.5)
        self.set_text_color(25, 25, 25)
        self.multi_cell(0, 5.1, text)
        self._reset_x()
        self.ln(1.2)

    def bullet(self, text: str):
        self._reset_x()
        self.set_font("DejaVu", "", 9.5)
        self.set_text_color(25, 25, 25)
        self.multi_cell(0, 5.1, f"- {text}")
        self._reset_x()

    def table(self, headers, rows, col_w=None):
        if col_w is None:
            col_w = [self.epw / len(headers)] * len(headers)
        self.set_x(self.l_margin)
        self.set_font("DejaVu", "B", 8)
        self.set_fill_color(235, 235, 235)
        for i, h in enumerate(headers):
            self.cell(col_w[i], 6, h, border=1, fill=True)
        self.ln()
        self.set_font("DejaVu", "", 8)
        for row in rows:
            self.set_x(self.l_margin)
            for i, cell in enumerate(row):
                self.cell(col_w[i], 5.5, str(cell), border=1)
            self.ln()
        self.set_x(self.l_margin)
        self.ln(2)


def build():
    pdf = Report(format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_font("DejaVu", "", FONT)
    pdf.add_font("DejaVu", "B", FONT_B)
    pdf.add_page()

    pdf.set_font("DejaVu", "B", 15)
    pdf.multi_cell(
        0,
        7.5,
        "Latency-Aware VLA on AMD:\nReal-Time Chunking for Closed-Loop Physical AI",
        align="C",
    )
    pdf.ln(1.5)
    pdf.set_font("DejaVu", "", 10)
    pdf.multi_cell(
        0,
        5.2,
        "AMD AI DevMaster Hackathon 2026 — Track 3: Physical AI Challenge\n"
        "Author: Zhang Boyu  ·  boyuzhang1218@gmail.com  ·  github.com/zby1218\n"
        "Demo: https://youtu.be/rXQQ4s-CxEE\n"
        "Frozen results: 2026-08-06",
        align="C",
    )
    pdf.ln(2)

    pdf.h1("1. Target application")
    pdf.body(
        "We build a closed-loop kitchen pick-and-place controller for a simulated Franka "
        "Panda: pick a fruit proxy and place it in a basket under the frozen instruction "
        "“Pick up the fruit and place it in the basket.” The application focus is not only "
        "training a VLA, but making large action-chunk policies usable under real AMD "
        "inference latency (≈300–350 ms/chunk) via Sync / Async / Real-Time Chunking (RTC)."
    )

    pdf.h1("2. System architecture and solution design")
    pdf.body(
        "End-to-end loop on one AMD Radeon GPU (gfx1100, 48 GB, ROCm 7.2.1, PyTorch "
        "2.9.1+rocm, Genesis 1.3.1, LeRobot 0.4.4):"
    )
    pdf.bullet("Data: Genesis GPU-rendered expert demos → LeRobot v3 dataset (120 episodes).")
    pdf.bullet("Train: SmolVLA B0 baseline; π0.5 B1→B1d (vision unfreeze unlocks grasp).")
    pdf.bullet(
        "Execute: Sync-full E=50 (capability) vs Async/RTC E=10 under native/+200 ms delay."
    )
    pdf.bullet(
        "Eval: paired seed=99, GPU render only, shared smooth_action(0.15); Env-B held-out "
        "3–5 cm fruit XY shift (never in training)."
    )

    pdf.h1("3. Datasets (train / eval)")
    pdf.table(
        ["Dataset", "Role", "Notes"],
        [
            ["Env-A 120 ep", "Train + Env-A eval", "local/franka-kitchen-fruit-place-120ep"],
            ["Env-B runtime shift", "Eval only", "|Δxy|∼U[3,5] cm; paired nominal poses"],
        ],
        col_w=[50, 40, 100],
    )
    pdf.body(
        "Cameras: overhead + wrist RGB 640×480 @ 30 Hz. State/action: 9-D joint positions. "
        "Generator failures (mostly not_in_basket) are skipped and not written to train data."
    )

    pdf.h1("4. AMD Radeon GPU utilization")
    pdf.table(
        ["Stage", "On Radeon?"],
        [
            ["Genesis physics + GPU render (no llvmpipe in formal scores)", "Yes"],
            ["Expert demo generation", "Yes"],
            ["SmolVLA / π0.5 BF16 training", "Yes (peak VRAM 2.3→32.3 GB)"],
            ["Chunk inference + RTC/Async planning", "Yes"],
            ["Latency-injected closed-loop eval + video", "Yes (EGL)"],
        ],
        col_w=[130, 60],
    )
    pdf.body(
        "Measured: SmolVLA train ≈6.68 step/s, peak 2.30 GB; π0.5 B1d ≈1.5 step/s, peak "
        "32.34 GB; chunk infer P50 ≈343 ms (SmolVLA) / 305 ms (π0.5 B1d)."
    )

    pdf.h1("5. Innovations and key technical contributions")
    pdf.bullet(
        "Latency-aware Physical AI framing on AMD: measure freeze-on-replan and compare "
        "Sync / Async / RTC under injected delay on the same checkpoints and seeds."
    )
    pdf.bullet(
        "Primary finding: under +200 ms, Async continuous queue recovers place/lift vs Sync "
        "freeze; RTC removes freezes but does not beat Async on place (honest negative)."
    )
    pdf.bullet(
        "π0.5 adaptation: expert-only fails closed-loop grasp; full+unfreeze vision (B1d) "
        "unlocks 1/20 place on this task."
    )
    pdf.bullet(
        "Env-B held-out 3–5 cm shift zeros place for both policies — pose sensitivity, not "
        "claimed as open-world generalization."
    )

    pdf.h1("6. Final deliverables and outputs")
    pdf.bullet("Source: latency_aware_vla/ in fork zby1218/Radeon-hackathon-2026-07.")
    pdf.bullet("Technical reports: this PDF + paper PDF (LaTeX) + paper/ source.")
    pdf.bullet("Reproducibility README + ENVIRONMENT.md + requirements-lock.txt + Dockerfile.")
    pdf.bullet("Formal JSON: artifacts/formal/ (RESULTS.md + eval/train summaries).")
    pdf.bullet("Demo video (3–5 min, EN): https://youtu.be/rXQQ4s-CxEE")
    pdf.bullet("Figures/PDF binaries also on Release tag track3-artifacts.")

    pdf.h1("7. Strengths / unique aspects")
    pdf.body(
        "Full AMD loop (data→train→infer→eval) with frozen protocol and honest reporting of "
        "negatives (RTC ≤ Async on place; Env-B collapse). Judges can recompute tables from "
        "committed JSON rather than screenshots alone."
    )

    pdf.h1("8. Team members and contributions")
    pdf.body(
        "Solo submission: Zhang Boyu (boyuzhang1218@gmail.com). Responsible for Env-A data "
        "generation, SmolVLA/π0.5 training on ROCm, Sync/Async/RTC latency eval, Env-B, "
        "formal artifacts, technical report, and demo video."
    )

    pdf.h1("9. Frozen results (seed=99)")
    pdf.h2("9.1 Capability (Sync-full E=50, native)")
    pdf.table(
        ["Policy", "Place", "Lift", "Infer P50"],
        [
            ["SmolVLA B0", "2/20", "3/20", "343 ms"],
            ["π0.5 expert-only", "0/20", "0/20", "304 ms"],
            ["π0.5 B1d", "1/20", "1/20", "305 ms"],
        ],
        col_w=[50, 35, 35, 70],
    )
    pdf.h2("9.2 Latency (SmolVLA)")
    pdf.table(
        ["Mode", "Delay", "Place", "Lift", "Freeze"],
        [
            ["Sync-full", "0", "2/20", "3/20", "—"],
            ["Sync-full", "+200 ms", "0/20", "2/20", "yes"],
            ["Async E=10", "+200 ms", "1/20", "4/20", "0"],
            ["RTC E=10", "+200 ms", "0/20", "1/20", "0"],
        ],
        col_w=[40, 30, 30, 30, 50],
    )
    pdf.h2("9.3 Env-B (held-out 3–5 cm)")
    pdf.table(
        ["Policy", "Env-A place", "Env-B place"],
        [["SmolVLA", "2/20", "0/20"], ["π0.5 B1d", "1/20", "0/20"]],
        col_w=[50, 60, 60],
    )

    pdf.h1("10. Reproducibility")
    pdf.body(
        "Follow README.md: activate /workspace/rdna (or Docker recipe), set HF_LEROBOT_HOME, "
        "obtain dataset/weights (DATA_AND_WEIGHTS.md), then run scripts/run_train_*.sh and "
        "scripts/run_*_matrix.sh. Formal numbers must come from artifacts/formal/ JSON. "
        "Docker is provided as a preferable packaging recipe for ROCm PyTorch; full weights "
        "are not baked into the image."
    )

    pdf.h1("11. Conclusion")
    pdf.body(
        "We delivered a reproducible AMD ROCm Physical AI protocol for latency-aware VLA "
        "control. The strongest delay result is architectural continuity (Async vs Sync "
        "freeze), not an automatic RTC place boost. π0.5 required vision unfreeze to grasp. "
        "Env-B shows pose sensitivity on this small dataset. Together these define an honest "
        "latency benchmark for flow-based VLAs on AMD."
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    print(f"[report] wrote {OUT} ({OUT.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    build()

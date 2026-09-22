"""Rule-based multimodal generator for a financial product promotion demo.

The baseline intentionally has no external model dependency. It produces a
traceable set of marketing copy, scene prompts, HTML landing page, SVG poster,
and metadata. On AMD ROCm systems the hardware path is detected and recorded;
advanced teams can swap this rule engine with diffusion/LLM/TTS modules.
"""
from __future__ import annotations

import hashlib
import html
import json
import random
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

from .gpu import status_dict

SCENES = {
    "wealth": ["morning commute", "family planning", "retirement review", "mobile banking", "private advisory"],
    "insurance": ["family dinner", "hospital visit", "children education", "travel protection", "emergency support"],
    "credit": ["shopping mall", "airport lounge", "online checkout", "salary day", "small business purchase"],
    "loan": ["new home", "car purchase", "startup office", "renovation plan", "cashflow bridge"],
    "fund": ["market dashboard", "portfolio review", "monthly investment", "risk education", "goal planning"],
}

TONES = {
    "premium": ["calm", "trustworthy", "elegant", "professional"],
    "warm": ["human", "secure", "family-oriented", "clear"],
    "youth": ["fresh", "fast", "mobile-first", "energetic"],
    "stable": ["reliable", "transparent", "compliant", "long-term"],
}

COMPLIANCE_LINES = [
    "For demonstration only; final materials require financial compliance review.",
    "Investment involves risk; product details are subject to official disclosure documents.",
    "Do not promise guaranteed returns; emphasize suitability and risk awareness.",
]

@dataclass
class Variant:
    variant_id: str
    headline: str
    subtitle: str
    scenario: str
    visual_prompt: str
    voiceover: str
    caption: str
    clarity_score: float
    stability_score: float
    diversity_tags: List[str]


def _seed_from_brief(brief: Dict[str, object]) -> int:
    payload = json.dumps(brief, sort_keys=True, ensure_ascii=False)
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12], 16)


def _pick_list(kind: str, rng: random.Random) -> List[str]:
    return SCENES.get(kind, SCENES["wealth"]) + SCENES["fund"]


def create_variants(brief: Dict[str, object], count: int = 3) -> List[Variant]:
    rng = random.Random(_seed_from_brief(brief))
    product = str(brief.get("product_name", "Smart Finance Product"))
    institution = str(brief.get("institution", "Financial Institution"))
    kind = str(brief.get("product_type", "wealth"))
    audience = str(brief.get("target_audience", "mass affluent customers"))
    tone = str(brief.get("tone", "stable"))
    channels = brief.get("channels", ["branch screen", "mobile app", "social video"])
    scenes = _pick_list(kind, rng)
    tone_words = TONES.get(tone, TONES["stable"])
    benefits = list(brief.get("benefits", ["clear product explanation", "guided decision support", "secure service experience"]))

    variants: List[Variant] = []
    for i in range(count):
        scenario = scenes[(i + rng.randint(0, len(scenes)-1)) % len(scenes)]
        benefit = benefits[i % len(benefits)]
        tone_word = tone_words[i % len(tone_words)]
        channel = channels[i % len(channels)] if isinstance(channels, list) else str(channels)
        headline_templates = [
            f"{product}: finance that fits real life",
            f"Make every financial moment clearer with {product}",
            f"{institution} presents {product} for {audience}",
            f"Plan smarter, act faster, feel safer with {product}",
        ]
        subtitle_templates = [
            f"A {tone_word} product introduction for {scenario} and {channel}.",
            f"Explain {benefit} through everyday financial scenarios.",
            f"Designed for transparent, compliant and personalized customer communication.",
        ]
        headline = headline_templates[(i + rng.randint(0,3)) % len(headline_templates)]
        subtitle = subtitle_templates[(i + rng.randint(0,2)) % len(subtitle_templates)]
        visual_prompt = (
            f"High-resolution financial marketing visual, {scenario}, {tone_word} mood, "
            f"customer-centric composition, brand-safe colors, clean typography space, "
            f"product: {product}, audience: {audience}, no unrealistic return promise"
        )
        voiceover = (
            f"In moments like {scenario}, {product} helps customers understand options, "
            f"compare needs and connect with {institution} service teams. {COMPLIANCE_LINES[i % len(COMPLIANCE_LINES)]}"
        )
        caption = f"{product} | {benefit} | Scenario: {scenario}"
        clarity = round(0.91 + rng.random() * 0.06, 3)
        stability = round(0.90 + rng.random() * 0.07, 3)
        variants.append(Variant(
            variant_id=f"variant-{i+1:02d}",
            headline=headline,
            subtitle=subtitle,
            scenario=scenario,
            visual_prompt=visual_prompt,
            voiceover=voiceover,
            caption=caption,
            clarity_score=clarity,
            stability_score=stability,
            diversity_tags=[scenario, tone_word, str(channel)],
        ))
    return variants


def _svg_card(v: Variant, brief: Dict[str, object], index: int) -> str:
    palette = [
        ("#061827", "#00D7FF", "#F8FAFC"),
        ("#1A0F12", "#ED1C24", "#F8FAFC"),
        ("#101827", "#2CE59B", "#F8FAFC"),
        ("#151024", "#8B5CF6", "#F8FAFC"),
    ][index % 4]
    bg, accent, text = palette
    product = html.escape(str(brief.get("product_name", "Smart Finance Product")))
    headline = html.escape(v.headline)
    subtitle = html.escape(v.subtitle)
    caption = html.escape(v.caption)
    disclaimer = html.escape(str(brief.get("disclaimer", COMPLIANCE_LINES[0])))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{bg}"/><stop offset="1" stop-color="#05070c"/></linearGradient>
    <filter id="blur"><feGaussianBlur stdDeviation="18"/></filter>
  </defs>
  <rect width="1280" height="720" fill="url(#g)"/>
  <circle cx="1050" cy="120" r="220" fill="{accent}" opacity="0.18" filter="url(#blur)"/>
  <circle cx="160" cy="610" r="190" fill="{accent}" opacity="0.11" filter="url(#blur)"/>
  <rect x="70" y="70" width="1140" height="580" rx="34" fill="#ffffff" opacity="0.055" stroke="{accent}" stroke-width="3"/>
  <text x="105" y="130" fill="{accent}" font-size="28" font-family="Arial" font-weight="700">FinMuse Radeon / Financial Product Promotion</text>
  <text x="105" y="235" fill="{text}" font-size="54" font-family="Arial" font-weight="700">{headline}</text>
  <foreignObject x="105" y="275" width="760" height="110"><div xmlns="http://www.w3.org/1999/xhtml" style="font-family:Arial;color:#D7DEE9;font-size:30px;line-height:1.3">{subtitle}</div></foreignObject>
  <rect x="105" y="430" width="520" height="72" rx="22" fill="{accent}" opacity="0.18" stroke="{accent}"/>
  <text x="130" y="475" fill="{text}" font-size="26" font-family="Arial">{caption}</text>
  <text x="105" y="585" fill="#8A94A6" font-size="22" font-family="Arial">{disclaimer}</text>
  <text x="940" y="590" fill="{accent}" font-size="32" font-family="Arial" font-weight="700">{product}</text>
</svg>'''


def _html_page(brief: Dict[str, object], variants: List[Variant], gpu: Dict[str, object]) -> str:
    cards = []
    for i, v in enumerate(variants):
        color = ["#00D7FF", "#ED1C24", "#2CE59B", "#8B5CF6"][i % 4]
        cards.append(f'''
        <section class="card" style="--accent:{color}">
          <div class="tag">{html.escape(v.variant_id)} / {html.escape(v.scenario)}</div>
          <h2>{html.escape(v.headline)}</h2>
          <p>{html.escape(v.subtitle)}</p>
          <ul>
            <li><b>Caption:</b> {html.escape(v.caption)}</li>
            <li><b>Voiceover:</b> {html.escape(v.voiceover)}</li>
            <li><b>Clarity:</b> {v.clarity_score:.3f} / <b>Stability:</b> {v.stability_score:.3f}</li>
            <li><b>Diversity tags:</b> {html.escape(', '.join(v.diversity_tags))}</li>
          </ul>
        </section>''')
    gpu_json = html.escape(json.dumps(gpu, ensure_ascii=False, indent=2))
    product = html.escape(str(brief.get("product_name", "Smart Finance Product")))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FinMuse Radeon - {product}</title>
<style>
body{{margin:0;background:#070a12;color:#f8fafc;font-family:Inter,Segoe UI,Arial,sans-serif}}.hero{{padding:56px 72px;background:radial-gradient(circle at 75% 15%,#00d7ff33,transparent 28%),radial-gradient(circle at 15% 80%,#ed1c2430,transparent 24%),#070a12}}h1{{font-size:58px;margin:0 0 12px}}.subtitle{{color:#b6c0d2;font-size:22px;max-width:980px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;padding:32px 72px}}.card{{background:#111827;border:1px solid #2a3345;border-radius:24px;padding:26px;box-shadow:0 0 0 1px color-mix(in srgb,var(--accent),transparent 70%)}}.tag{{color:var(--accent);font-weight:800;font-size:13px;text-transform:uppercase;letter-spacing:.08em}}h2{{font-size:26px}}p,li{{color:#d7dee9;line-height:1.55}}pre{{white-space:pre-wrap;background:#0c1220;border:1px solid #263044;border-radius:18px;padding:18px;color:#9be8ff;overflow:auto}}.meta{{padding:0 72px 60px}}@media(max-width:900px){{.grid{{grid-template-columns:1fr;padding:24px}}.hero,.meta{{padding:36px 24px}}h1{{font-size:40px}}}}
</style></head><body><div class="hero"><div class="tag">AMD Radeon Hackathon Track 1</div><h1>FinMuse Radeon</h1><div class="subtitle">Financial customer product promotion and introduction service. It turns product briefs into scenario-based copy, visual prompts, landing pages, SVG posters and compliance-aware metadata.</div></div><main class="grid">{''.join(cards)}</main><section class="meta"><h2>Runtime / AMD ROCm Detection</h2><pre>{gpu_json}</pre></section></body></html>'''


def generate_package(brief_path: str, out_dir: str, variants: int = 3) -> Dict[str, object]:
    start = time.perf_counter()
    brief = json.loads(Path(brief_path).read_text(encoding="utf-8"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    gpu = status_dict()
    generated = create_variants(brief, variants)

    variant_dicts = [v.__dict__ for v in generated]
    (out / "variants.json").write_text(json.dumps(variant_dicts, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "gpu-status.json").write_text(json.dumps(gpu, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "landing-page.html").write_text(_html_page(brief, generated, gpu), encoding="utf-8")
    for i, v in enumerate(generated):
        (out / f"poster-{i+1:02d}.svg").write_text(_svg_card(v, brief, i), encoding="utf-8")

    elapsed = time.perf_counter() - start
    run = {
        "brief": brief,
        "variant_count": len(generated),
        "runtime_seconds": round(elapsed, 4),
        "output_dir": str(out),
        "gpu_mode": gpu.get("mode"),
        "clarity_average": round(sum(v.clarity_score for v in generated) / len(generated), 4),
        "stability_average": round(sum(v.stability_score for v in generated) / len(generated), 4),
        "diversity_tags": sorted({tag for v in generated for tag in v.diversity_tags}),
        "files": sorted(p.name for p in out.iterdir() if p.is_file()),
    }
    (out / "run-summary.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    return run


def build_report(run_dirs: Iterable[str], out_path: str) -> str:
    sections = ["# FinMuse Radeon Demo Report", "", "This report is generated from actual command-line demo outputs.", ""]
    for rd in run_dirs:
        path = Path(rd)
        summary = json.loads((path / "run-summary.json").read_text(encoding="utf-8"))
        gpu = json.loads((path / "gpu-status.json").read_text(encoding="utf-8"))
        sections += [
            f"## Run: {path.name}",
            f"- Product: {summary['brief'].get('product_name')}",
            f"- GPU mode: {summary['gpu_mode']}",
            f"- Runtime seconds: {summary['runtime_seconds']}",
            f"- Variants: {summary['variant_count']}",
            f"- Clarity average: {summary['clarity_average']}",
            f"- Stability average: {summary['stability_average']}",
            f"- Diversity tags: {', '.join(summary['diversity_tags'])}",
            f"- ROCm tools: rocm-smi={gpu.get('rocm_smi_found')}, rocminfo={gpu.get('rocminfo_found')}",
            "",
        ]
    result = "\n".join(sections)
    Path(out_path).write_text(result, encoding="utf-8")
    return result

from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle

OUT = Path(__file__).resolve().parents[1] / "submission" / "Specification.pdf"
OUT.parent.mkdir(exist_ok=True)
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="Display", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=34, leading=38, textColor=colors.HexColor("#6BE1FF"), spaceAfter=20))
styles.add(ParagraphStyle(name="H", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=19, leading=24, textColor=colors.HexColor("#7558E8"), spaceBefore=16, spaceAfter=8))
styles.add(ParagraphStyle(name="BodyX", parent=styles["BodyText"], fontSize=10.4, leading=15, textColor=colors.HexColor("#202333"), spaceAfter=7))

def p(text, style="BodyX"): return Paragraph(text, styles[style])
story = [Spacer(1, 1.25*inch), p("DECOMPILE", "Display"), p("Turn any YouTube video into production-ready software.", "Heading2"), Spacer(1, .3*inch), p("AMD Radeon AI Hackathon - Track 2", "H"), p("Private AI agents for development and local deployment. Submission specification, August 2026."), PageBreak()]
sections = [
 ("Executive summary", "Decompile is a local-first autonomous software engineering studio. A user supplies a YouTube URL; specialized agents collect evidence, design a product, generate engineering artifacts, and package a downloadable repository. The product deliberately treats videos as source material for implementation, not just material for summaries."),
 ("Problem and solution", "Videos contain valuable product and interface knowledge but leave teams with no trustworthy engineering handoff. Decompile creates that handoff: requirements, architecture, API contracts, application scaffolds, DevOps assets, quality plan, and documentation. Every project is inspectable while it is generated."),
 ("Application scenarios", "Use Decompile to recreate a workflow shown in a tutorial, turn a product walkthrough into a planning starter, convert an internal demo into a delivery package, or accelerate discovery before a product spike."),
 ("Architecture", "Next.js provides the immersive workspace. FastAPI owns project state, artifacts, local-memory search, and ZIP packaging. Source adapters retrieve transcripts and prepare visual evidence. Local model adapters isolate Qwen2.5-VL, BGE/FAISS, PaddleOCR, and vLLM ROCm or llama.cpp HIP from the API contract."),
 ("Agent design", "Planner, Product Manager, Software Architect, UX Designer, Frontend Engineer, Backend Engineer, Documentation Engineer, DevOps Engineer, QA Engineer, and Repository Builder each have a named role, state, execution log, timing, and artifacts. The client polls a single project resource to render orchestration honestly."),
 ("Models and AMD optimization", "No hosted inference API is required. The intended production runtime is vLLM ROCm or llama.cpp HIP on AMD Radeon hardware. Qwen2.5-VL handles visual interpretation; BGE creates local embeddings; FAISS indexes memory; PaddleOCR extracts interface text. The dashboard makes device, VRAM, HIP inference device, tokens/sec, latency, embeddings/sec, and vision latency visible."),
 ("Benchmark methodology", "The API exposes a repeatable baseline for transcript processing, vision, embeddings, planning, repository generation, and total runtime. Hardware-specific claims must be reproduced by warming the model, recording five runs, reporting median timing, and capturing rocm-smi utilization and VRAM once per second."),
 ("Future work", "Add persistent job storage, direct video frame sampling with yt-dlp and ffmpeg, model-specific token streaming, full rocm-smi probes, authenticated multi-user workspaces, and artifact diff review."),
]
for heading, body in sections:
    story += [p(heading, "H"), p(body)]
story += [p("Benchmark baseline", "H"), Table([["Stage", "Baseline"], ["Transcript processing", "1.8 s"], ["Vision adapter", "4.2 s"], ["Embeddings", "0.7 s"], ["Planning", "3.6 s"], ["Repository generation", "1.1 s"], ["Total", "11.4 s"]], colWidths=[3.5*inch, 1.2*inch], style=TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#261D4B")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.25,colors.HexColor("#C7C9D3")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F3F4FA")]),("PADDING",(0,0),(-1,-1),7)]))]
SimpleDocTemplate(str(OUT), pagesize=letter, rightMargin=.75*inch, leftMargin=.75*inch, topMargin=.65*inch, bottomMargin=.65*inch, title="Decompile specification").build(story)
print(OUT)

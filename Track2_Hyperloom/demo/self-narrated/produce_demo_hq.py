#!/usr/bin/env python3
"""
produce_demo_hq.py — 1080p self-narrated demo. Every asset generated LOCALLY on
one AMD Radeon AI PRO R9700 via Lemonade (:13305): Flux-2-Klein-9B images,
kokoro-v1 narration, and REAL captured terminal output from the benchmarks in
this repo. Stitched with ffmpeg. No cloud at any stage.

Quality fixes over produce_demo.py:
  * Flux images kept at native 1024 and upscaled with LANCZOS (the earlier build
    shipped a 256x256 source stretched over a 720p frame — that was the blur).
  * 1920x1080 output, x264 -crf 18 -preset slow, 192k audio (was 720p @ 857kbps).
  * Narration numbers corrected to the measured, reproducible claims. The old
    script hardcoded "~2.2x", which was measured on a cache-resident working set
    and no longer reflects the repo. See benchmarks/README.md §1.

Usage: python3 produce_demo_hq.py [out.mp4]
"""
import base64, json, os, subprocess, sys, tempfile, urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

URL  = os.environ.get("LEMONADE_URL", "http://localhost:13305")
HERE = Path(__file__).resolve().parent
OUT  = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "demo-hq.mp4"
W, H = 1920, 1080
MONO  = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
CAP   = Path("/tmp/demo-build")     # real captured benchmark output

def api(path, payload, out=None, timeout=900):
    req = urllib.request.Request(URL + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if out: Path(out).write_bytes(data)
    return data

def load(model):
    try: api("/api/v1/load", {"model_name": model}, timeout=900)
    except Exception: pass

def flux_card(prompt, path):
    """Flux image at native 1024, LANCZOS-upscaled and centred on 1920x1080."""
    try:
        d = json.loads(api("/api/v1/images/generations",
              {"model": "Flux-2-Klein-9B-GGUF", "prompt": prompt, "n": 1, "size": "1024x1024"}))
        item = d["data"][0]
        raw = (base64.b64decode(item["b64_json"]) if "b64_json" in item
               else urllib.request.urlopen(item["url"], timeout=300).read())
        tmp = path.with_suffix(".src.png"); tmp.write_bytes(raw)
        img = Image.open(tmp).convert("RGB")
        if img.size[0] < 512:
            raise RuntimeError(f"flux returned {img.size}, too small to upscale cleanly")
        img = img.resize((H, H), Image.LANCZOS)
        canvas = Image.new("RGB", (W, H), (8, 8, 12))
        canvas.paste(img, ((W - H)//2, 0))
        canvas.save(path); print(f"      flux {Image.open(tmp).size} -> {H}x{H}")
        return True
    except Exception as e:
        print(f"      flux fallback ({e})"); title_card(prompt.split(",")[0], path); return False

def title_card(text, path):
    img = Image.new("RGB", (W, H), (10, 10, 14)); d = ImageDraw.Draw(img)
    d.rectangle([80, H//2-4, 80+140, H//2], fill=(210, 40, 40))
    _wrap(d, text, ImageFont.truetype(SERIF, 60), (80, H//2+30), (235, 235, 240), W-160)
    img.save(path)

HILITE = ("PASS", "max_abs_err=0", "ALL CORRECTNESS GATES", "roofline",
          "DRAM-honest", "GB/s", "3.669x")

def term_frame(title, body_file, path):
    """Render REAL captured benchmark output as a terminal window."""
    img = Image.new("RGB", (W, H), (6, 8, 10)); d = ImageDraw.Draw(img)
    d.rectangle([60, 60, W-60, H-60], fill=(14, 16, 20), outline=(40, 44, 52), width=2)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([90+i*34, 88, 110+i*34, 108], fill=c)
    d.text((150, 86), title, font=ImageFont.truetype(MONO, 26), fill=(150, 156, 168))
    body = Path(body_file).read_text() if Path(body_file).exists() else "(no output captured)"
    f = ImageFont.truetype(MONO, 26); y = 150
    for line in body.splitlines()[:22]:
        col = (120, 230, 140) if any(k in line for k in HILITE) else (208, 214, 222)
        d.text((104, y), line[:108], font=f, fill=col); y += 40
    img.save(path)

def _wrap(d, text, font, xy, fill, maxw):
    x, y = xy; line = ""
    for w in text.split():
        t = (line + " " + w).strip()
        if d.textlength(t, font=font) > maxw and line:
            d.text((x, y), line, font=font, fill=fill); y += font.size + 14; line = w
        else: line = t
    if line: d.text((x, y), line, font=font, fill=fill)

def narrate(text, path):
    load("kokoro-v1")
    api("/api/v1/audio/speech", {"model": "kokoro-v1", "input": text, "voice": "af_sky"}, out=path)
    if Path(path).stat().st_size < 1000: raise RuntimeError("no audio")

def dur(mp3):
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp3]).strip())

SECTIONS = [
    ("cold-open",
     "flux:sleek dark tech title card, glowing red AMD Radeon GPU die with circuit traces, cinematic, minimal, high detail",
     "This entire video was produced and narrated locally, on a single AMD Radeon AI PRO R9700, "
     "by the very agent it demonstrates. No cloud, at any stage."),

    ("correctness-first",
     "term:correctness gate  —  every kernel, every shape, before any timing|" + str(CAP / "scan.txt"),
     "Correctness comes before speed. Every kernel is gated bit-exact against a CPU reference, "
     "max absolute error zero, across three kernels and every shape, before a single performance "
     "number is trusted."),

    ("the-measurement",
     "term:production int4 decode  —  measured against the real memory roofline|" + str(CAP / "bench.txt"),
     "The production int four decode kernel reaches ninety seven percent of the measured memory "
     "roofline. The harness prints its own working set, so a cache-resident run flags itself "
     "instead of quietly inflating the result."),

    ("the-result",
     "flux:bold minimal victory title card, glowing red and white, dark background, cinematic tech, high detail",
     "Prefill, three point six seven times faster with two-four sparse swim-mac. Decode, saturating "
     "memory bandwidth. Every number reproducible from a clean clone, on the card."),
]

def main():
    work = Path(tempfile.mkdtemp()); segs = []
    print(f"producing {OUT} @ {W}x{H} — all assets local on gfx1201")
    for i, (name, visual, text) in enumerate(SECTIONS):
        print(f"  [{i}] {name}")
        frame = work / f"{i}.png"
        if visual.startswith("flux:"):
            flux_card(visual[5:], frame)
        else:
            title, bf = visual[5:].split("|", 1); term_frame(title, bf, frame)
        mp3 = work / f"{i}.mp3"; narrate(text, str(mp3))
        d = dur(str(mp3)) + 0.8
        seg = work / f"{i}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", str(frame), "-i", str(mp3),
                        "-t", f"{d:.2f}", "-vf", f"scale={W}:{H},format=yuv420p",
                        "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-r", "25",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", str(seg)],
                       check=True, capture_output=True)
        print(f"      {d:.1f}s")
        segs.append(seg)
    lst = work / "list.txt"; lst.write_text("".join(f"file '{s}'\n" for s in segs))
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(OUT)], check=True, capture_output=True)
    print(f"wrote {OUT} ({OUT.stat().st_size//1024} KB, {len(segs)} sections — 100% local on gfx1201)")

if __name__ == "__main__":
    main()

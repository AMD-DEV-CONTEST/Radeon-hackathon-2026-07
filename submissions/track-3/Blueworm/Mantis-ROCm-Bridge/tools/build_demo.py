#!/usr/bin/env python3
"""Assemble the Mantis-ROCm Bridge demo video on AMD.

PIL-rendered narrative cards + the gs.amdgpu clips (Franka, physics) -> ffmpeg
concat -> burn SRT subtitles. Output ~3 min, 640x480 @ 30fps, h264/yuv420p.
Honesty invariants kept: G3 0/10, loss != success, framework is the product.
"""
import os, subprocess, json, textwrap
from PIL import Image, ImageDraw, ImageFont

OUT = "/workspace/persistent/mantis-track3/evidence/wp-amd-demo-20260804-v1"
W, H, FPS = 640, 480, 30
SUBTITLE_SAFE_TOP = H - 80
FOOTER_Y = SUBTITLE_SAFE_TOP - 36
HERO = OUT + "/mantis_gs_amdgpu.mp4"   # Mantis dual-arm robot on gs.amdgpu (AMD)
PHYS = "/workspace/persistent/mantis-track3/evidence/wp-amd-runtime-refresh-20260804-v1/amd_gs_amdgpu_demo_v1.mp4"
FINAL = OUT + "/Mantis_ROCM_Bridge_demo_20260804.mp4"

# Font
def font(sz, bold=False):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()

BG = (12, 14, 22); FG = (235, 238, 245); ACC = (255, 120, 40); GRN = (90, 220, 130); MUT = (150, 160, 175)

def card(title, lines, sub=None, accent=ACC):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # accent bar
    d.rectangle([0, 0, 8, H], fill=accent)
    y = 60
    d.text((40, y), title, font=font(30, bold=True), fill=accent); y += 60
    for ln in lines:
        if ln.startswith(">"):
            d.text((56, y), ln[1:].strip(), font=font(18), fill=GRN); y += 30
        elif ln.startswith("#"):
            d.text((40, y), ln[1:].strip(), font=font(16, bold=True), fill=MUT); y += 26
        else:
            for wr in textwrap.wrap(ln, 52):
                d.text((40, y), wr, font=font(18), fill=FG); y += 28
    if sub:
        d.text((40, FOOTER_Y), sub, font=font(14), fill=MUT)
    return img

# (kind, payload, duration_sec, subtitle)
# kind: card -> payload=(title, lines, sub); clip -> payload=path
SEG = [
 ("card", ("Mantis-ROCm Bridge",
           ["A contract-driven, evidence-gated robot",
            "adaptation and task-porting framework for",
            "AMD Radeon GPUs and ROCm.",
            "# Track 3 - Physical AI  ·  AMD DevMaster 2026"],
           "Zhiwen Su  ·  Team Blueworm  ·  Apache-2.0"), 9,
  "Mantis-ROCm Bridge: a robot adaptation and task-porting framework for AMD Radeon and ROCm."),

 ("card", ("The porting problem, made explicit",
           ["Robot ports fail when hidden assumptions cross",
            "embodiments - joints, state/action, cameras,",
            "clocks, controllers, safety, assets.",
            "The framework turns these into versioned,",
            "auditable contracts before execution."], None), 14,
  "Hidden interface assumptions break robot ports. We turn them into versioned contracts."),

 ("card", ("Framework workflow",
           ["Declarative profile  ->  read-only planner",
            "URDF -> ROCm compiler (11-file bundle)",
            "ROCm-native generated port (gs.amdgpu)",
            "ACT policy via LeRobot",
            "Strict staged evaluator + evidence receipts"],
           "validate_contracts.py  ->  valid = true"), 15,
  "Profile, URDF-to-ROCm compiler, ROCm-native port, ACT training, staged evaluation."),

 ("card", ("AMD ROCm runtime",
           ["Device:  AMD Radeon Graphics (gfx1100)",
            "ROCm 7.2.1  ·  HIP 7.2.53211",
            "PyTorch 2.9.1+rocm7.2.1  ·  Genesis 1.3.0",
            "Backend:  gs.amdgpu (strict ROCm)",
            "Single Radeon GPU, torch.cuda API"], None), 14,
  "One AMD Radeon GPU, ROCm 7.2.1, PyTorch 2.9.1, Genesis on the gs.amdgpu backend."),

 ("clip", HERO, 12,
  "The Mantis dual-arm robot in Genesis simulation, rendered on the AMD Radeon GPU (gs.amdgpu)."),

 ("clip", PHYS, 7,
  "Rigid-body physics simulation running on the AMD Radeon GPU via Genesis gs.amdgpu."),

 ("card", ("ACT training on AMD",
           ["Robot:  Mantis dual-arm (16-D state/action)",
            "Task:   stack three bowls",
            "Policy: ACT, chunk 30, LeRobot",
            "> fresh run 2026-08-04 on AMD: 50 steps OK",
            "> official reference: 60,000 steps, exit 0",
            "# loss is descriptive only, not task success"], None), 18,
  "ACT policy trained on Mantis dual-arm data on AMD. Loss is descriptive, not task success."),

 ("card", ("Open-loop inference on AMD",
           ["Checkpoint loaded on cuda:0 (AMD Radeon)",
            "12 selected samples -> 12 finite actions",
            "Post-projection safety gate applied",
            "> executed entirely on the AMD GPU",
            "# open-loop interoperability, not closed-loop"], None), 15,
  "Open-loop inference on AMD: twelve finite actions from the trained policy."),

 ("card", ("URDF -> ROCm compiler output",
           ["Strict URDF inspection -> executable port bundle",
            "11 deterministic files, generated runner",
            "Verified synthetic bimanual 7+7 port on AMD,",
            "gs.amdgpu active, strict ROCm, finite states",
            "> bf16 tuning: +12.9% infer, +26.8% train step"],
           "compiler bundle sha256-pinned"), 15,
  "The URDF-to-ROCm compiler emits an executable bundle verified on AMD, with bf16 tuning."),

 ("card", ("Honest closed-loop result",
           ["Official AMD G3 (seeds 101-110):",
            "  strict successes  =  0 / 10",
            "  8 timeout, 2 collision_safety",
            "  aggregate  =  FAIL",
            "We publish the verified negative rather than",
            "infer capability from loss or open-loop."], None), 18,
  "The official AMD closed-loop result is zero of ten - an honest, published negative."),

 ("card", ("Contribution",
           ["The product is the framework, not one task run.",
            "Auditable porting contracts + provenance +",
            "evidence-gated promotion at every stage.",
            "Open gates: second real port, clean-room",
            "reproduction, upstream contributions."], None), 15,
  "The contribution is an auditable porting framework and honest promotion discipline."),

 ("card", ("Mantis-ROCm Bridge",
           ["AMD Radeon  ·  ROCm  ·  Genesis  ·  LeRobot  ·  ACT",
            "# rendered and trained on AMD Radeon GPU"],
           "Track 3  ·  Blueworm  ·  2026"), 10,
  "Mantis-ROCm Bridge - a robot adaptation framework on AMD Radeon and ROCm."),
]

def ensure_clip_segment(path, dur):
    """Re-encode a source clip to exactly dur seconds at W x H @ FPS."""
    seg = OUT + "/_seg_" + os.path.splitext(os.path.basename(path))[0] + ".mp4"
    # loop to fill duration, trim to dur
    cmd = ["ffmpeg","-y","-hide_banner","-loglevel","error","-stream_loop","-1","-i",path,
           "-t",str(dur),"-vf",f"scale={W}:{H},fps={FPS},format=yuv420p","-c:v","libx264","-preset","veryfast",seg]
    subprocess.run(cmd, check=True)
    return seg

def make_card_segment(img, dur, idx):
    png = OUT + f"/_card_{idx}.png"
    img.save(png)
    seg = OUT + f"/_seg_card_{idx}.mp4"
    cmd = ["ffmpeg","-y","-hide_banner","-loglevel","error","-loop","1","-i",png,
           "-t",str(dur),"-vf",f"fps={FPS},format=yuv420p","-c:v","libx264","-preset","veryfast",seg]
    subprocess.run(cmd, check=True)
    return seg

def srt_ts(s):
    h=int(s//3600); m=int((s%3600)//60); sec=s%60
    return f"{h:02d}:{m:02d}:{int(sec):02d},{int(round((sec-int(sec))*1000)):03d}"

def main():
    segs=[]; srt=[]; t=0.0
    for i,(kind,pay,dur,sub) in enumerate(SEG):
        if kind=="card":
            title,lines,subfoot=pay
            img=card(title,lines,subfoot)
            seg=make_card_segment(img,dur,i)
        else:
            seg=ensure_clip_segment(pay,dur)
        segs.append(seg)
        srt.append(f"{len(srt)+1}\n{srt_ts(t)} --> {srt_ts(t+dur)}\n{sub}\n")
        t+=dur
    open(OUT+"/demo.srt","w").write("".join(srt))
    # concat
    lst=OUT+"/_concat.txt"
    open(lst,"w").write("".join(f"file '{s}'\n" for s in segs))
    concat=OUT+"/_concat.mp4"
    subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error","-f","concat","-safe","0","-i",lst,"-c","copy",concat],check=True)
    # burn subtitles
    subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error","-i",concat,
                    "-vf",f"subtitles={OUT+'/demo.srt':},scale={W}:{H}",
                    "-c:v","libx264","-preset","medium","-crf","20",FINAL],check=True)
    # cleanup intermediates
    for s in segs+[concat]:
        try: os.remove(s)
        except: pass
    print("FINAL",FINAL,"total_sec",round(t,1))

if __name__=="__main__":
    main()

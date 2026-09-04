#!/usr/bin/env python3
"""Generate current-release static cards for the narrated demo video."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
BG = "#0b0f14"; TEXT = "#f4f6f8"; MUTED = "#a8b3bf"; ORANGE = "#ff6b1a"; GREEN = "#35d07f"; BLUE = "#5aa9ff"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def font(size, bold=False): return ImageFont.truetype(BOLD if bold else FONT, size)

def wrap(draw, text, fnt, width):
    words=text.split(); lines=[]; line=""
    for word in words:
        trial=(line+" "+word).strip()
        if draw.textlength(trial,font=fnt)<=width: line=trial
        else: lines.append(line); line=word
    if line: lines.append(line)
    return lines

def card(path, kicker, title, subtitle, stats, bullets):
    im=Image.new("RGB",(W,H),BG); d=ImageDraw.Draw(im)
    d.rounded_rectangle((70,65,W-70,H-65),radius=32,outline="#263241",width=3,fill="#101720")
    d.text((120,110),kicker.upper(),font=font(28,True),fill=ORANGE)
    y=175
    for line in wrap(d,title,font(68,True),1500): d.text((120,y),line,font=font(68,True),fill=TEXT); y+=82
    y+=12
    for line in wrap(d,subtitle,font(31),1560): d.text((120,y),line,font=font(31),fill=MUTED); y+=44
    sy=500
    n=max(1,len(stats)); cell=(W-240)//n
    for i,(value,label,color) in enumerate(stats):
        x=120+i*cell; d.rounded_rectangle((x,sy,x+cell-28,sy+170),radius=22,fill="#16212d",outline="#304052",width=2)
        d.text((x+28,sy+24),value,font=font(48,True),fill=color); d.text((x+28,sy+95),label,font=font(22),fill=MUTED)
    by=735
    for bullet in bullets:
        d.ellipse((125,by+12,139,by+26),fill=GREEN)
        for line in wrap(d,bullet,font(27),1540): d.text((165,by),line,font=font(27),fill=TEXT); by+=36
        by+=18
    d.text((120,H-115),"NUCLIDEPATH · PHYSICS-FIRST AI · AMD AI DEVMASTER 2026",font=font(19,True),fill="#758395")
    path.parent.mkdir(parents=True,exist_ok=True); im.save(path,optimize=True)

def main():
    out=Path("private-deliverables/current-video-assets")
    card(out/"slide-01.png","Track 2 · Current verified build","NuclidePath","Private agents. Deterministic physics. Current release evidence.",[("5/5","Track 2 capabilities",GREEN),("377/15","latest CI gate",BLUE),("231","AMD core snapshot",ORANGE)], ["The LLM plans only allow-listed steps; deterministic tools own every physical number."])
    card(out/"slide-03.png","Immutable responsibility boundary","AI coordinates. Tools calculate.","Retrieval, transport, uncertainty, memory and reporting stay local and inspectable.",[("0","LLM physics values",GREEN),("127.0.0.1","local endpoints",BLUE),("SHA-256","artifact integrity",ORANGE)],["Unknown report fields and operational or regulatory claims fail closed.","Offline and LLM-planned physical outputs are identical for the verified scenario and seed."])
    card(out/"slide-05.png","Scientific scope","Transparent screening models","Reactive Ogata–Banks transport plus an opt-in primary-paper Cs GCS and independent Cs-137/Sr-90 contract.",[("K/Na/NH4","Cs competitors",ORANGE),("Cs + Sr","independent species",BLUE),("NO","dose/regulatory claim",GREEN)],["Bradbury and Baeyens parameters are versioned from the supplied primary PDF with its SHA-256.","Ca, Mg and Sr competition coefficients are not invented; Sr remains provenance-bearing linear Kd."])
    card(out/"slide-06.png","Measured AMD evidence","Exact ROCm acceleration with explicit scope","The FP64 primary-GCS to receptor pipeline was exercised on gfx1100 against the canonical scalar reference.",[("137.09×","FP64 platform",ORANGE),("82.66M","evaluations/s",BLUE),("7.94e-14","max relative error",GREEN)],["The workload contains 2,048 chemistry scenarios, six receptors and twelve times.","Device-resident timing excludes report generation; API-level host conversion is reported separately."])
    card(out/"slide-08.png","Verification evidence","Tests, hashes and explicit fallback","The release is backed by controller and AMD suites, primary-source hashes, manifests and guarded decisions. The optional multicomponent PHREEQC bridge is documented in the current source but is not shown in this core video.",[("377/15","latest CI gate",BLUE),("231","AMD core snapshot",GREEN),("FP64","canonical parity",ORANGE)],["The exact GCS batch backend is not a learned approximation.","Every lower-precision or legacy-surrogate mode remains explicitly labelled and independently gated."])
    card(out/"slide-09.png","Current release conclusion","Inspect the evidence — not a black box.","Sources, assumptions, domains, limits, tests, hashes and fallback decisions remain visible.",[("231","AMD core snapshot",GREEN),("4 rocks","paper inputs",BLUE),("137.09×","FP64 platform",ORANGE)],["This is a screening demonstration, not field or regulatory validation.","The PHREEQC bridge remains PROCESS-QUALIFIED ONLY; hosted video and official PR remain human-gated."])
    print(out)
if __name__=="__main__": main()

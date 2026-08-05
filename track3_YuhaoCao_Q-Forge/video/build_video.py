#!/usr/bin/env python3
"""Build the 15-scene Q-Forge submission video from reproducible SVG scenes."""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import subprocess
from pathlib import Path

from manuscript import load_finalized_narration

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "video"
WORK = VIDEO / "work_v2"
W, H = 1920, 1080

BG = "#07111f"
PANEL = "#101f32"
PANEL2 = "#142943"
WHITE = "#f4f8ff"
MUTED = "#9fb2c9"
BLUE = "#36a7ff"
GREEN = "#43e6a1"
PURPLE = "#a98bff"
ORANGE = "#ffb454"
RED = "#ff657a"
CORAL = "#ff5f6d"
ASSET = ROOT / "assets" / "generated-v2"


def esc(s: str) -> str:
    return html.escape(s)


def text(x, y, s, size=34, color=WHITE, weight=400, anchor="start", opacity=1):
    return f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" opacity="{opacity}">{esc(s)}</text>'


def rect(x, y, w, h, fill=PANEL, r=22, stroke="none", sw=1, opacity=1):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" opacity="{opacity}"/>'


def raster(path: Path, x, y, w, h, opacity=1, preserve="xMidYMid slice"):
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<image href="data:image/png;base64,{payload}" x="{x}" y="{y}" width="{w}" height="{h}" preserveAspectRatio="{preserve}" opacity="{opacity}"/>'


def line(x1, y1, x2, y2, color=BLUE, sw=4, dash=""):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}" stroke-linecap="round"{d}/>'


def pill(x, y, s, color=BLUE, width=None):
    width = width or max(120, len(s) * 17 + 42)
    return rect(x, y, width, 48, color, 24, opacity=.14) + text(x + width/2, y + 33, s, 22, color, 700, "middle")


def card(x, y, w, h, title, lines, accent=BLUE, big=None):
    out = rect(x, y, w, h, "#111b31", 24, "none", 0, .86)
    out += rect(x, y, 5, h, accent, 3)
    out += text(x+32, y+48, title, 29, accent, 700)
    yy = y+96
    if big:
        out += text(x+32, yy+28, big, 54, WHITE, 700)
        yy += 78
    for s in lines:
        out += text(x+32, yy, s, 25, MUTED, 400)
        yy += 39
    return out


def base_svg(index, title, kicker="Q-FORGE · PHYSICAL AI"):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="DejaVu Sans, sans-serif">',
            '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#081225"/><stop offset=".56" stop-color="#11162b"/><stop offset="1" stop-color="#311526"/></linearGradient><linearGradient id="veil" x1="0" x2="1"><stop stop-color="#080f20" stop-opacity=".98"/><stop offset=".58" stop-color="#080f20" stop-opacity=".35"/><stop offset="1" stop-color="#080f20" stop-opacity=".08"/></linearGradient><filter id="glow"><feGaussianBlur stdDeviation="8" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>',
            rect(0,0,W,H,'url(#bg)',0),
            f'<circle cx="1650" cy="90" r="390" fill="#7e263f" opacity=".13" filter="url(#glow)"/>',
            text(92, 70, kicker, 18, "#8795b4", 600), text(1828, 70, f'{index:02d} / 15', 18, "#6f7c99", 500, 'end'),
            text(92, 143, title, 43, WHITE, 600)]


def finish(a):
    a += [text(92, 1034, 'CAO YUHAO  ·  AMD RADEON HACKATHON  ·  TRACK 3 PHYSICAL AI', 16, "#71809e", 500), '</svg>']
    return ''.join(a)


def scene(i):
    titles = [
        "Learning from a VLA Policy's Own Experience",
        "VLA policies learn from demonstrations—but deployment produces experience",
        "Why off-policy value learning?",
        "From multimodal observation to value-improved action",
        "An action-sensitive Q ensemble",
        "Turn closed-loop experience into local value supervision",
        "Three Q-learning strategies for SmolVLA",
        "One protocol, four policy-improvement paths",
        "Same reset. Same seed. Different outcome.",
        "Action-direction improvement outperforms candidate selection",
        "Same method ranking on a second LIBERO task",
        "Built and profiled on AMD Radeon PRO",
        "10.1% lower policy latency without retraining",
        "Judging Criteria Alignment",
        "Value learning for flow-matching Physical AI",
    ]
    a = base_svg(i, titles[i-1])
    if i == 1:
        a = base_svg(i, '', '')
        a += [raster(ASSET/'robot-hero-v2.png',0,0,W,H,.82),rect(0,0,W,H,'url(#veil)',0),
              text(105,305,'Q-Forge',118,WHITE,700),
              text(112,376,"Learning from a VLA Policy's Own Experience",35,"#b5c0d9",400),
              text(112,425,'Three Q-learning paths for flow-matching SmolVLA',31,"#b5c0d9",400),
              rect(108,560,720,168,"#351e2d",25,CORAL,3,.78),
              text(160,635,'42%',55,WHITE,700),text(322,635,'→',48,CORAL,600),text(435,635,'68%',55,CORAL,700),
              text(160,687,'Q-guidance · paired closed-loop · no policy retraining',22,"#b5c0d9",400),
              text(112,940,'CAO YUHAO  ·  TRACK 3 PHYSICAL AI',20,"#8592b0",500)]
    elif i == 2:
        xs=[110,520,930,1340]; labels=['Expert demos','SFT','Base SmolVLA','Success + failure']; colors=[PURPLE,BLUE,BLUE,GREEN]
        for x,l,c in zip(xs,labels,colors): a += [rect(x,380,330,150,PANEL,22,c,2),text(x+165,470,l,28,c,700,'middle')]
        for x in [440,850,1260]: a += [line(x,455,x+70,455,MUTED,6),text(x+35,443,'›',42,MUTED,700,'middle')]
        a += [rect(1250,600,520,126,RED,20,opacity=.11),text(1510,653,'UNUSED BY IMITATION',24,RED,700,'middle'),text(1510,692,'deployment experience',24,MUTED,400,'middle'),
              text(960,825,'Task success and failure become supervision.',38,WHITE,700,'middle')]
    elif i == 3:
        a += [card(92,270,800,510,'ON-POLICY POLICY GRADIENT',['Fresh rollouts','Expensive interaction','Approximate denoising likelihood'],RED),
              card(1028,270,800,510,'OFF-POLICY VALUE LEARNING',['Reuse historical replay','Learn from success and failure','No explicit action likelihood','First-order direction  ∇A Q(s,A)'],GREEN),
              text(960,870,'Learn value from replay. Use value to improve the flow policy.',34,WHITE,700,'middle')]
    elif i == 4:
        a += [raster(ASSET/'smolvla-flow-architecture-v2.png',70,195,1780,735,.92),
              pill(105,220,'RGB OBSERVATIONS',BLUE,250),pill(105,715,'LANGUAGE + PROPRIO',PURPLE,300),
              pill(625,475,'FROZEN SMOLVLM PREFIX',PURPLE,330),pill(1045,310,'FLOW ACTION EXPERT',CORAL,290),
              pill(1455,510,'CLEAN 5 × 7 CHUNK',GREEN,300),
              text(116,870,'Q-Forge surrounds the frozen flow policy with replay, value learning and three improvement paths.',24,"#c2cbe0",500)]
    elif i == 5:
        a += [raster(ASSET/'q-critic-ensemble-v2.png',70,195,1780,720,.95),
              pill(95,225,'512D COMPACT STATE',PURPLE,275),pill(95,410,'8D PROPRIO',BLUE,190),pill(95,695,'5 × 7 ACTION CHUNK',CORAL,270),
              pill(690,465,'SHARED ACTION-SENSITIVE ENCODER',CORAL,430),
              pill(1240,245,'5 INDEPENDENT Q NETWORKS',PURPLE,370),
              text(1510,470,'MEAN',20,GREEN,700),text(1510,645,'CONSERVATIVE MIN',20,GREEN,700),text(1510,815,'DISAGREEMENT',20,ORANGE,700),
              rect(550,842,820,66,"#291d2c",18,CORAL,2,.82),text(960,884,'MC ranking  →  H-step TD  →  Cal-QL  →  validation gate',22,"#d5dbea",500,'middle')]
    elif i == 6:
        a += [raster(ASSET/'perturb-chunk-v2.png',70,190,1780,745,.95),
              pill(92,225,'ONE RESET STATE',BLUE,225),pill(480,275,'6 CLOSED-LOOP PERTURBATIONS',ORANGE,390),
              pill(1430,230,'SUCCESS',GREEN,165),pill(1430,650,'FAILURE',CORAL,165),
              rect(102,842,1715,78,"#10182d",18,"none",0,.88),
              text(145,891,'300 episodes',23,WHITE,600),text(435,891,'60,505 transitions',23,WHITE,600),text(790,891,'36 mixed-outcome states',23,WHITE,600),text(1235,891,'sliding action chunk  H = 5',23,GREEN,600)]
    elif i == 7:
        a += [card(92,260,520,530,'Q SELECTION · CHOOSE',['Sample N=4 · score · choose','Weights frozen','Critic online'],BLUE),
              card(700,260,520,530,'Q GUIDANCE · EDIT',['Bounded projected Q-gradient edit','Weights frozen','Critic online'],GREEN),
              card(1308,260,520,530,'QVGM RESIDUAL · WRITE',['Distill into the velocity field','Offline fine-tune','No deployment critic'],PURPLE)]
    elif i == 8:
        methods=[('BASE',BLUE),('SELECTION N=4',BLUE),('Q GUIDANCE',GREEN),('QVGM RESIDUAL',PURPLE)]
        for j,(lab,c) in enumerate(methods): a += [rect(150+j*430,290,330,120,PANEL,22,c,2),text(315+j*430,362,lab,26,c,700,'middle')]
        a += [rect(180,520,1560,190,PANEL2,28),text(960,580,'FROZEN PAIRED CONDITIONS',25,WHITE,700,'middle'),
              text(960,642,'50 reset states  ·  seed 2001  ·  240 max steps  ·  5 actions / replan',31,MUTED,500,'middle'),
              text(960,810,'Paired transitions + exact McNemar test',36,GREEN,700,'middle')]
    elif i == 9:
        a += [rect(92,220,836,650,'#05080d',24,BLUE,3),rect(992,220,836,650,'#05080d',24,GREEN,3),
              text(510,274,'BASE · FAILURE',28,RED,700,'middle'),text(1410,274,'Q GUIDANCE · SUCCESS',28,GREEN,700,'middle'),
              pill(680,900,'RESET 1 · SEED 2001 · SAME CHECKPOINT',PURPLE,560)]
    elif i == 10:
        vals=[('BASE',42,BLUE,'21 / 50'),('SELECTION',36,MUTED,'18 / 50'),('GUIDANCE',68,GREEN,'34 / 50'),('RESIDUAL',64,PURPLE,'32 / 50')]
        for j,(lab,v,c,n) in enumerate(vals):
            x=170+j*430; bh=v*7.2
            a += [rect(x,820-bh,250,bh,c,18,opacity=.82),text(x+125,785-bh,f'{v}%',38,WHITE,700,'middle'),text(x+125,870,lab,25,c,700,'middle'),text(x+125,910,n,22,MUTED,500,'middle')]
        a += [pill(1120,225,'+13 STATES · +26 PP',GREEN,350),pill(1500,225,'p = 0.0146',ORANGE,230)]
    elif i == 11:
        a += [text(505,250,'TASK 7 · PRIMARY',25,MUTED,700,'middle'),text(1395,250,'TASK 3 · DIAGNOSTIC',25,MUTED,700,'middle')]
        names=[('Base',42,76,BLUE),('Selection',36,70,MUTED),('Guidance',68,88,GREEN),('Residual',64,86,PURPLE)]
        for j,(n,v1,v2,c) in enumerate(names):
            y=315+j*130;a += [text(150,y+34,n.upper(),22,c,700),rect(390,y,470,56,'#1a314b',16),rect(390,y,v1/100*470,56,c,16,opacity=.8),text(880,y+38,f'{v1}%',25,WHITE,700),rect(1280,y,470,56,'#1a314b',16),rect(1280,y,v2/100*470,56,c,16,opacity=.8),text(1770,y+38,f'{v2}%',25,WHITE,700)]
        a += [pill(610,850,'TASK 3 GUIDANCE · +6 · 0 REGRESSIONS · p = 0.03125',GREEN,700),
              text(960,940,'Diagnostic: held-out TD loss 0.0121 exceeded the 0.01 gate; conservative preset used.',21,ORANGE,600,'middle')]
    elif i == 12:
        a += [pill(92,220,'Radeon PRO W7000 Series · 48 GiB',BLUE,470),pill(590,220,'gfx1100 · 96 CUs · PyTorch 2.8 + ROCm',PURPLE,560)]
        charts=[('FORWARD','CK up to 5.25×',.92,.32,GREEN),('BACKWARD','SDPA faster',.48,.82,BLUE),('FWD + BWD','SDPA faster',.52,.86,ORANGE)]
        for j,(name,note,ck,sd,c) in enumerate(charts):
            x=92+j*585;a += [rect(x,330,520,470,PANEL,24,'#24405f',2),text(x+34,380,name,27,WHITE,700),text(x+34,425,note,23,c,700),text(x+60,735,'CK',22,MUTED,700),text(x+265,735,'SDPA',22,MUTED,700),rect(x+65,700-270*ck,110,270*ck,GREEN,14),rect(x+270,700-270*sd,110,270*sd,BLUE,14)]
        a += [text(960,890,'Choose the backend for the workload—not the headline.',31,WHITE,700,'middle')]
    elif i == 13:
        a += [card(92,270,580,360,'BASELINE',['Policy inference only','Simulator time excluded'],BLUE,'321.8 ms'),text(760,470,'→',72,MUTED,700,'middle'),
              card(870,270,580,360,'OPTIMIZED',['No retraining','Maximum Δ action: 9.3e−4'],GREEN,'289.3 ms'),
              card(1530,270,298,360,'GAIN',['1.112× speedup','Upstream-ready'],PURPLE,'−10.1%'),
              text(960,760,'Fused SDPA  ·  inference mode  ·  fixed denoising loop  ·  language/layer caches  ·  lightweight output',25,MUTED,500,'middle'),
              pill(650,830,'REPRODUCIBLE BENCHMARK + ROLLBACK SWITCHES',ORANGE,620)]
    elif i == 14:
        rows=[('Robot capability',30,'Task 7: 42% → 68% · Task 3: 76% → 88% diagnostic',GREEN),('AMD Radeon / ROCm',20,'W7000 Series + ROCm · profiling · −10.1% latency',BLUE),('Innovation',20,'selection · guidance · velocity residual',PURPLE),('Real-world value',20,'reuse failed rollouts · no new expert labels',ORANGE),('Upstream open source',10,'upstream-ready LeRobot patches + benchmarks',MUTED)]
        y=235
        for name,pts,evidence,c in rows:
            a += [rect(92,y,1736,116,PANEL,18,'#24405f',1),text(135,y+69,name,27,WHITE,700),pill(545,y+34,f'{pts} PTS',c,125),text(730,y+69,evidence,26,MUTED,500)];y+=136
        a += [pill(1300,900,'100-POINT RUBRIC · EVIDENCE MAP',GREEN,528)]
    elif i == 15:
        a += [text(92,275,'Q-FORGE',92,WHITE,800),text(96,335,'Value learning for flow-matching Physical AI',32,MUTED,500),
              card(92,430,520,270,'THREE PATHS',['Selection · Guidance · Residual','Guidance best · residual critic-free'],BLUE),
              card(700,430,520,270,'BEST RESULT',['Q guidance · no retraining','Exact McNemar p = 0.0146'],GREEN,'68%'),
              card(1308,430,520,270,'AMD DEPLOYMENT',['Radeon PRO W7000 Series','ROCm policy latency reduction'],PURPLE,'−10.1%'),
              text(92,810,'Project / Team',22,MUTED,700),text(92,855,'Q-Forge · Cao Yuhao',31,WHITE,700),text(1828,810,'GitHub',22,MUTED,700,'end'),text(1828,855,'ZorAttC',31,WHITE,700,'end')]
    return finish(a)


def run(cmd):
    subprocess.run(cmd, check=True)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--audio',type=Path,default=VIDEO/'voiceover.mp3');ap.add_argument('--output',type=Path,default=VIDEO/'Q-Forge-demo.mp4');args=ap.parse_args()
    narration_path=VIDEO/'narration.txt'
    narration,paragraphs=load_finalized_narration(narration_path)
    WORK.mkdir(parents=True,exist_ok=True)
    alignment_path=WORK/'voice_alignment.json'
    if not alignment_path.exists():
        raise ValueError('Final build requires character alignment generated from the finalized 15-page narration')
    if not args.audio.exists():
        raise FileNotFoundError(f'Voiceover not found: {args.audio}')
    payload=json.loads(alignment_path.read_text(encoding='utf-8'))
    expected_narration_hash=hashlib.sha256(narration.encode()).hexdigest()
    expected_audio_hash=hashlib.sha256(args.audio.read_bytes()).hexdigest()
    if (
        payload.get('paragraph_count') != 15
        or payload.get('narration_sha256') != expected_narration_hash
        or payload.get('audio_sha256') != expected_audio_hash
    ):
        raise ValueError('Voiceover or alignment does not match the finalized 15-page narration; regenerate both before building slides')
    for i in range(1,16):
        svg=WORK/f'{i:02d}.svg';png=WORK/f'{i:02d}.png';svg.write_text(scene(i),encoding='utf-8')
        run(['ffmpeg','-y','-loglevel','error','-i',str(svg),'-frames:v','1',str(png)])
    duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(args.audio)]))
    # Each narration paragraph maps to one semantic scene. Derive boundaries
    # from ElevenLabs timestamps so page changes follow the finalized script.
    al=payload.get('alignment') or payload['normalized_alignment']
    aligned=''.join(al['characters'])
    ends=al['character_end_times_seconds']
    raw_duration=ends[-1]
    time_scale=duration/raw_duration
    paragraph_ends=[];cursor=0
    for paragraph in paragraphs:
        idx=aligned.find(paragraph,cursor)
        if idx < 0: raise ValueError(f'Paragraph not found in alignment: {paragraph[:60]}')
        cursor=idx+len(paragraph)
        paragraph_ends.append(ends[cursor-1]*time_scale)
    boundaries=[0.0,*paragraph_ends]
    durations=[boundaries[n+1]-boundaries[n] for n in range(15)]
    clips=[]
    for i,d in enumerate(durations,1):
        out=WORK/f'{i:02d}.mp4';clips.append(out)
        if i==9:
            base=VIDEO/'raw/base_state1/smolvla_task7_episode1.mp4';guide=VIDEO/'raw/guidance_state1/smolvla_task7_episode1.mp4'
            fc=(f'[0:v]scale=820:540:force_original_aspect_ratio=decrease,pad=820:540:(ow-iw)/2:(oh-ih)/2:black,setpts=PTS-STARTPTS,setpts={d/12.05}*PTS[b];'
                f'[1:v]scale=820:540:force_original_aspect_ratio=decrease,pad=820:540:(ow-iw)/2:(oh-ih)/2:black,setpts=PTS-STARTPTS,setpts={d/12.05}*PTS[g];'
                f'[2:v]scale=1920:1080[bg];[bg][b]overlay=100:300[tmp];[tmp][g]overlay=1000:300[v]')
            run(['ffmpeg','-y','-loglevel','error','-i',str(base),'-i',str(guide),'-loop','1','-i',str(WORK/'09.png'),'-filter_complex',fc,'-map','[v]','-t',f'{d:.3f}','-r','30','-c:v','libx264','-pix_fmt','yuv420p',str(out)])
        else:
            run(['ffmpeg','-y','-loglevel','error','-loop','1','-i',str(WORK/f'{i:02d}.png'),'-t',f'{d:.3f}','-r','30','-vf','fade=t=in:st=0:d=0.3,fade=t=out:st='+f'{max(0,d-.3):.3f}'+':d=0.3','-c:v','libx264','-pix_fmt','yuv420p',str(out)])
    concat=WORK/'concat.txt';concat.write_text(''.join(f"file '{p}'\n" for p in clips),encoding='utf-8')
    visuals=WORK/'visuals.mp4';run(['ffmpeg','-y','-loglevel','error','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(visuals)])
    style="FontName=DejaVu Sans,FontSize=11,PrimaryColour=&H00FFFFFF,OutlineColour=&HCC000000,BackColour=&H00000000,BorderStyle=1,Outline=1.2,Shadow=0,Alignment=2,MarginV=24"
    vf=f"subtitles={VIDEO/'subtitles.srt'}:force_style='{style}'"
    run(['ffmpeg','-y','-loglevel','error','-i',str(visuals),'-i',str(args.audio),'-vf',vf,'-map','0:v','-map','1:a','-c:v','libx264','-preset','medium','-crf','18','-c:a','aac','-b:a','192k','-shortest','-movflags','+faststart',str(args.output)])
    (WORK/'build_metadata.json').write_text(json.dumps({'duration':duration,'scene_durations':durations},indent=2)+'\n')

if __name__=='__main__': main()

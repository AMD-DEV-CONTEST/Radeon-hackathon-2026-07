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

BG = "#F5F7FA"
PANEL = "#FFFFFF"
PANEL2 = "#EAF0F6"
WHITE = "#172033"
MUTED = "#5D6978"
BLUE = "#2D6EA8"
GREEN = "#168568"
PURPLE = "#6B5CA5"
ORANGE = "#B9751A"
RED = "#C23B4B"
CORAL = RED
BORDER = "#CBD5DF"
ASSET = ROOT / "assets" / "generated-v3"


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


def arrow(x1, y1, x2, y2, color=MUTED, sw=3):
    return (
        line(x1, y1, x2 - 14, y2, color, sw)
        + f'<path d="M {x2-16} {y2-9} L {x2} {y2} L {x2-16} {y2+9} Z" fill="{color}"/>'
    )


def down_arrow(x, y1, y2, color=MUTED, sw=3):
    return (
        line(x, y1, x, y2 - 14, color, sw)
        + f'<path d="M {x-9} {y2-16} L {x} {y2} L {x+9} {y2-16} Z" fill="{color}"/>'
    )


def pill(x, y, s, color=BLUE, width=None):
    width = width or max(120, len(s) * 17 + 42)
    return rect(x, y, width, 48, color, 10, opacity=.10) + text(x + width/2, y + 33, s, 22, color, 700, "middle")


def card(x, y, w, h, title, lines, accent=BLUE, big=None):
    out = rect(x, y, w, h, PANEL, 12, BORDER, 2)
    out += rect(x, y, 6, h, accent, 3)
    out += text(x+32, y+48, title, 29, accent, 700)
    yy = y+96
    if big:
        out += text(x+32, yy+28, big, 54, WHITE, 700)
        yy += 78
    for s in lines:
        out += text(x+32, yy, s, 25, MUTED, 400)
        yy += 39
    return out


def node(x, y, w, h, title, subtitle="", accent=BLUE, title_size=27):
    out = rect(x, y, w, h, PANEL, 10, BORDER, 2)
    out += rect(x, y, 6, h, accent, 3)
    out += text(x + 26, y + 45, title, title_size, WHITE, 700)
    if subtitle:
        out += text(x + 26, y + 82, subtitle, 21, MUTED, 400)
    return out


def emphasis_row(x, y, w, title, detail, color, symbol):
    return (
        rect(x, y, w, 112, "#F8FAFC", 8, BORDER, 1)
        + rect(x + 18, y + 22, 48, 48, color, 24, opacity=.12)
        + text(x + 42, y + 56, symbol, 27, color, 800, "middle")
        + text(x + 86, y + 43, title, 27, WHITE, 750)
        + text(x + 86, y + 78, detail, 21, MUTED, 400)
    )


def base_svg(index, title, kicker="Q-FORGE · PHYSICAL AI"):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="DejaVu Sans, sans-serif">',
            '<defs><linearGradient id="veil" x1="0" x2="1"><stop stop-color="#0A1726" stop-opacity=".96"/><stop offset=".55" stop-color="#0A1726" stop-opacity=".62"/><stop offset="1" stop-color="#0A1726" stop-opacity=".04"/></linearGradient></defs>',
            rect(0,0,W,H,BG,0),
            rect(0,0,W,10,BLUE,0),
            text(92, 58, kicker, 17, "#6B7785", 700), text(1828, 58, f'{index:02d} / 15', 17, "#7C8795", 500, 'end'),
            text(92, 126, title, 41, WHITE, 650),
            line(92, 158, 1828, 158, BORDER, 2)]


def finish(a):
    a += [line(92, 1005, 1828, 1005, BORDER, 1),
          text(92, 1038, 'CAO YUHAO  ·  AMD RADEON HACKATHON  ·  TRACK 3 PHYSICAL AI', 16, "#75808D", 500), '</svg>']
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
        "Two tasks. Same paired improvement.",
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
        a += [raster(ASSET/'robot-hero-v3.png',0,0,W,H,.98),rect(0,0,W,H,'url(#veil)',0),
              text(105,292,'Q-Forge',112,"#FFFFFF",700),
              text(112,365,"Learning from a VLA Policy's Own Experience",34,"#E8EEF5",400),
              text(112,414,'Three Q-learning paths for flow-matching SmolVLA',29,"#CFD9E4",400),
              rect(108,540,700,150,"#0B1827",12,"#8EA0B3",1,.84),
              text(154,610,'42%',52,"#FFFFFF",700),text(306,610,'→',42,"#D7E0E9",600),text(398,610,'68%',52,"#7EE0BD",700),
              text(154,657,'Q-guidance · paired closed-loop · no policy retraining',21,"#D8E1EA",400),
              text(112,965,'CAO YUHAO  ·  AMD RADEON HACKATHON  ·  TRACK 3 PHYSICAL AI',18,"#D8E1EA",500)]
    elif i == 2:
        a += [
            text(92,205,'SUPERVISED TRAINING',18,MUTED,700),
            node(92,250,330,120,'Expert demonstrations','20 labeled episodes',PURPLE,23),
            arrow(422,310,470,310),
            node(470,250,330,120,'Supervised fine-tuning','imitation objective',BLUE,23),
            arrow(800,310,848,310),
            node(848,250,330,120,'Base SmolVLA','frozen deployment policy',BLUE,23),
            arrow(1178,310,1226,310),
            node(1226,250,500,120,'Closed-loop deployment','new interaction experience',GREEN,23),
            down_arrow(1476,370,485,GREEN,3),
            node(1226,485,500,120,'Success + failure rollouts','task outcomes label behavior',GREEN,23),
            down_arrow(1476,605,710,RED,3),
            rect(1226,710,500,110,"#FCEDEF",10,RED,2),
            text(1476,755,'UNUSED BY IMITATION',24,RED,800,'middle'),
            text(1476,792,'deployment experience is discarded',20,MUTED,400,'middle'),
            rect(92,515,860,250,PANEL2,12,BORDER,1),
            text(130,570,'THE OPPORTUNITY',20,BLUE,800),
            text(130,630,'The policy produces its own supervision signal:',28,WHITE,700),
            text(130,685,'task success, failure, and near-miss outcomes.',28,GREEN,700),
            text(960,885,'Q-Forge learns from deployment outcomes instead of requesting new expert labels.',27,WHITE,650,'middle'),
        ]
    elif i == 3:
        a += [
            rect(92,220,820,610,PANEL,12,BORDER,2),
            rect(1008,220,820,610,PANEL,12,BORDER,2),
            text(132,275,'WHY NOT ON-POLICY HERE?',29,RED,800),
            text(1048,275,'WHY OFF-POLICY VALUE FITS',29,GREEN,800),
            emphasis_row(122,315,760,'FRESH ROLLOUTS','every update needs new robot interaction',RED,'−'),
            emphasis_row(122,445,760,'LIKELIHOOD CHALLENGE','flow denoising has no simple action log-prob',RED,'−'),
            emphasis_row(122,575,760,'WEAK REPLAY REUSE','historical failures are underused',RED,'−'),
            emphasis_row(1038,315,760,'REUSE REPLAY','learn from already collected episodes',GREEN,'+'),
            emphasis_row(1038,445,760,'OUTCOME SUPERVISION','success and failure directly train Q',GREEN,'+'),
            emphasis_row(1038,575,760,'ACTION DIRECTION','∇A Q suggests a bounded local correction',GREEN,'+'),
            rect(365,865,1190,74,PANEL2,10,BORDER,1),
            text(960,912,'Learn value from replay  +  obtain a direction in action space',29,WHITE,750,'middle'),
        ]
    elif i == 4:
        a += [
            text(92,205,'POLICY INFERENCE',18,MUTED,700),
            node(92,235,310,105,'Multimodal input','RGB · language · state',BLUE,25),
            arrow(402,287,445,287),
            node(445,235,310,105,'Frozen SmolVLM','multimodal state zₛ',PURPLE,25),
            arrow(755,287,798,287),
            node(798,220,370,135,'Flow Action Expert','iterative velocity prediction',RED,25),
            arrow(1168,287,1210,287),
            node(1210,235,420,105,'Clean action chunk','5 × 7 executable actions',GREEN,25),
            text(92,442,'EXPERIENCE AND VALUE LOOP',18,MUTED,700),
            node(160,475,280,100,'20 demonstrations','few-shot SFT',PURPLE,24),
            arrow(440,525,490,525),
            node(490,475,280,100,'Base policy','frozen checkpoint',BLUE,24),
            arrow(770,525,820,525),
            node(820,475,300,100,'Closed-loop replay','success + failure',ORANGE,24),
            arrow(1120,525,1170,525),
            node(1170,475,300,100,'Offline Q critic','action-value learning',GREEN,24),
            line(1320,575,1320,650,GREEN,3),
            line(585,650,1360,650,GREEN,3),
            down_arrow(585,650,710,BLUE,2),
            down_arrow(960,650,710,GREEN,2),
            down_arrow(1360,650,710,PURPLE,2),
            node(420,710,330,100,'Selection','choose sampled chunks',BLUE,24),
            node(795,710,330,100,'Guidance','edit the Base chunk',GREEN,24),
            node(1170,710,380,100,'Residual distillation','write improvement into policy',PURPLE,24),
            text(960,900,'A frozen flow policy surrounded by replay, value learning, and three improvement paths.',26,WHITE,600,'middle'),
        ]
    elif i == 5:
        a += [
            text(92,205,'INPUTS',18,MUTED,700),
            node(92,235,330,92,'Compact state','512D feature',PURPLE,25),
            node(92,365,330,92,'Proprioception','8D robot state',BLUE,25),
            node(92,495,330,92,'Action chunk','5 × 7 executable actions',RED,25),
            arrow(422,281,550,410),
            arrow(422,411,550,410),
            arrow(422,541,550,410),
            node(550,335,390,150,'Action-sensitive encoder','joint state–action representation',ORANGE),
            text(1065,205,'ENSEMBLE HEADS',18,MUTED,700),
        ]
        for j in range(5):
            y=230+j*105
            a += [arrow(940,410,1055,y+37,BLUE,2),
                  rect(1055,y,235,74,PANEL,8,BORDER,2),
                  text(1172,y+47,f'Q{j+1}(s, A)',24,WHITE,700,'middle'),
                  line(1290,y+37,1345,y+37,GREEN,2)]
        a += [
            line(1345,267,1345,687,GREEN,3),
            arrow(1345,330,1395,330,GREEN,2),
            arrow(1345,450,1395,450,GREEN,2),
            arrow(1345,570,1395,570,GREEN,2),
            node(1395,285,345,90,'Ensemble mean','candidate ranking',GREEN,24),
            node(1395,405,345,90,'Conservative min','bounded guidance',GREEN,24),
            node(1395,525,345,90,'Disagreement','uncertainty diagnostic',ORANGE,24),
            rect(300,820,1320,88,PANEL2,10,BORDER,1),
            text(960,856,'MC outcome ranking  →  H-step TD  →  Cal-QL calibration  →  held-out validation gate',24,WHITE,600,'middle'),
            text(960,890,'The critic must rank outcomes, stay conservative, and provide finite action gradients.',20,MUTED,400,'middle'),
        ]
    elif i == 6:
        a += [
            node(92,280,340,150,'One reset state','fixed task configuration',BLUE,26),
            arrow(432,355,500,355),
            node(500,280,340,150,'Base action','perturb arm dimensions only',ORANGE,26),
            line(840,355,870,355,ORANGE,3),
            line(870,250,870,660,ORANGE,3),
            text(920,205,'EXECUTED ROLLOUTS · SCHEMATIC OUTCOMES',17,MUTED,700),
        ]
        noises=['0.00','0.01','0.03','0.03','0.05','0.05']
        outcomes=[GREEN,RED,GREEN,RED,GREEN,RED]
        labels=['success','failure','success','failure','success','failure']
        for j,(noise,color,label) in enumerate(zip(noises,outcomes,labels)):
            y=250+j*82
            a += [
                text(920,y+10,f'noise {noise}',20,MUTED,600),
                line(870,y,900,y,ORANGE,2),
                line(1050,y,1560,y,color,3),
                f'<circle cx="1560" cy="{y}" r="11" fill="{color}"/>',
                text(1590,y+8,label.upper(),19,color,700),
            ]
        a += [
            rect(92,795,1668,112,PANEL2,10,BORDER,1),
            text(210,845,'300 episodes',25,WHITE,700,'middle'),
            text(580,845,'60,505 transitions',25,WHITE,700,'middle'),
            text(1010,845,'36 mixed-outcome states',25,WHITE,700,'middle'),
            text(1470,845,'sliding chunk H = 5',25,GREEN,700,'middle'),
            text(960,885,'Perturbations are executed in simulation, producing new observations and outcomes.',20,MUTED,400,'middle'),
        ]
    elif i == 7:
        strategy_cards=[
            (92,'Q SELECTION · CHOOSE',ASSET/'strategies/selection-figure.png',
             ['Sample N=4 candidate chunks','Score with ensemble Q','Execute the highest-Q chunk'],BLUE,'FROZEN WEIGHTS · CRITIC ONLINE'),
            (700,'Q GUIDANCE · EDIT',ASSET/'strategies/guidance-figure.png',
             ['Start from the Base chunk','Apply bounded local Q-gradient edits','Keep the policy weights frozen'],GREEN,'FROZEN WEIGHTS · CRITIC ONLINE'),
            (1308,'QVGM RESIDUAL · WRITE',ASSET/'strategies/residual-figure.png',
             ['Build a critic-improved target','Distill into the velocity field','Deploy without the critic'],PURPLE,'OFFLINE FINE-TUNE · CRITIC-FREE'),
        ]
        for x,title_name,image_path,lines_,accent,status in strategy_cards:
            a += [rect(x,215,520,660,PANEL,12,BORDER,2),
                  rect(x,215,6,660,accent,3),
                  text(x+28,260,title_name,25,accent,800),
                  raster(image_path,x+20,285,480,305,1,'xMidYMid slice'),
                  line(x+28,615,x+492,615,BORDER,1)]
            for row,line_text in enumerate(lines_):
                a += [text(x+34,660+row*42,'•',22,accent,800),
                      text(x+62,660+row*42,line_text,21,WHITE,500)]
            a += [pill(x+30,805,status,accent,460)]
    elif i == 8:
        methods=[('BASE',BLUE),('SELECTION N=4',BLUE),('Q GUIDANCE',GREEN),('QVGM RESIDUAL',PURPLE)]
        for j,(lab,c) in enumerate(methods): a += [rect(150+j*430,290,330,120,PANEL,22,c,2),text(315+j*430,362,lab,26,c,700,'middle')]
        a += [rect(180,520,1560,190,PANEL2,28),text(960,580,'FROZEN PAIRED CONDITIONS',25,WHITE,700,'middle'),
              text(960,642,'50 reset states  ·  seed 2001  ·  240 max steps  ·  5 actions / replan',31,MUTED,500,'middle'),
              text(960,810,'Paired transitions + exact McNemar test',36,GREEN,700,'middle')]
    elif i == 9:
        a += [
            text(92,205,'TASK 7 · PAIRED BASE VS Q GUIDANCE · RESET 1 · SEED 2001',20,MUTED,700),
            rect(92,215,836,325,'#05080d',10,BLUE,3),
            rect(992,215,836,325,'#05080d',10,GREEN,3),
            text(510,258,'BASE · FAILURE',24,RED,700,'middle'),
            text(1410,258,'Q GUIDANCE · SUCCESS',24,GREEN,700,'middle'),
            text(92,555,'TASK 3 · PAIRED BASE VS CONSERVATIVE Q GUIDANCE · RESET 14 · SEED 2001',20,MUTED,700),
            rect(92,565,836,325,'#05080d',10,BLUE,3),
            rect(992,565,836,325,'#05080d',10,GREEN,3),
            text(510,598,'BASE · FAILURE',24,RED,700,'middle'),
            text(1410,598,'Q GUIDANCE · SUCCESS',24,GREEN,700,'middle'),
            text(960,920,'Both rows use the same reset, seed, Base checkpoint, and action horizon within each task.',18,GREEN,600,'middle'),
        ]
    elif i == 10:
        vals=[('BASE',42,BLUE,'21 / 50'),('SELECTION',36,MUTED,'18 / 50'),('GUIDANCE',68,GREEN,'34 / 50'),('RESIDUAL',64,PURPLE,'32 / 50')]
        for j,(lab,v,c,n) in enumerate(vals):
            x=170+j*430; bh=v*7.2
            a += [rect(x,820-bh,250,bh,c,18,opacity=.82),text(x+125,785-bh,f'{v}%',38,WHITE,700,'middle'),text(x+125,870,lab,25,c,700,'middle'),text(x+125,910,n,22,MUTED,500,'middle')]
        a += [pill(1120,225,'+13 STATES · +26 PP',GREEN,350),pill(1500,225,'p = 0.0146',ORANGE,230)]
    elif i == 11:
        a += [text(505,250,'TASK 7 · PRIMARY',25,MUTED,700,'middle'),text(1395,250,'TASK 3 · DIAGNOSTIC',25,MUTED,700,'middle')]
        names=[('Base',42,76,BLUE),('Selection',36,70,MUTED),('Guidance',68,88,GREEN),('Residual',64,86,PURPLE)]
        a += [rect(115,550,1735,112,'#E7F5F0',10,GREEN,2),
              pill(285,580,'BEST',GREEN,82),
              pill(1165,580,'BEST',GREEN,82)]
        for j,(n,v1,v2,c) in enumerate(names):
            y=315+j*130
            bar_stroke=GREEN if n=='Guidance' else 'none'
            bar_sw=2 if n=='Guidance' else 1
            bar_opacity=1 if n=='Guidance' else .82
            a += [text(150,y+34,n.upper(),22,c,800 if n=='Guidance' else 700),
                  rect(390,y,470,56,'#DCE3EA',10),
                  rect(390,y,v1/100*470,56,c,10,bar_stroke,bar_sw,bar_opacity),
                  text(880,y+38,f'{v1}%',27 if n=='Guidance' else 25,WHITE,800 if n=='Guidance' else 700),
                  rect(1280,y,470,56,'#DCE3EA',10),
                  rect(1280,y,v2/100*470,56,c,10,bar_stroke,bar_sw,bar_opacity),
                  text(1770,y+38,f'{v2}%',27 if n=='Guidance' else 25,WHITE,800 if n=='Guidance' else 700)]
        a += [pill(610,810,'TASK 3 GUIDANCE · +6 · 0 REGRESSIONS · p = 0.03125',GREEN,700),
              text(960,890,'Diagnostic: held-out TD loss 0.0121 exceeded the 0.01 gate; conservative preset used.',21,ORANGE,600,'middle')]
    elif i == 12:
        a += [pill(92,205,'Radeon PRO W7000 Series · 48 GiB',BLUE,470),
              pill(590,205,'fp16 causal · S = 256–4096 · relative to SDPA',PURPLE,620)]
        phases=[
            ('FORWARD-ONLY','FA-CK BEST',[
                ('FA-CK','2.58–5.25×',GREEN,True),
                ('FA-Triton','0.78–1.43×',PURPLE,False),
                ('SDPA','1.00×',BLUE,False),
            ]),
            ('BACKWARD','SDPA BEST',[
                ('FA-CK','0.50–0.55×',GREEN,False),
                ('FA-Triton','0.31–0.58×',PURPLE,False),
                ('SDPA','1.00×',BLUE,True),
            ]),
            ('FWD + BWD STEP','SDPA BEST',[
                ('FA-CK','0.62–0.81×',GREEN,False),
                ('FA-Triton','0.37–0.73×',PURPLE,False),
                ('SDPA','1.00×',BLUE,True),
            ]),
        ]
        for j,(phase,best,rows) in enumerate(phases):
            x=92+j*585
            a += [rect(x,300,520,500,PANEL,12,BORDER,2),
                  text(x+30,350,phase,27,WHITE,800),
                  pill(x+330,318,best,GREEN if 'CK' in best else BLUE,160)]
            for row,(backend,value,color,is_best) in enumerate(rows):
                y=405+row*112
                if is_best:
                    a += [rect(x+24,y-24,472,90,'#E7F5F0' if color==GREEN else '#E8F1F8',8,color,2)]
                a += [text(x+42,y+10,backend,24,color,800),
                      text(x+475,y+10,value,29,WHITE,800,'end')]
        a += [rect(190,835,1540,92,PANEL2,10,BORDER,1),
              text(960,872,'S=4096 peak memory:  FA-Triton 614 MiB  ·  FA-CK 742 MiB  ·  SDPA 744 MiB',23,WHITE,700,'middle'),
              text(960,905,'CK wins forward-only throughput; SDPA wins training speed; Triton minimizes memory.',20,MUTED,500,'middle')]
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
            a += [rect(92,y,1736,116,PANEL,10,BORDER,1),text(135,y+69,name,27,WHITE,700),pill(545,y+34,f'{pts} PTS',c,125),text(730,y+69,evidence,26,MUTED,500)];y+=136
        a += [pill(1300,865,'100-POINT RUBRIC · EVIDENCE MAP',GREEN,528)]
    elif i == 15:
        a += [text(92,275,'Q-FORGE',92,WHITE,800),text(96,335,'Value learning for flow-matching Physical AI',32,MUTED,500),
              card(92,430,520,270,'THREE PATHS',['Selection · Guidance · Residual','Guidance best · residual critic-free'],BLUE),
              card(700,430,520,270,'BEST RESULT',['Q guidance · no retraining','Exact McNemar p = 0.0146'],GREEN,'68%'),
              card(1308,430,520,270,'AMD DEPLOYMENT',['Radeon PRO W7000 Series','ROCm policy latency reduction'],PURPLE,'−10.1%'),
              text(92,810,'Project / Team',22,MUTED,700),text(92,855,'Q-Forge · Cao Yuhao',31,WHITE,700),text(1828,810,'GitHub',22,MUTED,700,'end'),text(1828,855,'ZorAttC',31,WHITE,700,'end')]
    if i == 1:
        return ''.join(a + ['</svg>'])
    return finish(a)


def run(cmd):
    subprocess.run(cmd, check=True)


def media_duration(path: Path) -> float:
    return float(subprocess.check_output([
        'ffprobe','-v','error','-show_entries','format=duration',
        '-of','default=nw=1:nk=1',str(path)
    ]))


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
            task7_fail=VIDEO/'raw/base_state1_exact/smolvla_task7_episode1.mp4'
            task7_success=VIDEO/'raw/guidance_state1_exact/smolvla_task7_episode1.mp4'
            task3_fail=VIDEO/'raw/task3_base_state14_exact/smolvla_task3_episode14.mp4'
            task3_success=VIDEO/'raw/task3_guidance_state14_exact/smolvla_task3_episode14.mp4'
            paths=[task7_fail,task7_success,task3_fail,task3_success]
            ratios=[d/media_duration(path) for path in paths]
            filters=[]
            for index,ratio in enumerate(ratios):
                filters.append(
                    f'[{index}:v]scale=780:256:force_original_aspect_ratio=decrease,'
                    f'setsar=1,pad=780:256:(ow-iw)/2:(oh-ih)/2:black,'
                    f'setpts=PTS-STARTPTS,setpts={ratio:.9f}*PTS[v{index}]'
                )
            filters += [
                '[4:v]scale=1920:1080[bg]',
                '[bg][v0]overlay=120:265[t0]',
                '[t0][v1]overlay=1020:265[t1]',
                '[t1][v2]overlay=120:615[t2]',
                '[t2][v3]overlay=1020:615[v]',
            ]
            run([
                'ffmpeg','-y','-loglevel','error',
                '-i',str(task7_fail),'-i',str(task7_success),
                '-i',str(task3_fail),'-i',str(task3_success),
                '-loop','1','-i',str(WORK/'09.png'),
                '-filter_complex',';'.join(filters),'-map','[v]',
                '-t',f'{d:.3f}','-r','30','-c:v','libx264','-pix_fmt','yuv420p',str(out)
            ])
        else:
            run(['ffmpeg','-y','-loglevel','error','-loop','1','-i',str(WORK/f'{i:02d}.png'),'-t',f'{d:.3f}','-r','30','-vf','fade=t=in:st=0:d=0.3,fade=t=out:st='+f'{max(0,d-.3):.3f}'+':d=0.3','-c:v','libx264','-pix_fmt','yuv420p',str(out)])
    concat=WORK/'concat.txt';concat.write_text(''.join(f"file '{p}'\n" for p in clips),encoding='utf-8')
    visuals=WORK/'visuals.mp4';run(['ffmpeg','-y','-loglevel','error','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(visuals)])
    style="FontName=DejaVu Sans,FontSize=11,PrimaryColour=&H00332217,OutlineColour=&H00FFFFFF,BackColour=&HFF000000,BorderStyle=1,Outline=1.2,Shadow=0,Alignment=2,MarginV=24"
    vf=f"subtitles={VIDEO/'subtitles.srt'}:force_style='{style}'"
    run(['ffmpeg','-y','-loglevel','error','-i',str(visuals),'-i',str(args.audio),'-vf',vf,'-map','0:v','-map','1:a','-c:v','libx264','-preset','medium','-crf','18','-c:a','aac','-b:a','192k','-shortest','-movflags','+faststart',str(args.output)])
    (WORK/'build_metadata.json').write_text(json.dumps({'duration':duration,'scene_durations':durations},indent=2)+'\n')

if __name__=='__main__': main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MoonRabbits Season 1《白色 · 德化白瓷》20 集成片包批量生成器。
纯增量文件：只 import moonrabbits_agents 复用本地 Ollama 链路（qwen2.5:14b），
不碰 app.py / cloudflared / vLLM 进程与配置，不写任何 key。
每集输出 EP??.md：①集标题 ②60秒旁白稿 ③3镜头分镜 ④即梦提示词(中英) ⑤字幕文本。
batch_log.txt 记录每集耗时与 token 数。
"""
import json, re, sys, time, traceback
from pathlib import Path
import urllib.request

BASE = Path("/workspace/persistent/moonrabbits")
sys.path.insert(0, str(BASE))
import moonrabbits_agents as ma  # 复用 retrieve / kb_block / OLLAMA / LLM

OUT = BASE / "episodes" / "season1"
OUT.mkdir(parents=True, exist_ok=True)
LOGF = OUT / "batch_log.txt"

def log(msg):
    line = "[%s] %s" % (time.strftime("%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOGF, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def chat_t(system, user, temperature=0.5):
    """带 token 统计的 chat：返回 (文本, prompt_tokens, eval_tokens)。"""
    req = urllib.request.Request(
        ma.OLLAMA + "/api/generate",
        data=json.dumps({"model": ma.LLM, "system": system, "prompt": user,
                         "stream": False,
                         "options": {"temperature": temperature}}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        res = json.loads(r.read())
    return (res.get("response", "").strip(),
            res.get("prompt_eval_count", 0), res.get("eval_count", 0))

DEFAULT_NAMES = ["月白", "象牙白", "甜白", "卵白", "猪油白", "乳白", "霜白", "雪白",
                 "鱼肚白", "羊脂白", "素白", "银白", "莹白", "润白", "粉白",
                 "米白", "玉白", "云白", "藕丝白", "珍珠白"]

def season1_names():
    """让考据官基于知识库给 20 个白色相色级命名；失败则用兜底清单。"""
    try:
        hits = ma.retrieve("白瓷 白色 釉色 色级 名称 月白 象牙白 甜白 卵白")
        kb = ma.kb_block(hits)
        sys_p = ("你是 MoonRabbits 的考据官。为纪录片第一季《白色 · 德化白瓷》选出 20 个"
                 "白色相的色级名称作为 20 集主题（如 月白/象牙白/甜白/卵白/猪油白 等）。"
                 "优先使用知识库条目中出现过的名称，不足时补陶瓷史公认的白色雅称。"
                 "只输出 JSON 数组（20 个字符串），不要任何解释。")
        txt, pt, et = chat_t(sys_p, "知识库条目：\n%s\n\n请给出 20 个色级名称的 JSON 数组。" % kb,
                             temperature=0.3)
        m = re.search(r"\[.*\]", txt, re.S)
        names = [str(x).strip() for x in json.loads(m.group(0)) if str(x).strip()]
        if len(names) >= 20:
            log("色级命名来自考据官(知识库): %s" % "、".join(names[:20]))
            return names[:20], pt + et
        log("考据官命名不足 20 个(%d)，用兜底清单" % len(names))
    except Exception as e:
        log("色级命名失败(%r)，用兜底清单" % e)
    return DEFAULT_NAMES, 0

def make_subtitles(vo_text):
    """把旁白按句切分并均摊 60 秒时间轴，生成字幕文本。"""
    clean = re.sub(r"\[[^\]]*\]", "", vo_text)  # 字幕里去掉 [KB-id]
    parts = [p.strip() for p in re.split(r"(?<=[。！？!?])", clean) if p.strip()]
    if not parts:
        parts = [clean]
    per = 60.0 / len(parts)
    lines = []
    for i, p in enumerate(parts):
        t0, t1 = i * per, (i + 1) * per
        lines.append("%02d  [%05.1fs-%05.1fs]  %s" % (i + 1, t0, t1, p))
    return "\n".join(lines)

def make_episode(idx, name):
    t_start = time.time()
    tokens = 0
    hits = ma.retrieve("%s 白瓷 釉色 德化 白色" % name)
    kb = ma.kb_block(hits)

    # 1) 考据事实（带 [KB-id] 引用）
    sys_h = ("你是 MoonRabbits 的考据官（Historian）。铁律：每个事实句句尾必须挂知识库条目编号，"
             "格式 [编号]。没有依据的内容标注（暂无文献支撑，仅为推测）。用中文，不超过 300 字。")
    facts, pt, et = chat_t(sys_h,
        "知识库条目：\n%s\n\n主题：白色相「%s」。请给出该色级/釉色与白瓷（重点德化白瓷）相关的"
        "核心事实 5-8 条，涵盖年代、窑口、工艺、审美。" % (kb, name), temperature=0.2)
    tokens += pt + et

    # 2) 集标题 + 60 秒旁白稿
    sys_v = ("你是纪录片旁白撰稿人。第一行输出「集标题：」（12 字以内，含色级名，有诗意），"
             "换行后写 60 秒中文旁白稿（220-260 字），口吻温暖克制、以小见大，"
             "事实以给定考据为准并保留 [编号] 引用，不编造新事实。")
    vo_raw, pt, et = chat_t(sys_v, "色级：%s\n考据事实：\n%s" % (name, facts), temperature=0.6)
    tokens += pt + et
    m = re.search(r"集标题[：:]\s*(.+)", vo_raw)
    title = m.group(1).strip() if m else "「%s」的白色往事" % name
    vo = vo_raw[m.end():].strip() if m else vo_raw

    # 3) 3 镜头分镜 + 即梦提示词（中英）
    sys_s = ("你是纪录片分镜师兼 AI 绘图提示词专家。根据旁白写 3 个镜头分镜，每个镜头含："
             "镜头号、建议时长、画面描述、运镜方式。然后为每个镜头写即梦提示词：中文一条、英文一条，"
             "风格统一为：博物馆级陶瓷微距摄影、柔和大面积留白、东方静谧美学、电影感光影。"
             "严格按此格式输出：\n镜头1（约20s）：画面…；运镜…\n即梦中文1：…\nJimeng EN 1: …\n"
             "镜头2（约20s）：…\n即梦中文2：…\nJimeng EN 2: …\n镜头3（约20s）：…\n即梦中文3：…\nJimeng EN 3: …")
    sb, pt, et = chat_t(sys_s, "色级：%s\n旁白：\n%s" % (name, vo), temperature=0.6)
    tokens += pt + et

    # 4) 字幕（程序化切分，不烧 token）
    subs = make_subtitles(vo)

    ep = "EP%02d" % idx
    md = ("# %s · %s\n\n> Season 1《白色 · 德化白瓷》  |  色级：%s  |  本地链路 qwen2.5:14b 生成\n\n"
          "## ① 集标题\n%s\n\n## ② 60 秒旁白稿（中文）\n%s\n\n## ③ 3 镜头分镜 + ④ 即梦提示词（中英）\n%s\n\n"
          "## ⑤ 字幕文本\n```\n%s\n```\n" % (ep, name, name, title, vo, sb, subs))
    (OUT / (ep + ".md")).write_text(md, encoding="utf-8")
    return time.time() - t_start, tokens

def main():
    log("===== Season1 batch start =====")
    names, tk = season1_names()
    ok = 0
    t_all = time.time()
    for i, name in enumerate(names, 1):
        ep = "EP%02d" % i
        if (OUT / (ep + ".md")).exists():
            log("%s %s 已存在，跳过" % (ep, name))
            ok += 1
            continue
        try:
            dt, tk_ep = make_episode(i, name)
            ok += 1
            log("%s「%s」SUCCESS  %.1fs  tokens=%d" % (ep, name, dt, tk_ep))
        except Exception as e:
            log("%s「%s」FAIL  %r" % (ep, name, e))
            traceback.print_exc()
    log("===== DONE %d/%d  总耗时 %.1fs =====" % (ok, len(names), time.time() - t_all))

if __name__ == "__main__":
    main()

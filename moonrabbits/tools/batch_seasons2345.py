#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MoonRabbits Season 2-5（青/赤/黄/黑）80 集成片包批量生成器。
纯增量文件：复用本地 Ollama 链路（qwen2.5:14b），不碰任何运行中服务，不写 key。
每季 20 集，输出 episodes/seasonN/EP01.md…EP20.md + 各季 batch_log.txt。
断点续跑：已存在的 EP 文件自动跳过。
"""
import json, re, sys, time, traceback
from pathlib import Path
import urllib.request

BASE = Path("/workspace/persistent/moonrabbits")
sys.path.insert(0, str(BASE))
import moonrabbits_agents as ma

SEASONS = [
    (2, "青 · 青瓷与青花", "青瓷、青花瓷等青色瓷器", "青瓷 青花 青釉 色级 名称 月白 天青 粉青 梅子青"),
    (3, "赤 · 中国红釉", "红釉瓷器（祭红/郎窑红/豇豆红等）", "红釉 祭红 郎窑红 豇豆红 钧红 胭脂红 釉里红"),
    (4, "黄 · 帝王黄釉", "黄釉与黄彩瓷器（娇黄/鸡油黄等）", "黄釉 娇黄 鸡油黄 米黄 鳝鱼黄 茶叶末 黄彩"),
    (5, "黑 · 玄色黑釉", "黑釉瓷器（乌金釉/建盏/黑定等）", "黑釉 乌金 建盏 兔毫 油滴 黑定 天目"),
]

def chat_t(system, user, temperature=0.5):
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

def make_logger(logf):
    def log(msg):
        line = "[%s] %s" % (time.strftime("%m-%d %H:%M:%S"), msg)
        print(line, flush=True)
        with open(logf, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return log

def season_names(focus, name_query, log):
    """考据官基于知识库为当季取 20 个色级名。"""
    try:
        hits = ma.retrieve(name_query)
        kb = ma.kb_block(hits)
        sys_p = ("你是 MoonRabbits 的考据官。为纪录片一季选出 20 个与「%s」相关的色级/釉色名称"
                 "作为 20 集主题。优先使用知识库条目中出现过的名称，不足时补陶瓷史公认的雅称。"
                 "只输出 JSON 数组（20 个字符串），不要任何解释。" % focus)
        txt, pt, et = chat_t(sys_p, "知识库条目：\n%s\n\n请给出 20 个名称的 JSON 数组。" % kb,
                             temperature=0.3)
        m = re.search(r"\[.*\]", txt, re.S)
        names = [str(x).strip() for x in json.loads(m.group(0)) if str(x).strip()]
        if len(names) >= 20:
            log("色级命名来自考据官(知识库): %s" % "、".join(names[:20]))
            return names[:20]
        log("考据官命名不足 20 个(%d)，跳过本季" % len(names))
    except Exception as e:
        log("色级命名失败(%r)，跳过本季" % e)
    return []

def make_subtitles(vo_text):
    clean = re.sub(r"\[[^\]]*\]", "", vo_text)
    parts = [p.strip() for p in re.split(r"(?<=[。！？!?])", clean) if p.strip()]
    if not parts:
        parts = [clean]
    per = 60.0 / len(parts)
    return "\n".join("%02d  [%05.1fs-%05.1fs]  %s" % (i + 1, i * per, (i + 1) * per, p)
                     for i, p in enumerate(parts))

def make_episode(out_dir, idx, name, season_title, focus):
    t_start = time.time()
    tokens = 0
    hits = ma.retrieve("%s %s 釉色 工艺 历史" % (name, focus))
    kb = ma.kb_block(hits)

    sys_h = ("你是 MoonRabbits 的考据官（Historian）。铁律：每个事实句句尾必须挂知识库条目编号，"
             "格式 [编号]。没有依据的内容标注（暂无文献支撑，仅为推测）。用中文，不超过 300 字。")
    facts, pt, et = chat_t(sys_h,
        "知识库条目：\n%s\n\n主题：色级「%s」。请给出该色级/釉色与%s相关的核心事实 5-8 条，"
        "涵盖年代、窑口、工艺、审美。" % (kb, name, focus), temperature=0.2)
    tokens += pt + et

    sys_v = ("你是纪录片旁白撰稿人。第一行输出「集标题：」（12 字以内，含色级名，有诗意），"
             "换行后写 60 秒中文旁白稿（220-260 字），口吻温暖克制、以小见大，"
             "事实以给定考据为准并保留 [编号] 引用，不编造新事实。")
    vo_raw, pt, et = chat_t(sys_v, "色级：%s\n考据事实：\n%s" % (name, facts), temperature=0.6)
    tokens += pt + et
    m = re.search(r"集标题[：:]\s*(.+)", vo_raw)
    title = m.group(1).strip() if m else "「%s」往事" % name
    vo = vo_raw[m.end():].strip() if m else vo_raw

    sys_s = ("你是纪录片分镜师兼 AI 绘图提示词专家。根据旁白写 3 个镜头分镜，每个镜头含："
             "镜头号、建议时长、画面描述、运镜方式。然后为每个镜头写即梦提示词：中文一条、英文一条，"
             "风格统一为：博物馆级陶瓷微距摄影、柔和大面积留白、东方静谧美学、电影感光影。"
             "严格按此格式输出：\n镜头1（约20s）：画面…；运镜…\n即梦中文1：…\nJimeng EN 1: …\n"
             "镜头2（约20s）：…\n即梦中文2：…\nJimeng EN 2: …\n镜头3（约20s）：…\n即梦中文3：…\nJimeng EN 3: …")
    sb, pt, et = chat_t(sys_s, "色级：%s\n旁白：\n%s" % (name, vo), temperature=0.6)
    tokens += pt + et

    subs = make_subtitles(vo)
    ep = "EP%02d" % idx
    md = ("# %s · %s\n\n> Season《%s》  |  色级：%s  |  本地链路 qwen2.5:14b 生成\n\n"
          "## ① 集标题\n%s\n\n## ② 60 秒旁白稿（中文）\n%s\n\n## ③ 3 镜头分镜 + ④ 即梦提示词（中英）\n%s\n\n"
          "## ⑤ 字幕文本\n```\n%s\n```\n" % (ep, name, season_title, name, title, vo, sb, subs))
    (out_dir / (ep + ".md")).write_text(md, encoding="utf-8")
    return time.time() - t_start, tokens

def main():
    t_all = time.time()
    total_ok = 0
    for sn, title, focus, nq in SEASONS:
        out_dir = BASE / "episodes" / ("season%d" % sn)
        out_dir.mkdir(parents=True, exist_ok=True)
        log = make_logger(out_dir / "batch_log.txt")
        log("===== Season%d《%s》batch start =====" % (sn, title))
        names = season_names(focus, nq, log)
        ok = 0
        for i, name in enumerate(names, 1):
            ep = "EP%02d" % i
            if (out_dir / (ep + ".md")).exists():
                log("%s %s 已存在，跳过" % (ep, name))
                ok += 1
                continue
            try:
                dt, tk = make_episode(out_dir, i, name, title, focus)
                ok += 1
                log("%s「%s」SUCCESS  %.1fs  tokens=%d" % (ep, name, dt, tk))
            except Exception as e:
                log("%s「%s」FAIL  %r" % (ep, name, e))
                traceback.print_exc()
        log("===== Season%d DONE %d/%d =====" % (sn, ok, len(names)))
        total_ok += ok
    print("[%s] ALL SEASONS DONE %d/80  总耗时 %.1fs" %
          (time.strftime("%m-%d %H:%M:%S"), total_ok, time.time() - t_all), flush=True)

if __name__ == "__main__":
    main()

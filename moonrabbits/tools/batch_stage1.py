#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MoonRabbits Stage 1 跑量：900 集成片包批量生成器（名窑/朝代/器型/工艺/纹饰）。
纯增量文件：只 import moonrabbits_agents 复用本地 Ollama 链路（qwen2.5:14b），
不碰 app.py / cloudflared / vLLM / Ollama 进程与配置，不写任何 key。
质量门（自动执行，不等人工）：
  ① 名单自净：考据官出名单后逐主题知识库试检索，命中 <3 条直接换名；
  ② 每集校验：五节结构齐 / 旁白 >=3 个引用角标 / 主题名出现在旁白 / 全文字数 800-1600，
     不过删文件用更严提示词重跑一次，再不过标记 SKIP；
  ③ 每个主题随机留 3 集全文进 qc_samples/。
截止红线：2026-08-06 07:30 (+08) = epoch 1785972600，到点不再开新集，跑完当前集退出。
"""
import json, re, sys, time, random, shutil, traceback
from pathlib import Path
import urllib.request

BASE = Path("/workspace/persistent/moonrabbits")
sys.path.insert(0, str(BASE))
import moonrabbits_agents as ma  # 复用 retrieve / kb_block / OLLAMA / LLM

ROOT = BASE / "episodes" / "stage1"
QC = BASE / "episodes" / "qc_samples"
QC.mkdir(parents=True, exist_ok=True)
DEADLINE = 1785972600  # 2026-08-06 07:30 Asia/Shanghai

# (目录名, 中文大类, 主题数, 每主题集数, 考据官出题提示, 兜底名单)
CATS = [
    ("kilns", "名窑", 10, 20,
     "选出 10 个中国陶瓷史上最重要的瓷窑/窑口作为主题（如 汝窑/官窑/哥窑/钧窑/定窑/德化窑/龙泉窑/磁州窑/建窑/景德镇窑）。",
     ["汝窑", "官窑", "哥窑", "钧窑", "定窑", "德化窑", "龙泉窑", "磁州窑", "建窑", "景德镇窑"]),
    ("dynasties", "朝代", 8, 20,
     "选出 8 个对中国陶瓷影响最深的朝代作为主题（如 唐/宋/元/明/清 等）。",
     ["唐", "五代", "宋", "元", "明永乐", "明成化", "清康熙", "清乾隆"]),
    ("shapes", "器型", 20, 10,
     "选出 20 种经典陶瓷器型作为主题（如 梅瓶/玉壶春瓶/天球瓶/罐/碗/盘/壶/盏/尊/觚/炉/洗/盒/枕/杯/钵/盂/砚滴/花觚/蒜头瓶 等），彼此不得重复。",
     ["梅瓶", "玉壶春瓶", "天球瓶", "罐", "碗", "盘", "壶", "盏", "尊", "觚",
      "炉", "洗", "盒", "枕", "杯", "钵", "盂", "砚滴", "花觚", "蒜头瓶"]),
    ("techniques", "工艺", 20, 10,
     "选出 20 种陶瓷装饰或烧成工艺作为主题（如 青花/釉里红/斗彩/五彩/粉彩/珐琅彩/窑变/开片/刻花/划花/印花/贴花/堆塑/镂空/描金/玲珑/颜色釉/化妆土/素胎/涩圈 等），彼此不得重复。",
     ["青花", "釉里红", "斗彩", "五彩", "粉彩", "珐琅彩", "窑变", "开片", "刻花", "划花",
      "印花", "贴花", "堆塑", "镂空", "描金", "玲珑", "颜色釉", "化妆土", "素胎", "涩圈"]),
    ("decorations", "纹饰", 14, 10,
     "选出 14 种经典陶瓷纹饰题材作为主题（如 缠枝莲/折枝花果/云龙/云凤/婴戏/八仙/山水人物/花鸟/鱼藻/冰梅/锦地开光/回纹/蕉叶/海水江崖 等），彼此不得重复。",
     ["缠枝莲", "折枝花果", "云龙", "云凤", "婴戏", "八仙", "山水人物",
      "花鸟", "鱼藻", "冰梅", "锦地开光", "回纹", "蕉叶", "海水江崖"]),
]

ANGLES = ["历史源流", "工艺技法", "审美意涵", "传承与影响",
          "人物与掌故", "名品赏析", "中外交流", "现代回响"]

JM_RULE = (
    "即梦提示词必须套此模板：「运镜+主体（具体器型釉色名）+质感词（温润如玉/釉面宝光/胎骨细腻）"
    "+光线（柔和侧光/暖金）+调性（东方奇幻电影质感、月光主题、克制优雅、写实与童话融合）+16:9；"
    "禁止：文字/水印/现代元素/变形」。英文提示词同构（camera movement + subject + texture words "
    "+ lighting + mood + 16:9; no text/watermark/modern elements/deformation）。"
    "每条提示词末尾必须加锚图绑定语：中文加「严格保持 @图片1 的形象」，英文加 "
    "'Strictly preserve the appearance of @Image1'。")

def logcat(logf, msg):
    line = "[%s] %s" % (time.strftime("%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with open(logf, "a", encoding="utf-8") as f:
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

def retrieve_hits(theme):
    try:
        return ma.retrieve(theme, 8)
    except TypeError:
        return ma.retrieve(theme)

def gen_theme_candidates(cat_cn, hint, want, extra_prompt=""):
    """让考据官基于知识库给候选主题名单（多要 8 个做自净缓冲）。"""
    hits = ma.retrieve(cat_cn + " 陶瓷 " + hint[:30])
    kb = ma.kb_block(hits)
    sys_p = ("你是 MoonRabbits 的考据官。%s"
             "优先使用知识库条目中出现过的名称，不足时补陶瓷史公认名称。"
             "名称要具体（2-6 字），不得彼此重复，不得与常见色级名重复。"
             "只输出 JSON 数组（%d 个字符串），不要任何解释。%s"
             % (hint, want + 8, extra_prompt))
    txt, _, _ = chat_t(sys_p, "知识库条目：\n%s\n\n请给出 JSON 数组。" % kb, temperature=0.35)
    m = re.search(r"\[.*\]", txt, re.S)
    names = []
    for x in json.loads(m.group(0)):
        s = re.sub(r"\s+", "", str(x))
        if s and 1 < len(s) <= 8 and s not in names:
            names.append(s)
    return names

def build_themes(cat_key, cat_cn, n_themes, hint, fallback, logf, seen):
    """名单自净：检索命中 <3 的直接换名，最多 3 轮；结果落盘可断点续用。"""
    cache = ROOT / ("themes_%s.json" % cat_key)
    if cache.exists():
        themes = json.loads(cache.read_text(encoding="utf-8"))
        logcat(logf, "%s 名单用缓存 %d 个：%s" % (cat_cn, len(themes), "、".join(themes)))
        return themes
    pool = []
    for rnd in range(3):
        try:
            extra = "" if rnd == 0 else "（请给出与上一批完全不同的一批名称）"
            pool += [x for x in gen_theme_candidates(cat_cn, hint, n_themes, extra)
                     if x not in pool]
        except Exception as e:
            logcat(logf, "%s 名单生成第%d轮失败 %r" % (cat_cn, rnd + 1, e))
        pool += [x for x in fallback if x not in pool]
        themes, bad = [], []
        for name in pool:
            if len(themes) >= n_themes:
                break
            if name in seen:
                bad.append((name, "跨大类重名"))
                continue
            try:
                nh = len(retrieve_hits(name))
            except Exception as e:
                nh = 0
                logcat(logf, "检索异常 %s %r" % (name, e))
            if nh >= 3:
                themes.append(name)
            else:
                bad.append((name, "命中%d<3" % nh))
        for nm, why in bad:
            logcat(logf, "%s 自净剔除「%s」：%s" % (cat_cn, nm, why))
        if len(themes) >= n_themes:
            break
        logcat(logf, "%s 第%d轮后仅 %d/%d 个达标，再补一轮" % (cat_cn, rnd + 1, len(themes), n_themes))
        pool = [x for x in pool if x not in themes]
    for t in themes:
        seen.add(t)
    cache.write_text(json.dumps(themes, ensure_ascii=False, indent=1), encoding="utf-8")
    logcat(logf, "%s 最终名单 %d 个：%s" % (cat_cn, len(themes), "、".join(themes)))
    return themes

def make_subtitles(vo_text):
    clean = re.sub(r"\[[^\]]*\]", "", vo_text)
    parts = [p.strip() for p in re.split(r"(?<=[。！？!?])", clean) if p.strip()]
    if not parts:
        parts = [clean]
    per = 60.0 / len(parts)
    return "\n".join("%02d  [%05.1fs-%05.1fs]  %s" % (i + 1, i * per, (i + 1) * per, p)
                     for i, p in enumerate(parts))

def split_sb(sb):
    """把分镜+即梦混合输出拆成 ③分镜 ④即梦 两节。"""
    m = re.search(r"即梦中文\s*1", sb)
    if not m:
        return sb.strip(), ""
    shots = sb[:m.start()].strip()
    prompts = sb[m.start():].strip()
    return shots, prompts

def gen_episode(cat_cn, theme, idx, angle, strict=False):
    """返回 (md_text, tokens, vo)。校验不过抛 ValueError 由上层处理。"""
    tokens = 0
    hits = retrieve_hits("%s %s 陶瓷 %s" % (theme, cat_cn, angle))
    kb = ma.kb_block(hits)

    sys_h = ("你是 MoonRabbits 的考据官（Historian）。铁律：每个事实句句尾必须挂知识库条目编号，"
             "格式 [编号]。没有依据的内容标注（暂无文献支撑，仅为推测）。用中文，不超过 300 字。")
    facts, pt, et = chat_t(sys_h,
        "知识库条目：\n%s\n\n主题：%s「%s」（角度：%s）。给出核心事实 5-8 条，"
        "涵盖年代、窑口、工艺、审美。" % (kb, cat_cn, theme, angle), temperature=0.2)
    tokens += pt + et

    sys_v = ("你是纪录片旁白撰稿人。第一行输出「集标题：」（12 字以内，含主题名，有诗意），"
             "换行后写 60 秒中文旁白稿（230-280 字），口吻温暖克制、以小见大，"
             "旁白中必须出现主题名「%s」，事实以给定考据为准并保留 [编号] 引用"
             "（至少 3 处），不编造新事实。" % theme)
    if strict:
        sys_v += "上一次输出未通过校验，这次务必：①标题行格式严格「集标题：×××」②旁白至少 3 处 [编号] ③旁白里写明主题名 ④字数 230-280。"
    vo_raw, pt, et = chat_t(sys_v, "主题：%s（%s，角度：%s）\n考据事实：\n%s"
                            % (theme, cat_cn, angle, facts), temperature=0.55 if strict else 0.65)
    tokens += pt + et
    m = re.search(r"集标题[：:]\s*(.+)", vo_raw)
    title = m.group(1).strip() if m else "「%s」纪事" % theme
    vo = vo_raw[m.end():].strip() if m else vo_raw

    sys_s = ("你是纪录片分镜师兼 AI 绘图提示词专家。根据旁白写 3 个镜头分镜，每个镜头含："
             "镜头号、建议时长、画面描述、运镜方式。然后为每个镜头写即梦提示词：中文一条、英文一条。"
             + JM_RULE +
             "严格按此格式输出：\n镜头1（约20s）：画面…；运镜…\n镜头2（约20s）：…\n镜头3（约20s）：…\n"
             "即梦中文1：…\nJimeng EN 1: …\n即梦中文2：…\nJimeng EN 2: …\n即梦中文3：…\nJimeng EN 3: …")
    if strict:
        sys_s += "务必完整输出 6 条提示词（中英各 3），每条带 @图片1/@Image1 绑定语。"
    sb, pt, et = chat_t(sys_s, "主题：%s（%s）\n旁白：\n%s" % (theme, cat_cn, vo),
                        temperature=0.55 if strict else 0.65)
    tokens += pt + et
    shots, prompts = split_sb(sb)

    subs = make_subtitles(vo)
    md = ("# %s「%s」· %s\n\n> Stage 1 · %s大类  |  角度：%s  |  本地链路 qwen2.5:14b 生成\n\n"
          "## ① 集标题\n%s\n\n## ② 60 秒旁白稿（中文）\n%s\n\n## ③ 3 镜头分镜\n%s\n\n"
          "## ④ 即梦提示词（中英）\n%s\n\n## ⑤ 字幕文本\n```\n%s\n```\n"
          % (theme, angle, title, cat_cn, angle, title, vo, shots, prompts, subs))
    return md, tokens, vo, prompts

def validate(md, vo, theme, prompts):
    """质量门②：五节结构 / >=3 引用角标 / 主题名在旁白 / 全文字数 800-1600。"""
    secs = ["## ①", "## ②", "## ③", "## ④", "## ⑤"]
    if not all(s in md for s in secs):
        return "五节结构不齐"
    if len(re.findall(r"\[[^\]]{1,24}\]", vo)) < 3:
        return "旁白引用角标 <3"
    if theme not in vo:
        return "主题名未出现在旁白"
    # 字数只数 ①-④ 节正文：⑤字幕是旁白的程序化复制，不重复计入
    n = len(re.sub(r"\s", "", md.split("## ⑤")[0]))
    if not (800 <= n <= 1600):
        return "全文字数 %d 不在 800-1600" % n
    if not prompts or prompts.count("即梦中文") < 2:
        return "即梦提示词缺失"
    return None

def run_category(cat_key, cat_cn, n_themes, eps, hint, fallback, seen):
    catdir = ROOT / cat_key
    catdir.mkdir(parents=True, exist_ok=True)
    logf = catdir / "batch_log.txt"
    logcat(logf, "===== %s（%s）start  主题数%d x 每主题%d集 =====" % (cat_key, cat_cn, n_themes, eps))
    themes = build_themes(cat_key, cat_cn, n_themes, hint, fallback, logf, seen)
    ok = skip = fail = 0
    t_all = time.time()
    for theme in themes:
        tdir = catdir / theme
        tdir.mkdir(exist_ok=True)
        good_files = []
        for i in range(1, eps + 1):
            if time.time() > DEADLINE:
                logcat(logf, "!!! 到达 07:30 截止时间，停止开新集 !!!")
                return ok, skip, fail
            ep = "EP%02d" % i
            fp = tdir / (ep + ".md")
            if fp.exists():
                ok += 1
                good_files.append(fp)
                continue
            angle = ANGLES[(i - 1) % len(ANGLES)]
            t0 = time.time()
            try:
                md, tk, vo, prompts = gen_episode(cat_cn, theme, i, angle, strict=False)
                why = validate(md, vo, theme, prompts)
                if why:
                    logcat(logf, "%s/%s 首跑未过校验(%s)，更严提示词重跑" % (theme, ep, why))
                    md, tk2, vo, prompts = gen_episode(cat_cn, theme, i, angle, strict=True)
                    tk += tk2
                    why = validate(md, vo, theme, prompts)
                if why:
                    skip += 1
                    logcat(logf, "%s/%s「%s」SKIP  重跑仍未过：%s" % (theme, ep, angle, why))
                    continue
                fp.write_text(md, encoding="utf-8")
                ok += 1
                good_files.append(fp)
                logcat(logf, "%s/%s「%s·%s」SUCCESS  %.1fs  tokens=%d"
                       % (theme, ep, theme, angle, time.time() - t0, tk))
            except Exception as e:
                fail += 1
                logcat(logf, "%s/%s FAIL  %r" % (theme, ep, e))
                traceback.print_exc()
        # 质量门③：每主题随机 3 集留样
        sample = random.sample(good_files, min(3, len(good_files))) if good_files else []
        for f in sample:
            dst = QC / ("%s_%s_%s" % (cat_key, theme, f.name))
            shutil.copyfile(str(f), str(dst))
        logcat(logf, "%s 主题「%s」完成 %d/%d，留样 %d 集" % (theme, theme,
               len(good_files), eps, len(sample)))
    logcat(logf, "===== %s DONE  ok=%d skip=%d fail=%d  耗时 %.1fs ====="
           % (cat_key, ok, skip, fail, time.time() - t_all))
    return ok, skip, fail

def main():
    random.seed(20260805)
    t0 = time.time()
    seen = set()
    tot = [0, 0, 0]
    print("[stage1] start %s, deadline epoch %d" % (time.strftime("%F %T"), DEADLINE), flush=True)
    for cat_key, cat_cn, n_themes, eps, hint, fallback in CATS:
        if time.time() > DEADLINE:
            print("[stage1] deadline reached before %s, stop" % cat_key, flush=True)
            break
        r = run_category(cat_key, cat_cn, n_themes, eps, hint, fallback, seen)
        tot = [a + b for a, b in zip(tot, r)]
    print("[stage1] ALL DONE ok=%d skip=%d fail=%d total_time=%.1fs"
          % (tot[0], tot[1], tot[2], time.time() - t0), flush=True)

if __name__ == "__main__":
    main()

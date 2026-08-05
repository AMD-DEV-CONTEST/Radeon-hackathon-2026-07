import streamlit as st
import streamlit.components.v1 as components
import requests
import json
import re
import time
import subprocess
import statistics
import pandas as pd

LLM_API_URL = "http://127.0.0.1:8000/v1/chat/completions"
LLM_MODEL = "qwen3"

st.set_page_config(page_title="断脉 · AI剧本共创工作台", page_icon="🎬", layout="wide")

STAGES = ["点子", "故事", "大纲", "剧本", "脚本", "分镜"]

STAGE_GUIDE = {
    "点子": "填种子卡 → AI诊断/提问/给选项 → 锁主题与人物弧光",
    "故事": "点子转因果链（因为→所以→但是）→ 转折两推 → 情绪六格",
    "大纲": "六话结构 + 每话断点 + 场景≤8/角色≤5 + 坑清单",
    "剧本": "分场景剧本：对白极少、画面为主、唐朝语",
    "脚本": "镜头化：镜头号|景别|画面|声音",
    "分镜": "生图（暂挂）",
}

FOUNDATION_LABELS = [
    ("theme", "🎯 主题问句"),
    ("want", "🙏 主角Want"),
    ("need", "❤️ 主角Need"),
    ("core_fear", "😨 核心恐惧/共鸣"),
    ("external_stakes", "⚔️ 外部赌注"),
    ("internal_stakes", "🏠 内部赌注"),
    ("climax_tone", "🔥 高潮基调"),
    ("ending_tone", "🌫️ 结局基调"),
]

PILLAR_HELP = {
    "theme": "**✅示例** 一个平时混日子的普通人，被逼到墙角时，有没有资格当一次英雄？",
    "want": "**✅示例** 赶紧结案子、报功绩、回衙门。（越具体越自私越好）",
    "need": "**✅示例** 证明自己不是废物，配当这个官，配当这个爹。",
    "core_fear": "**✅示例** 观众在主角身上看到自己\"职责vs自保\"的矛盾。",
    "external_stakes": "**✅示例** 怪物逃出山洞，残害更多人。",
    "internal_stakes": "**✅示例** 自己的家人就在山村里等候自己。",
    "climax_tone": "**✅示例** 到死都觉得自己不配，困惑，不是释然。",
    "ending_tone": "**✅示例** 疤痕消失，女儿不记得爹。",
}

SEED_FIELDS = [
    ("logline", "📖 一句话故事 *", "一个___的___，因为___，必须___，否则___，但最大的阻碍是___。"),
    ("theme", "🎯 主题问句 *", "这个故事在问\"___？\""),
    ("want", "🙏 主角Want *", "他想要___（越具体越自私越好）"),
    ("need", "❤️ 主角Need（可空，AI给选项）", "他真正需要___"),
    ("final", "🌫️ 最后一帧画面 *", "最后一帧，你看到什么画面？"),
    ("fear", "😱 比失败更可怕的 *", "外部后果之外，更可怕的是什么？"),
]

SEED_HELP = {
    "logline": "**❌问题示例** 县令进洞查案救村民。\n\n**✅答案示例** 一个怂、怕死的赘婿县令，因村民误触古瓮失踪，必须进洞封印白骨，否则怪物屠村，但最大阻碍是他自己怕死。",
    "theme": "**❌问题示例** 他能不能打败怪物？（情节问句，不是主题问句）\n\n**✅答案示例** 一个平时混日子的普通人，被逼到墙角时，到底有没有资格、有没有胆量当一次英雄？",
    "want": "**❌问题示例** 他想保护村民。（太伟大太抽象）\n\n**✅答案示例** 赶紧结案子、报功绩、回衙门喝茶，让媳妇娘家别再念叨。",
    "need": "**❌问题示例** 他需要变强。（空）\n\n**✅答案示例** 证明自己不是废物，配当这个官，配当这个爹——哪怕代价是被女儿彻底忘记。",
    "final": "**❌问题示例** 主角打败怪物，全家团圆。（没余味）\n\n**✅答案示例** 村口，女儿回头：\"到底丢了什么呢？\"额头疤痕消失，手里攥着永不复彩的灰色石头花。",
    "fear": "**❌问题示例** 他会死。（死只是外部代价）\n\n**✅答案示例** 妻女在村口等他；而他若封印怪物，她们将永远忘记他存在过。",
}

TOOLS = [
    ("✨ 润色", "请把下面文字润色成更专业的剧本语言（保持原意，增强画面感与节奏），直接输出润色版：\n\n",
     "**示例** \"他很害怕\" → \"他的腿在抖，但他还是往前走了。\""),
    ("🎈 扩写", "请把下面文字扩写（补充镜头/光影/动作/情绪细节），直接输出扩写版：\n\n",
     "**示例** 给\"他走进山洞\"补上光/影/声/味。"),
    ("✂️ 浓缩", "请把下面文字浓缩（删冗余，保留关键镜头与情绪爆点），直接输出浓缩版：\n\n",
     "**示例** 把一段300字压成3个关键镜头。"),
    ("🏮 唐语化", "请把下面对白改写成唐朝文人日常语（带点咬文嚼字，本质大白话），直接输出改写版：\n\n",
     "**示例** \"你别碰\" → \"莫碰。\"／\"你在干什么\" → \"作甚？\""),
    ("🎬 镜头化", "请把下面散文式描述拆解为分镜序列（镜头号|景别|画面|声音），用表格输出：\n\n",
     "**示例** 散文 → 镜头号|景别|画面|声音 表格。"),
    ("🔍 逻辑自检", "请对照【永久记忆】【角色档案】【伏笔追踪】，对下面文字做逻辑自检，列出所有矛盾、OOC、未回收伏笔，逐条输出：\n\n",
     "**示例** 查出\"师爷不识字却指壁画\"这类矛盾。"),
]

CONTEST_PROMPT = ("请基于当前项目状态（核心基石/永久记忆/已封存文档），生成参赛材料：\n"
                  "1) GitHub README 大纲（英文标题+中文说明）；\n"
                  "2) 3分钟 Demo 视频解说稿（含画面描述）；\n"
                  "3) AMD W7900 / ROCm 性能优化亮点清单。用 Markdown 输出。")

# ================= 交互增强 =================
CTRL_ENTER_JS = """
<script>
(function(){
  try{
    var d = (window.parent && window.parent.document) ? window.parent.document : document;
    d.addEventListener('keydown', function(e){
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        var btns = d.querySelectorAll('button');
        for (var i=0;i<btns.length;i++){
          var t = btns[i].textContent || '';
          if (t.indexOf('🚀') !== -1) { e.preventDefault(); btns[i].click(); break; }
        }
      }
    }, true);
  }catch(err){}
})();
</script>
"""

TIDY_PROMPT = (
    "请整理下面这份【永久记忆池】：合并重复、删除过期或互相矛盾的条目、把每条改写为≤30字的原子短句，最多保留12条。\n"
    "输出格式要求：每行一条，以\"- \"开头。除此之外不要任何解释文字、不要编号、不要state_update块。\n\n"
)

# ================= 去AI味 =================
DEAI_BLACKLIST = [
    "不知不觉", "一瞬间", "那一刻", "仿佛", "宛如", "不禁", "一丝", "一抹", "一缕",
    "然而", "但是", "此外", "与此同时", "随后", "因此", "于是", "总之", "综上所述", "值得注意的是", "不仅", "而且",
    "通过", "使得", "深刻地", "不断地", "极大地", "深入", "生动", "细腻", "淋漓尽致", "悄然",
    "心头一紧", "呼吸一滞", "眼眶湿润", "嘴角上扬", "脸上露出", "眉头紧锁", "心中", "一股",
    "注入", "展现", "描绘", "呈现", "带来", "凝聚", "捕捉", "勾勒",
]
EMOTION_WORDS = [
    "害怕", "恐惧", "悲伤", "难过", "紧张", "焦虑", "愤怒", "生气", "开心", "喜悦",
    "绝望", "无助", "痛苦", "感动", "惊讶", "震惊", "不安", "恐慌", "悲痛", "苦涩", "孤独",
]
CONNECTIVE_STARTS = ["但是", "然而", "此外", "与此同时", "随后", "因此", "于是", "而且", "接着", "于是乎"]

def deai_rules():
    return (
        "\n【系统指令：顶级人类编剧瑕疵模式 - 最高优先级】\n"
        "从现在起，你是一个脾气暴躁、有严重烟瘾的独立人类编剧。你的文字必须充满人类的瑕疵，彻底打破AI的完美感：\n"
        "1. 废笔注入（必须有）：场景中必须包含20%与主线无关的'生活毛边'（如：嗡嗡叫的苍蝇、桌角没撕干净的胶带、角色说话时突然咳嗽、打火机打不着）。\n"
        "2. 潜台词对白：人类从不直接表达情绪。角色必须通过'顾左右而言他'、打断（——）、欲言又止、废话来掩饰内心。禁止角色把心里话完整说出来。\n"
        "3. 极高的Burstiness：绝对禁止工整的排比。允许连续使用3个字的超短句，突然接一个毫无逻辑的长句。\n"
        "4. 封杀AI指纹词：眼中闪过、嘴角上扬、深吸一口气、不可否认、总而言之、在这个...的时代、宛如、交织、注定。出现一个即作废。\n"
        "5. 白描动作：只写摄像机能拍到的动作。把'他很悲伤'改成'他盯着烟灰缸，点了两次打火机都没打着'。\n"
    )

def physical_humanize(text):
    """纯Python物理洗稿：破坏标点、注入废笔、掐头去尾"""
    import random
    if not text: return text
    ai_starts = ["在这个", "随着", "总而言之", "综上所述", "画面转向", "夜幕降临"]
    for s in ai_starts:
        if text.startswith(s):
            idx = text.find("，")
            text = text[idx+1:] if idx != -1 and idx < 20 else text[10:]
    sentences = text.split("。")
    for i in range(len(sentences)-1):
        r = random.random()
        if r < 0.12:
            sentences[i] += "——"
        elif r < 0.20:
            sentences[i] += "……"
        else:
            sentences[i] += "。"
    text = "".join(sentences)
    fillers = ["（咳嗽）", "……啧，", "（停顿）", "那什么，", "说白了，", "（摸烟）"]
    lines = text.split("\n")
    for i in range(len(lines)):
        if random.random() < 0.15 and len(lines[i]) > 10:
            pos = random.randint(3, len(lines[i])-3)
            lines[i] = lines[i][:pos] + random.choice(fillers) + lines[i][pos:]
    text = "\n".join(lines)
    text = text.replace("**", "", 2)
    return text

HUMANIZE_PROMPT = (
    "你是一位干了二十年的小说编辑，外号\"去模板刀\"。任务：对下面文本做二遍改写。\n"
    "铁律：\n"
    "1. 情节、信息、场景顺序、对白含义——一律不准改，只改笔法。\n"
    "2. 句长必须剧烈交错：每段插入至少一句≤10字（断句、无主语句），保留一两句30字以上长句。\n"
    "3. 把一切直接写情绪的句子换成动作/物件/声音（\"他很害怕\"→\"他把刀掉了，没去捡\"）。\n"
    "4. 删光连接词开头（但是/然而/此外/与此同时/随后），直接写下一句。\n"
    "5. 删光段尾总结/升华句（\"那一刻，他终于明白了……\"），收在动作或物件上。\n"
    "6. 对白带毛边：打断（——）、没说完、重复、口语。\n"
    "7. 段落不许等长：相邻段字数差>30%。\n"
    "8. 禁用词：仿佛、宛如、不禁、一丝、然而、与此同时、悄然、心头一紧、眼眶湿润、嘴角上扬。\n"
    "直接输出改写后的全文，不要解释。\n\n【待改写文本】\n"
)

def split_sentences(text):
    parts = re.split(r"[。！？；…\n]+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 2]

def deai_report(text):
    sents = split_sentences(text)
    if len(sents) < 5:
        return None
    lens = [len(s) for s in sents]
    mean = sum(lens) / len(lens)
    sd = statistics.pstdev(lens)
    burst = sd / mean if mean else 0
    n = max(1, len(re.sub(r"\s", "", text)))
    black = [(w, text.count(w)) for w in DEAI_BLACKLIST if text.count(w) > 0]
    black_hits = sum(c for _, c in black)
    conn = [s for s in sents if any(s.startswith(c) for c in CONNECTIVE_STARTS)]
    emo = [(w, text.count(w)) for w in EMOTION_WORDS if text.count(w) > 0]
    emo_hits = sum(c for _, c in emo)
    s_burst = max(0.0, min(1.0, (0.55 - burst) / 0.55)) * 100
    s_black = max(0.0, min(1.0, (black_hits * 1000 / n) / 6)) * 100
    s_conn = max(0.0, min(1.0, (len(conn) / len(sents)) / 0.25)) * 100
    s_emo = max(0.0, min(1.0, (emo_hits * 1000 / n) / 5)) * 100
    total = int(round(0.35 * s_burst + 0.30 * s_black + 0.15 * s_conn + 0.20 * s_emo))
    risky = []
    for s in sents:
        reasons = []
        hit = [w for w in DEAI_BLACKLIST if w in s]
        if hit:
            reasons.append("黑名单:" + "/".join(hit[:3]))
        if any(s.startswith(c) for c in CONNECTIVE_STARTS):
            reasons.append("连接词开头")
        eh = [w for w in EMOTION_WORDS if w in s]
        if eh:
            reasons.append("直陈情绪:" + "/".join(eh[:2]))
        if reasons:
            risky.append((s, reasons))
    return {
        "total": total, "burst": round(burst, 2),
        "black": black_hits, "conn": len(conn), "emo": emo_hits,
        "black_top": sorted(black, key=lambda x: -x[1])[:6],
        "emo_top": sorted(emo, key=lambda x: -x[1])[:6],
        "risky": risky[:12],
    }

THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@600;900&display=swap');
html,body,[data-testid="stAppViewContainer"]{background:#f6f1e8;}
h1,h2,h3,h4,p,label,textarea,input,button{font-family:'Noto Serif SC','Songti SC',serif !important;}
span[data-testid="stIconMaterial"]{
font-family:'Material Symbols Outlined','Material Symbols Rounded','Material Icons',sans-serif !important;
font-weight:400 !important;}
#MainMenu,footer{visibility:hidden;}
header[data-testid="stHeader"]{background:transparent;}
section[data-testid="stSidebar"]{background:#efe8dc;border-right:1px solid #e0d6c3;}
section[data-testid="stSidebar"] hr{margin:0.5rem 0;}
div[data-testid="stExpander"]{background:#fffdf8;border:1px solid #e6ddcb;border-radius:10px;}
div[data-testid="stChatInputTextArea"],div[data-testid="stTextArea"] textarea{background:#fffdf8 !important;border:1px solid #ddd2bc !important;border-radius:10px;}
div[data-testid="stMarkdown"] p{line-height:1.75;}
div[data-testid="stTooltipIcon"]{cursor:help;}
.dm-banner{display:flex;align-items:center;gap:10px;}
.dm-seal{width:40px;height:40px;background:#c73e2e;color:#fff;font-size:24px;font-weight:900;
display:flex;align-items:center;justify-content:center;border-radius:7px;
box-shadow:0 2px 8px rgba(199,62,46,.35);flex-shrink:0;}
.dm-title{font-size:18px;font-weight:900;color:#2f2a26;line-height:1.15;}
.dm-sub{font-size:10px;color:#8a7f6f;letter-spacing:.5px;}
.dm-kpi{font-size:11px;color:#5c5347;background:#fffdf8;border:1px solid #e4dac6;
border-radius:9px;padding:7px 12px;line-height:1.5;}
.dm-kpi b{color:#c73e2e;font-size:13px;}
.dm-card{background:#fffdf8;border:1px solid #e6ddcb;border-radius:10px;padding:10px 12px;margin-bottom:8px;}
.dm-fores{border-left:3px solid #b98a2e;}
.dm-seednote{background:#fdf6e3;border:1px dashed #b98a2e;border-radius:10px;
padding:8px 12px;font-size:12px;color:#7a5c1e;margin-bottom:8px;}
</style>
"""
FOCUS_CSS = """
<style>
section[data-testid="stSidebar"]{display:none;}
header[data-testid="stHeader"]{display:none;}
</style>
"""

ALL_STATE_KEYS = [
    "core_pillars", "memories", "pits_todo", "pits_done", "inspirations",
    "characters", "foreshadow", "emotion_curve", "anchors",
    "stage_artifacts", "current_stage", "document", "messages",
    "seed", "seed_submitted", "deai_mode", "stage_autodetected", "idea_turns",
]

def init_state():
    if "core_pillars" not in st.session_state:
        st.session_state.core_pillars = {
            "theme": "一个平时混日子的普通人，被逼到墙角时，到底有没有资格、有没有胆量当一次英雄？",
            "want": "赶紧结案子、报功绩、回衙门，让媳妇娘家别再念叨",
            "need": "证明自己不是废物，配当这个官，配当这个爹",
            "core_fear": "面对职责和自我保护的矛盾",
            "external_stakes": "怪物逃出山洞，残害更多人",
            "internal_stakes": "自己的家人就在山村里等候自己",
            "climax_tone": "到死都觉得自己不配，困惑，不是释然",
            "ending_tone": "疤痕消失，女儿不记得爹，到底丢了什么呢？",
        }
    if "memories" not in st.session_state:
        st.session_state.memories = [
            "漫剧：对白极少，画面/镜头语言为主",
            "唐朝设定：对话用唐朝文人日常语（咬文嚼字+大白话）",
            "主角：赘婿、清贫、木讷、不会做官、老学究、怕死、没用的好人",
            "怪物无智慧，纯规则执行器：不识字者触之即死，识字者无事",
            "封印条件：身负皇气（官）＋识字者方可＋以血为契、断脉为终",
            "符号四次：马车（埋）→洞壁（撩）→幻觉（炸）→血迹（还）",
            "石头花闭环：变色→封印→全灰→好像从来不变色",
            "媳妇不是恶人，恨铁不成钢，不会表达，压力来自娘家",
            "师爷的死零台词，只管让男主折回来",
        ]
    if "pits_todo" not in st.session_state:
        st.session_state.pits_todo = [
            "媳妇恨铁不成钢的分镜细化",
            "媳妇承受娘家压力的画面",
            "结局村口分镜细化",
            "马车戏分镜（半闪回+逃避+三堵墙）",
            "女儿那本书的封面/内容视觉设计",
            "男主读懂断脉的情绪节奏",
        ]
    if "pits_done" not in st.session_state:
        st.session_state.pits_done = [
            "媳妇和女儿中间几话在干嘛（老人传闻+村口等待）",
            "师爷的死（零台词，一个眼神，手落下）",
            "石头花结局（全灰，不再提变色）",
        ]
    if "inspirations" not in st.session_state:
        st.session_state.inspirations = [
            "疤痕消失：因果抹除，他连伤害过她这件事都不存在了！",
            "幻觉中枯骨手从女儿背后伸出：恐怖与内疚交织！",
            "三堵墙的马车戏：零台词立住家庭关系！",
            "石头花闭环：好像这种花从来就不会变色一样！",
            "一声爷+碗碎声：听觉记忆的终极扳机！",
        ]
    if "characters" not in st.session_state:
        st.session_state.characters = [
            {"name": "男主", "role": "赘婿县令", "trait": "清贫木讷、老学究、怕死、没用的好人", "visual": "旧官服+总攥紧的袖口+手上旧疤", "arc": "逃→被师爷尸体击中→被一声爷拽回→选择被忘记"},
            {"name": "媳妇", "role": "王家女", "trait": "不是恶人，恨铁不成钢，不会表达，压力来自娘家", "visual": "素色襦裙+系紧的腰带", "arc": "永远不知道发生了什么"},
            {"name": "嫣儿", "role": "女儿·七八岁", "trait": "天真好奇，因石头花跟来山村", "visual": "额头疤痕（结局消失）+灰色石头花", "arc": "从记得到彻底不记得"},
            {"name": "师爷", "role": "吏", "trait": "油滑但关键时刻舍身", "visual": "圆领袍+算盘", "arc": "碰巧挡刀，零台词死"},
            {"name": "衙役", "role": "吏", "trait": "磨蹭、胆小", "visual": "皂衣+朴刀", "arc": "踢翻罐子被拖走"},
        ]
    if "foreshadow" not in st.session_state:
        st.session_state.foreshadow = [
            {"name": "疤痕符号", "plant": "第1话马车半闪回", "payoff": "第5话血迹成符号", "status": "已回收"},
            {"name": "石头花", "plant": "第1话灰色小花", "payoff": "第6话全灰", "status": "已回收"},
            {"name": "腰带", "plant": "第1话媳妇系腰带", "payoff": "第5话死前闪回", "status": "已回收"},
            {"name": "爷·喝水", "plant": "第1话闪回", "payoff": "第3话幻觉拽回", "status": "已回收"},
            {"name": "王父买官", "plant": "第1话媳妇闪回", "payoff": "待用（娘家压力）", "status": "未回收"},
        ]
    if "emotion_curve" not in st.session_state:
        st.session_state.emotion_curve = [
            {"act": "第1话", "word": "骂", "intensity": 6},
            {"act": "第2话", "word": "屏", "intensity": 7},
            {"act": "第3话", "word": "酸", "intensity": 8},
            {"act": "第4话", "word": "凉", "intensity": 8},
            {"act": "第5话", "word": "拳", "intensity": 10},
            {"act": "第6话", "word": "空", "intensity": 9},
        ]
    for k, v in [("anchors", []), ("stage_artifacts", {}), ("current_stage", "点子"),
                 ("document", ""), ("messages", []), ("layout_mode", "default"),
                 ("show_brain", True), ("seed", {}), ("seed_submitted", False),
                 ("deai_mode", True), ("stage_autodetected", False), ("deai_report", None),
                 ("idea_turns", 0)]:
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

if not st.session_state.get("stage_autodetected"):
    sealed = [s for s in STAGES if s in st.session_state.stage_artifacts]
    if sealed:
        idx = STAGES.index(sealed[-1])
        target = STAGES[min(idx + 1, len(STAGES) - 1)]
    else:
        target = "点子"
    st.session_state.current_stage = target
    st.session_state.document = st.session_state.stage_artifacts.get(target, "")
    st.session_state.stage_autodetected = True

@st.cache_data(ttl=5)
def get_gpu_stats():
    debug = []
    try:
        import torch
        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            if total > 0:
                return round(total / 1024**3, 1), round((total - free) / 1024**3, 1), "torch.hip"
    except Exception as e:
        debug.append("torch: " + str(e))
    try:
        res = subprocess.run(["rocm-smi", "--showmeminfo", "vram", "--json"],
                             capture_output=True, text=True, timeout=4)
        debug.append("JSON raw: " + res.stdout[:300])
        data = json.loads(res.stdout)
        for card, info in data.items():
            t = u = None
            for k, v in info.items():
                kl = k.lower()
                if "vram" in kl and "used" in kl:
                    u = v
                elif "vram" in kl and "total" in kl:
                    t = v
            if t and u:
                tf, uf = float(t), float(u)
                if tf > 1e9:
                    return tf / 1024**3, uf / 1024**3, "rocm-smi(B)"
                return tf / 1024, uf / 1024, "rocm-smi(MB)"
    except Exception as e:
        debug.append("json: " + str(e))
    try:
        res = subprocess.run(["rocm-smi", "--showmeminfo", "vram"],
                             capture_output=True, text=True, timeout=4)
        debug.append("TEXT raw: " + res.stdout[:300])
        t = re.search(r"VRAM Total Memory[^:]*:\s*([\d.]+)", res.stdout)
        u = re.search(r"VRAM Total Used Memory[^:]*:\s*([\d.]+)", res.stdout)
        if t and u:
            tf, uf = float(t.group(1)), float(u.group(1))
            if tf > 1e9:
                return tf / 1024**3, uf / 1024**3, "rocm-smi(B)"
            return tf / 1024, uf / 1024, "rocm-smi(MB)"
    except Exception as e:
        debug.append("text: " + str(e))
    for card in ("card0", "card1"):
        try:
            base = "/sys/class/drm/" + card + "/device/"
            t = int(open(base + "mem_info_vram_total").read().strip())
            u = int(open(base + "mem_info_vram_used").read().strip())
            if t > 0:
                return t / 1024**3, u / 1024**3, "sysfs"
        except Exception as e:
            debug.append("sysfs " + card + ": " + str(e))
    st.session_state.gpu_debug = debug
    return 48.0, 0.0, "fallback"

def build_system_prompt():
    cp = st.session_state.core_pillars
    pillars = "\n".join("- " + l + "：" + cp.get(k, "") for k, l in FOUNDATION_LABELS if cp.get(k))
    mem = "\n".join("- " + m for m in st.session_state.memories) or "暂无"
    pits = "\n".join("- " + p for p in st.session_state.pits_todo) or "暂无"
    anchors = "\n".join("- " + a for a in st.session_state.anchors) or "暂无"
    chars = "；".join(c["name"] + "(" + c["role"] + ")：" + c["trait"] + "｜视觉：" + c["visual"]
                     for c in st.session_state.characters)
    fores = "；".join(f["name"] + "（埋：" + f["plant"] + "／收：" + f["payoff"] + "）[" + f["status"] + "]"
                      for f in st.session_state.foreshadow)
    curve = "→".join(e["act"] + e["word"] + "(" + str(e["intensity"]) + ")" for e in st.session_state.emotion_curve)
    prev = ""
    idx = STAGES.index(st.session_state.current_stage)
    if idx > 0:
        ps = STAGES[idx - 1]
        if ps in st.session_state.stage_artifacts:
            prev = "\n【上一阶段定稿（" + ps + "）- 不可推翻】\n" + st.session_state.stage_artifacts[ps][:2000] + "\n"
    base = (
        "你是一个专业的漫剧剧本共创AI（严师模式：大白话、不客气、一次只推进一个阶段），正在与用户进行【问答+辅助+扩写】。\n"
        "当前创作阶段：" + st.session_state.current_stage + "。本阶段任务：" + STAGE_GUIDE[st.session_state.current_stage] + "\n\n"
        "【核心基石】\n" + pillars + "\n\n"
        "【永久记忆 - 绝对不可违背】\n" + mem + "\n\n"
        "【角色档案】\n" + chars + "\n\n"
        "【伏笔追踪】\n" + fores + "\n\n"
        "【情绪曲线】\n" + curve + "\n\n"
        "【当前未解决的坑位】\n" + pits + "\n\n"
        "【注意力锚定词】\n" + anchors + "\n" + prev + "\n"
        "【你的回复规则】\n"
        "1. 漫剧风格：对白极少，画面/镜头语言为主。唐朝设定用唐朝文人日常语。\n"
        "2. 如果用户提出修改，必须基于【永久记忆】进行。若发现冲突，直接指出。\n"
        "3. 诊断≤3条、提问≤3个、选项≤3个，禁止一口气写完整故事。\n"
        "4. 每次回复的末尾，必须附加一个 <state_update> 块（多条用竖线|分隔），格式：\n"
        "<state_update>\n<memory_add>新增的永久记忆</memory_add>\n<memory_remove>要删除的记忆原文</memory_remove>\n"
        "<pit_add>发现的新坑</pit_add>\n<pit_resolve>已填坑的简述</pit_resolve>\n<inspiration>用户提出的绝佳灵感简述</inspiration>\n</state_update>\n"
        "5. 某项没有更新就留空标签。<state_update> 之外的内容才是给用户看的正文。\n"
        "6. memory_add 只允许≤40字的原子短句（如\"怪物无智慧，纯规则执行器\"），禁止长段总结、禁止多项拼接；\n"
        "   若需修改已有记忆，必须同时用 memory_remove 删旧的 + memory_add 加新的，禁止只加不删导致池子膨胀。"
    )
    if st.session_state.current_stage == "点子" and st.session_state.get("seed_submitted") \
       and st.session_state.get("idea_turns", 0) >= 3:
        base += ("\n【强制收敛】用户已回答足够多问题。本次回复必须直接输出《点子定稿卡》"
                 "（主题/Want/Need/高潮基调/结局基调 各一句），并明确指引：点击页面绿色按钮"
                 "\"✅ 点子定稿 → 转入故事\"。禁止再提出任何新问题。\n")
    if st.session_state.get("deai_mode", True):
        base += deai_rules()
    return base

def build_seed_prompt(s):
    return (
        "【点子种子卡（用户认真填写）】\n"
        "一句话故事：" + s.get("logline", "") + "\n"
        "主题问句：" + s.get("theme", "") + "\n"
        "主角Want：" + s.get("want", "") + "\n"
        "主角Need：" + (s.get("need", "") or "（空，请你给3个候选）") + "\n"
        "最后一帧：" + s.get("final", "") + "\n"
        "比失败更可怕的：" + s.get("fear", "") + "\n\n"
        "【你的任务】进入严师模式，禁止直接写故事：\n"
        "1. 诊断：指出这颗种子最多3个致命伤，大白话，不客气；\n"
        "2. 提问：问最多3个必须由我回答的问题（围绕：主角最丢人的毛病、高潮的代价、结局他变没变）；\n"
        "3. 选项：给主题方向3个候选（A/B/C），让我圈一个；\n"
        "4. 收敛铁律：全程最多2轮问答。一旦我回答了问题并圈了主题（或表现出不耐烦），"
        "立即输出《点子定稿卡》（主题/Want/Need/高潮基调/结局基调 各一句），并在正文末尾明确指引："
        "点击页面绿色按钮\"✅ 点子定稿 → 转入故事\"。禁止再提新问题。"
    )

def parse_state_update(text):
    updates = {"memory_add": [], "memory_remove": [], "pit_add": [], "pit_resolve": [], "inspiration": []}
    m = re.search(r"<state_update>(.*?)</state_update>", text, re.DOTALL)
    clean = text
    if m:
        block = m.group(1)
        clean = (text[:m.start()] + text[m.end():]).strip()
        for key in updates:
            tm = re.search(r"<" + key + r">(.*?)</" + key + r">", block, re.DOTALL)
            if tm and tm.group(1).strip():
                updates[key] = [x.strip() for x in tm.group(1).split("|") if x.strip()]
    return clean, updates

def apply_updates(updates):
    changes = []
    for item in updates["memory_add"]:
        it = item.strip()
        if not it or len(it) > 60:
            continue
        if it in st.session_state.memories:
            continue
        if any(it in m or m in it for m in st.session_state.memories):
            continue
        st.session_state.memories.append(it)
        changes.append("🧠 新增记忆：" + it)
    for item in updates["memory_remove"]:
        before = len(st.session_state.memories)
        st.session_state.memories = [m for m in st.session_state.memories if item not in m]
        if len(st.session_state.memories) < before:
            changes.append("🗑️ 删除记忆：" + item)
    for item in updates["pit_add"]:
        if item and item not in st.session_state.pits_todo:
            st.session_state.pits_todo.append(item)
            changes.append("🕳️ 发现新坑：" + item)
    for item in updates["pit_resolve"]:
        if item:
            st.session_state.pits_done.append(item)
            st.session_state.pits_todo = [p for p in st.session_state.pits_todo if item not in p and p not in item]
            changes.append("✅ 填坑：" + item)
    for item in updates["inspiration"]:
        if item and item not in st.session_state.inspirations:
            st.session_state.inspirations.append(item)
            changes.append("✨ 灵感入墙：" + item)
    return changes

def run_ai(user_text):
    msgs = [{"role": "system", "content": build_system_prompt()}]
    for m in st.session_state.messages[-12:]:
        msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": user_text})
    start_time = time.time()
    reasoning_text = ""
    body = {"model": LLM_MODEL, "messages": msgs, "max_tokens": 8192}
    if st.session_state.get("deai_mode", True):
        body.update({"temperature": 1.15, "top_p": 0.98, "presence_penalty": 0.6, "frequency_penalty": 0.3})
    else:
        body.update({"temperature": 0.7})
    truncated = False
    try:
        r = requests.post(LLM_API_URL, json=body, timeout=900)
        raw_json = r.json()
        choice = raw_json["choices"][0]
        msg = choice["message"]
        raw_content = msg.get("content", "")
        reasoning_text = msg.get("reasoning_content", "")
        if not reasoning_text:
            think_match = re.search(r"<think>(.*?)</think>", raw_content, re.DOTALL)
            if think_match:
                reasoning_text = think_match.group(1).strip()
                raw_content = raw_content.replace(think_match.group(0), "").strip()
        if choice.get("finish_reason") == "length":
            truncated = True
        completion_tokens = raw_json.get("usage", {}).get("completion_tokens", 0)
        elapsed = time.time() - start_time
        st.session_state.last_tps = completion_tokens / elapsed if elapsed > 0 and completion_tokens > 0 else 0.0
        st.session_state.last_tokens = completion_tokens
    except Exception as e:
        raw_content = "⚠️ 调用失败：" + str(e)
        st.session_state.last_tps = 0.0
    clean, updates = parse_state_update(raw_content)
    changes = apply_updates(updates)
    if truncated:
        changes.append("⚠️ 本回答触及输出上限，结尾可能不完整：请重试或缩短文档后再试")
    return clean, changes, reasoning_text

def llm_ok():
    try:
        return requests.get("http://127.0.0.1:8000/v1/models", timeout=3).status_code == 200
    except Exception:
        return False

def fmt(s):
    return ("✅ " + s) if s in st.session_state.stage_artifacts else ("⬜ " + s)

mode = st.session_state.layout_mode
st.markdown(THEME_CSS, unsafe_allow_html=True)
if mode == "focus":
    st.markdown(FOCUS_CSS, unsafe_allow_html=True)

vram_total, vram_used, vram_src = get_gpu_stats()
tps = st.session_state.get("last_tps", 0.0)
tokens = st.session_state.get("last_tokens", 0)
pct = int(vram_used / vram_total * 100) if vram_total > 0 else 0

tb = st.columns([3.2, 2.2, 0.9, 0.9, 1.0], gap="small")
with tb[0]:
    st.markdown(
        '<div class="dm-banner"><div class="dm-seal">断</div><div>'
        '<div class="dm-title">断脉 · AI剧本共创工作台</div>'
        '<div class="dm-sub">AMD DEVELOPER CLOUD · TRACK 2 · AGENTIC AI · ROCm 本地推理</div>'
        '</div></div>', unsafe_allow_html=True)
with tb[1]:
    tps_txt = f"{tps:.1f}" if tps > 0 else "—"
    st.markdown(
        f'<div class="dm-kpi"> W7900 显存 <b>{vram_used:.1f}</b> / {vram_total:.0f} GB（{pct}%）'
        f'｜ ⚡ 推理 <b>{tps_txt}</b> t/s（{tokens} tok）</div>', unsafe_allow_html=True)
with tb[2]:
    if st.button("⛶ 全窗口", use_container_width=True, type="primary" if mode == "wide" else "secondary",
                 help="隐藏左右两栏，对话区占满宽度，适合写长剧本"):
        st.session_state.layout_mode = "wide"; st.rerun()
with tb[3]:
    if st.button("🖥 全屏", use_container_width=True, type="primary" if mode == "focus" else "secondary",
                 help="连侧边栏、页头一起隐藏，只剩对话，极致专注"):
        st.session_state.layout_mode = "focus"; st.rerun()
with tb[4]:
    if st.button("↩ 返回默认", use_container_width=True, type="primary" if mode == "default" else "secondary",
                 help="恢复三栏默认布局"):
        st.session_state.layout_mode = "default"; st.rerun()

with st.sidebar:
    if vram_src in ("fallback", "sysfs"):
        with st.expander("🔧 VRAM调试（读数不对时点开）"):
            st.caption("当前来源：" + vram_src)
            for line in st.session_state.get("gpu_debug", []):
                st.code(line)
    st.markdown('**📋 创作阶段** <span style="font-size:10px;color:#8a7f6f;">（智能定位；切换自动封存；✅=已封存）</span>',
                unsafe_allow_html=True)
    new_stage = st.radio("当前阶段", STAGES, index=STAGES.index(st.session_state.current_stage),
                         format_func=fmt, label_visibility="collapsed")
    if new_stage != st.session_state.current_stage:
        if st.session_state.document.strip():
            st.session_state.stage_artifacts[st.session_state.current_stage] = st.session_state.document
        st.session_state.current_stage = new_stage
        st.session_state.document = st.session_state.stage_artifacts.get(new_stage, "")
        st.rerun()
    st.session_state.show_brain = st.toggle("🧠 显示AI大脑（左栏）", value=st.session_state.show_brain,
                                            help="关掉后左栏隐藏、对话区变宽；所有设置都会自动注入AI")
    st.session_state.deai_mode = st.toggle("🧼 去AI味模式（默认开）", value=st.session_state.get("deai_mode", True),
                                           help="开=生成源头注入写作铁律+高扰动采样；强烈建议常开")
    st.divider()
    if st.button("🎯 生成注意力锚定词", use_container_width=True,
                 help="把基石+记忆压缩成\"护身符\"，每次对话自动注入，防AI长对话忘设定"):
        anchors = [l + "：" + st.session_state.core_pillars.get(k, "") for k, l in FOUNDATION_LABELS
                   if st.session_state.core_pillars.get(k)]
        anchors += list(st.session_state.memories)
        st.session_state.anchors = anchors
        st.success("已生成 " + str(len(anchors)) + " 条锚定词")
    with st.expander("🎯 查看当前锚定词"):
        if st.session_state.anchors:
            for a in st.session_state.anchors:
                st.text("• " + a)
        else:
            st.info("尚未生成")
    st.divider()
    with st.expander("📦 项目导出/导入（本地文件）"):
        st.caption("💾保存/加载=云侧快捷存档；📦这里=把整个项目下载到你电脑/从电脑恢复。")
        st.download_button("⬇️ 导出项目到本地",
                           json.dumps({k: st.session_state[k] for k in ALL_STATE_KEYS},
                                      ensure_ascii=False, indent=2),
                           file_name="duanmai_project.json", use_container_width=True,
                           help="下载完整项目JSON到你电脑")
        up = st.file_uploader("⬆️ 从本地导入项目", type=["json"],
                              help="选择你电脑上的 duanmai_project.json")
        if up is not None:
            try:
                data = json.load(up)
                for k, v in data.items():
                    st.session_state[k] = v
                st.session_state.stage_autodetected = True
                st.success("导入成功！"); st.rerun()
            except Exception as e:
                st.error("导入失败：" + str(e))
    st.divider()
    if st.button("🏆 生成参赛材料", use_container_width=True,
                 help="一键生成 README大纲 / 3分钟Demo解说稿 / W7900性能亮点清单"):
        st.session_state["pending"] = CONTEST_PROMPT
        st.rerun()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 保存", use_container_width=True, help="云侧快捷存档（服务器JSON）"):
            data = {k: st.session_state[k] for k in ALL_STATE_KEYS}
            with open("/workspace/duanmai/project_state.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            st.success("已保存")
    with c2:
        if st.button("📂 加载", use_container_width=True, help="读回云侧存档"):
            try:
                with open("/workspace/duanmai/project_state.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.items():
                    st.session_state[k] = v
                st.rerun()
            except Exception:
                st.error("无存档")
    st.divider()
    if st.button("🩺 检测 llama.cpp", use_container_width=True,
                 help="测试 127.0.0.1:8000 的本地大模型服务是否活着"):
        st.success("llama.cpp 正常 (8000)") if llm_ok() else st.error("连不上 llama.cpp")

def render_brain():
    with st.expander("🧠 AI 大脑", expanded=True):
        tabs = st.tabs(["🧱 基石", "🕳️ 坑位", "✨ 灵感", "🎭 角色", "🧵 伏笔", "📊 曲线"])
        with tabs[0]:
            st.markdown("**核心基石**")
            for key, label in FOUNDATION_LABELS:
                st.session_state.core_pillars[key] = st.text_input(
                    label, value=st.session_state.core_pillars.get(key, ""), key="cp_" + key,
                    help=PILLAR_HELP.get(key))
            st.divider()
            st.markdown("**永久记忆池**")
            for i, mem in enumerate(st.session_state.memories):
                cc1, cc2 = st.columns([6, 1])
                cc1.text("• " + mem)
                if cc2.button("❌", key="dm_" + str(i), help="删除这条记忆"):
                    st.session_state.memories.pop(i); st.rerun()
            new_mem = st.text_input("添加新记忆", key="new_mem",
                                    help="**示例** 怪物无智慧，纯规则执行器。（≤40字短句）")
            if st.button("➕ 添加记忆", help="把上面输入框的内容加入记忆池") and new_mem.strip():
                st.session_state.memories.append(new_mem.strip()); st.rerun()
            if st.button("🧹 一键整理记忆池", use_container_width=True,
                         help="让AI合并重复、删除过期、把每条改写成≤30字原子短句（最多12条）"):
                st.session_state["pending"] = TIDY_PROMPT + "\n".join("- " + m for m in st.session_state.memories)
                st.session_state["tidy_mode"] = True
                st.rerun()
        with tabs[1]:
            st.markdown("**🕳️ 未填的坑**")
            if st.session_state.pits_todo:
                for i, pit in enumerate(st.session_state.pits_todo):
                    cc1, cc2 = st.columns([6, 1])
                    cc1.warning(pit)
                    if cc2.button("🪄", key="fp_" + str(i), help="把\"请帮我填这个坑\"发给AI"):
                        st.session_state["pending"] = "请帮我填这个坑：" + pit
                        st.rerun()
            else:
                st.success("没有未填的坑 🎉")
            st.divider()
            st.markdown("**✅ 已填的坑**")
            for pit in st.session_state.pits_done:
                st.success(pit)
        with tabs[2]:
            for ins in st.session_state.inspirations:
                st.markdown(
                    '<div style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;'
                    'padding:8px 12px;border-radius:8px;margin-bottom:6px;font-size:12px;">🏆 ' + ins + '</div>',
                    unsafe_allow_html=True)
        with tabs[3]:
            for i, ch in enumerate(st.session_state.characters):
                with st.expander("🎭 " + ch["name"] + " · " + ch["role"], expanded=(i == 0)):
                    a, b = st.columns(2)
                    ch["name"] = a.text_input("名字", ch["name"], key="ch_n_" + str(i), help="**示例** 男主。")
                    ch["role"] = b.text_input("身份", ch["role"], key="ch_r_" + str(i), help="**示例** 赘婿县令。")
                    ch["trait"] = st.text_area("性格", ch["trait"], height=64, key="ch_t_" + str(i),
                                               help="**示例** 清贫木讷、老学究、怕死、没用的好人。")
                    ch["visual"] = st.text_input("视觉辨识点", ch["visual"], key="ch_v_" + str(i),
                                                 help="**示例** 旧官服+总攥紧的袖口。")
                    ch["arc"] = st.text_input("人物弧光", ch["arc"], key="ch_a_" + str(i),
                                              help="**示例** 逃→被一声爷拽回→选择被忘记。")
        with tabs[4]:
            for i, fo in enumerate(st.session_state.foreshadow):
                st.markdown('<div class="dm-card dm-fores"><b>🧵 ' + fo["name"] + '</b>　[' + fo["status"] + ']</div>',
                            unsafe_allow_html=True)
                a, b = st.columns(2)
                fo["plant"] = a.text_input("埋点", fo["plant"], key="fo_p_" + str(i), help="**示例** 第1话马车半闪回。")
                fo["payoff"] = b.text_input("回收", fo["payoff"], key="fo_r_" + str(i), help="**示例** 第5话血迹成符号。")
                fo["status"] = st.selectbox("状态", ["已回收", "未回收"],
                                            index=0 if fo["status"] == "已回收" else 1, key="fo_s_" + str(i),
                                            help="已回收=伏笔已在故事里落地；未回收=还等着用。")
        with tabs[5]:
            for i, e in enumerate(st.session_state.emotion_curve):
                a, b, c = st.columns([1.1, 1.2, 2])
                a.markdown("**" + e["act"] + "**")
                e["word"] = b.text_input("情绪词", e["word"], key="ec_w_" + str(i), help="**示例** 骂/屏/酸/凉/拳/空。")
                e["intensity"] = c.slider("强度", 1, 10, e["intensity"], key="ec_i_" + str(i),
                                          help="**示例** 第1话\"骂\"=观众想骂主角怂又心疼他。")
            df = pd.DataFrame([{"act": e["act"] + "·" + e["word"], "强度": e["intensity"]}
                               for e in st.session_state.emotion_curve])
            st.line_chart(df.set_index("act"), height=170)

def render_seed_form():
    st.markdown('<div class="dm-seednote">✍️ <b>点子种子卡</b>：这6题是故事的种子，请<b>仔细填写</b>。'
                '每个输入框右上角的 <b>?</b> 气泡里有❌问题示例和✅答案示例。'
                '其余（触发事件/中点/高潮/场景/分话数…）提交后由AI一步步引导补全。</div>',
                unsafe_allow_html=True)
    with st.form("seed_form"):
        vals = {}
        for key, label, ph in SEED_FIELDS:
            vals[key] = st.text_area(label, value=st.session_state.seed.get(key, ""),
                                     placeholder=ph, height=60, help=SEED_HELP.get(key))
        submitted = st.form_submit_button("🚀 提交给AI分析", use_container_width=True, type="primary",
                                          help="提交后AI进入严师模式：诊断≤3、提问≤3、主题选项3个；最多2轮问答后自动收敛")
    if submitted:
        missing = [l for (k, l, p) in SEED_FIELDS if k != "need" and not vals[k].strip()]
        if missing:
            st.error("请先填完：" + "、".join(missing))
        else:
            st.session_state.seed.update({k: v.strip() for k, v in vals.items()})
            st.session_state.seed_submitted = True
            st.session_state["pending"] = build_seed_prompt(st.session_state.seed)
            st.rerun()

def render_seed_done():
    s = st.session_state.seed
    with st.expander("📖 已提交的种子卡（点击修改）", expanded=False):
        for key, label, ph in SEED_FIELDS:
            st.markdown("**" + label + "**：" + (s.get(key, "") or "（空）"))
        if st.button("✏️ 重新填写种子卡", help="改完需要重新提交才生效"):
            st.session_state.seed_submitted = False
            st.session_state.idea_turns = 0
            st.rerun()
    st.markdown('<div class="dm-card">✅ 种子已提交。AI <b>最多2轮问答</b>就会收敛：你答完问题、圈了主题，'
                '它会输出《点子定稿卡》。看到定稿卡后，点下面绿色按钮转入【故事】。</div>',
                unsafe_allow_html=True)
    if st.button("✅ 点子定稿 → 转入故事", type="primary", use_container_width=True,
                 help="把种子写入基石、封存点子文档，并自动触发\"转故事流\"指令"):
        cp = st.session_state.core_pillars
        if s.get("theme"):
            cp["theme"] = s["theme"]
        if s.get("want"):
            cp["want"] = s["want"]
        if s.get("need"):
            cp["need"] = s["need"]
        if s.get("fear"):
            cp["internal_stakes"] = s["fear"]
        if s.get("final"):
            cp["ending_tone"] = s["final"]
        if st.session_state.document.strip():
            st.session_state.stage_artifacts["点子"] = st.session_state.document
        st.session_state.current_stage = "故事"
        st.session_state.document = st.session_state.stage_artifacts.get("故事", "")
        st.session_state["pending"] = ("点子已定稿。请把点子转成完整故事流：用\"因为→所以→但是\"因果链写300-600字，"
                                       "末尾附【情绪曲线六格】（每话一个观众身体反应词）和【主角转折两推】。不要写剧本。")
        st.rerun()

def handle_chat(height):
    st.markdown("**💬 共创对话 — " + st.session_state.current_stage + "**")
    st.caption("🧭 " + STAGE_GUIDE[st.session_state.current_stage])
    if st.session_state.current_stage == "点子":
        if not st.session_state.seed_submitted:
            render_seed_form()
        else:
            render_seed_done()
    tc = st.columns(len(TOOLS))
    for col, (label, prompt, hp) in zip(tc, TOOLS):
        if col.button(label, use_container_width=True, help=hp):
            src = st.session_state.document.strip()
            if not src:
                for m in reversed(st.session_state.messages):
                    if m["role"] == "assistant":
                        src = m["content"]; break
            st.session_state["pending"] = prompt + src[-3000:]
            st.rerun()
    chat_box = st.container(height=height)
    with chat_box:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                if msg.get("reasoning"):
                    with st.expander("🧠 查看 AI 的深度思考过程...", expanded=False):
                        st.markdown(msg["reasoning"])
                st.markdown(msg["content"])
    # ---- 输入区：Enter=换行，Ctrl+Enter=发送 ----
    st.text_area("指令输入", height=92, key="chat_ta", label_visibility="collapsed",
                 placeholder="输入你的想法、问题或指令...\n（Enter=换行　Ctrl+Enter=发送）")
    sc1, sc2 = st.columns([6, 1])
    sc1.caption("⌨️ **Enter**=换行　｜　**Ctrl + Enter**=发送　｜　或点右侧 🚀")
    send_clicked = sc2.button("🚀", use_container_width=True, type="primary",
                              help="发送（Ctrl+Enter）")
    components.html(CTRL_ENTER_JS, height=0)
    user_text = None
    if send_clicked and st.session_state.get("chat_ta", "").strip():
        user_text = st.session_state["chat_ta"].strip()
        st.session_state["chat_ta"] = ""
    if user_text is None:
        user_text = st.session_state.pop("pending", None)
    if user_text:
        if st.session_state.current_stage == "点子" and st.session_state.get("seed_submitted"):
            st.session_state.idea_turns = st.session_state.get("idea_turns", 0) + 1
        st.session_state.messages.append({"role": "user", "content": user_text})
        try:
            clean, changes, reasoning = run_ai(user_text)
        except Exception as e:
            clean, changes, reasoning = "⚠️ 调用失败：" + str(e), [], ""
        st.session_state.messages.append({"role": "assistant", "content": clean, "reasoning": reasoning})
        if st.session_state.pop("tidy_mode", False):
            lines = [ln.strip()[1:].strip() for ln in clean.splitlines()
                     if ln.strip().startswith("- ") and len(ln.strip()) <= 60]
            if lines:
                st.session_state.memories = lines[:12]
                st.toast("🧹 记忆池已整理为 " + str(len(st.session_state.memories)) + " 条", icon="✅")
        for c in changes:
            st.toast(c, icon="✅")
        st.rerun()
    if st.button("🗑️ 清空对话历史", help="只清聊天记录，不清记忆/坑/基石等设置"):
        st.session_state.messages = []; st.rerun()

def render_canvas():
    st.markdown("**📝 画布 — " + st.session_state.current_stage + "**")
    idx = STAGES.index(st.session_state.current_stage)
    if idx > 0:
        ps = STAGES[idx - 1]
        if ps in st.session_state.stage_artifacts:
            with st.expander("📌 上一阶段定稿（" + ps + "）"):
                st.markdown(st.session_state.stage_artifacts[ps])
    st.session_state.document = st.text_area(
        "当前阶段文档", value=st.session_state.document, height=340, label_visibility="collapsed",
        help="当前阶段文档：可手动编辑，也可📥采纳AI回复")
    wc = len(re.sub(r"\s", "", st.session_state.document))
    st.caption("当前字数：" + str(wc))
    st.download_button("📤 导出当前文档 (.md)", st.session_state.document,
                       file_name="duanmai_" + st.session_state.current_stage + ".md",
                       use_container_width=True, help="把当前文档下载为Markdown文件")
    if st.button("📥 采纳最后一条AI回复", use_container_width=True, help="把AI最新回复追加进当前文档"):
        last_ai = None
        for msg in reversed(st.session_state.messages):
            if msg["role"] == "assistant":
                last_ai = msg["content"]; break
        if last_ai:
            st.session_state.document += "\n\n" + last_ai
            st.rerun()
    if st.button("🔒 定稿封存", use_container_width=True, help="锁定为阶段定稿，供下一阶段引用，AI不可推翻"):
        if st.session_state.document.strip():
            st.session_state.stage_artifacts[st.session_state.current_stage] = st.session_state.document
            st.success("已封存！")
        else:
            st.warning("文档为空")
    h1, h2, h3 = st.columns(3)
    with h1:
        if st.button("🧼 深度拟人化改写", use_container_width=True,
                     help="调LLM用暴躁编剧人格重写（保留情节，改笔法）"):
            src = st.session_state.document.strip()
            if src:
                st.session_state["pending"] = HUMANIZE_PROMPT + src[-6000:]
                st.rerun()
            else:
                st.warning("文档为空")
    with h2:
        if st.button("🧨 物理洗稿(过朱雀绝杀)", use_container_width=True,
                     help="纯代码破坏标点/注入废笔/掐头去尾，不调LLM，瞬间破坏AI指纹！"):
            if st.session_state.document.strip():
                st.session_state.document = physical_humanize(st.session_state.document)
                st.success("物理洗稿完成！建议再去朱雀测一次。")
                st.rerun()
            else:
                st.warning("文档为空")
    with h3:
        if st.button("🧪 AI味自测", use_container_width=True,
                     help="本地打分（爆发度/黑名单/连接词/直陈情绪），不联网"):
            rep = deai_report(st.session_state.document)
            st.session_state.deai_report = rep
            st.rerun()
    rep = st.session_state.get("deai_report")
    if rep:
        grade = "🟢 低AI味" if rep["total"] < 30 else ("🟡 中度AI味" if rep["total"] < 60 else "🔴 重度AI味")
        st.markdown("**🧪 AI味自测**：" + grade + " — 得分 **" + str(rep["total"]) + "**/100（越高越AI）")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("爆发度", rep["burst"], help="句长方差，越高越像人，≥0.5为佳")
        m2.metric("黑名单词", rep["black"])
        m3.metric("连接词开头", rep["conn"])
        m4.metric("直陈情绪", rep["emo"])
        with st.expander("🔍 高危句（先改这几句就能翻盘）", expanded=(rep["total"] >= 60)):
            if rep["risky"]:
                for s, r in rep["risky"]:
                    st.warning("「" + s + "」 — " + "；".join(r))
            else:
                st.success("无明显高危句")
    st.divider()
    st.markdown("**已封存**")
    if st.session_state.stage_artifacts:
        for name, doc in st.session_state.stage_artifacts.items():
            with st.expander("✅ " + name + "（" + str(len(doc)) + "字）"):
                st.markdown(doc[:300])
    else:
        st.info("暂无")

if mode == "default":
    if st.session_state.show_brain:
        col_left, col_mid, col_right = st.columns([0.8, 2.5, 0.75], gap="small")
        with col_left:
            render_brain()
    else:
        col_mid, col_right = st.columns([3.2, 0.85], gap="small")
    with col_mid:
        handle_chat(520)
    with col_right:
        render_canvas()
else:
    handle_chat(720)
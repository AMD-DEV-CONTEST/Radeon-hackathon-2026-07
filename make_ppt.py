# -*- coding: utf-8 -*-
import os, re, json, glob
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_AUTO_SIZE
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

ANSWER_TXT   = "/workspace/exam_result.txt"
EXPLAIN_JSON = "/workspace/explanations.json"
OUT_PATH     = "/workspace/AI课程PPT/金华十校高一语文试卷讲评.pptx"
QUESTION_DIR = next((p for p in ["/test/questions", "/workspace/test/questions",
                                 "/workspace/questions"] if os.path.isdir(p)), "")

INK = RGBColor(0x1F,0x2A,0x44); RED = RGBColor(0xC0,0x39,0x2B)
GRAY= RGBColor(0x6E,0x6E,0x6E); BAR = RGBColor(0x8C,0x1F,0x28)
WHT = RGBColor(0xFF,0xFF,0xFF)

SECTIONS = [
    ("01 现代文阅读Ⅰ（信息类文本 19分）", list(range(1,6))),
    ("02 现代文阅读Ⅱ（文学类文本 16分）", list(range(6,10))),
    ("03 文言文阅读（20分）",             list(range(10,15))),
    ("04 古代诗歌阅读与默写（9分）",      list(range(15,18))),
    ("05 语言文字运用（20分）",           list(range(18,23))),
    ("06 写作（60分）",                   list(range(23,24))),
]

def cn(run, name="微软雅黑"):
    run.font.name = name
    rpr = run._r.get_or_add_rPr()
    rpr.append(rpr.makeelement(qn("a:ea"), {"typeface": name}))

def text(s, l, t, w, h, lines, align=PP_ALIGN.LEFT, fit=False):
    tf = s.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h)).text_frame
    tf.word_wrap = True
    if fit:
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    for i,(txt,sz,col,bold) in enumerate(lines):
        p = tf.paragraphs[0] if i==0 else tf.add_paragraph()
        p.alignment = align; p.space_after = Pt(6)
        r = p.add_run(); r.text = txt
        r.font.size = Pt(sz); r.font.color.rgb = col; r.font.bold = bold; cn(r)

def titled(prs, title):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(0.95))
    sh.fill.solid(); sh.fill.fore_color.rgb = BAR; sh.line.fill.background()
    text(s, .5, .18, 12.3, .7, [(title, 26, WHT, True)])
    return s

def parse_answers(path):
    ans = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*(\d+)\s*[\.、．]\s*(.+)", line)
        if m: ans[int(m.group(1))] = m.group(2).strip()
    return ans

if __name__ == "__main__":
    ans  = parse_answers(ANSWER_TXT)
    expl = json.load(open(EXPLAIN_JSON, encoding="utf-8")) if os.path.exists(EXPLAIN_JSON) else {}
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)

    s = prs.slides.add_slide(prs.slide_layouts[6])
    text(s, 1, 2.2, 11.3, 2.5, [
        ("金华十校2025—2026学年第二学期期末质量检测", 32, INK, True),
        ("高一语文试题卷 · 试卷讲评", 44, BAR, True),
        ("AI 自动讲评 · 原文 / 参考答案 / 解析 / 原卷附录", 18, GRAY, False)], PP_ALIGN.CENTER)

    s = titled(prs, "目录")
    text(s, 1, 1.4, 11.3, 5.5, [(t, 24, INK, False) for t,_ in SECTIONS] + [("07 备考策略总结", 24, INK, False)])

    s = titled(prs, "考向细目表（题号 · 板块 · 参考答案）")
    tbl = s.shapes.add_table(len(ans)+1, 3, Inches(.6), Inches(1.2), Inches(12.1), Inches(6.0)).table
    tbl.columns[0].width, tbl.columns[1].width, tbl.columns[2].width = Inches(1.2), Inches(6.5), Inches(4.4)
    for c,h in enumerate(["题号","所属板块","参考答案"]): tbl.cell(0,c).text = h
    sec_of = {n:t for t,ns in SECTIONS for n in ns}
    for i,n in enumerate(sorted(ans), start=1):
        tbl.cell(i,0).text, tbl.cell(i,1).text, tbl.cell(i,2).text = str(n), sec_of.get(n,""), ans[n]
    for r in range(len(ans)+1):
        for c in range(3):
            for p in tbl.cell(r,c).text_frame.paragraphs:
                for run in p.runs: run.font.size = Pt(11); cn(run)

    for name, nums in SECTIONS:
        s = titled(prs, name)
        text(s, 1, 3, 11.3, 1.5, [(name, 40, INK, True)], PP_ALIGN.CENTER)
        for n in nums:
            a = ans.get(n, "（见原卷）")
            kind = "选择题" if len(a)==1 and a in "ABCD" else "表述题"
            e = expl.get(str(n)) or {}
            orig = str(e.get("原文","")).strip()
            if len(orig) > 700:
                orig = orig[:700] + "……（原文较长，完整版见附录原卷图）"
            title = f"第 {n} 题｜{kind}" + (f"｜答案：{a}" if kind=="选择题" else "")
            s = titled(prs, title)
            lines = []
            if orig:
                lines += [("【原文】", 18, RED, True), (orig, 13, INK, False)]
            lines += [("【参考答案】", 18, RED, True), (a, 16, INK, False)]
            if e:
                lines += [("【解析】", 18, RED, True), (e.get("解析",""), 14, INK, False),
                          ("【易错点】", 18, RED, True), (e.get("易错",""), 14, GRAY, False)]
            text(s, .6, 1.2, 12.1, 6.0, lines, fit=True)

    s = titled(prs, "07 备考策略总结")
    text(s, .8, 1.4, 11.7, 5.5, [
        ("1. 信息类文本：先读选项再回原文定位，警惕偷换概念、无中生有。", 20, INK, False),
        ("2. 文学类文本：作用题从结构、内容、主旨、读者四个角度作答。", 20, INK, False),
        ("3. 文言文：断句抓主谓宾与虚词，翻译落实关键词与特殊句式。", 20, INK, False),
        ("4. 默写：理解性默写先还原语境，再核对字形，避免同音错别字。", 20, INK, False),
        ("5. 作文：漫画类材料先析画面再联现实，立意求稳求深。", 20, INK, False)])

    if QUESTION_DIR:
        for f in sorted(glob.glob(QUESTION_DIR+"/*.png") + glob.glob(QUESTION_DIR+"/*.jpg")):
            s = prs.slides.add_slide(prs.slide_layouts[6])
            pic = s.shapes.add_picture(f, Inches(0), Inches(.25), height=Inches(7.0))
            pic.left = Inches((13.333 - pic.width/914400)/2)

    s = prs.slides.add_slide(prs.slide_layouts[6])
    text(s, 1, 3, 11.3, 1.5, [("谢谢你的观看", 44, BAR, True)], PP_ALIGN.CENTER)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    prs.save(OUT_PATH)
    print("PPT saved ->", OUT_PATH, "| slides:", len(list(prs.slides)))
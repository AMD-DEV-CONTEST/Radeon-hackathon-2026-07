# -*- coding: utf-8 -*-
import os, re, json
from PIL import Image
from vllm import LLM, SamplingParams
from transformers import AutoTokenizer

def find_model():
    for py in ["/workspace/run_exam.py", "/workspace/untitled.py"]:
        if os.path.exists(py):
            src = open(py, encoding="utf-8").read()
            for c in re.findall(r'["\'](/[^"\'\n]+)["\']', src):
                if os.path.isfile(os.path.join(c, "config.json")):
                    return c
    for base in ["/workspace/models", "/models"]:
        for root, dirs, files in os.walk(base):
            if "config.json" in files:
                return root
    return None

# 每题题干印在哪页（第1题跨2、3两页，特殊）
Q2PAGES = {1:[2,3],2:[3],3:[3],4:[3],5:[3],6:[5],7:[5],8:[5],9:[5],
           10:[6],11:[6],12:[6],13:[7],14:[7],15:[7],16:[7],17:[7],
           18:[8],19:[8],20:[8],21:[8],22:[8],23:[8]}

def prompt_for(n):
    return (f"你是试卷录入员。图片是试卷中含第{n}题的页面。请逐字抄录第{n}题的完整原文："
            "题号、题干、选项（ABCD）、括号横线都要。"
            "若该题配套的阅读材料/文言段落也完整印在图片页中，请一并抄录放在原文开头；"
            "若材料不在图片页中或只有部分，则不要抄材料，只抄题干和选项。"
            f"只输出JSON：{{\"{n}\": \"原文\"}}，不要答案、不要解析、不要多余文字；"
            "字符串内禁止英文双引号，引用用「」。")

def clean(t):
    t = t.strip()
    t = re.sub(r"^```(json)?", "", t)
    return re.sub(r"```$", "", t).strip()

def salvage(t):
    out = {}
    ks = list(re.finditer(r'["\'](\d{1,2})["\']\s*[:：]', t))
    for i, km in enumerate(ks):
        seg = t[km.end(): ks[i + 1].start() if i + 1 < len(ks) else len(t)]
        seg = seg.strip().strip(' \n\t",，}』」').strip()
        if len(seg) > 10:
            out[km.group(1)] = seg
    return out

def main():
    MODEL_PATH = find_model()
    print("MODEL_PATH =", MODEL_PATH)
    QUESTION_DIR = next(p for p in ["/test/questions", "/workspace/test/questions",
                                    "/workspace/questions", "/workspace/test", "/test"]
                        if os.path.isdir(p))
    OUT = "/workspace/explanations.json"
    data = json.load(open(OUT, encoding="utf-8"))

    missing = [n for n in range(1, 24)
               if not (isinstance(data.get(str(n)), dict) and str(data[str(n)].get("原文", "")).strip())]
    todo = sorted(set(missing) | {1})   # 第1题跨两页，重抄保证完整
    print("待抄题号:", todo)

    llm = LLM(model=MODEL_PATH, trust_remote_code=True,
              gpu_memory_utilization=0.9, max_model_len=32768)
    sp = SamplingParams(temperature=0.1, max_tokens=8192)
    tok = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)

    for n in todo:
        files = [os.path.join(QUESTION_DIR, f"{p}.png") for p in Q2PAGES[n]]
        files = [f for f in files if os.path.exists(f)]
        imgs = [Image.open(f).convert("RGB") for f in files]
        val = None
        for attempt in range(2):
            content = [{"type": "image", "image": "file://" + f} for f in files]
            content.append({"type": "text", "text": prompt_for(n) +
                            ("【注意】上次输出不是合法JSON，这次务必只输出合法JSON。" if attempt else "")})
            prompt = tok.apply_chat_template([{"role": "user", "content": content}],
                                             tokenize=False, add_generation_prompt=True)
            out = llm.generate([{"prompt": prompt, "multi_modal_data": {"image": imgs}}], sp)[0].outputs[0].text
            t = clean(out)
            m = re.search(r"\{.*\}", t, re.S)
            if m:
                try:
                    obj = json.loads(m.group(0))
                    val = obj.get(str(n))
                except Exception:
                    val = salvage(m.group(0)).get(str(n))
            if val is None:
                val = salvage(t).get(str(n))
            if val and len(str(val).strip()) > 10:
                val = str(val).strip()
                break
            val = None
        if val:
            d = data.setdefault(str(n), {})
            d["原文"] = val
            json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"题{n} 录入（{len(val)}字）")
        else:
            print(f"题{n} 失败")

    have = sum(1 for v in data.values() if isinstance(v, dict) and v.get("原文"))
    print("含原文题数:", have, "/", len(data))

if __name__ == "__main__":
    main()
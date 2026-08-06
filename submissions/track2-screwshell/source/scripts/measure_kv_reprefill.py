#!/usr/bin/env python3
"""T10 — KV 失效 re-prefill 真机实测（纯 stdlib，无第三方依赖）。

回答一个问题：roomy 模式每步 per-request 切 lora 之后，已缓存的共享前缀 KV
是否仍然命中？若失效，则每次换帽子都强制一次全量 re-prefill —— 这才是热切的
真实成本，而不是 0.65ms 的控制面 toggle。

核心测量量（llama.cpp `/completion` 响应）：
    timings.prompt_n   —— 真正被预填充的 token 数（命中 KV 的不计）
    timings.cache_n    —— 直接命中 KV 的 token 数（部分版本才有）
    tokens_evaluated   —— 本次请求的 prompt 总 token 数

五组实验（前缀在 A/B/C/D 之间逐字节相同）：
    A 冷启动     cache_prompt=false                      → cold 全量 prefill 基线
    B 仅缓存     cache_prompt=true, 不换 lora            → warm 命中基线
    C per-req    cache_prompt=true, 每步切 per-request lora 数组（roomy chat 注入）
    D roomy 热切 cache_prompt=true, POST /lora-adapters 全局 scale toggle
    E 知识注入   cache_prompt=true, 变动 prefill 长度（前缀不变，尾部追加）

判据（蓝图 §5.2 T10）：
    median(prompt_n[换 lora 后]) > 0.5 x median(prompt_n[冷启]) ⇒ KV 失效

只读测量：不改 server 配置、不重载模型。脚本启动时快照全局 lora scale，
退出前（含异常）无条件复位。

用法：
    python3 measure_kv_reprefill.py [--host 127.0.0.1] [--port 8080]
                                    [--reps 5] [--slot 0] [--prefix-tokens 1500]
stdout 为一个 JSON 文档（原始逐请求数据 + 中位数 + verdict + 环境指纹）。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------- HTTP 基础层

TIMEOUT = 600


def _req(base: str, path: str, payload=None, method: str | None = None):
    """发一个 JSON 请求，返回 (解析后的对象, wall_ms)。失败抛 RuntimeError（带响应体）。"""
    url = base + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method or ("POST" if data else "GET"))
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # 不静默失败：把 server 的错误体原样带出来（蓝图 R3）
        detail = exc.read().decode("utf-8", "replace")[:800]
        raise RuntimeError(f"HTTP {exc.code} on {method or 'POST'} {path}: {detail}") from None
    except Exception as exc:
        raise RuntimeError(f"{type(exc).__name__} on {method or 'POST'} {path}: {exc}") from None
    wall_ms = (time.perf_counter() - t0) * 1000.0
    try:
        return json.loads(body), wall_ms
    except json.JSONDecodeError:
        raise RuntimeError(f"non-JSON body on {path}: {body[:400]}") from None


# ------------------------------------------------------------------ 语料构造

_PARA = (
    "You are ScrewShell, a local-first autonomous investigation agent running "
    "entirely on operator-owned hardware. You plan, call tools, read evidence, "
    "and produce a cited report. Every claim in the final answer must be backed "
    "by an explicit citation to an observation id that actually exists in the "
    "evidence store. Never invent file paths, never invent line numbers, and "
    "never cite an observation you did not read. When a tool fails, surface the "
    "failure as a degradation instead of silently continuing. "
)


def build_prefix(target_tokens: int, tokenize) -> tuple[str, int]:
    """构造一个 >= target_tokens 的确定性固定前缀，返回 (文本, 实测 token 数)。"""
    text = "<<SCREWSHELL-T10-FIXED-PREFIX>>\n"
    n = tokenize(text)
    i = 0
    while n < target_tokens:
        text += f"[spec {i:03d}] " + _PARA + "\n"
        i += 1
        if i % 2 == 0:  # 每 2 段测一次：省 tokenize 往返，又不至于严重超目标
            n = tokenize(text)
    return text, tokenize(text)


def build_knowledge(idx: int) -> str:
    """E 组：每次不同的"知识注入"块，追加在固定前缀之后。"""
    return (f"\n<<INJECTED-KNOWLEDGE #{idx}>>\n"
            + f"Finding {idx}: " + _PARA * (1 + idx % 3) + "\n")


SUFFIX = "\n<<TASK>> Summarize the operating constraints in one word:"


# ------------------------------------------------------------------ 单次采样

FIELD_MAP = {
    # 报告里记录的字段名 → 真机响应中的取值路径
    "prompt_n": ("timings", "prompt_n"),
    "cache_n": ("timings", "cache_n"),
    "prompt_ms": ("timings", "prompt_ms"),
    "prompt_per_second": ("timings", "prompt_per_second"),
    "predicted_n": ("timings", "predicted_n"),
}


def sample(base: str, prompt: str, *, slot: int, cache_prompt: bool,
           lora=None, label: str = "") -> dict:
    payload = {
        "prompt": prompt,
        "n_predict": 1,
        "temperature": 0.0,
        "cache_prompt": cache_prompt,
        "id_slot": slot,
    }
    if lora is not None:
        payload["lora"] = lora
    body, wall_ms = _req(base, "/completion", payload)

    rec: dict = {"label": label, "wall_ms": round(wall_ms, 2),
                 "cache_prompt": cache_prompt, "lora": lora}
    timings = body.get("timings") or {}
    for name, (outer, inner) in FIELD_MAP.items():
        src = timings if outer == "timings" else body
        rec[name] = src.get(inner)  # 缺失 → None，报告里如实标注
    # 该端点没有 OAI 的 usage.prompt_tokens；tokens_evaluated 是等价物
    rec["tokens_evaluated"] = body.get("tokens_evaluated")
    rec["tokens_cached"] = body.get("tokens_cached")
    rec["id_slot"] = body.get("id_slot")
    # 本次请求「实际生效」的 lora —— D 组假阴性的唯一防线：
    # 若全局 toggle 没真正作用到该请求，这里会暴露出来。
    rec["effective_lora"] = (body.get("generation_settings") or {}).get("lora")
    rec["content"] = (body.get("content") or "")[:40]
    # 独立于 cache_n 的命中探针（蓝图 §3.10 的减法）
    pt, pn = rec["tokens_evaluated"], rec["prompt_n"]
    rec["cached_by_subtraction"] = (max(0, pt - pn)
                                    if isinstance(pt, int) and isinstance(pn, int) else None)
    return rec


def med(recs, key="prompt_n"):
    vals = [r[key] for r in recs if isinstance(r.get(key), (int, float))]
    return statistics.median(vals) if vals else None


# ------------------------------------------------------------------ 主流程

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--prefix-tokens", type=int, default=1500)
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"

    out: dict = {"schema": "screwshell.t10.kv_reprefill/1",
                 "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                 "config": vars(args)}

    # ---- 环境指纹 ------------------------------------------------------
    props, _ = _req(base, "/props")
    out["env"] = {
        "model_path": props.get("model_path"),
        "model_ftype": props.get("model_ftype"),
        "n_ctx": (props.get("default_generation_settings") or {}).get("n_ctx"),
        "total_slots": props.get("total_slots"),
        "build_info": props.get("build_info"),
    }

    adapters, _ = _req(base, "/lora-adapters")
    # 该版本 /lora-adapters 不返回 name，只有 id+path → 从 path 取专家名
    name_of = {a["id"]: a["path"].rstrip("/").split("/")[-2] for a in adapters}
    initial_scales = [{"id": a["id"], "scale": a.get("scale", 0.0)} for a in adapters]
    out["env"]["lora_adapters"] = [
        {"id": a["id"], "name": name_of[a["id"]], "path": a["path"],
         "initial_scale": a.get("scale")} for a in adapters
    ]

    ids = sorted(name_of)
    if len(ids) < 2:
        print(json.dumps({"error": "需要 >=2 个已预载 lora 才能做换帽实验",
                          "adapters": adapters}), flush=True)
        return 2
    LA, LB = ids[0], ids[1]  # 换帽实验用的两顶帽子

    def tokenize(text: str) -> int:
        body, _ = _req(base, "/tokenize", {"content": text})
        return len(body.get("tokens") or [])

    prefix, n_prefix = build_prefix(args.prefix_tokens, tokenize)
    fixed_prompt = prefix + SUFFIX
    n_fixed = tokenize(fixed_prompt)
    out["prompt"] = {"prefix_tokens": n_prefix, "full_prompt_tokens": n_fixed,
                     "suffix": SUFFIX}

    def set_global_lora(scales):
        _req(base, "/lora-adapters", scales)

    groups: dict[str, list] = {}
    out["groups"] = groups
    out["errors"] = []

    try:
        # 全局 lora 归零，让 A/B/C 组的全局态干净可控（D 组自己会改）
        set_global_lora([{"id": i, "scale": 0.0} for i in ids])

        # ---- A 冷启动：cache_prompt=false，每次全量 prefill ----------------
        recs = []
        for k in range(args.reps):
            recs.append(sample(base, fixed_prompt, slot=args.slot,
                               cache_prompt=False, label=f"A/cold#{k}"))
        groups["A_cold"] = recs

        # ---- B 仅 cache_prompt，不换 lora → warm 命中基线 ------------------
        sample(base, fixed_prompt, slot=args.slot, cache_prompt=True, label="B/warmup")
        recs = []
        for k in range(args.reps):
            recs.append(sample(base, fixed_prompt, slot=args.slot,
                               cache_prompt=True, label=f"B/warm#{k}"))
        groups["B_warm_no_lora_switch"] = recs

        # ---- C0 对照：带 per-request lora 但每次都是同一顶帽子（不换）------
        # 区分两件事：是「携带 lora 字段」本身就失效，还是只有「换帽」才失效。
        sample(base, fixed_prompt, slot=args.slot, cache_prompt=True,
               lora=[{"id": LA, "scale": 1.0}], label="C0/warmup")
        recs = []
        for k in range(args.reps):
            recs.append(sample(base, fixed_prompt, slot=args.slot, cache_prompt=True,
                               lora=[{"id": LA, "scale": 1.0}],
                               label=f"C0/same#{k}->{name_of[LA]}"))
        groups["C0_per_request_lora_repeat"] = recs

        # ---- C cache_prompt + 每步 per-request 切 lora（roomy chat 注入）---
        sample(base, fixed_prompt, slot=args.slot, cache_prompt=True,
               lora=[{"id": LA, "scale": 1.0}], label="C/warmup")
        recs = []
        for k in range(args.reps):
            hat = LB if k % 2 == 0 else LA  # 每步换一顶帽子，前缀逐字节不变
            recs.append(sample(base, fixed_prompt, slot=args.slot, cache_prompt=True,
                               lora=[{"id": hat, "scale": 1.0}],
                               label=f"C/perreq#{k}->{name_of[hat]}"))
        groups["C_per_request_lora_switch"] = recs

        # ---- D roomy 热切：POST /lora-adapters 全局 scale toggle -----------
        set_global_lora([{"id": i, "scale": 1.0 if i == LA else 0.0} for i in ids])
        sample(base, fixed_prompt, slot=args.slot, cache_prompt=True, label="D/warmup")
        recs = []
        for k in range(args.reps):
            hat = LB if k % 2 == 0 else LA
            t0 = time.perf_counter()
            set_global_lora([{"id": i, "scale": 1.0 if i == hat else 0.0} for i in ids])
            toggle_ms = (time.perf_counter() - t0) * 1000.0
            r = sample(base, fixed_prompt, slot=args.slot, cache_prompt=True,
                       label=f"D/roomy#{k}->{name_of[hat]}")
            r["control_plane_toggle_ms"] = round(toggle_ms, 3)
            recs.append(r)
        groups["D_roomy_global_toggle"] = recs
        set_global_lora([{"id": i, "scale": 0.0} for i in ids])

        # ---- E 知识注入：固定前缀不变，尾部追加变动内容（对照组）----------
        sample(base, fixed_prompt, slot=args.slot, cache_prompt=True, label="E/warmup")
        recs = []
        for k in range(args.reps):
            p = prefix + build_knowledge(k) + SUFFIX
            r = sample(base, p, slot=args.slot, cache_prompt=True,
                       label=f"E/inject#{k}")
            r["prompt_tokens_total"] = tokenize(p)
            recs.append(r)
        groups["E_knowledge_injection"] = recs

        # ---- P 正确性探针：两条换帽路径「是否真的换上了帽子」-----------------
        # prompt_n/cache_n 只能证明缓存命中与否，**不能**证明权重真的换了。
        # `generation_settings.lora` 只反映请求级覆盖（全局路径下恒为 []），也不可用。
        # 唯一可靠办法：固定 seed + 贪心解码，把生成内容与三个 ground truth 对拍。
        vp = ("<<V>> You are a security expert. In one sentence, state the single "
              "most important rule when handling an untrusted input file:")

        def gen(*, lora=None, cache=False):
            body, _ = _req(base, "/completion", {
                "prompt": vp, "n_predict": 48, "temperature": 0.0, "seed": 42,
                "cache_prompt": cache, "id_slot": args.slot,
                **({"lora": lora} if lora else {})})
            t = body.get("timings") or {}
            return body.get("content"), t.get("cache_n"), t.get("prompt_n")

        def zero():
            set_global_lora([{"id": i, "scale": 0.0} for i in ids])

        def only(hat):
            set_global_lora([{"id": i, "scale": 1.0 if i == hat else 0.0} for i in ids])

        # ground truth 取自「冷启 + per-request lora」——P2 会证明这条路径可信
        zero()
        REF = {"base": gen()[0],
               name_of[LA]: gen(lora=[{"id": LA, "scale": 1.0}])[0],
               name_of[LB]: gen(lora=[{"id": LB, "scale": 1.0}])[0]}

        def who(c):
            for k, v in REF.items():
                if c == v:
                    return k
            return "HYBRID/UNKNOWN"

        P: dict = {"refs_distinct": len(set(REF.values())) == len(REF), "trials": {}}

        def rec(bucket, tag, triple, expect):
            content, cache_n, _ = triple
            P["trials"].setdefault(bucket, []).append(
                {"step": tag, "cache_n": cache_n, "got": who(content),
                 "expected": expect, "ok": who(content) == expect})

        NA, NB = name_of[LA], name_of[LB]
        LORA_A = [{"id": LA, "scale": 1.0}]
        LORA_B = [{"id": LB, "scale": 1.0}]

        # P1 纯全局路径（roomy 控制面 toggle）
        for t in range(3):
            zero()
            only(LA)
            rec("P1_global_only", f"t{t}/A_cold", gen(cache=False), NA)
            rec("P1_global_only", f"t{t}/A_warm", gen(cache=True), NA)
            only(LB)
            rec("P1_global_only", f"t{t}/B_warm_after_toggle", gen(cache=True), NB)
            rec("P1_global_only", f"t{t}/B_warm2", gen(cache=True), NB)

        # P2 纯 per-request 路径（chat 注入 lora 数组）
        zero()
        for t in range(2):
            rec("P2_per_request_only", f"t{t}/A_switch", gen(lora=LORA_A, cache=True), NA)
            rec("P2_per_request_only", f"t{t}/A_repeat", gen(lora=LORA_A, cache=True), NA)
            rec("P2_per_request_only", f"t{t}/B_switch", gen(lora=LORA_B, cache=True), NB)
            rec("P2_per_request_only", f"t{t}/B_repeat", gen(lora=LORA_B, cache=True), NB)

        # P3 混用：per-request 打底 → 转全局路径（命中缓存）← 会静默掉专家
        for t in range(3):
            zero()
            rec("P3_mixed_perreq_then_global", f"t{t}/prime_perreq_B",
                gen(lora=LORA_B, cache=False), NB)
            only(LA)
            rec("P3_mixed_perreq_then_global", f"t{t}/global_A_warm", gen(cache=True), NA)
            rec("P3_mixed_perreq_then_global", f"t{t}/global_A_warm2", gen(cache=True), NA)
            rec("P3_mixed_perreq_then_global", f"t{t}/global_A_cold_recover",
                gen(cache=False), NA)

        # P4 混用反向：全局打底 → 转 per-request（命中缓存）
        for t in range(2):
            zero()
            only(LA)
            rec("P4_mixed_global_then_perreq", f"t{t}/prime_global_A", gen(cache=False), NA)
            rec("P4_mixed_global_then_perreq", f"t{t}/perreq_B_warm",
                gen(lora=LORA_B, cache=True), NB)
        zero()

        P["summary"] = {b: {"steps": len(v), "all_correct": all(x["ok"] for x in v),
                            "wrong": [x for x in v if not x["ok"]]}
                        for b, v in P["trials"].items()}
        out["P_adapter_correctness"] = P

    except RuntimeError as exc:
        out["errors"].append(str(exc))
    finally:
        # 只读测量的收尾：无条件把全局 lora scale 复位到进场时的快照
        try:
            set_global_lora(initial_scales)
            restored, _ = _req(base, "/lora-adapters")
            out["lora_state_restored"] = [{"id": a["id"], "scale": a.get("scale")}
                                          for a in restored]
        except RuntimeError as exc:
            out["errors"].append(f"lora 复位失败: {exc}")

    # ---- 汇总 + 判据 ---------------------------------------------------
    out["medians"] = {g: {"prompt_n": med(rs, "prompt_n"),
                          "cache_n": med(rs, "cache_n"),
                          "prompt_ms": med(rs, "prompt_ms"),
                          "tokens_evaluated": med(rs, "tokens_evaluated"),
                          "wall_ms": med(rs, "wall_ms")}
                      for g, rs in groups.items()}

    cold = med(groups.get("A_cold", []))
    warm = med(groups.get("B_warm_no_lora_switch", []))
    c_med = med(groups.get("C_per_request_lora_switch", []))
    d_med = med(groups.get("D_roomy_global_toggle", []))

    def ratio(x, y):
        return round(x / y, 4) if isinstance(x, (int, float)) and y else None

    verdict: dict = {
        "criterion": "median(prompt_n[after lora switch]) > 0.5 * median(prompt_n[cold]) => KV INVALIDATED",
        "cold_prompt_n": cold, "warm_prompt_n": warm,
        "C_prompt_n": c_med, "D_prompt_n": d_med,
        "C_over_cold": ratio(c_med, cold), "D_over_cold": ratio(d_med, cold),
        "C_over_warm": ratio(c_med, warm), "D_over_warm": ratio(d_med, warm),
    }
    if cold and isinstance(c_med, (int, float)):
        verdict["C_kv_invalidated"] = c_med > 0.5 * cold
    if cold and isinstance(d_med, (int, float)):
        verdict["D_kv_invalidated"] = d_med > 0.5 * cold
    inval = [v for k, v in verdict.items() if k.endswith("_kv_invalidated")]
    verdict["kv_survives_lora_switch"] = (not any(inval)) if inval else None
    # 换帽的真实 re-prefill 代价（相对 warm 基线多付的 token / 毫秒）
    cm, wm = med(groups.get("C_per_request_lora_switch", []), "prompt_ms"), \
        med(groups.get("B_warm_no_lora_switch", []), "prompt_ms")
    if isinstance(c_med, (int, float)) and isinstance(warm, (int, float)):
        verdict["reprefill_tokens_per_switch"] = c_med - warm
    if isinstance(cm, (int, float)) and isinstance(wm, (int, float)):
        verdict["reprefill_ms_per_switch"] = round(cm - wm, 2)
    verdict["C0_same_lora_prompt_n"] = med(groups.get("C0_per_request_lora_repeat", []))
    # D 组有效性自检：全局 toggle 是否真的作用到了这些请求上？
    d_eff = [r.get("effective_lora") for r in groups.get("D_roomy_global_toggle", [])]
    verdict["D_effective_lora_seen"] = d_eff
    verdict["D_switch_observable_in_response"] = len(
        {json.dumps(x, sort_keys=True) for x in d_eff}) > 1
    out["verdict"] = verdict

    out["field_availability"] = {
        name: any(isinstance(r.get(name), (int, float))
                  for rs in groups.values() for r in rs)
        for name in list(FIELD_MAP) + ["tokens_evaluated", "tokens_cached"]
    }

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 1 if out["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())

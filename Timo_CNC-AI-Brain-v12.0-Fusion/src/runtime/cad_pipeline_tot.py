"""cad_pipeline_tot — TOT(Tree of Thoughts) 多画图管道竞争机制
对同一自然语言用例并行运行多条候选参数提取管道，按
schema合法性/文本覆盖率/几何一致性/bbox合理性 打分，
选出置信度最高的管道作为默认执行路径 (winner)。

候选管道 (按输入可用性裁剪):
  1) llm        — LLM结构化提取 (多温度采样k次; LLM不可用记为不可用+低分, 不抛异常)
  2) regex      — 正则规则管道 (复用 app.main._legacy_extract_cad_spec, 单一维护点)
  3) structured — 结构化直填管道 (请求自带 part_type/params 表单字段时适用)

产出:
  - winner spec (part_type/params/material/quantity/surface_treatment)
  - cad_tot 推理链: 每条候选一个INFER步骤(含分项得分evidence) + winner一个CONCLUDE步骤
  - 利用确定性STEP文件名特性: winner的OCC试算产物即正式产物, 非winner临时STEP自动清理

开关: 环境变量 TOT_ENABLED=0 关闭 (main.py 回退原单路径, 本模块不被导入)。
作者: timo.cao | 邮箱: miscdd@163.com | 生成: 大帅教练系统"""
import os
import re
import math
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.neuro_core.reasoning_chain import ReasoningChain, StepType, register_chain, get_chain
from src.runtime.step_generator_occ import generate_part_occ, occ_available

# ── 配置 ──
TOT_ENABLED = os.environ.get("TOT_ENABLED", "1") != "0"
LLM_SAMPLE_TEMPS = (0.1, 0.4)          # LLM管道采样温度 (k=len(temps))
UNAVAILABLE_SCORE = 0.05               # 不可用管道的固定低分 (不参与择优)
# 打分权重 (flange且OCC可用: 四维; 其他零件仅 schema+覆盖率)
W_SCHEMA, W_COVER, W_GEOM, W_BBOX = 0.30, 0.30, 0.25, 0.15


def _get_main_attr(name):
    """惰性获取 app.main 属性 — 仅查 sys.modules, 不主动导入。
    服务运行时 app.main 已加载可直接复用; 测试通过 sys.modules['app.main']
    注入stub。避免在此处 import app.main — 其模块级代码会触发模型健康检查/网络请求。"""
    mod = sys.modules.get("app.main")
    if mod is None:
        return None
    return getattr(mod, name, None)


def _validate(spec):
    """schema清洗 — 复用 main.py 的 validate_part_spec。"""
    fn = _get_main_attr("validate_part_spec")
    if fn is None:
        return None
    try:
        return fn(spec)
    except Exception:
        return None


# ══════════════════════════════════════════════════
# 候选管道 1: LLM管道 (多温度采样)
# ══════════════════════════════════════════════════

def pipeline_llm_candidates(message: str, temps=LLM_SAMPLE_TEMPS) -> list:
    """LLM采样候选: 每个温度一次采样 → 一个候选。
    LLM不可用/提取失败 → 候选记为不可用(低分), 不抛异常中断TOT。"""
    extract = _get_main_attr("llm_extract_part_spec")
    out = []
    if extract is None:
        for t in temps:
            out.append({"source": f"llm@T={t}", "spec": None, "available": False,
                        "note": "llm_extract_part_spec 不可导入"})
        return out
    for t in temps:
        try:
            spec, _raw, meta = extract(message, temperature=t)
        except TypeError:
            # 兼容无temperature参数的旧签名
            try:
                spec, _raw, meta = extract(message)
            except Exception as e:
                spec, meta = None, {"note": f"LLM调用异常: {e}"}
        except Exception as e:
            spec, meta = None, {"note": f"LLM调用异常: {e}"}
        ok = isinstance(spec, dict) and spec.get("part_type") and spec.get("params")
        out.append({
            "source": f"llm@T={t}", "spec": spec if ok else None, "available": bool(ok),
            "note": (meta or {}).get("note", ""),
            "model": (meta or {}).get("model"),
        })
    return out


# ══════════════════════════════════════════════════
# 候选管道 2: 正则规则管道 (复用 main.py 正则逻辑, 不重复维护)
# ══════════════════════════════════════════════════

def pipeline_regex_candidate(message: str) -> dict:
    """正则规则候选: 调用 main.py 的 _legacy_extract_cad_spec(llm_spec=None),
    得到与原单路径正则分支完全一致的 spec (含默认值填充与法兰孔显式化)。"""
    chain = ReasoningChain("cad_tot_regex", "正则管道内部提取")
    fn = _get_main_attr("_legacy_extract_cad_spec")
    try:
        if fn is None:
            return {"source": "regex", "spec": None, "available": False,
                    "note": "main._legacy_extract_cad_spec 不可导入", "defaulted": []}
        part_type, params, defaulted, _rx = fn(message, message.lower(), None, chain)
        spec = {"part_type": part_type, "params": dict(params or {}),
                "material": None, "quantity": None, "surface_treatment": None}
        ok = bool(part_type) and bool(params)
        return {"source": "regex", "spec": spec if ok else None, "available": ok,
                "note": f"正则提取{len(_rx)}项, 默认值填充{len(defaulted)}项",
                "defaulted": defaulted}
    except Exception as e:
        return {"source": "regex", "spec": None, "available": False,
                "note": f"正则管道异常: {e}", "defaulted": []}


# ══════════════════════════════════════════════════
# 候选管道 3: 结构化直填管道 (请求自带表单字段时适用)
# ══════════════════════════════════════════════════

def pipeline_structured_candidate(structured_spec: dict) -> dict:
    """结构化直填候选: 请求body自带 part_type/params 时直接构造并经schema校验。"""
    if not isinstance(structured_spec, dict):
        return {"source": "structured", "spec": None, "available": False,
                "note": "请求未携带结构化参数"}
    pt = structured_spec.get("part_type")
    params = structured_spec.get("params") or {}
    if not pt or not isinstance(params, dict) or not params:
        return {"source": "structured", "spec": None, "available": False,
                "note": "请求未携带结构化参数(part_type/params缺失)"}
    cleaned = _validate({"part_type": pt, "params": params,
                         "material": structured_spec.get("material"),
                         "quantity": structured_spec.get("quantity"),
                         "surface_treatment": structured_spec.get("surface_treatment")})
    if not cleaned or not cleaned.get("params"):
        return {"source": "structured", "spec": None, "available": False,
                "note": "结构化参数未通过 validate_part_spec"}
    return {"source": "structured", "spec": cleaned, "available": True,
            "note": "请求自带结构化参数直填", "defaulted": []}


# ══════════════════════════════════════════════════
# 打分函数 (0~1 置信度 + 分项明细)
# ══════════════════════════════════════════════════

def _score_schema(spec: dict) -> dict:
    """schema合法性: validate_part_spec 通过、不钳制出界、part_type在白名单、params非空。"""
    v = _validate(spec)
    if not v:
        return {"score": 0.0, "valid": False, "clamped": [],
                "reason": "validate_part_spec 校验失败或part_type不在白名单"}
    clamped = []
    for k, val in (spec.get("params") or {}).items():
        try:
            f = float(val)
        except (TypeError, ValueError):
            continue
        cv = (v.get("params") or {}).get(k)
        if cv is not None and abs(float(cv) - f) > 1e-6:
            clamped.append(f"{k}: {val}→{cv}")
    score = 1.0
    if not v.get("params"):
        score = 0.3
    elif clamped:
        score = max(0.4, 1.0 - 0.2 * len(clamped))
    return {"score": round(score, 3), "valid": True, "clamped": clamped,
            "reason": "schema合法" + (f", 钳制{len(clamped)}项" if clamped else ", 无钳制")}


def _score_coverage(message: str, spec: dict) -> dict:
    """文本覆盖率: 原句中的数字与特征关键词被 params 覆盖的比例。"""
    params = spec.get("params") or {}
    pvals = []
    for v in params.values():
        try:
            pvals.append(float(v))
        except (TypeError, ValueError):
            pass

    def _near(a, b, rel=0.02):
        return abs(a - b) <= max(1e-9, rel * max(abs(a), abs(b)))

    nums = re.findall(r"\d+(?:\.\d+)?", message or "")
    num_hit = sum(1 for t in nums if any(_near(float(t), pv) for pv in pvals))
    num_score = (num_hit / len(nums)) if nums else 1.0

    # 特征关键词: 原句提及且 params 中对应项存在 → 覆盖
    kws = [("外径", "od"), ("直径", "od"), ("内径", "id"), ("中心孔", "id"), ("内孔", "id"),
           ("厚度", "thickness"), ("螺栓孔", "bolt_holes"), ("通孔", "bolt_holes"),
           ("孔径", "bolt_d"), ("分度圆", "bolt_pcd"), ("分布圆", "bolt_pcd"), ("PCD", "bolt_pcd"),
           ("长度", "length"), ("宽", "w"), ("高", "h")]
    msg = message or ""
    msg_upper = msg.upper()
    present, covered = [], []
    for kw, key in kws:
        hit = (kw in msg) if kw != "PCD" else ("PCD" in msg_upper)
        if not hit:
            continue
        if key not in present:
            present.append(key)
            if key in params:
                covered.append(key)
    kw_score = (len(covered) / len(present)) if present else 1.0
    score = 0.6 * num_score + 0.4 * kw_score
    return {"score": round(min(1.0, max(0.0, score)), 3),
            "detail": {"nums": f"{num_hit}/{len(nums)}", "keywords": f"{len(covered)}/{len(present)}",
                       "uncovered": [k for k in present if k not in covered]}}


def _flange_analytic_volume_mm3(params: dict) -> float:
    """法兰闭式解析体积: π/4(od²−id²)t − n·π/4·d²·t (mm³)。"""
    od = float(params.get("od", 0) or 0)
    id_ = float(params.get("id", 0) or 0)
    t = float(params.get("thickness", 0) or 0)
    n = int(params.get("bolt_holes", 0) or 0)
    d = float(params.get("bolt_d", 0) or 0)
    v = math.pi / 4.0 * (od * od - id_ * id_) * t
    if n > 0 and d > 0:
        v -= n * math.pi / 4.0 * d * d * t
    return v


def _score_geometry(spec: dict) -> dict:
    """几何一致性: OCC试算体积 vs 闭式解析解 (flange)。
    偏差<1%满分, >5%记0分, 其间线性插值。同时返回试算STEP路径(winner即正式产物)。"""
    pt = spec.get("part_type")
    params = spec.get("params") or {}
    if pt != "flange" or not occ_available():
        return {"score": None, "note": "非flange或OCC不可用, 仅用schema+覆盖率", "step_path": None}
    analytic = _flange_analytic_volume_mm3(params)
    if analytic <= 0:
        return {"score": 0.0, "note": "解析体积非正, 参数不合法", "step_path": None}
    try:
        res = generate_part_occ(pt, dict(params))
    except Exception as e:
        return {"score": 0.0, "note": f"OCC试算异常: {e}", "step_path": None}
    if not isinstance(res, dict) or "error" in res:
        return {"score": 0.0, "note": f"OCC试算失败: {(res or {}).get('error')}", "step_path": None}
    occ_vol = float(res.get("volume_mm3", 0) or 0)
    dev = abs(occ_vol - analytic) / analytic
    if dev < 0.01:
        gs = 1.0
    elif dev > 0.05:
        gs = 0.0
    else:
        gs = round(1.0 - (dev - 0.01) / 0.04, 3)
    return {"score": gs, "analytic_mm3": round(analytic, 1), "occ_mm3": occ_vol,
            "dev_pct": round(dev * 100, 2),
            "bbox": res.get("bounding_box_mm"), "step_path": res.get("step_file"),
            "note": f"OCC实测 vs 解析解偏差{dev * 100:.2f}%"}


def _score_bbox(spec: dict, occ_result_detail: dict) -> dict:
    """bbox合理性: flange的 od/thickness 与 OCC实测bbox一致。"""
    if spec.get("part_type") != "flange":
        return {"score": None, "note": "非flange不校验bbox"}
    bbox = (occ_result_detail or {}).get("bbox")
    if not bbox:
        return {"score": 0.0, "note": "无OCC bbox可比对"}
    params = spec.get("params") or {}
    od = float(params.get("od", 0) or 0)
    t = float(params.get("thickness", 0) or 0)
    sxy = 1.0 if od > 0 and abs(bbox[0] - od) <= 0.5 and abs(bbox[1] - od) <= 0.5 else 0.0
    sz = 1.0 if t > 0 and abs(bbox[2] - t) <= 0.5 else 0.0
    return {"score": round(0.7 * sxy + 0.3 * sz, 3), "bbox": bbox, "expected": [od, od, t]}


def score_candidate(message: str, cand: dict) -> dict:
    """单候选打分 → {confidence: 0~1, detail: 分项明细}。"""
    base = {"source": cand.get("source"), "available": bool(cand.get("available"))}
    if not cand.get("available") or not isinstance(cand.get("spec"), dict):
        base.update({"confidence": UNAVAILABLE_SCORE,
                     "detail": {"note": cand.get("note") or "候选不可用"}})
        return base
    spec = cand["spec"]
    schema = _score_schema(spec)
    if not schema["valid"]:
        base.update({"confidence": UNAVAILABLE_SCORE, "detail": {"schema": schema}})
        return base
    cover = _score_coverage(message, spec)
    geom = _score_geometry(spec) if spec.get("part_type") == "flange" else \
        {"score": None, "note": "非flange, 仅用schema+覆盖率", "step_path": None}
    bbox = _score_bbox(spec, geom)
    if geom.get("score") is not None and bbox.get("score") is not None:
        conf = (W_SCHEMA * schema["score"] + W_COVER * cover["score"]
                + W_GEOM * geom["score"] + W_BBOX * bbox["score"])
    else:
        conf = 0.5 * schema["score"] + 0.5 * cover["score"]
    base.update({"confidence": round(min(1.0, max(0.0, conf)), 3),
                 "detail": {"schema": schema, "coverage": cover,
                            "geometry": geom, "bbox": bbox}})
    return base


# ══════════════════════════════════════════════════
# TOT 竞争主流程
# ══════════════════════════════════════════════════

def _cleanup_temp_steps(scored: list, winner: dict):
    """清理非winner候选的临时STEP。确定性文件名特性: winner的试算产物即正式产物,
    后续 generate_part(winner params) 会写出同名文件(直接复用)。与winner同参数的
    候选共享同一文件, 不得删除。"""
    wp = json.dumps({"t": (winner or {}).get("part_type"),
                     "p": (winner or {}).get("params")}, sort_keys=True, default=str)
    keep, removed = set(), []
    for sc in scored:
        sp = (((sc.get("detail") or {}).get("geometry") or {}).get("step_path"))
        if not sp:
            continue
        same = json.dumps({"t": sc.get("part_type"), "p": sc.get("params")},
                          sort_keys=True, default=str) == wp
        if same:
            keep.add(sp)
            continue
        if sp in keep:
            continue
        try:
            if os.path.exists(sp):
                os.remove(sp)
                removed.append(sp)
        except OSError as e:
            print(f"[TOT] 清理临时STEP失败: {sp} ({e})")
    if removed:
        print(f"[TOT] 已清理非winner临时STEP {len(removed)}个")
    return removed


def run_tot_competition(message: str, structured_spec: dict = None) -> dict:
    """TOT竞争主入口: 候选收集 → 逐条打分 → 择优winner + cad_tot推理链。
    返回 dict(part_spec, winner, candidates, chain_dict, defaulted, scoreboard, ...)；
    无任何可用候选时 part_spec=None (调用方回退原单路径)。"""
    chain = ReasoningChain("cad_tot", f"TOT多画图管道竞争: 候选打分择优 | {message[:60]}")

    candidates = []
    candidates.extend(pipeline_llm_candidates(message))
    candidates.append(pipeline_regex_candidate(message))
    candidates.append(pipeline_structured_candidate(structured_spec))

    scored = []
    for cand in candidates:
        sc = score_candidate(message, cand)
        spec = cand.get("spec") or {}
        sc["part_type"] = spec.get("part_type")
        sc["params"] = spec.get("params")
        sc["spec"] = spec if cand.get("available") else None
        sc["note"] = cand.get("note")
        sc["defaulted"] = cand.get("defaulted") or []
        scored.append(sc)
        det = sc.get("detail") or {}
        chain.add_step(
            StepType.INFERENCE, f"候选管道: {sc['source']}",
            (f"置信度={sc['confidence']:.3f} ({'可用' if sc['available'] else '不可用'}); "
             + (f"分项: {json.dumps(det, ensure_ascii=False, default=str)[:500]}"
                if sc["available"] else f"原因: {sc.get('note') or det.get('note')}")),
            evidence={"confidence": sc["confidence"], "available": sc["available"],
                      "part_type": sc.get("part_type"), "params": sc.get("params"),
                      "detail": det},
            confidence=sc["confidence"], source=f"pipeline:{sc['source']}")

    viable = [s for s in scored if s["available"] and s.get("spec")]
    if not viable:
        chain.add_warning("所有候选管道均不可用 — 调用方应回退原单路径", severity="warning")
        chain.add_conclusion("TOT竞争失败: 无可用候选管道", confidence=0.0,
                             rationale="LLM/正则/结构化管道均未产出有效spec")
        chain_dict = get_chain(register_chain(chain))
        print(f"[TOT] 无可用候选管道 (message={message[:40]})")
        return {"part_spec": None, "winner": None, "candidates": scored,
                "chain_dict": chain_dict, "total_candidates": len(scored), "defaulted": [],
                "scoreboard": [{"source": s["source"], "confidence": s["confidence"],
                                "available": s["available"]} for s in scored]}

    winner = max(viable, key=lambda s: s["confidence"])
    n_comp = len(viable)
    chain.add_step(
        StepType.CONCLUSION, f"Winner: {winner['source']}管道",
        f"{n_comp}条可用候选中置信度最高 ({winner['confidence']:.3f}) → 作为默认执行路径；"
        f"最终参数: {json.dumps(winner.get('params'), ensure_ascii=False, default=str)[:300]}",
        evidence={"winner": winner["source"], "confidence": winner["confidence"],
                  "part_type": winner.get("part_type"), "params": winner.get("params"),
                  "candidates": n_comp},
        confidence=winner["confidence"], source="cad_tot")
    chain.overall_confidence = winner["confidence"]
    chain_dict = get_chain(register_chain(chain))

    _cleanup_temp_steps(scored, winner)

    scoreboard = [{"source": s["source"], "confidence": s["confidence"],
                   "available": s["available"]} for s in scored]
    print(f"[TOT] winner={winner['source']} confidence={winner['confidence']:.3f} "
          f"(候选{n_comp}条可用/共{len(scored)}条) params={winner.get('params')}")
    return {
        "part_spec": winner["spec"],
        "winner": {"source": winner["source"], "confidence": winner["confidence"],
                   "note": winner.get("note")},
        "candidates": scored,
        "chain_dict": chain_dict,
        "total_candidates": len(scored),
        "defaulted": winner.get("defaulted") or [],
        "scoreboard": scoreboard,
    }


def format_score_table(result: dict) -> str:
    """格式化TOT打分表 (演示/测试展示用)。"""
    lines = ["┌─ TOT 打分表 " + "─" * 60,
             f"│ {'候选管道':<14} {'置信度':>6}  {'schema':>6} {'覆盖率':>6} {'几何':>6} {'bbox':>6}  状态"]
    winner_src = ((result.get("winner") or {}).get("source"))
    for sc in result.get("candidates", []):
        det = sc.get("detail") or {}
        def _fmt(d, k):
            v = (d.get(k) or {}).get("score") if isinstance(d.get(k), dict) else None
            return f"{v:.2f}" if isinstance(v, (int, float)) else "  - "
        mark = "★winner" if sc["source"] == winner_src else ("不可用" if not sc["available"] else "")
        lines.append(f"│ {sc['source']:<14} {sc['confidence']:>6.3f}  "
                     f"{_fmt(det, 'schema'):>6} {_fmt(det, 'coverage'):>6} "
                     f"{_fmt(det, 'geometry'):>6} {_fmt(det, 'bbox'):>6}  {mark}")
    lines.append("└" + "─" * 74)
    return "\n".join(lines)

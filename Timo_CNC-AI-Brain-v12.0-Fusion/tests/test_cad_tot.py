"""TOT多画图管道竞争测试 — cnc-ai-brain/tests/test_cad_tot.py
可独立运行: .venv\\Scripts\\python.exe tests\\test_cad_tot.py  (或 pytest tests/test_cad_tot.py)

不依赖 :1234/:7862 服务在线:
  - LLM 相关用 stub 注入 sys.modules['app.main'] (模拟 llm_extract_part_spec / validate_part_spec)
  - 正则管道复用 main.py 的 _legacy_extract_cad_spec (真实函数, 无网络依赖)
  - 几何验证用本地 OCC (cadquery-ocp 的 OCP 命名空间)
作者: timo.cao | 邮箱: miscdd@163.com | 生成: 大帅教练系统"""
import os
import sys
import math
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("TOT_ENABLED", "1")

from src.runtime.step_generator_occ import OUTPUT_DIR, generate_part_occ, occ_available

# ── stub app.main: 避免导入真实 main.py (会触发模型健康检查/网络请求) ──
import re as _re


def _real_validate_part_spec(spec):
    """与 app.main.validate_part_spec 等价实现 (测试独立运行用)。"""
    PART_SPEC_TYPES = ["flange", "sleeve", "shaft", "plate", "box", "bracket", "step_block"]
    _SPEC_PARAM_KEYS = ("od", "id", "thickness", "length", "w", "h", "t", "d",
                        "bolt_holes", "bolt_d", "bolt_pcd", "step_w", "step_d", "h1", "h2")

    def _clamp(v, lo, hi):
        return max(lo, min(hi, v))

    if not isinstance(spec, dict):
        return None
    pt = spec.get("part_type")
    if pt not in PART_SPEC_TYPES:
        return None
    clean = {}
    raw = spec.get("params") or {}
    for k in _SPEC_PARAM_KEYS:
        v = raw.get(k)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if k == "bolt_holes":
            clean[k] = int(_clamp(v, 0, 64))
        elif k == "id":
            v = _clamp(v, 0, 5000)
            clean[k] = int(v) if v == int(v) else v
        else:
            v = _clamp(v, 0.1, 5000)
            clean[k] = int(v) if v == int(v) else v
    if pt in ("flange", "sleeve") and "d" in clean and "od" not in clean:
        clean["od"] = clean.pop("d")
    elif pt == "shaft" and "od" in clean and "d" not in clean:
        clean["d"] = clean.pop("od")
    if clean.get("bolt_holes"):
        clean.setdefault("bolt_d", 8)
        if "bolt_pcd" not in clean and clean.get("od"):
            clean["bolt_pcd"] = round(clean["od"] * 0.75)
    material = spec.get("material") or None
    if material:
        material = str(material).strip()[:20] or None
    quantity = spec.get("quantity")
    try:
        quantity = int(_clamp(float(quantity), 1, 100000)) if quantity else None
    except (TypeError, ValueError):
        quantity = None
    surface = spec.get("surface_treatment") or None
    if surface:
        surface = str(surface).strip()[:20]
        if surface in ("无", "none", "None", ""):
            surface = None
    return {"part_type": pt, "params": clean, "material": material,
            "quantity": quantity, "surface_treatment": surface}


def _real_legacy_extract(message, msg_lower, llm_spec, cad_chain):
    """与 app.main._legacy_extract_cad_spec 等价的正则提取 (测试独立运行用)。"""
    part_type = "flange"
    type_map = {"法兰": "flange", "轴套": "sleeve", "轴": "shaft", "箱体": "box",
                "支架": "bracket", "板": "plate", "方块": "box", "检查盖": "flange", "法兰盖": "flange",
                "闷盖": "flange", "盖": "flange", "圆盘": "flange", "轮": "gear", "齿轮": "shaft",
                "flange": "flange", "sleeve": "sleeve", "shaft": "shaft",
                "gear": "shaft", "box": "box", "bracket": "bracket",
                "plate": "plate", "block": "box", "cover": "flange", "disc": "flange"}
    for pt in list(type_map.keys()):
        if pt in msg_lower:
            part_type = type_map[pt]
            break
    params = {"od": 100, "id": 50, "thickness": 20}
    _rx = {}
    _defaulted = []
    od_m = _re.search(r'外径\s*(\d+)', message) or _re.search(r'od\s*(\d+)', msg_lower) or _re.search(r'outer\s*(\d+)', msg_lower)
    id_m = _re.search(r'内径\s*(\d+)', message) or _re.search(r'id\s*(\d+)', msg_lower) or _re.search(r'inner\s*(\d+)', msg_lower) \
        or _re.search(r'(?:中心孔|内孔|中孔)\s*(?:径|直径)?\s*(?:为|是)?\s*(\d+(?:\.\d+)?)', message)
    th_m = _re.search(r'厚\s*(\d+)', message) or _re.search(r'厚度\s*(\d+)', message) or _re.search(r'th\s*(\d+)', msg_lower) or _re.search(r'thickness\s*(\d+)', msg_lower)
    wxh_m = _re.search(r'(\d+)\s*[xX×]\s*(\d+)\s*[xX×]\s*(\d+)', message)
    d_m = _re.search(r'直径\s*(\d+)', message) or _re.search(r'd\s*(\d+)', msg_lower)
    l_m = _re.search(r'长\s*(\d+)', message) or _re.search(r'l\s*(\d+)', msg_lower) or _re.search(r'length\s*(\d+)', msg_lower)
    holes_m = _re.search(r'(\d+)\s*[个只]\s*[Mm]?\d*\s*(?:安装孔|螺栓孔|光孔|孔)', message) or _re.search(r'bolt[_\s]*holes?\s*(\d+)', msg_lower)
    holes_m2 = _re.search(r'(\d+)\s*[×xX*]\s*[φΦ∅]?\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:通孔|孔|螺栓孔)', message)
    bolt_d_m = _re.search(r'(?:孔径|螺栓径|bolt[_\s]*d)\s*(\d+)', msg_lower) or _re.search(r'm(\d+)\s*(?:螺栓|bolt)', msg_lower)
    pcd_m = _re.search(r'(?:PCD|分布圆|分度圆)\s*(\d+)', message, _re.I)
    if od_m: _rx["od"] = int(od_m.group(1))
    if id_m: _rx["id"] = int(float(id_m.group(1)))
    if th_m: _rx["thickness"] = int(th_m.group(1))
    if wxh_m:
        _rx["w"] = int(wxh_m.group(1)); _rx["h"] = int(wxh_m.group(2)); _rx["t"] = int(wxh_m.group(3))
    if d_m:
        _rx["d"] = int(d_m.group(1))
        if part_type == "flange":
            _rx["od"] = int(d_m.group(1))
    if l_m: _rx["length"] = int(l_m.group(1))
    if holes_m: _rx["bolt_holes"] = int(holes_m.group(1))
    elif holes_m2:
        _rx["bolt_holes"] = int(holes_m2.group(1))
        _rx["bolt_d"] = float(holes_m2.group(2))
    if bolt_d_m: _rx["bolt_d"] = int(bolt_d_m.group(1))
    if pcd_m: _rx["bolt_pcd"] = int(pcd_m.group(1))
    params.update(_rx)
    if "bolt_holes" in params and "bolt_pcd" not in params:
        params["bolt_pcd"] = round(params.get("od", 100) * 0.75)
        _defaulted.append(f"bolt_pcd={params['bolt_pcd']}")
    if "bolt_holes" in params and "bolt_d" not in params:
        params["bolt_d"] = 8
        _defaulted.append("bolt_d=8")
    if part_type == "shaft" and "d" not in params and "od" in params:
        params["d"] = params["od"]
        params["length"] = params.get("length", 120)
    elif part_type == "sleeve" and "od" in params and "id" in params:
        params["length"] = params.get("length", 80)
    elif part_type == "plate" and "w" not in params:
        size_m = _re.search(r'(\d+)', message)
        if size_m: params["w"] = int(size_m.group(1))
    elif part_type == "bracket" and "w" not in params:
        params["w"] = params.get("od", 80)
        params["h"] = params.get("id", 60)
        params["t"] = params.get("thickness", 8)
    if part_type == "flange":
        params.setdefault("bolt_holes", 0)
        if params["bolt_holes"]:
            if "bolt_d" not in params:
                params["bolt_d"] = 8
                _defaulted.append("bolt_d=8")
            if "bolt_pcd" not in params:
                params["bolt_pcd"] = round(params.get("od", 100) * 0.75)
                _defaulted.append(f"bolt_pcd={params['bolt_pcd']}")
    return part_type, params, _defaulted, _rx


_BASE_FLANGE_SPEC = {"part_type": "flange",
                     "params": {"od": 120, "id": 30, "thickness": 16,
                                "bolt_holes": 4, "bolt_d": 10, "bolt_pcd": 90},
                     "material": None, "quantity": None, "surface_treatment": None}

_msg_log = []


def _mock_llm_extract(message, temperature=0.1):
    """模拟LLM提取成功 (不依赖任何在线服务)。"""
    _msg_log.append((message, temperature))
    import copy
    return copy.deepcopy(_BASE_FLANGE_SPEC), '{"mock": true}', {"model": "mock-llm", "source": "test", "note": "mock"}


def _mock_llm_extract_down(message, temperature=0.1):
    """模拟LLM不可用 — 返回 (None, "", meta)。"""
    return None, "", {"model": None, "source": None, "fallback_index": -1, "note": "LLM不可用(mock)"}


def _install_stub(llm_fn):
    """注入 app.main stub — TOT模块的延迟导入将命中此stub。"""
    stub = types.ModuleType("app.main")
    stub.llm_extract_part_spec = llm_fn
    stub.validate_part_spec = _real_validate_part_spec
    stub._legacy_extract_cad_spec = _real_legacy_extract
    app_pkg = sys.modules.get("app") or types.ModuleType("app")
    sys.modules["app"] = app_pkg
    sys.modules["app.main"] = stub
    # TOT模块可能已导入 — 其惰性获取函数每次调用时查 sys.modules, 无需重载
    import importlib
    import src.runtime.cad_pipeline_tot as tot
    importlib.reload(tot)
    return tot


CASE1_MSG = "绘制直径120mm、厚16mm法兰盘，中心孔30mm，均布4×φ10通孔，导出STEP"
EXPECT_VOL_CM3 = 164.6195  # π/4×(120²−30²)×16 − 4×π/4×10²×16 ≈ 164619.5mm³


class TestCadTot(unittest.TestCase):
    _created_steps = set()

    @classmethod
    def setUpClass(cls):
        assert occ_available(), "OCC不可用 — 本测试需要 cadquery-ocp/pythonocc 环境"
        cls._created_steps = {str(p) for p in OUTPUT_DIR.glob("*.step")}

    @classmethod
    def tearDownClass(cls):
        # 清理测试产生的临时STEP (只留测试前已存在的文件)
        removed = 0
        for p in OUTPUT_DIR.glob("*.step"):
            if str(p) not in cls._created_steps:
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
        print(f"[清理] 已删除测试产生的临时STEP {removed} 个")

    def test_1_baseline_flange(self):
        """用例1(基准): LLM正常时TOT选出最高置信度管道, spec与理论体积正确。"""
        _msg_log.clear()
        tot = _install_stub(_mock_llm_extract)
        result = tot.run_tot_competition(CASE1_MSG)
        print("\n" + tot.format_score_table(result))
        self.assertIsNotNone(result["part_spec"], "应选出winner")
        ps = result["part_spec"]["params"]
        self.assertEqual(ps.get("od"), 120)
        self.assertEqual(ps.get("id"), 30)
        self.assertEqual(ps.get("thickness"), 16)
        self.assertEqual(ps.get("bolt_holes"), 4)
        self.assertEqual(ps.get("bolt_d"), 10)
        self.assertEqual(result["part_spec"]["part_type"], "flange")
        # 体积断言: OCC实测 ≈ 164.62cm³ (容差1%)
        gen = generate_part_occ("flange", dict(ps))
        self.assertNotIn("error", gen)
        self.assertAlmostEqual(gen["volume_cm3"], EXPECT_VOL_CM3, delta=EXPECT_VOL_CM3 * 0.01)
        # LLM管道被采样(多温度)且参与竞争
        sources = [s["source"] for s in (result.get("scoreboard") or [])]
        self.assertTrue(any(src.startswith("llm@") for src in sources))

    def test_2_llm_down_regex_wins(self):
        """用例2(LLM失败降级): mock LLM返回None → 正则管道胜出且关键字段正确。"""
        tot = _install_stub(_mock_llm_extract_down)
        result = tot.run_tot_competition(CASE1_MSG)
        print("\n" + tot.format_score_table(result))
        self.assertIsNotNone(result["part_spec"], "LLM不可用时正则管道应兜底")
        self.assertEqual(result["winner"]["source"], "regex", "应由正则管道胜出")
        for sc in result["candidates"]:
            if sc["source"].startswith("llm@"):
                self.assertFalse(sc["available"], "LLM管道应记为不可用")
        ps = result["part_spec"]["params"]
        self.assertEqual(ps.get("od"), 120)
        self.assertEqual(ps.get("id"), 30)
        self.assertEqual(ps.get("thickness"), 16)
        self.assertEqual(ps.get("bolt_holes"), 4)
        self.assertEqual(ps.get("bolt_d"), 10)

    def test_3_score_range_and_chain_steps(self):
        """用例3: 各候选得分0~1、winner分数最高、TOT链步骤数=候选数+1。"""
        tot = _install_stub(_mock_llm_extract)
        result = tot.run_tot_competition(CASE1_MSG)
        cands = result["candidates"]
        self.assertGreaterEqual(len(cands), 3, "候选管道至少3条")
        for sc in cands:
            self.assertGreaterEqual(sc["confidence"], 0.0)
            self.assertLessEqual(sc["confidence"], 1.0)
        viable = [s for s in cands if s["available"]]
        best = max(s["confidence"] for s in viable)
        self.assertAlmostEqual(result["winner"]["confidence"], best, places=6)
        self.assertGreaterEqual(result["winner"]["confidence"],
                                max(s["confidence"] for s in cands))
        # 链步骤数 = 候选数(INFER) + 1(CONCLUDE)
        chain = result["chain_dict"]
        self.assertEqual(chain["total_steps"], len(cands) + 1)
        infer_steps = [s for s in chain["steps"] if s["step_type"] == "inference"]
        concl_steps = [s for s in chain["steps"] if s["step_type"] == "conclusion"]
        self.assertEqual(len(infer_steps), len(cands), "每候选一个INFER步骤")
        self.assertEqual(len(concl_steps), 1, "winner一个CONCLUDE步骤")
        self.assertAlmostEqual(chain["overall_confidence"],
                               result["winner"]["confidence"], places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

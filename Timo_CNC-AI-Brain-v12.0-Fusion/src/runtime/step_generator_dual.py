"""双引擎自动路由 — OCC (B-Rep精确) + trimesh (三角网格预览)
启动时自动检测OCC可用性，可用则优先OCC，不可用降级trimesh。
对用户透明 — 同一个 generate_part() 签名。
作者: timo.cao | 邮箱: miscdd@163.com | 生成: 大帅教练系统"""
from pathlib import Path
from typing import Optional

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "step"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# trimesh 后备引擎
from src.runtime.step_generator import generate_part as _trimesh_generate, PART_GENERATORS

# OCC 精确引擎
from src.runtime.step_generator_occ import generate_part_occ, occ_available, occ_status

# === 双引擎路由 ===
_current_engine = None  # 测试时懒加载

def get_engine_status() -> dict:
    """返回当前引擎状态。"""
    global _current_engine
    occ_ok = occ_available()

    # 测试OCC一次
    if occ_ok and _current_engine is None:
        try:
            test = generate_part_occ("flange", {"od": 50, "id": 25, "thickness": 10})
            if "error" not in test:
                _current_engine = "OCC"
            else:
                _current_engine = "trimesh"
        except Exception:
            _current_engine = "trimesh"
    elif not occ_ok:
        _current_engine = "trimesh"
    elif _current_engine is None:
        _current_engine = "trimesh"

    return {
        "engine": _current_engine or "trimesh",
        "occ_available": occ_ok,
        "trimesh_available": True,
        "occ_parts": occ_status()["parts"] if occ_ok else [],
        "trimesh_parts": list(PART_GENERATORS.keys()),
    }


def generate_part(part_type: str, params: dict) -> dict:
    """统一入口 — 自动选最优引擎。
    OCC可用 → OCC (B-Rep精确STEP)
    OCC不可用 → trimesh (三角网格STEP+STL预览)
    """
    global _current_engine
    occ_ok = occ_available()

    # 先试OCC — 生成B-Rep STEP (CAM加工)
    occ_result = None
    if occ_ok:
        try:
            occ_result = generate_part_occ(part_type, params)
            if "error" in occ_result:
                occ_result = None
        except Exception:
            occ_result = None

    # 同时生成 trimesh STL (3D预览用浏览器渲染)
    stl_result = None
    try:
        stl_result = _trimesh_generate(part_type, params)
        if "error" in stl_result:
            stl_result = None
    except Exception:
        pass

    if occ_result:
        _current_engine = "OCC"
        occ_result["engine"] = "OCC"
        occ_result["stl_url"] = stl_result.get("stl_url") if stl_result else None
        occ_result["note"] = "B-Rep精确几何 — CAM可直接加工"
        return occ_result

    # OCC不可用 → trimesh
    _current_engine = "trimesh"
    if stl_result:
        stl_result["engine"] = "trimesh"
        stl_result["note"] = "三角网格近似 — 预览用，CAM需导出为B-Rep"
        return stl_result

    return {"error": f"所有引擎均无法生成: {part_type}"}


def generate_preview(part_type: str, params: dict) -> str:
    """生成STL预览文件 (始终用trimesh, 浏览器需要三角网格)。"""
    return _trimesh_generate(part_type, params).get("stl_url", "")

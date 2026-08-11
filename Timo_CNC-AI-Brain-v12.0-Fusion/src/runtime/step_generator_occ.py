"""STEP Generator OCC — 使用 OpenCASCADE 生成 B-Rep 精确 STEP
支持: flange, sleeve, shaft, plate, box, bracket
用OCC生成时STEP文件是精确几何（不是三角网格），CAM软件直接出刀路。

双命名空间兼容:
  - pythonocc-core → OCC.Core.*
  - cadquery-ocp   → OCP.* (pip可装, OCC 7.9内核)
作者: timo.cao | 邮箱: miscdd@163.com | 生成: 大帅教练系统"""
import os, math, json, tempfile, importlib, hashlib
from pathlib import Path

# ── OCC 导入 — 双命名空间容错 (OCC.Core → OCP) ──
_OCC_AVAILABLE = False
_OCC_NS = None
try:
    try:
        importlib.import_module("OCC.Core.gp")
        _NS = "OCC.Core"
    except ImportError:
        importlib.import_module("OCP.gp")
        _NS = "OCP"

    def _imp(mod, *names):
        m = importlib.import_module(f"{_NS}.{mod}")
        return tuple(getattr(m, n) for n in names)

    BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism = _imp(
        "BRepPrimAPI", "BRepPrimAPI_MakeCylinder", "BRepPrimAPI_MakeBox", "BRepPrimAPI_MakePrism")
    gp_Ax2, gp_Pnt, gp_Dir, gp_Circ, gp_Pln, gp_Vec, gp_Trsf = _imp(
        "gp", "gp_Ax2", "gp_Pnt", "gp_Dir", "gp_Circ", "gp_Pln", "gp_Vec", "gp_Trsf")
    BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse = _imp(
        "BRepAlgoAPI", "BRepAlgoAPI_Cut", "BRepAlgoAPI_Fuse")
    STEPControl_Writer, STEPControl_AsIs = _imp(
        "STEPControl", "STEPControl_Writer", "STEPControl_AsIs")
    BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform = _imp(
        "BRepBuilderAPI", "BRepBuilderAPI_MakeEdge", "BRepBuilderAPI_MakeWire",
        "BRepBuilderAPI_MakeFace", "BRepBuilderAPI_Transform")
    Geom_CylindricalSurface = _imp("Geom", "Geom_CylindricalSurface")[0]
    TopoDS_Shape = _imp("TopoDS", "TopoDS_Shape")[0]
    Bnd_Box = _imp("Bnd", "Bnd_Box")[0]
    try:
        brepbndlib = _imp("BRepBndLib", "brepbndlib")[0]  # pythonocc: 模块级
    except AttributeError:
        brepbndlib = _imp("BRepBndLib", "BRepBndLib")[0]  # OCP: 类(静态Add)
    BRepGProp = _imp("BRepGProp", "BRepGProp")[0]
    GProp_GProps = _imp("GProp", "GProp_GProps")[0]
    _OCC_AVAILABLE = True
    _OCC_NS = _NS
except ImportError:
    pass

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "step"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_OCC_GENERATORS = {}


def occ_available() -> bool:
    """检查OCC是否可用。"""
    return _OCC_AVAILABLE


def register_occ(name):
    """注册一个OCC零件生成器。"""
    def dec(fn):
        _OCC_GENERATORS[name] = fn
        return fn
    return dec


def _make_step(shape, filename: str) -> str:
    """将OCC Shape导出为STEP文件。"""
    filepath = str(OUTPUT_DIR / filename)
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    writer.Write(filepath)
    return filepath


def _bbox(shape) -> tuple:
    """计算OCC Shape的包围盒."""
    b = Bnd_Box()
    try:
        brepbndlib.Add(shape, b)    # pythonocc
    except AttributeError:
        brepbndlib.Add_s(shape, b)  # OCP静态方法 _s 后缀
    xmin, ymin, zmin, xmax, ymax, zmax = b.Get()
    return (round(xmax - xmin, 1), round(ymax - ymin, 1), round(zmax - zmin, 1))


def _exact_volume_mm3(shape) -> float:
    """B-Rep精确体积 (GProp积分) — 非包围盒估算。"""
    try:
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        return props.Mass()
    except Exception:
        return 0.0


def _result(shape, part_type: str, params: dict) -> dict:
    """统一结果格式 — 与 trimesh 生成器兼容 + 精确体积。
    文件名后缀用确定性哈希(排序后params的md5前8位hex)，跨进程可复现；
    GProp失败退化为包围盒乘积时打 volume_warning 标记。"""
    _pk = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    step_name = f"{part_type}_occ_{hashlib.md5(_pk.encode('utf-8')).hexdigest()[:8]}.step"
    step_path = _make_step(shape, step_name)
    bbox = _bbox(shape)
    vol_mm3 = _exact_volume_mm3(shape)
    vol_warn = None
    if vol_mm3 <= 0:  # GProp失败时退化为包围盒估算(非精确值, 必须标记警告)
        vol_mm3 = bbox[0] * bbox[1] * bbox[2]
        vol_warn = "GProp精确体积计算失败，已退化为包围盒乘积估算(体积可能偏大)"
    # OCC STEP是从B-Rep精确几何导出的，文件大小远小于trimesh三角网格
    file_size = os.path.getsize(step_path)
    result = {
        "engine": "OCC",
        "occ_namespace": _OCC_NS,
        "step_file": step_path,
        "file_size_bytes": file_size,
        "bounding_box_mm": list(bbox),
        "volume_mm3": round(vol_mm3, 1),
        "volume_cm3": round(vol_mm3 / 1000.0, 3),
        "params": params,
        "note": "B-Rep精确几何 — CAM可直接加工"
    }
    if vol_warn:
        result["volume_warning"] = True
        result["volume_warning_reason"] = vol_warn
    return result


# ══════════════════════════════════════════════════
# 零件生成器
# ══════════════════════════════════════════════════

@register_occ("flange")
def make_flange(params: dict) -> dict:
    """法兰 — OCC精确B-Rep (支持螺栓孔真实差集)"""
    od = float(params.get("od", 100))
    id_ = float(params.get("id", 50))
    thickness = float(params.get("thickness", 20))
    outer = BRepPrimAPI_MakeCylinder(od / 2.0, thickness).Shape()
    shape = outer
    if id_ > 0:
        inner = BRepPrimAPI_MakeCylinder(id_ / 2.0, thickness).Shape()
        shape = BRepAlgoAPI_Cut(shape, inner).Shape()
    # 螺栓孔: 沿PCD圆周均布，真实B-Rep差集
    n_holes = int(params.get("bolt_holes", 0) or 0)
    bolt_d = float(params.get("bolt_d", 0) or 0)
    bolt_pcd = float(params.get("bolt_pcd", 0) or 0)
    if n_holes > 0 and bolt_d > 0 and bolt_pcd > 0:
        for i in range(n_holes):
            angle = 2 * math.pi * i / n_holes
            bx = bolt_pcd / 2.0 * math.cos(angle)
            by = bolt_pcd / 2.0 * math.sin(angle)
            hole = BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(bx, by, -1.0), gp_Dir(0, 0, 1)),
                bolt_d / 2.0, thickness + 2.0).Shape()
            shape = BRepAlgoAPI_Cut(shape, hole).Shape()
    return _result(shape, "flange", params)


@register_occ("sleeve")
def make_sleeve(params: dict) -> dict:
    """轴套 — OCC精确B-Rep"""
    od = float(params.get("od", 60))
    id_ = float(params.get("id", 30))
    length = float(params.get("length", 100))
    outer = BRepPrimAPI_MakeCylinder(od / 2.0, length).Shape()
    inner = BRepPrimAPI_MakeCylinder(id_ / 2.0, length).Shape()
    shape = BRepAlgoAPI_Cut(outer, inner).Shape()
    return _result(shape, "sleeve", params)


@register_occ("shaft")
def make_shaft(params: dict) -> dict:
    """轴 — OCC精确B-Rep (d/od均可指定直径)"""
    diameter = float(params.get("d", params.get("od", 30)))
    length = float(params.get("length", 200))
    shape = BRepPrimAPI_MakeCylinder(diameter / 2.0, length).Shape()
    return _result(shape, "shaft", params)


@register_occ("plate")
def make_plate(params: dict) -> dict:
    """平板 — OCC精确B-Rep (t/thickness均可)"""
    w = float(params.get("w", params.get("width", 150)))
    h = float(params.get("h", params.get("height", 100)))
    t = float(params.get("t", params.get("thickness", 10)))
    shape = BRepPrimAPI_MakeBox(w, h, t).Shape()
    return _result(shape, "plate", params)


@register_occ("box")
def make_box(params: dict) -> dict:
    """箱体 — OCC精确B-Rep (薄壁抽壳)"""
    w = float(params.get("w", params.get("width", 200)))
    h = float(params.get("h", params.get("height", 100)))
    d = float(params.get("d", params.get("depth", 150)))
    thickness = float(params.get("thickness", params.get("t", 5)))
    outer = BRepPrimAPI_MakeBox(w, h, d).Shape()
    inner = BRepPrimAPI_MakeBox(w - 2 * thickness, h - 2 * thickness, d - 2 * thickness).Shape()
    tr = gp_Trsf()
    tr.SetTranslation(gp_Vec(thickness, thickness, thickness))
    inner_moved = BRepBuilderAPI_Transform(inner, tr).Shape()
    shape = BRepAlgoAPI_Cut(outer, inner_moved).Shape()
    return _result(shape, "box", params)


@register_occ("bracket")
def make_bracket(params: dict) -> dict:
    """支架 — OCC精确B-Rep (近似: 平板+立板)"""
    w = float(params.get("w", 80))
    h = float(params.get("h", 120))
    t = float(params.get("t", params.get("thickness", 10)))
    base = BRepPrimAPI_MakeBox(w, 30, t).Shape()
    wall = BRepPrimAPI_MakeBox(t, h, w).Shape()
    tr = gp_Trsf()
    tr.SetTranslation(gp_Vec(0, 30, 0))
    wall_moved = BRepBuilderAPI_Transform(wall, tr).Shape()
    shape = BRepAlgoAPI_Fuse(base, wall_moved).Shape()
    return _result(shape, "bracket", params)


def generate_part_occ(part_type: str, params: dict) -> dict:
    """OCC统一入口 — 与trimesh generate_part相同签名。"""
    gen = _OCC_GENERATORS.get(part_type)
    if not gen:
        return {"error": f"OCC不支持: {part_type}", "available": list(_OCC_GENERATORS.keys())}
    try:
        return gen(params)
    except Exception as e:
        return {"error": f"OCC生成失败: {e}"}


def get_occ_parts() -> list:
    """可用OCC零件类型列表。"""
    return list(_OCC_GENERATORS.keys())


def occ_status() -> dict:
    """OCC引擎状态。"""
    return {
        "available": _OCC_AVAILABLE,
        "namespace": _OCC_NS,
        "parts": get_occ_parts(),
        "engine": f"OCC (B-Rep精确几何, {_OCC_NS})" if _OCC_AVAILABLE else "OCC不可用"
    }

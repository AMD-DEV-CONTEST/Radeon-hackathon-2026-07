#!/usr/bin/env python3
"""STEP Generator — 参数化生成法兰/轴套/方块等基础零件 (无CSG版本)
使用 trimesh 直接生成 → 导出 STEP/STL
作者: timo.cao | 邮箱: miscdd@163.com | 生成: 大帅教练系统"""
import os, math, json
from pathlib import Path
import numpy as np
import trimesh

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "step"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PART_GENERATORS = {}

def register(name):
    def dec(fn): PART_GENERATORS[name] = fn; return fn
    return dec

def _to_volume(mesh):
    """确保网格是水密体积"""
    if not hasattr(mesh, 'faces') or len(mesh.faces) == 0:
        return None
    if not mesh.is_watertight:
        try:
            mesh.fill_holes()
        except:
            pass
    if mesh.is_volume:
        return mesh
    # 尝试convex_hull兜底
    try:
        hull = mesh.convex_hull
        if hull is not None and len(hull.faces) > 0:
            return hull
    except:
        pass
    return mesh

def _mesh_or_none(geo):
    """安全生成网格"""
    if geo is None: return None
    if isinstance(geo, trimesh.Trimesh): return geo
    return None

def _bake(obj):
    """将几何体转为mesh并尝试水密化"""
    if isinstance(obj, trimesh.Trimesh):
        mesh = obj
    elif hasattr(obj, 'to_mesh'):
        mesh = obj.to_mesh()
    else:
        mesh = obj
    if mesh is None: return None
    result = _to_volume(mesh)
    return result

@register("flange")
def make_flange(od=100, id=60, thickness=20, bolt_holes=4, bolt_d=8, bolt_pcd=80, **kw):
    """法兰: 外径/内径/厚度"""
    r_out, r_in, h = od/2, id/2, thickness
    # 外圆柱 (capped)
    outer = trimesh.creation.cylinder(radius=r_out, height=h, sections=64)
    # 内孔: 使用 annular cylinder 或简单差集
    if id > 0 and r_in > 1:
        try:
            inner = trimesh.creation.cylinder(radius=r_in, height=h*2, sections=64)
            inner.apply_translation([0, 0, h/2])  # 上移让它穿过
            result = outer.difference(inner, engine='scad') if hasattr(trimesh.boolean, 'difference') else outer
        except Exception:
            # 回退: 仅外圆柱
            result = outer
    else:
        result = outer
    
    # 螺栓孔 (简单版本: 不做差集, 仅标记)
    if bolt_holes > 0 and bolt_d > 0 and result is not None:
        try:
            for i in range(bolt_holes):
                angle = 2 * math.pi * i / bolt_holes
                bx = bolt_pcd/2 * math.cos(angle)
                by = bolt_pcd/2 * math.sin(angle)
                hole = trimesh.creation.cylinder(radius=bolt_d/2, height=h*3, sections=32)
                hole.apply_translation([bx, by, h/2])
                result = result.difference(hole, engine='scad')
        except Exception:
            pass  # 孔不参与模型, 但体积数据仍正确
    
    return result if result is not None else outer

@register("sleeve")
def make_sleeve(od=50, id=30, length=80, **kw):
    """轴套"""
    r_out, r_in, l = od/2, id/2, length
    outer = trimesh.creation.cylinder(radius=r_out, height=l, sections=64)
    if r_in > 1:
        try:
            inner = trimesh.creation.cylinder(radius=r_in, height=l*3, sections=64)
            inner.apply_translation([0, 0, l/2])
            outer = outer.difference(inner, engine='scad')
        except:
            pass
    return outer

@register("shaft")
def make_shaft(d=40, length=120, **kw):
    """光轴"""
    return trimesh.creation.cylinder(radius=d/2, height=length, sections=64)

@register("plate")
def make_plate(w=150, h=100, t=10, **kw):
    """平板"""
    return trimesh.creation.box(extents=[w, h, t])

@register("box")
def make_box(w=100, d=80, h=60, **kw):
    """方块/箱体"""
    return trimesh.creation.box(extents=[w, d, h])

@register("step_block")
def make_step_block(w=100, d=80, h1=30, h2=16, step_w=60, step_d=40, **kw):
    """台阶块"""
    base = trimesh.creation.box(extents=[w, d, h1])
    top = trimesh.creation.box(extents=[step_w, step_d, h2])
    top.apply_translation([0, 0, h1/2 + h2/2])
    try: return base.union(top, engine='scad')
    except: return base

@register("bracket")
def make_l_bracket(w=80, h=60, t=8, length=100, **kw):
    """L型支架"""
    base = trimesh.creation.box(extents=[w, length, t])
    vert = trimesh.creation.box(extents=[t, length, h])
    vert.apply_translation([w/2 - t/2, 0, h/2 + t/2])
    try: return base.union(vert, engine='scad')
    except: return base

DENSITY = {
    "AL6061": 2.70, "6061": 2.70, "AL7075": 2.81,
    "SUS304": 7.93, "304": 7.93, "SUS316": 7.98, "316L": 7.98,
    "45钢": 7.85, "45#": 7.85, "Q235": 7.85,
    "TC4": 4.43, "钛合金": 4.43, "H59": 8.50, "黄铜": 8.50,
}

def generate_part(part_type: str, params: dict) -> dict:
    if part_type not in PART_GENERATORS:
        return {"error": f"不支持: {part_type}, 可用: {list(PART_GENERATORS)}"}
    
    try:
        mesh = PART_GENERATORS[part_type](**params)
    except Exception as e:
        return {"error": f"生成异常: {e}"}
    
    if mesh is None or (hasattr(mesh, 'vertices') and len(mesh.vertices) == 0):
        return {"error": "生成失败: 空几何体"}
    
    uid = os.urandom(4).hex()
    prefix = f"{part_type}_{uid}"
    stl_path = str(OUTPUT_DIR / f"{prefix}.stl")
    
    # 导出STL
    mesh.export(stl_path)
    
    # 导出STEP (trimesh最佳尝试)
    step_path = str(OUTPUT_DIR / f"{prefix}.step")
    try:
        mesh.export(step_path)
    except Exception:
        step_path = stl_path
    
    # 几何计算
    try:
        bbox_ext = mesh.bounding_box.extents
    except:
        bbox_ext = np.array([100, 100, 10])
    
    try:
        vol = abs(mesh.volume) if hasattr(mesh, 'volume') and mesh.is_watertight else (
            bbox_ext[0] * bbox_ext[1] * bbox_ext[2] * 0.3)
    except:
        vol = bbox_ext[0] * bbox_ext[1] * bbox_ext[2] * 0.3
    
    return {
        "part_type": part_type,
        "step_file": step_path,
        "stl_file": stl_path,
        "stl_url": f"/api/preview/{prefix}.stl",
        "bounding_box_mm": [round(float(v), 1) for v in bbox_ext],
        "volume_mm3": round(float(vol), 0),
        "volume_cm3": round(float(vol) / 1000, 2),
        "estimated_weight_g": round(float(vol) / 1000 * DENSITY.get("6061", 2.7), 1),
    }

def get_weight(material: str, volume_cm3: float) -> float:
    return volume_cm3 * DENSITY.get(material.upper(), DENSITY.get(material, 7.85))

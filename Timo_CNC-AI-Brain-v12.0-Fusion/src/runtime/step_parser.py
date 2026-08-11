#!/usr/bin/env python3
"""STEP Parser — 从STEP文件提取包围盒(CARTESIAN_POINT解析)
复用的 batch_quote.py 核心逻辑, 轻量化版本
作者: timo.cao | 邮箱: miscdd@163.com | 生成: 大帅教练系统"""
import re, os
from pathlib import Path

def detect_file_format(filepath: str) -> str:
    """检测文件实际格式（基于文件内容而非扩展名）"""
    try:
        with open(filepath, 'rb') as f:
            header = f.read(1000)
        
        # 检查常见格式标记（按优先级顺序）
        
        # 1. STEP格式 (ASCII)
        if b'ISO-10303-21' in header or header.strip().startswith(b'ISO-10303'):
            return 'step'
        
        # 2. STL ASCII格式
        if header.strip().startswith(b'solid') and b'facet' in header:
            return 'stl_ascii'
        
        # 3. 二进制STL格式
        if len(header) >= 84:
            import struct
            try:
                num_triangles = struct.unpack('<I', header[80:84])[0]
                expected_size = 80 + 4 + num_triangles * 50
                file_size = os.path.getsize(filepath)
                # 如果文件大小与STL预期大小匹配(±10%)，则认为是二进制STL
                if 0.9 * expected_size <= file_size <= 1.1 * expected_size and num_triangles > 0:
                    return 'stl_binary'
            except Exception:
                pass
        
        # 4. OLE/CFBF格式（Microsoft Compound Document）
        # 魔数: D0 CF 11 E0 A1 B1 1A E1
        if header[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
            return 'ole_cfbf'
        
        # 5. 压缩格式
        if header[:4] == b'PK\x03\x04':
            return 'zip'
        if header[:3] == b'\x1f\x8b\x08':
            return 'gzip'
        if header[:4] == b'Rar!':
            return 'rar'
        
        # 6. IGES格式
        if b'IGES' in header[:20]:
            return 'iges'
        
        # 7. 检查是否是未知的二进制格式
        # 如果文件不包含任何ASCII STEP标记，且大部分是非文本字符，则认为是未知二进制
        text_chars = sum(1 for b in header[:200] if 32 <= b < 127 or b in (9, 10, 13))
        if text_chars < len(header[:200]) * 0.3:  # 少于30%是文本字符
            return 'binary_unknown'
        
        return 'unknown'
    except Exception:
        return 'unknown'


def extract_bbox_from_step(filepath: str) -> dict | None:
    """从STEP/STL文件提取包围盒"""
    filepath_lower = filepath.lower()
    
    # 检测实际文件格式
    actual_format = detect_file_format(filepath)
    print(f"[step_parser] 文件格式检测: {actual_format} (扩展名: {filepath_lower.split('.')[-1]})")
    
    # 如果是OLE/CFBF格式（SolidWorks等CAD软件的原生格式），返回错误信息
    if actual_format == 'ole_cfbf':
        return {
            "error": "文件格式不支持 — 检测到CAD原生格式",
            "detail": "该文件是SolidWorks或其他CAD软件的原生格式（OLE/CFBF），不是标准的STEP格式。文件扩展名虽然为.STEP，但实际内容不是ISO-10303标准STEP格式。",
            "suggestions": [
                "1. 在CAD软件中选择「另存为」或「导出」→ 选择「STEP AP214」或「STEP AP203」格式",
                "2. 确保导出时选择ASCII格式（而非二进制）",
                "3. 或者导出为STL格式（推荐用于3D预览）",
                "4. SolidWorks: 文件 → 另存为 → 选择文件类型为 STEP (*.stp;*.step)",
                "5. CATIA: 文件 → 另存为 → 选择 stp 格式",
                "6. UG/NX: 文件 → 导出 → STEP"
            ],
            "detected_format": actual_format,
            "file_size": os.path.getsize(filepath)
        }
    
    # 如果是未知二进制格式，返回错误信息
    if actual_format == 'binary_unknown':
        return {
            "error": "文件格式不支持 — 检测到未知二进制格式",
            "detail": "该文件是二进制格式，但不是标准的STEP、STL或IGES格式。文件扩展名虽然为.STEP，但实际内容不匹配任何支持的CAD格式。",
            "suggestions": [
                "1. 检查文件是否从CAD软件正确导出（不是保存为原生格式）",
                "2. 在CAD软件中选择「导出」而非「保存」，选择标准STEP格式",
                "3. 或者导出为STL格式（推荐用于3D预览）",
                "4. 检查文件是否损坏或被加密",
                "5. 尝试用其他CAD软件打开并重新导出"
            ],
            "detected_format": actual_format,
            "file_size": os.path.getsize(filepath)
        }
    
    # STL文件处理
    if filepath_lower.endswith('.stl') or actual_format in ('stl_ascii', 'stl_binary'):
        try:
            import trimesh
            mesh = trimesh.load(filepath)
            if hasattr(mesh, 'geometry'):
                meshes = [m for m in mesh.geometry.values() if hasattr(m, 'vertices')]
                if meshes:
                    mesh = trimesh.util.concatenate(meshes)
            if hasattr(mesh, 'bounding_box') and hasattr(mesh, 'vertices') and len(mesh.vertices) > 0:
                bbox_ext = mesh.bounding_box.extents
                bounds = mesh.bounds
                return {
                    "x_min": round(float(bounds[0][0]), 2),
                    "x_max": round(float(bounds[1][0]), 2),
                    "y_min": round(float(bounds[0][1]), 2),
                    "y_max": round(float(bounds[1][1]), 2),
                    "z_min": round(float(bounds[0][2]), 2),
                    "z_max": round(float(bounds[1][2]), 2),
                    "dim_x": round(float(bbox_ext[0]), 2),
                    "dim_y": round(float(bbox_ext[1]), 2),
                    "dim_z": round(float(bbox_ext[2]), 2),
                    "total_points": len(mesh.vertices),
                }
            return None
        except Exception as e:
            return {"error": f"STL解析失败: {e}"}
    
    # STEP文件处理（仅处理文本格式）
    if actual_format != 'step' and actual_format != 'unknown':
        return {
            "error": f"文件格式不匹配",
            "detail": f"文件扩展名是.stp/.step，但实际格式是{actual_format}。",
            "detected_format": actual_format
        }
    
    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read()

        # 优先尝试 OCP 精确读取 STEP 几何（覆盖旋转体退化轴问题）
        try:
            import importlib
            try:
                importlib.import_module('OCP.gp')
                _NS = 'OCP'
            except ImportError:
                importlib.import_module('OCC.Core.gp')
                _NS = 'OCC.Core'

            def _imp(mod, *names):
                m = importlib.import_module(f'{_NS}.{mod}')
                return tuple(getattr(m, n) for n in names)

            STEPControl_Reader = _imp('STEPControl', 'STEPControl_Reader')[0]
            IFSelect_RetDone = _imp('IFSelect', 'IFSelect_RetDone')[0]
            GProp_GProps = _imp('GProp', 'GProp_GProps')[0]
            BRepGProp = _imp('BRepGProp', 'BRepGProp')[0]
            Bnd_Box = _imp('Bnd', 'Bnd_Box')[0]
            try:
                brepbndlib = _imp('BRepBndLib', 'brepbndlib')[0]
            except AttributeError:
                brepbndlib = _imp('BRepBndLib', 'BRepBndLib')[0]

            reader = STEPControl_Reader()
            status = reader.ReadFile(filepath)
            if status == IFSelect_RetDone:
                reader.NbRootsForTransfer()
                reader.TransferRoots()
                shape = reader.OneShape()
                props = GProp_GProps()
                BRepGProp.VolumeProperties_s(shape, props)
                volume_mm3 = props.Mass()
                box = Bnd_Box()
                try:
                    brepbndlib.Add(shape, box)
                except AttributeError:
                    brepbndlib.Add_s(shape, box)
                xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
                return {
                    'x_min': round(xmin, 2),
                    'x_max': round(xmax, 2),
                    'y_min': round(ymin, 2),
                    'y_max': round(ymax, 2),
                    'z_min': round(zmin, 2),
                    'z_max': round(zmax, 2),
                    'dim_x': round(xmax - xmin, 2),
                    'dim_y': round(ymax - ymin, 2),
                    'dim_z': round(zmax - zmin, 2),
                    'total_points': 0,
                    'volume_mm3': round(volume_mm3, 2),
                    'volume_cm3': round(volume_mm3 / 1000, 2),
                    'volume_source': 'ocp_brep',
                }
        except Exception:
            pass

        # 检查是否真的是STEP文本
        if 'ISO-10303-21' not in content and 'CARTESIAN_POINT' not in content:
            return {
                "error": "文件不是有效的STEP格式",
                "detail": "文件内容不包含STEP格式标记（ISO-10303-21）",
                "suggestions": [
                    "1. 从CAD软件重新导出为标准STEP格式",
                    "2. 确认导出时选择ASCII格式（而非二进制）",
                    "3. 尝试导出为其他格式如STL或IGES"
                ]
            }
        
        points = []
        # 模式1: CARTESIAN_POINT('label', (x, y, z))
        pattern1 = r"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(\s*([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)\s*\)"
        for m in re.finditer(pattern1, content):
            points.append((float(m.group(1)), float(m.group(2)), float(m.group(3))))
        
        if not points:
            # 模式2: #N = CARTESIAN_POINT(...(x, y, z))
            pattern2 = r"#\d+\s*=\s*CARTESIAN_POINT\s*\([^)]*\(\s*([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)\s*\)"
            for m in re.finditer(pattern2, content):
                points.append((float(m.group(1)), float(m.group(2)), float(m.group(3))))
        
        if not points:
            return None
        
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        zs = [p[2] for p in points]
        
        bbox = {
            "x_min": round(min(xs), 2),
            "x_max": round(max(xs), 2),
            "y_min": round(min(ys), 2),
            "y_max": round(max(ys), 2),
            "z_min": round(min(zs), 2),
            "z_max": round(max(zs), 2),
            "dim_x": round(max(xs) - min(xs), 2),
            "dim_y": round(max(ys) - min(ys), 2),
            "dim_z": round(max(zs) - min(zs), 2),
            "total_points": len(points),
            "volume_source": "bbox_estimate",
        }
        return bbox
    except Exception as e:
        return {"error": str(e)}

def estimate_volume_from_bbox(bbox: dict, solid_ratio: float = 0.30) -> float:
    """包围盒 → 估计体积(mm³)"""
    return bbox["dim_x"] * bbox["dim_y"] * bbox["dim_z"] * solid_ratio

# 材料密度 (g/cm³)
DENSITY = {
    "AL6061": 2.70, "6061": 2.70, "AL7075": 2.81,
    "SUS304": 7.93, "304": 7.93, "SUS316": 7.98, "316L": 7.98,
    "45钢": 7.85, "45#": 7.85, "Q235": 7.85,
    "TC4": 4.43, "钛合金": 4.43,
    "H59": 8.50, "黄铜": 8.50,
}

def get_material_density(material: str) -> float:
    return DENSITY.get(material.upper(), DENSITY.get(material, 7.85))

# 表面处理费 (¥/cm²)
SURFACE_COST = {
    "阳极氧化": 0.05, "发黑": 0.02, "镀锌": 0.03,
    "电镀": 0.08, "钝化": 0.03, "喷漆": 0.06,
    "无": 0, "": 0, None: 0,
}

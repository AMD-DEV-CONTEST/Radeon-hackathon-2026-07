"""任务7 端到端 API 测试 — 验证 :7862 端口的 chat / upload / upload-step 三端点。
独立运行: .venv\\Scripts\\python.exe tests\\e2e_api_test_task7.py
作者: 测试工程师 (任务7)"""
import json
import os
import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:7862"
UPLOAD_DIR = Path(r"C:\Users\miscd\Desktop\比赛\摩尔\新建文件夹\CNC-AI-Brain-v12.0-Fusion\cnc-ai-brain\data\uploads")

results = {}


def unwrap(d):
    """响应可能被 wrap_shadow 包装 — 优先返回 d['data'], 否则返回 d 本身。"""
    if isinstance(d, dict) and "data" in d and isinstance(d["data"], dict):
        # 同时存在 shadow 标记时优先 data
        return d["data"]
    return d


# ───────────────────────── 1. chat 端点 ─────────────────────────
def test_chat():
    print("\n" + "=" * 70)
    print("[1/3] chat 端点测试: POST /api/chat")
    print("=" * 70)
    msg = "绘制直径120mm、厚16mm法兰盘，中心孔30mm，均布4×φ10通孔，导出STEP"
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/api/chat", json={"message": msg}, timeout=120)
        elapsed = round(time.time() - t0, 2)
        print(f"HTTP 状态码: {r.status_code}  耗时: {elapsed}s")
        if r.status_code != 200:
            print(f"非200响应, 前500字符: {r.text[:500]}")
            results["chat"] = {"pass": False, "status": r.status_code, "error": f"非200状态: {r.status_code}"}
            return
        d = r.json()
        print(f"顶层键: {list(d.keys())}")
        inner = unwrap(d)
        print(f"内层键: {list(inner.keys()) if isinstance(inner, dict) else type(inner)}")

        # 提取 part_spec
        part_spec = inner.get("part_spec") or d.get("part_spec")
        cad_tot_chain = inner.get("cad_tot_chain") or d.get("cad_tot_chain")
        step_file = inner.get("step_file") or d.get("step_file")
        step_path = inner.get("step_path") or d.get("step_path")

        info = {
            "pass": True,
            "status": r.status_code,
            "elapsed_s": elapsed,
            "part_spec": part_spec,
            "cad_tot_chain_present": cad_tot_chain is not None,
            "cad_tot_chain_steps": (cad_tot_chain.get("total_steps") if isinstance(cad_tot_chain, dict) else None),
            "cad_tot_chain_winner": (cad_tot_chain.get("winner", {}).get("source") if isinstance(cad_tot_chain, dict) else None),
            "step_file": step_file,
            "step_path": step_path,
        }

        # 验证 part_spec 关键参数
        if not part_spec:
            info["pass"] = False
            info["error"] = "part_spec 缺失"
        else:
            params = part_spec.get("params", {}) if isinstance(part_spec, dict) else {}
            checks = {
                "od=120": params.get("od") == 120,
                "id=30": params.get("id") == 30,
                "thickness=16": params.get("thickness") == 16,
                "bolt_holes=4": params.get("bolt_holes") == 4,
            }
            info["param_checks"] = checks
            if not all(checks.values()):
                info["pass"] = False
                info["error"] = f"part_spec 参数校验失败: {checks}"

        # 验证 cad_tot_chain 存在
        if not info["cad_tot_chain_present"]:
            info["pass"] = False
            info["error"] = (info.get("error", "") + "; cad_tot_chain 缺失").strip("; ")

        # 验证 step_file 存在
        step_exists = False
        if step_file:
            if isinstance(step_file, str) and os.path.exists(step_file):
                step_exists = True
            elif isinstance(step_file, dict):
                fp = step_file.get("path") or step_file.get("file")
                if fp and os.path.exists(fp):
                    step_exists = True
        if step_path and os.path.exists(step_path):
            step_exists = True
        info["step_file_exists"] = step_exists
        if not step_exists:
            info["pass"] = False
            info["error"] = (info.get("error", "") + "; step_file 文件不存在").strip("; ")

        print(f"part_spec: {json.dumps(part_spec, ensure_ascii=False, indent=2) if part_spec else '缺失'}")
        print(f"cad_tot_chain: 存在={info['cad_tot_chain_present']} 步数={info['cad_tot_chain_steps']} winner={info['cad_tot_chain_winner']}")
        print(f"step_file: {step_file}")
        print(f"step_file 文件存在: {step_exists}")
        print(f"结论: {'PASS' if info['pass'] else 'FAIL'} — {info.get('error', '')}")
        results["chat"] = info
    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        print(f"异常: {type(e).__name__}: {e}  耗时: {elapsed}s")
        results["chat"] = {"pass": False, "error": f"{type(e).__name__}: {e}", "elapsed_s": elapsed}


# ───────────────────────── 2. upload PDF ─────────────────────────
def test_upload_pdf():
    print("\n" + "=" * 70)
    print("[2/3] upload 端点 PDF 测试: POST /api/upload")
    print("=" * 70)
    pdf_path = UPLOAD_DIR / "test_form.pdf"
    t0 = time.time()
    try:
        with open(pdf_path, "rb") as f:
            files = {"file": ("test_form.pdf", f, "application/pdf")}
            r = requests.post(f"{BASE}/api/upload", files=files, timeout=60)
        elapsed = round(time.time() - t0, 2)
        print(f"HTTP 状态码: {r.status_code}  耗时: {elapsed}s")
        if r.status_code != 200:
            print(f"非200响应, 前500字符: {r.text[:500]}")
            results["upload_pdf"] = {"pass": False, "status": r.status_code, "error": f"非200状态: {r.status_code}"}
            return
        d = r.json()
        print(f"顶层键: {list(d.keys())}")
        inner = unwrap(d)
        print(f"内层键: {list(inner.keys()) if isinstance(inner, dict) else type(inner)}")

        form_structure = inner.get("form_structure") or d.get("form_structure")
        info = {
            "pass": True,
            "status": r.status_code,
            "elapsed_s": elapsed,
            "form_structure_present": form_structure is not None,
            "label_count": (form_structure.get("label_count") if isinstance(form_structure, dict) else None),
        }
        if not form_structure:
            info["pass"] = False
            info["error"] = "form_structure 缺失"
        else:
            lc = form_structure.get("label_count", 0)
            if not (isinstance(lc, int) and lc > 0):
                info["pass"] = False
                info["error"] = f"label_count 非正整数: {lc}"
        print(f"form_structure: 存在={info['form_structure_present']} label_count={info['label_count']}")
        print(f"结论: {'PASS' if info['pass'] else 'FAIL'} — {info.get('error', '')}")
        results["upload_pdf"] = info
    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        print(f"异常: {type(e).__name__}: {e}  耗时: {elapsed}s")
        results["upload_pdf"] = {"pass": False, "error": f"{type(e).__name__}: {e}", "elapsed_s": elapsed}


# ───────────────────────── 3. upload-step STEP ─────────────────────────
def test_upload_step():
    print("\n" + "=" * 70)
    print("[3/3] upload-step 端点 STEP 测试: POST /api/upload-step")
    print("=" * 70)
    step_path = UPLOAD_DIR / "a0514a_flange_cq.step"
    t0 = time.time()
    try:
        with open(step_path, "rb") as f:
            files = {"file": ("flange.step", f, "application/octet-stream")}
            r = requests.post(f"{BASE}/api/upload-step", files=files, timeout=60)
        elapsed = round(time.time() - t0, 2)
        print(f"HTTP 状态码: {r.status_code}  耗时: {elapsed}s")
        if r.status_code != 200:
            print(f"非200响应, 前500字符: {r.text[:500]}")
            results["upload_step"] = {"pass": False, "status": r.status_code, "error": f"非200状态: {r.status_code}"}
            return
        d = r.json()
        print(f"顶层键: {list(d.keys())}")
        inner = unwrap(d)
        print(f"内层键: {list(inner.keys()) if isinstance(inner, dict) else type(inner)}")

        mesh_stats = inner.get("mesh_stats") or d.get("mesh_stats")
        info = {
            "pass": True,
            "status": r.status_code,
            "elapsed_s": elapsed,
            "mesh_stats_present": mesh_stats is not None,
            "mesh_stats": mesh_stats,
        }
        if not mesh_stats:
            info["pass"] = False
            info["error"] = "mesh_stats 缺失"
        else:
            required = ["is_watertight", "vertex_count", "face_count", "surface_area_mm2"]
            missing = [k for k in required if k not in mesh_stats]
            if missing:
                info["pass"] = False
                info["error"] = f"mesh_stats 缺字段: {missing}"
        print(f"mesh_stats: {json.dumps(mesh_stats, ensure_ascii=False, indent=2) if mesh_stats else '缺失'}")
        print(f"结论: {'PASS' if info['pass'] else 'FAIL'} — {info.get('error', '')}")
        results["upload_step"] = info
    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        print(f"异常: {type(e).__name__}: {e}  耗时: {elapsed}s")
        results["upload_step"] = {"pass": False, "error": f"{type(e).__name__}: {e}", "elapsed_s": elapsed}


if __name__ == "__main__":
    test_chat()
    test_upload_pdf()
    test_upload_step()
    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    all_pass = all(v.get("pass", False) for v in results.values())
    print(f"\n总体结论: {'ALL PASS' if all_pass else '有失败项'}")
    sys.exit(0 if all_pass else 1)
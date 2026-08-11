import os
import sys
import traceback

os.environ["TOT_ENABLED"] = "1"
project_dir = r"C:\Users\miscd\Desktop\比赛\摩尔\新建文件夹\CNC-AI-Brain-v12.0-Fusion\cnc-ai-brain"
os.chdir(project_dir)
sys.path.insert(0, project_dir)

# 先导入 app.main（模拟服务环境，使 sys.modules['app.main'] 可用）
import app.main  # noqa
print("[OK] app.main imported, in sys.modules:", "app.main" in sys.modules)
print("[OK] _legacy_extract_cad_spec available:", hasattr(app.main, "_legacy_extract_cad_spec"))
print("[OK] llm_extract_part_spec available:", hasattr(app.main, "llm_extract_part_spec"))
print("[OK] validate_part_spec available:", hasattr(app.main, "validate_part_spec"))

message = "绘制直径120mm、厚16mm法兰盘，中心孔30mm，均布4×φ10通孔，导出STEP"

try:
    from src.runtime.cad_pipeline_tot import run_tot_competition
    print("\n[TOT] calling run_tot_competition ...")
    result = run_tot_competition(message, structured_spec={"part_type": None, "params": {}})
    print("\n[RESULT] part_spec:", result.get("part_spec"))
    print("[RESULT] winner:", result.get("winner"))
    print("[RESULT] total_candidates:", result.get("total_candidates"))
    print("[RESULT] scoreboard:", result.get("scoreboard"))
    cd = result.get("chain_dict")
    print("[RESULT] chain_dict steps:", len(cd.get("steps", [])) if cd else "None")
    print("[RESULT] chain_dict conclusion:", cd.get("overall_conclusion") if cd else "None")
except Exception as e:
    print("[ERROR] Exception:")
    traceback.print_exc()
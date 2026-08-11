import os
import sys
import traceback

os.environ["TOT_ENABLED"] = "1"
project_dir = r"C:\Users\miscd\Desktop\比赛\摩尔\新建文件夹\CNC-AI-Brain-v12.0-Fusion\cnc-ai-brain"
os.chdir(project_dir)
sys.path.insert(0, project_dir)

message = "绘制直径120mm、厚16mm法兰盘，中心孔30mm，均布4×φ10通孔，导出STEP"

try:
    from src.runtime.cad_pipeline_tot import run_tot_competition
    print("[OK] import run_tot_competition success")
    result = run_tot_competition(message, structured_spec={"part_type": None, "params": {}})
    print("[OK] run_tot_competition returned")
    print("part_spec:", result.get("part_spec"))
    print("winner:", result.get("winner"))
    print("total_candidates:", result.get("total_candidates"))
    print("chain_dict is None:", result.get("chain_dict") is None)
    if result.get("chain_dict"):
        cd = result["chain_dict"]
        print("chain_dict keys:", list(cd.keys()) if isinstance(cd, dict) else type(cd))
except Exception as e:
    print("[ERROR] Exception:")
    traceback.print_exc()
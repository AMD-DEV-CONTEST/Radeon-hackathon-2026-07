"""Archive old interference task residuals from d:\\APPs\\amdRadeon.

Categorization:
  round1_login_flow/        — 登录流程脚本 (01-09) + 登录截图 + 早期 logs JSON
  round2_env_setup/         — 环境检查/UV/Torch/LeRobot 安装脚本
  round3_api_inspect/       — check_*/inspect_*/find_*/dump_* 诊断脚本
  round4_sort_debug/        — diagnose_*/upload_diag/run_sort_demo*/调试下载
"""
import shutil
from pathlib import Path
from datetime import datetime

BASE = Path(r"d:\APPs\amdRadeon")
ARCHIVE_BASE = BASE / "archive" / "old_interference_2026"
SCRIPTS = BASE / "scripts"
LOGS = BASE / "logs"
SHOTS = BASE / "screenshots"

# 创建归档子目录
DIRS = {
    "login_scripts": ARCHIVE_BASE / "round1_login_flow" / "scripts",
    "login_outputs": ARCHIVE_BASE / "round1_login_flow" / "outputs",
    "env_setup": ARCHIVE_BASE / "round2_env_setup" / "scripts",
    "api_inspect": ARCHIVE_BASE / "round3_api_inspect" / "scripts",
    "sort_debug": ARCHIVE_BASE / "round4_sort_debug" / "scripts",
    "sort_debug_outputs": ARCHIVE_BASE / "round4_sort_debug" / "outputs",
}
for d in DIRS.values():
    d.mkdir(parents=True, exist_ok=True)

# ============== 保留清单（当前任务必需） ==============
KEEP_SCRIPTS = {
    "remote_exec.py",           # 远程执行核心工具
    "run_eval_sort_bg.py",      # 评估启动器（当前任务）
    "upload_eval_sort.py",      # 上传评估脚本（当前任务）
    "run_smolvla_train.py",     # 训练启动器
    "monitor_train.py",         # 训练监控
    "run_record_sort_bg.py",    # 数据采集启动器
    "download_eval_videos.py",  # 下载评估视频（当前任务）
    "recon_contest.py",         # 比赛页探测（当前任务）
    "archive_residuals.py",     # 本归档脚本自身
}

# ============== 分类规则 ==============
def classify(name: str) -> str | None:
    """Return archive dir key or None to keep."""
    # 登录流程脚本
    login_prefixes = ("01_", "02_", "03_", "04_", "05_", "06_", "07_", "08_", "09_")
    if any(name.startswith(p) for p in login_prefixes):
        return "login_scripts"

    # 环境安装/检查
    env_keywords = ("install_", "env_check", "start_uv_sync", "run_uv_sync",
                    "restart_uv", "check_uv")
    if any(name.startswith(k) for k in env_keywords):
        return "env_setup"

    # API 探测/源码检查
    api_keywords = ("check_", "inspect_", "find_", "dump_")
    if any(name.startswith(k) for k in api_keywords):
        return "api_inspect"

    # sort 调试
    sort_debug_keywords = ("diagnose_", "upload_diag", "upload_and_run_",
                           "run_sort_demo", "run_sort_check", "run_build_scene",
                           "download_images", "download_sort_frames",
                           "download_smolvla", "deploy_sort_task", "fetch_train_log",
                           "verify_and_setup")
    if any(name.startswith(k) for k in sort_debug_keywords):
        return "sort_debug"

    return None


# ============== 执行归档 ==============
moved = {"login_scripts": 0, "login_outputs": 0, "env_setup": 0,
         "api_inspect": 0, "sort_debug": 0, "sort_debug_outputs": 0}
kept = []
unknown = []

# 1. 归档 scripts/ 下的 .py 文件
for item in sorted(SCRIPTS.iterdir()):
    if not item.is_file() or item.suffix != ".py":
        continue
    name = item.name
    if name in KEEP_SCRIPTS:
        kept.append(name)
        continue
    cat = classify(name)
    if cat is None:
        unknown.append(name)
        continue
    dst = DIRS[cat] / name
    shutil.move(str(item), str(dst))
    moved[cat] += 1

# 2. 归档 scripts/ 下的 .ps1（登录流程）
for item in sorted(SCRIPTS.iterdir()):
    if item.is_file() and item.suffix == ".ps1":
        dst = DIRS["login_scripts"] / item.name
        shutil.move(str(item), str(dst))
        moved["login_scripts"] += 1

# 3. 归档早期 logs JSON（登录/页面侦察）
early_logs = ["launch_dialog.json", "logged_in_recon.json",
              "page_recon.json", "space_recon.json"]
for name in early_logs:
    src = LOGS / name
    if src.exists():
        dst = DIRS["login_outputs"] / name
        shutil.move(str(src), str(dst))
        moved["login_outputs"] += 1

# 4. 归档 screenshots/ 根目录的登录流程截图（保留 sort_demo/ 子目录）
login_shots = [
    "02_landed_full.png", "02_landed_top.png", "03_after_login_click.png",
    "04_email_login_page.png", "05_after_send_code.png", "06_after_login.png",
    "07_space_page.png", "08_after_launch_click.png", "08_space_url.png",
    "09_launch_final.png", "world_cam.png", "wrist_cam.png",
]
for name in login_shots:
    src = SHOTS / name
    if src.exists():
        dst = DIRS["sort_debug_outputs"] / name
        shutil.move(str(src), str(dst))
        moved["sort_debug_outputs"] += 1

# ============== 统计 ==============
print("=" * 60)
print("ARCHIVE SUMMARY")
print("=" * 60)
total_moved = sum(moved.values())
for cat, n in moved.items():
    print(f"  {cat:25s}: {n}")
print(f"  {'TOTAL MOVED':25s}: {total_moved}")
print(f"\nKEPT scripts ({len(kept)}):")
for k in sorted(kept):
    print(f"  - {k}")
if unknown:
    print(f"\nUNKNOWN (not classified, {len(unknown)}):")
    for u in sorted(unknown):
        print(f"  - {u}")

# ============== 写 README.md ==============
readme = ARCHIVE_BASE / "README.md"
readme_content = f"""# Archive Index — old_interference_2026

生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
来源: `d:\\APPs\\amdRadeon\\scripts/`, `logs/`, `screenshots/`

## Statistics

| Round | Category | Files | Source | Description |
|-------|----------|-------|--------|-------------|
| 1 | login_scripts | {moved['login_scripts']} | `scripts/` | 登录流程自动化脚本 (01-09) + .ps1 |
| 1 | login_outputs | {moved['login_outputs']} | `logs/` | 早期登录/页面侦察 JSON |
| 2 | env_setup | {moved['env_setup']} | `scripts/` | UV/Torch/LeRobot 安装与环境检查 |
| 3 | api_inspect | {moved['api_inspect']} | `scripts/` | check_*/inspect_*/find_*/dump_* 诊断 |
| 4 | sort_debug | {moved['sort_debug']} | `scripts/` | diagnose_*/upload_diag/run_sort_demo* 调试 |
| 4 | sort_debug_outputs | {moved['sort_debug_outputs']} | `screenshots/` | 登录流程截图 + 早期相机测试 |
| **Total** | | **{total_moved}** | | |

## 当前任务保留文件（未归档）

| File | Purpose |
|------|---------|
| remote_exec.py | 远程执行核心工具（JupyterLab API） |
| run_eval_sort_bg.py | SmolVLA policy 闭环评估启动器 |
| upload_eval_sort.py | 上传评估脚本到远程实例 |
| run_smolvla_train.py | SmolVLA 训练启动器（ROCm） |
| monitor_train.py | 训练进度和 GPU 使用监控 |
| run_record_sort_bg.py | 数据采集启动器 |
| download_eval_videos.py | 下载评估视频到本地 |
| recon_contest.py | 比赛页面提交要求探测 |

## Archived Contents Detail

### round1_login_flow/
- `scripts/` — 登录流程自动化脚本 (01_launch_chrome_cdp.ps1 ~ 09_wait_for_launch.py)
- `outputs/` — 早期登录/页面侦察 JSON (launch_dialog, logged_in_recon, page_recon, space_recon)

### round2_env_setup/
- `scripts/` — 环境安装与检查脚本 (install_lerobot/torch, start_uv_sync v1-v4, check_uv*, env_check, restart_uv*)

### round3_api_inspect/
- `scripts/` — API/源码探测脚本 (check_dof_constants, check_grasp_demo_api, inspect_dataset v1-v5, inspect_policy*, find_select_action 等)

### round4_sort_debug/
- `scripts/` — sort 任务调试脚本 (diagnose_banana/plum/sort, upload_diag, run_sort_demo v1/v2, run_build_scene v1/v2, download_images v1/v2, deploy_sort_task 等)
- `outputs/` — 登录流程截图 + 早期相机测试图 (02_landed_full ~ 09_launch_final, world_cam, wrist_cam)

## 归档原则
- 归档而非删除（可追溯）
- 当前任务核心代码全部保留在 `scripts/` 和 `remote_files/`
- 评估证据保留在 `logs/eval_results.json`, `logs/smolvla_train.log`, `screenshots/sort_demo/`
"""
readme.write_text(readme_content, encoding="utf-8")
print(f"\nREADME written to {readme}")
print(f"\nArchive base: {ARCHIVE_BASE}")

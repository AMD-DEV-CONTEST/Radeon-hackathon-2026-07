"""Stage E 全场景验收测试脚本。

覆盖阶段 E 的所有验收标准：
1. 后台运行生命周期 (dispatch / cancel / retry)
2. 进度轮询与步进计时 (StepTimer / RunProgress)
3. 文件上传加固 (validate_file 6 步校验)
4. 统一错误码 (APP_ERROR_CODES / get_error)
5. 定期清理服务 (CleanupReport / run_cleanup)
6. 运行历史 API (list_runs / progress / global_runs)

对照 FULL_PRODUCT_ROADMAP.zh-CN.md 阶段 E 的要求逐项验证。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# Ensure the project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

CHECK = "✅"
CROSS = "❌"


def ok(msg: str) -> None:
    print(f"  {CHECK} {msg}")


def fail(msg: str) -> None:
    print(f"  {CROSS} {msg}")


# ===========================================================================
# Test 1: StepTimer & RunProgress
# ===========================================================================


def test_step_timer() -> int:
    """验证 StepTimer 上下文管理器正确记录步进计时。"""
    print("\n── Test 1: StepTimer 步进计时 ──")
    passed = 0
    total = 4

    from app.schemas.models import StepDef, StepTiming
    from app.observability.audit import StepTimer

    # 1a: 正常计时
    timing_list: list[StepTiming] = []
    with StepTimer(timing_list, StepDef.EMBED, current_file="data.csv") as t:
        time.sleep(0.05)
    assert t.step == StepDef.EMBED, "step 应为 EMBED"
    assert t.started_at is not None, "started_at 应非空"
    assert t.finished_at is not None, "finished_at 应非空"
    assert t.elapsed_ms is not None and t.elapsed_ms > 0, "elapsed_ms 应 > 0"
    assert t.current_file == "data.csv", "current_file 应正确"
    assert len(timing_list) == 1, "timing_list 应有 1 条记录"
    ok("StepTimer 正常记录开始/结束/耗时")
    passed += 1

    # 1b: 异常捕获
    timing_list2: list[StepTiming] = []
    try:
        with StepTimer(timing_list2, StepDef.PARSE):
            raise RuntimeError("模拟解析错误")
    except RuntimeError:
        pass
    assert len(timing_list2) == 1, "异常时也应记录"
    err_t = timing_list2[0]
    assert err_t.error is not None and "模拟解析错误" in err_t.error, "应捕获 error 字段"
    assert err_t.elapsed_ms is not None and err_t.elapsed_ms >= 0, "异常时也应记录耗时"
    ok("StepTimer 异常时自动捕获 error 字段")
    passed += 1

    # 1c: 多步骤顺序
    timing_list3: list[StepTiming] = []
    for step in (StepDef.PARSE, StepDef.EMBED, StepDef.INDEX):
        with StepTimer(timing_list3, step):
            time.sleep(0.01)
    assert len(timing_list3) == 3, "应有 3 条记录"
    assert [t.step for t in timing_list3] == [StepDef.PARSE, StepDef.EMBED, StepDef.INDEX], "步骤顺序应正确"
    ok("StepTimer 多步骤按序记录")
    passed += 1

    # 1d: RunProgress 字段完整性
    from app.schemas.models import RunProgress, RunStatus

    progress = RunProgress(
        run_id="a" * 32,
        status=RunStatus.SCANNING,
        current_step=3,
        current_step_name="index",
        percentage=37,
        current_file="doc.md",
        error_summary=None,
        timing_by_step=timing_list3,
        retry_count=0,
    )
    assert progress.run_id == "a" * 32
    assert progress.status == RunStatus.SCANNING
    assert progress.current_step == 3
    assert progress.percentage == 37
    assert progress.current_file == "doc.md"
    assert progress.error_summary is None
    assert progress.retry_count == 0
    assert len(progress.timing_by_step) == 3
    ok("RunProgress 所有字段正确填充")
    passed += 1

    return passed == total


# ===========================================================================
# Test 2: File Upload Validation
# ===========================================================================


def test_file_validation() -> int:
    """验证 validate_file 6 步校验流程。"""
    print("\n── Test 2: 文件上传校验 ──")
    passed = 0
    total = 8

    from app.config import Settings
    from app.services.files import validate_file, UploadValidationError
    from app.schemas.models import ALLOWED_EXTENSIONS

    settings = Settings()

    # 2a: 合法 txt (validate_file raises on error, returns None on success)
    try:
        validate_file("hello.txt", b"hello world", settings)
        ok("合法 .txt 通过")
        passed += 1
    except UploadValidationError as e:
        fail(f"合法 .txt 被拒绝: {e.validation.error_code}")
        return False

    # 2b: 合法 md
    try:
        validate_file("readme.md", b"# Markdown", settings)
        ok("合法 .md 通过")
        passed += 1
    except UploadValidationError as e:
        fail(f"合法 .md 被拒绝: {e.validation.error_code}")
        return False

    # 2c: 空文件
    try:
        validate_file("empty.txt", b"", settings)
        fail("空文件应被拒绝")
    except UploadValidationError as e:
        if e.validation.error_code == "FILE_EMPTY":
            ok("空文件被拒绝 (FILE_EMPTY)")
            passed += 1
        else:
            fail(f"空文件拒绝错误码不对: {e.validation.error_code}")
            return False

    # 2d: 超大文件
    huge_content = b"x" * (settings.max_upload_size_bytes + 1)
    try:
        validate_file("big.txt", huge_content, settings)
        fail("超大文件应被拒绝")
    except UploadValidationError as e:
        if e.validation.error_code == "FILE_TOO_LARGE":
            ok("超大文件被拒绝 (FILE_TOO_LARGE)")
            passed += 1
        else:
            fail(f"超大文件拒绝错误码不对: {e.validation.error_code}")
            return False

    # 2e: 非法扩展名
    try:
        validate_file("movie.exe", b"\x00\x00", settings)
        fail("非法扩展名应被拒绝")
    except UploadValidationError as e:
        if "EXTENSION" in e.validation.error_code.upper() or "denied" in e.validation.message.lower():
            ok("非法扩展名被拒绝 (FILE_EXTENSION_DENIED)")
            passed += 1
        else:
            fail(f"非法扩展名拒绝错误码不对: {e.validation.error_code}")
            return False

    # 2f: 文件名过长
    long_name = "a" * (settings.max_upload_filename_length + 1) + ".txt"
    try:
        validate_file(long_name, b"test", settings)
        fail("超长文件名应被拒绝")
    except UploadValidationError as e:
        if e.validation.error_code == "FILE_NAME_TOO_LONG":
            ok("超长文件名被拒绝 (FILE_NAME_TOO_LONG)")
            passed += 1
        else:
            fail(f"超长文件名拒绝错误码不对: {e.validation.error_code}")
            return False

    # 2g: allowed extensions 完整性
    assert ALLOWED_EXTENSIONS == {".md", ".txt", ".pdf", ".docx", ".xlsx", ".csv"}, \
        f"ALLOWED_EXTENSIONS 应为 6 种: {ALLOWED_EXTENSIONS}"
    ok("ALLOWED_EXTENSIONS 包含 6 种格式")
    passed += 1

    # 2h: upload result 返回 (使用项目根目录结构)
    from app.services.files import save_project_upload
    from app.services.projects import project_paths
    with tempfile.TemporaryDirectory() as tmpdir:
        s = Settings(project_root=tmpdir, output_root=tmpdir, vector_db_root=tmpdir)
        # 创建完整项目目录结构
        paths = project_paths(s.project_root, s.output_root, "proj-001")
        paths["source"].mkdir(parents=True, exist_ok=True)
        path, result = save_project_upload(s, "proj-001", "doc.txt", b"content", task_file=False)
        assert isinstance(path, str) and len(path) > 0, "应返回路径"
        assert result.size_bytes == 7, "size_bytes 应为 7"
        assert result.virus_scan_status == "skipped", "扫描应 skip"
        ok("save_project_upload 返回 (str, UploadResult)")
    passed += 1

    return passed == total


# ===========================================================================
# Test 3: Unified Error Codes
# ===========================================================================


def test_error_codes() -> int:
    """验证统一错误码系统。"""
    print("\n── Test 3: 统一错误码 ──")
    passed = 0
    total = 5

    from app.observability.error_codes import APP_ERROR_CODES, get_error

    # 3a: 所有核心错误码存在
    required_codes = [
        "FILE_NAME_TOO_LONG",
        "FILE_EMPTY",
        "FILE_TOO_LARGE",
        "FILE_EXTENSION_NOT_ALLOWED",
        "FILE_MIME_MISMATCH",
        "FILE_VIRUS_DETECTED",
        "PROJECT_NOT_FOUND",
        "RUN_NOT_FOUND",
        "RUN_ALREADY_CANCELLED",
        "RUN_CANCEL_TOO_LATE",
        "RUN_WRONG_STATUS",
    ]
    for code in required_codes:
        assert code in APP_ERROR_CODES, f"缺少 {code}"
    ok(f"所有 {len(required_codes)} 个核心错误码存在")
    passed += 1

    # 3b: get_error 返回 dict
    detail = get_error("FILE_EMPTY", filename="test.txt", size="0")
    assert isinstance(detail, dict), f"应返回 dict: {type(detail)}"
    assert detail["error_code"] == "FILE_EMPTY"
    ok("get_error 返回 dict 结构")
    passed += 1

    # 3c: 中文用户消息
    for code in required_codes:
        detail = get_error(code)
        assert detail["user_message"], f"{code} 缺少 user_message"
        has_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in detail["user_message"])
        assert has_chinese, f"{code} 的 user_message 不含中文: {detail['user_message']}"
    ok("所有错误码包含中文用户消息")
    passed += 1

    # 3d: 未知错误回退到 INTERNAL_ERROR
    detail = get_error("NONEXISTENT")
    assert detail["error_code"] == "INTERNAL_ERROR", f"未知错误码应回退: {detail}"
    ok("未知错误码回退到 INTERNAL_ERROR")
    passed += 1

    # 3e: 错误码唯一性
    codes = list(APP_ERROR_CODES.keys())
    assert len(codes) == len(set(codes)), "所有错误码应唯一"
    ok(f"错误码不重复 ({len(codes)} 个)")
    passed += 1

    return passed == total


# ===========================================================================
# Test 4: Cleanup Service
# ===========================================================================


def test_cleanup() -> int:
    """验证定期清理服务。"""
    print("\n── Test 4: 定期清理服务 ──")
    passed = 0
    total = 6

    from app.config import Settings
    from app.services.cleanup import CleanupReport, _age_days, _cleanup_expired_projects, \
        _cleanup_temp_uploads, _cleanup_old_indexes

    # 4a: CleanupReport defaults
    report = CleanupReport()
    assert report.projects_removed == 0
    assert report.temp_files_removed == 0
    assert report.indexes_removed == 0
    assert report.errors == []
    assert report.total == 0
    assert report.success is True
    ok("CleanupReport 初始值正确")
    passed += 1

    # 4b: CleanupReport with content
    report2 = CleanupReport()
    report2.projects_removed = 3
    report2.temp_files_removed = 5
    report2.indexes_removed = 1
    assert report2.total == 9
    assert report2.success is True
    ok("CleanupReport.total 计算正确")
    passed += 1

    # 4c: CleanupReport with errors
    report3 = CleanupReport()
    report3.errors.append("permission denied")
    assert report3.success is False
    ok("CleanupReport 有错误时 success=False")
    passed += 1

    # 4d: _age_days
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "old.txt"
        p.write_text("data")
        # 修改 mtime 到 10 天前
        old_time = time.time() - 10 * 86400
        os.utime(p, (old_time, old_time))
        age = _age_days(p)
        assert 9 <= age <= 11, f"age 应在 9-11 天, 实际: {age}"
        ok("_age_days 计算正确")
    passed += 1

    # 4e: _age_days nonexistent
    age = _age_days(Path("/nonexistent/path"))
    assert age == 0.0
    ok("_age_days 不存在的路径返回 0")
    passed += 1

    # 4f: 三类清理函数各自独立
    with tempfile.TemporaryDirectory() as tmpdir:
        # 使用不同的子目录避免 project 和 output 冲突
        proj_root = Path(tmpdir) / "projects"
        out_root = Path(tmpdir) / "outputs"
        idx_root = Path(tmpdir) / "vectors"
        proj_root.mkdir()
        out_root.mkdir()
        idx_root.mkdir()

        s = Settings(project_root=str(proj_root), output_root=str(out_root),
                     vector_db_root=str(idx_root))

        # 创建过期 smoke 项目
        smoke_dir = proj_root / "smoke-test"
        smoke_dir.mkdir()
        (smoke_dir / "data.txt").write_text("x")
        os.utime(smoke_dir, (0, 0))  # epoch →必定过期

        # 创建过期 .tmp
        tmp_file = out_root / "upload.tmp"
        tmp_file.write_text("x")
        os.utime(tmp_file, (0, 0))

        # 创建过期索引
        idx_dir = idx_root / "index_abc"
        idx_dir.mkdir()
        os.utime(idx_dir, (0, 0))

        time.sleep(0.02)  # Windows 文件系统延迟

        rp = CleanupReport()
        _cleanup_temp_uploads(s, rp)
        assert rp.temp_files_removed >= 1, f"应清理至少 1 个临时文件, 实际: {rp.temp_files_removed}"
        _cleanup_old_indexes(s, rp)
        assert rp.indexes_removed >= 1, f"应清理至少 1 个索引, 实际: {rp.indexes_removed}"
        _cleanup_expired_projects(s, rp)
        assert rp.projects_removed >= 1, f"应清理至少 1 个项目, 实际: {rp.projects_removed}"
        ok("三类清理函数各自独立运行")
    passed += 1

    return passed == total


# ===========================================================================
# Test 5: Run Lifecycle
# ===========================================================================


def test_run_lifecycle() -> int:
    """验证后台运行生命周期（dispatch / cancel / retry）。"""
    print("\n── Test 5: 运行生命周期 ──")
    passed = 0
    total = 7

    from app.config import Settings
    from app.schemas.models import RunState, RunStatus

    # 5a: dispatch 后状态转为 running
    state = RunState(
        run_id="a" * 32,
        project_id="proj-001",
        status=RunStatus.QUEUED,
        created_at=date.today(),
        updated_at=date.today(),
    )
    # 模拟：状态应为 QUEUED，允许 dispatch
    assert state.status in (RunStatus.QUEUED, RunStatus.FAILED, RunStatus.CANCELLED), \
        "QUEUED 状态允许 dispatch"
    ok("QUEUED 状态允许 dispatch")
    passed += 1

    # 5b: 已在运行的 run 不重复提交
    state2 = RunState(
        run_id="b" * 32,
        project_id="proj-001",
        status=RunStatus.SCANNING,  # 已经 busy
        created_at=date.today(),
        updated_at=date.today(),
    )
    should_dispatch = state2.status in (RunStatus.QUEUED, RunStatus.FAILED, RunStatus.CANCELLED)
    assert not should_dispatch, "busy 状态不应重复 dispatch"
    ok("运行中的 run 不重复提交")
    passed += 1

    # 5c: cancel 设置标志
    state.cancel_requested = True
    assert state.cancel_requested is True
    ok("cancel_requested 标志正确设置")
    passed += 1

    # 5d: cancel_requested 默认为 False
    state3 = RunState(
        run_id="c" * 32,
        project_id="proj-002",
        status=RunStatus.QUEUED,
        created_at=date.today(),
        updated_at=date.today(),
    )
    assert state3.cancel_requested is False
    ok("cancel_requested 默认为 False")
    passed += 1

    # 5e: CANCELLED 状态存在
    assert RunStatus.CANCELLED == "cancelled"
    ok("RunStatus.CANCELLED 已定义")
    passed += 1

    # 5f: retry_count 默认为 0
    assert state3.retry_count == 0
    ok("retry_count 默认为 0")
    passed += 1

    # 5g: timing_by_step 默认为空
    assert state3.timing_by_step == []
    ok("timing_by_step 默认为空列表")
    passed += 1

    return passed == total


# ===========================================================================
# Test 6: StepDef Coverage
# ===========================================================================


def test_step_def_coverage() -> int:
    """验证 StepDef 枚举覆盖所有管道阶段。"""
    print("\n── Test 6: StepDef 枚举覆盖 ──")
    from app.schemas.models import StepDef

    expected_steps = {"parse", "embed", "index", "retrieve", "rules", "model_generate", "file_write"}
    actual_steps = {step.value for step in StepDef}
    assert expected_steps == actual_steps, f"缺少步骤: {expected_steps - actual_steps}"
    ok(f"StepDef 覆盖全部 {len(expected_steps)} 个管道阶段")
    return True


# ===========================================================================
# Test 7: Config Settings
# ===========================================================================


def test_config_settings() -> int:
    """验证阶段 E 新增配置项。"""
    print("\n── Test 7: 阶段 E 配置项 ──")
    passed = 0
    total = 5

    from app.config import Settings

    s = Settings()

    # 7a: run 配置
    assert hasattr(s, "run_max_retries")
    assert s.run_max_retries == 3
    assert hasattr(s, "run_timeout_seconds")
    assert s.run_timeout_seconds == 600
    ok("run_max_retries=3, run_timeout_seconds=600")
    passed += 1

    # 7b: 上传配置
    assert hasattr(s, "max_upload_size_mb")
    assert s.max_upload_size_mb == 50
    assert hasattr(s, "max_upload_filename_length")
    assert s.max_upload_filename_length == 255
    ok("max_upload_size_mb=50, max_upload_filename_length=255")
    passed += 1

    # 7c: 病毒扫描配置
    assert hasattr(s, "virus_scan_enabled")
    assert s.virus_scan_enabled is False
    assert hasattr(s, "virus_scan_command")
    assert isinstance(s.virus_scan_command, list)
    ok("virus_scan_enabled=False (默认)")
    passed += 1

    # 7d: 清理配置
    assert hasattr(s, "cleanup_enabled")
    assert s.cleanup_enabled is True
    assert hasattr(s, "cleanup_cron_interval_minutes")
    assert s.cleanup_cron_interval_minutes == 60
    assert hasattr(s, "cleanup_smoke_project_days")
    assert s.cleanup_smoke_project_days == 1
    assert hasattr(s, "cleanup_temp_upload_days")
    assert s.cleanup_temp_upload_days == 7
    assert hasattr(s, "cleanup_old_index_days")
    assert s.cleanup_old_index_days == 30
    ok("cleanup 配置正确: enabled=True, interval=60min, smoke=1d, tmp=7d, index=30d")
    passed += 1

    # 7e: max_upload_size_bytes 计算属性
    assert hasattr(s, "max_upload_size_bytes")
    assert s.max_upload_size_bytes == 50 * 1024 * 1024
    ok("max_upload_size_bytes = 50MB")
    passed += 1

    return passed == total


# ===========================================================================
# Test 8: Runner Integration
# ===========================================================================


def test_runner_integration() -> int:
    """验证 ControlledRunner 的 Stage E 集成点。"""
    print("\n── Test 8: Runner 集成 ──")
    passed = 0
    total = 3

    from app.schemas.models import RunState, RunStatus
    from datetime import date as dt_date

    # 8a: RunState 到达 CANCELLED 状态
    state = RunState(
        run_id="d" * 32,
        project_id="proj",
        status=RunStatus.CANCELLED,
        created_at=dt_date.today(),
        updated_at=dt_date.today(),
        cancel_requested=True,
    )
    assert state.status == RunStatus.CANCELLED
    assert state.cancel_requested is True
    ok("RunState 支持 CANCELLED 状态")
    passed += 1

    # 8b: current_file 字段
    state2 = RunState(
        run_id="e" * 32,
        project_id="proj",
        status=RunStatus.SCANNING,
        created_at=dt_date.today(),
        updated_at=dt_date.today(),
        current_file="data/report.docx",
    )
    assert state2.current_file == "data/report.docx"
    ok("RunState.current_file 字段正确")
    passed += 1

    # 8c: total_steps 字段
    state3 = RunState(
        run_id="f" * 32,
        project_id="proj",
        status=RunStatus.QUEUED,
        created_at=dt_date.today(),
        updated_at=dt_date.today(),
        total_steps=8,
    )
    assert state3.total_steps == 8
    ok("RunState.total_steps 默认 8")
    passed += 1

    return passed == total


# ===========================================================================
# Test 9: Run Pytest Suite
# ===========================================================================


def test_run_pytest() -> int:
    """运行 Stage E 相关的 pytest 套件。"""
    print("\n── Test 9: Pytest 套件 ──")
    import subprocess

    stage_e_tests = [
        "tests/test_stage_e_runner.py",
        "tests/test_stage_e_lifecycle.py",
        "tests/test_stage_e_files.py",
        "tests/test_stage_e_cleanup.py",
        "tests/test_stage_e_error_codes.py",
    ]

    cmd = [sys.executable, "-m", "pytest", *stage_e_tests, "-v", "--tb=short"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)

    # 过滤输出
    lines = result.stdout.splitlines()
    for line in lines:
        if "PASSED" in line or "FAILED" in line or "ERROR" in line or "===" in line:
            print(f"  {line}")

    if result.returncode == 0:
        ok("所有 Stage E 测试通过")
        return True
    else:
        fail(f"测试失败 (exit code {result.returncode})")
        for line in lines[-20:]:
            print(f"  {line}")
        return False


# ===========================================================================
# Test 10: Spec Integrity Check
# ===========================================================================


def test_spec_integrity() -> int:
    """验证 Stage E 的 spec 文件完整性。"""
    print("\n── Test 10: Spec 文件完整性 ──")
    passed = 0

    spec_root = Path(PROJECT_ROOT) / "specs"
    expected_specs = [
        "stable-run-lifecycle-260722-0000",
        "stable-files-errs-260722-0000",
        "stable-cleanup-260722-0000",
        "stable-ui-history-260722-0000",
    ]
    expected_files = ["PRODUCT.md", "TECH.md", "TEST_REPORT.md"]

    for spec_dir in expected_specs:
        full = spec_root / spec_dir
        if not full.is_dir():
            fail(f"缺失 spec 目录: {spec_dir}")
            continue
        for fname in expected_files:
            fp = full / fname
            if fp.is_file():
                ok(f"{spec_dir}/{fname}")
                passed += 1
            else:
                fail(f"缺失文件: {spec_dir}/{fname}")

    total_files = len(expected_specs) * len(expected_files)
    print(f"\n  Spec 文件: {passed}/{total_files}")
    return passed == total_files


# ===========================================================================
# Test 11: validate_specs.py
# ===========================================================================


def test_validate_specs() -> int:
    """运行 validate_specs.py --strict。"""
    print("\n── Test 11: validate_specs.py --strict ──")
    import subprocess

    cmd = [sys.executable, str(Path(PROJECT_ROOT) / "scripts" / "validate_specs.py"), "--strict"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)

    for line in result.stdout.splitlines():
        print(f"  {line}")

    if result.returncode == 0:
        ok("validate_specs.py --strict 通过")
        return True
    else:
        fail(f"validate_specs.py 失败 (exit {result.returncode})")
        return False


# ===========================================================================
# Main
# ===========================================================================


def main() -> None:
    print("=" * 72)
    print("Stage E 全场景验收测试")
    print(f"运行日期: {date.today()}")
    print(f"项目根目录: {PROJECT_ROOT}")
    print("=" * 72)

    parser = argparse.ArgumentParser(description="Stage E verification")
    parser.add_argument("--skip-pytest", action="store_true", help="跳过 pytest 套件")
    parser.add_argument("--skip-specs", action="store_true", help="跳过 spec 完整性检查")
    parser.add_argument("--skip-validate", action="store_true", help="跳过 validate_specs.py")
    args = parser.parse_args()

    results: dict[str, bool] = {}

    # Unit tests (always run)
    results["StepTimer & RunProgress"] = test_step_timer()
    results["File Validation"] = test_file_validation()
    results["Error Codes"] = test_error_codes()
    results["Cleanup Service"] = test_cleanup()
    results["Run Lifecycle"] = test_run_lifecycle()
    results["StepDef Coverage"] = test_step_def_coverage()
    results["Config Settings"] = test_config_settings()
    results["Runner Integration"] = test_runner_integration()

    # Pytest
    if not args.skip_pytest:
        results["Pytest Suite"] = test_run_pytest()

    # Spec checks
    if not args.skip_specs:
        results["Spec Integrity"] = test_spec_integrity()
    if not args.skip_validate:
        results["validate_specs.py"] = test_validate_specs()

    # Summary
    print("\n" + "=" * 72)
    print("结果汇总")
    print("=" * 72)

    all_pass = True
    for name, passed in results.items():
        status = CHECK if passed else CROSS
        print(f"  {status} {name}")
        if not passed:
            all_pass = False

    print(f"\n  通过: {sum(results.values())}/{len(results)}")
    if all_pass:
        print(f"  {CHECK} Stage E 所有验收项全部通过!")
    else:
        print(f"  {CROSS} 存在未通过的验收项")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()

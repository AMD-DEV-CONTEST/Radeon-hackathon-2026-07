"""共享测试夹具与路径配置。

把仓库的 ``src/`` 目录插入 ``sys.path``，使 ``import drama...`` 在测试里可用，
并提供一个 ``dry_ctx`` 夹具：在 ``tmp_path`` 下建立一个 dry-run 的 ``Context``，
``config_dir`` 指向仓库真实的 ``config/``，从而无需任何外部依赖即可运行。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 路径常量：从本文件位置推导仓库根，避免依赖 pytest 的工作目录。
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
SHARED_CONTRACTS_SRC_DIR = REPO_ROOT.parent / "shared_contracts" / "src"
CONFIG_DIR = REPO_ROOT / "config"
SAMPLES_DIR = REPO_ROOT / "samples"

# 让 `import drama...` 生效（与 run.py 中的做法一致）。
for source_dir in (SHARED_CONTRACTS_SRC_DIR, SRC_DIR):
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def config_dir() -> Path:
    return CONFIG_DIR


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    return SAMPLES_DIR


@pytest.fixture()
def dry_ctx(tmp_path):
    """构造一个 dry-run 的 Context：项目根在 tmp_path 下，配置用仓库真实 config/。

    dry_run=True 保证 LLMRouter / ComfyClient 全部走桩，不触网、不调 GPU。
    """
    from drama.context import Context

    proj_root = tmp_path / "proj"
    return Context(project_root=proj_root, config_dir=CONFIG_DIR, dry_run=True)

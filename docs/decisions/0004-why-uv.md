# ADR 0004: 依赖管理用 uv(不用 pip / conda / poetry)

- **状态**: Accepted
- **日期**: 2026-07-16
- **决策者**: AMD Radeon Studio Team

## 背景

Python 项目需要选一个依赖管理工具。候选:

| 工具 | 速度 | 锁文件 | Python 版本管理 | Windows 友好 |
|---|---|---|---|---|
| **uv** | ⚡⚡⚡(10-100x pip) | ✅ `uv.lock` | ✅ 内置 | ✅ |
| pip | ⚡ | ❌(需 pip-tools) | ❌ | ✅ |
| conda | ⚡ | ✅ | ✅ | ⚠️ 装包慢 |
| poetry | ⚡⚡ | ✅ `poetry.lock` | ⚠️ 需插件 | ✅ |
| pdm | ⚡⚡ | ✅ | ✅ | ✅ |

## 决策

**采用 uv 0.11+。**

## 后果

### ✅ 优点
- **快** — 装 5GB 的 diffusers + 全部依赖,从 5 分钟降到 30 秒
- **锁文件** — `uv.lock` 跨平台,本机和 AMD Cloud 一致
- **Python 版本管理** — `uv python install 3.11` 一行装好,无需 pyenv
- **简单** — `uv sync` 装全部;`uv add` 加依赖;`uv run` 跑命令
- **AMD Cloud 友好** — Linux 上 `uv sync` 一样快

### ❌ 缺点
- 生态比 pip/conda 新,某些边缘 case 文档少
- Windows 上偶尔有 PATH 问题(需要在 PowerShell 加 `$env:PATH`)

### 🔁 为什么不用 conda
- 装 PyTorch 慢;conda-forge 镜像有时不稳
- 项目已经在用 uv,统一工具链

### 🔁 为什么不用 poetry
- poetry 在 Windows + 多 Python 版本场景坑多
- uv 更快

## 备注

- `uv.lock` 必须 commit(进 git)
- PyTorch 单独走 `uv pip install --index-url https://download.pytorch.org/whl/{cu121|rocm6.1}`(不在 pyproject.toml 的 dependencies 里,见 ADR 0005)

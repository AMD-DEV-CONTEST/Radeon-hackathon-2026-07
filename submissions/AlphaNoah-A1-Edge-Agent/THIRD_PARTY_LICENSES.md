# Third-Party License and Provenance Register

Document status: pre-release audit register.

Last reviewed: 2026-07-23.

Phase status: historical register plus adoption gate. No additional third-party
investigation is scheduled unless a component is selected for actual integration
or distribution.

## Scope and conclusion vocabulary

This register distinguishes repository contents from software, containers and model
artifacts reported on the external prototype machine. At the time of review:

- this repository contains no third-party source code, Git submodules, model
  weights, datasets, media files or executable binaries;
- `pyproject.toml` declares an empty dependency list and `requirements.txt`
  contains no installable requirement;
- the repository's own `LICENSE` reserves all rights and does not currently grant
  an open-source license.

Allowed review conclusions are:

- **Cleared**;
- **Cleared with obligations**;
- **Internal only**;
- **Permission required**;
- **Replace before release**;
- **Unknown**.

No `Unknown`, `Internal only`, `Permission required` or `Replace before release`
item may be distributed as part of a public release without a new review.

## Register

| 名称 | 资产类型 | 来源 | 版本或 Commit | License | 使用方式 | 是否修改 | 商用状态 | 署名要求 | 结论 |
|---|---|---|---|---|---|---|---|---|---|
| Ollama | 外部模型服务 | [官方仓库](https://github.com/ollama/ollama/tree/v0.20.3) | `v0.20.3`（实机仅为报告值） | [MIT](https://github.com/ollama/ollama/blob/v0.20.3/LICENSE) | 原型机外部运行；仓库未捆绑 | 否 | 上游 MIT 允许；实际分发版本仍需复核 | 分发代码/二进制时保留 MIT copyright 和 permission notice | **Cleared with obligations** |
| AMD ROCm | 外部系统运行时集合 | [ROCm component license table](https://rocm.docs.amd.com/en/docs-7.1.1/about/license.html) | 报告 `7.2.0`；安装包清单缺失 | 按组件不同 | 原型机外部运行；仓库未捆绑 | 否 | `Unknown`，须按实际组件判断 | 保留各组件许可证和 NOTICE；生成实际安装 SBOM | **Unknown** |
| PyTorch、Transformers、Accelerate、FastAPI、ModelScope、Triton、Safetensors | Python 包 | 外部 venv；wheel URL/hash 未提供 | 部分报告了版本，完整依赖树/构建缺失 | `Unknown`（本地 wheel 未核实） | 不是当前仓库依赖 | 否 | `Unknown` | 获取实际 wheel、传递依赖和许可证文本后判断 | **Unknown** |
| Open WebUI | 外部容器应用 | [官方 `v0.10.2` license](https://github.com/open-webui/open-webui/blob/v0.10.2/LICENSE) | 应用报告 `v0.10.2`，镜像却为滚动 `main`，digest 缺失 | 自定义/混合条款，含 branding 条款 | 外部容器；仓库未捆绑 | 未知 | 条件性；实际镜像与拟议用途未核实 | 按适用版本保留 notices；不满足明示 branding 例外时须获许可 | **Unknown** |
| `qwen3.5:9b` | Ollama 模型 | [官方 registry](https://ollama.com/library/qwen3.5:9b) | 本地完整 digest/Modelfile 缺失 | 官方当前条目称 Apache-2.0；本地身份未核实 | 外部模型；仓库未捆绑 | 未知 | `Unknown` | 固定本地 digest、上游 revision、模型卡和许可证 | **Unknown** |
| `qwen3.6:27b` | Ollama 模型 | [官方 registry](https://ollama.com/library/qwen3.6:27b) | 本地 digest 缺失；报告能力/context 冲突 | 官方当前条目称 Apache-2.0；本地身份未核实 | 外部模型；仓库未捆绑 | 未知 | `Unknown` | 同上，并保存 `ollama show` | **Unknown** |
| `qwen3.6:27b-32k` | Ollama 模型或本地 alias | 未确认精确官方条目 | `Unknown` | `Unknown` | 外部模型；仓库未捆绑 | 未知 | `Unknown` | 保存完整 digest 与 `ollama show --modelfile`，不得按名称推断 | **Unknown** |
| `gemma4:26b` | Ollama 模型 | [官方 registry](https://ollama.com/library/gemma4:26b) | 本地 digest 缺失；报告能力冲突 | 官方当前条目称 Apache-2.0；本地身份未核实 | 外部模型；仓库未捆绑 | 未知 | `Unknown` | 固定本地身份和适用 license/notice | **Unknown** |
| `qwen3-coder-next:q4_K_M` | Ollama 模型 | [官方 registry](https://ollama.com/library/qwen3-coder-next:q4_K_M) | 本地 digest 缺失 | 官方当前条目称 Apache-2.0；本地身份未核实 | 外部模型；仓库未捆绑 | 未知 | `Unknown` | 固定本地 digest、上游 revision 和 notices | **Unknown** |
| `Qwen3-VL-8B-Instruct` | Transformers 模型/权重 | [官方 Qwen model card](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct) | 本地 snapshot revision 缺失 | 官方仓库 Apache-2.0；本地 snapshot 未核实 | 外部模型目录；仓库未捆绑 | 未知 | `Unknown` | 固定 commit/snapshot 并保留许可证 | **Unknown** |
| `all-MiniLM-L6-v2` | Embedding 模型 | 报告来自外部 Open WebUI；精确源缺失 | `Unknown` | `Unknown` | 外部模型；仓库未捆绑 | 未知 | `Unknown` | 捕获完整模型 ID、revision、来源和许可证 | **Unknown** |
| `alphanoah/yolo11n-rocm:w1` | 自定义 Docker 镜像/模型 | 本地自定义镜像；[Ultralytics 官方许可说明](https://github.com/ultralytics/ultralytics#license) | Dockerfile、base digest、Ultralytics/权重版本缺失 | 可能涉及 AGPL-3.0 或 enterprise；实际路径未知 | 报告已安装、未运行；仓库未捆绑 | 未知 | `Unknown` | 完成构建来源、权重、训练数据、SBOM 和许可审查；否则排除 | **Replace before release** |
| ComfyUI 容器/镜像 | Docker 镜像及可能的 custom nodes | 精确镜像和节点来源缺失 | digest 缺失 | `Unknown` | 报告处于 restarting；仓库未捆绑 | 未知 | `Unknown` | 排除，或从固定且已审查的输入重建并附 SBOM/notices | **Replace before release** |
| HoloAgent-0 | 论文/项目引用 | [arXiv](https://arxiv.org/abs/2606.23565)、[官方仓库](https://github.com/HorizonRobotics/HoloAgent) | Closed / reference only | 本表不推断 | 仅学术与架构引用；没有复制代码、模型、数据或图 | 否 | 引用本身可用；资产复用另审 | 引用论文/项目；引用不授权复制资产；实际采用前重审 | **Cleared** |
| LangChain / LangGraph 文档 | 官方技术文档引用 | [官方文档](https://docs.langchain.com/oss/python/langgraph/overview) | 滚动文档，访问日 2026-07-23 | 不适用（未复制代码） | 仅架构参考；未安装 | 否 | 仅引用不构成软件分发 | 保留来源和访问日期 | **Cleared** |
| Mermaid/ASCII 图与内部 Markdown | 项目内部文档 | 当前仓库 | 未提交材料；个人作者未记录 | 当前仓库 `LICENSE` 为 all rights reserved | 内部设计文档 | 是/未知 | 对外授权状态未批准 | 发布前取得组织级作者/贡献者记录 | **Internal only** |
| OpenCode 审计报告与原始实机证据 | 审计输入/日志 | 用户提供的仓库外文件；见 Evidence Index | SHA-256 已登记 | 内部资料；再发布权未确认 | 只读审计输入，不复制原文进仓库 | 否 | 不对外分发 | 仅保留脱敏、获批摘录或 checksum | **Internal only** |
| 两个 Food-SOP JSON fixtures | 项目原创合成数据 | `examples/synthetic_food_sop_event.json`、`examples/synthetic_corrective_evidence.json` | v0.1 仓库版本 | 当前仓库 all rights reserved | 唯一演示场景的输入和证据 | 否 | 仅当前项目内部演示 | 保留 Synthetic demo data / not production labels | **Internal only** |
| 未来 dataset、图片、音视频、Prompt、fixture | 数据/媒体/文本资产 | 尚不存在；见 Data Policy | `Unknown` | `Unknown` | 尚未使用 | 未知 | `Unknown` | 每项必须先登记来源、版本、许可、hash 和署名 | **Unknown** |

## External runtime is not a repository dependency

The items reported on the prototype machine do not become repository dependencies
merely because an audit document names them. They must be deliberately selected,
pinned and recorded before an implementation or release can rely on them.

In particular:

- “available on the prototype” is not the same as “licensed for redistribution”;
- a model name is not an immutable model identity;
- a mutable container tag is not reproducible provenance;
- an official upstream license does not establish which local build or snapshot was
  used.

## Release gate

Before making the repository public or shipping a hackathon bundle:

1. select and document the repository's own license;
2. obtain an approved contributor/authorship record;
3. generate an SBOM from the actual pinned environment;
4. preserve every redistributed license and notice;
5. pin container digests and model revisions/full hashes;
6. remove or replace every item marked **Replace before release**;
7. resolve every distributed item marked **Unknown**, **Internal only** or
   **Permission required**;
8. rerun this register against the exact release artifact.

This document is an engineering compliance record, not legal advice.

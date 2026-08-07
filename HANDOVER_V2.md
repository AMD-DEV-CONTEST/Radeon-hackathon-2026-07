# NodeFlow 项目交接文档 V2（当前架构）

> 最后更新: 2026-08-04
> 项目: AMD AI DevMaster Hackathon Track 1 参赛作品
> 状态: 已从「单模型 Flux」重构为「多模型 + 双模式 + LoRA」架构,LoRA 集成进行中
> 说明: 本文档是原 `HANDOVER.md` 的**架构演进增量**。原文档中的部署、踩坑、恢复指南仍有效,请配合阅读。

---

## 一、本次会话做了什么（交给 trae code 的核心）

在原始单模型（Flux.1-schnell）基础上，将后端重构为**多模型 + 双模式（快速版/专家版）**架构，并开始集成 LoRA。

### 1.1 新增的核心能力

| 能力 | 说明 |
|------|------|
| **双模式** | `fast`（快速版，蒸馏模型少步）/ `expert`（专家版，全权重可调） |
| **多模型热切换** | 通过 `ModelManager.switch_model()` 在多个模型间切换，带回滚保护 |
| **模型注册表** | `config.MODEL_REGISTRY` 集中管理所有模型元数据 |
| **适配器模式** | `adapters/` 下按架构分：`sdxl_adapter` / `flux2klein_adapter` |
| **LoRA 注册表** | `config.LORA_REGISTRY` 集中管理预推荐 LoRA（本次新增） |
| **LoRA 批量下载** | `lora_downloader.py`（本次新增） |
| **模型商店** | `store_service.py` 聚合 HuggingFace/Civitai 热点模型 |

### 1.2 架构分层（重点）

```
前端 (React + Excalidraw)
   │  /api/*
   ▼
main.py (FastAPI 路由层)
   │
   ▼
engine.py (FluxEngine 兼容门面，委托给 ModelManager)
   │
   ▼
model_manager.py (ModelManager 单例：模型加载/切换/生成/LoRA)
   │
   ├── adapters/sdxl_adapter.py        (SDXL 系)
   ├── adapters/flux2klein_adapter.py  (FLUX.2 系)
   └── store_service.py                (模型商店，独立)
```

**关键设计**：`engine.py` 保留 `FluxEngine` 类名和单例语义，作为薄门面把一切委托给 `model_manager.ModelManager`，旧代码无需改动即可工作。

---

## 二、当前模型注册表（config.MODEL_REGISTRY）

| model_id | 模式 | 架构 | 说明 | 许可证 |
|----------|------|------|------|--------|
| `sdxl_lightning_4step` | fast | sdxl | SDXL Lightning 4 步蒸馏 | Open RAIL++-M 可商用 |
| `sdxl_lightning_8step` | fast | sdxl | SDXL Lightning 8 步蒸馏 | Open RAIL++-M 可商用 |
| `flux2klein_distilled` | expert | flux2klein | FLUX.2 Klein 蒸馏版 | Apache 2.0 |
| `flux2klein_base` | expert | flux2klein | FLUX.2 Klein 完整版 | Apache 2.0 |
| `animagine_xl` | expert | sdxl | Animagine XL 4.0（动漫） | SDXL License 可商用 |
| `illustrious_xl` | expert | sdxl | Illustrious XL（动漫） | Fair AI 禁商用 |
| `noobai_xl` | expert | sdxl | NoobAI XL 1.0（动漫，用户指定） | Fair AI 禁商用 |

**默认模型**：`DEFAULT_FAST_MODEL_ID = "sdxl_lightning_4step"`（快速版默认）。

### 2.1 关键设计决策（用户确认）

- **NoobAI XL 用于比赛**：用户认识开发方，比赛非商用，故 Fair AI 许可证可用。
- **各模型独立参数**：`default_params` + `param_ranges`（步数/引导/强度），且支持 `locked` 标志（如蒸馏模型步数锁定）。
- **比例映射**：SDXL 系（64 倍数）与 Flux 系（16 倍数）两套 `RATIO_MAPPINGS`，避免用错比例导致崩图。

---

## 三、LoRA 集成（本次新增，重点）

### 3.1 三层职责分离（用户核心诉求）

用户明确要求：**基础模型选好后，每个风格都带一个 LoRA**。设计上避免"系统自动猜模型"，而是三层解耦：

1. **基调（谁画）**：用户显式选「Anime 系 / 写实系 / 通用系」 → 对应选模型
2. **主题（怎么画）**：选风格 → 自动拼 prompt + 自动挂风格 LoRA
3. **LoRA 权重**：可调 → 实现「真人底 + 动漫 LoRA」的混合效果

### 3.2 config.LORA_REGISTRY（已实现）

新增在 `config.py` 末尾，每个条目字段：`id/name/category/architecture/base_hf/file_name/download_url/target_path/default_weight/license/commercial_use/note`。

**已填充下载地址的（可下载）：**

| ID | Category | Arch | 用途 | 许可 | 商用 |
|----|----|----|----|----|----|
| `sdxl_detail_tweaker` | general_quality | sdxl | SDXL 通用细节增强（可双向调） | CDLA-Permissive-2.0 | 是 |
| `flux_add_details` | general_quality | flux | FLUX.1-dev 细节增强 | FLUX.1-dev Non-Commercial | 否 |
| `flux_realistic_lora` | general_quality | flux | FLUX.1-dev 写实摄影 | FLUX.1-dev Non-Commercial | 否 |

**已占位待填地址的风格 LoRA（8 个）：** `sdxl_cyberpunk / sdxl_anime / sdxl_watercolor / sdxl_oil_painting / sdxl_3d_render / sdxl_pixel_art / sdxl_concept_art / sdxl_minimalist`（均 `download_url=None`，`target_path` 已预设）。

### 3.3 lora_downloader.py（新增）

```bash
cd backend
python lora_downloader.py --list          # 列出所有 LoRA 及可下载状态
python lora_downloader.py                # 下载全部已填地址的 LoRA（跳过已存在）
python lora_downloader.py --id sdxl_detail_tweaker  # 只下载指定 ID
python lora_downloader.py --force       # 强制覆盖
```
- 复用 `store_service.download_model`（异步流式、进度日志、大小校验）
- 目标目录 `/persistent/loras/{arch}/xxx.safetensors`
- Civitai 链接需 `CIVITAI_API_TOKEN` 环境变量；HF resolve 链接免鉴权

### 3.4 已复用未改的文件

- `model_manager.py` / `adapters/sdxl_adapter.py`：已有 `load_lora/unload_lora/get_loaded_loras`，兼容新注册表
- `store_service.py`：已有点下载能力，无需改

---

## 四、关键注意事项（接手者必读）

### 4.1 FLUX LoRA 兼容性问题（重要）

**当前 FLUX 底座是 `FLUX.2-klein-4B`，但找到的 LoRA 都是 `FLUX.1-dev` 训的，架构不通用。**

- `flux_add_details` / `flux_realistic_lora` 均为 FLUX.1-dev 非商用许可
- FLUX.2-klein 的 LoRA 生态尚不成熟，实际加载需在服务器上验证兼容性
- 若无法加载，可留空或换 repo

### 4.2 风格 LoRA 地址待填充

8 个风格化 LoRA 的 `download_url` 留空，需要：
- 从 Civitai 挑选对应风格且许可合规的 LoRA
- 配置 `CIVITAI_API_TOKEN` 才能下载
- 或改用 HF 托管的风格 LoRA（免 token）

### 4.3 快速版权重建议

SDXL-Lightning 是蒸馏模型，LoRA 权重不宜拉满：
- 通用优化：建议 `default_weight * 0.7`
- 风格化：建议 `default_weight * 0.8`
- 否则易出噪点/崩图

### 4.4 前端待办（UI 由 Trae Design 负责）

前端应增加：
- **基调选择器**（Anime/写实/通用），用户显式选模型，不自动猜
- 风格列表调 `/api/styles`，选风格后自动挂对应架构的 LoRA
- LoRA 权重可调（默认 `default_weight`，快速版自动降权）

---

## 五、API 端点清单（当前）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 前端页面 |
| `/api/info` | GET | API 基础信息（含当前模型） |
| `/api/health` | GET | 健康检查（含 GPU 状态） |
| `/api/styles` | GET | 风格列表 |
| `/api/models` | GET | 指定模式下的模型列表（`?mode=fast`） |
| `/api/models/current` | GET | 当前已加载模型 |
| `/api/models/{id}/config` | GET | 某模型参数配置 + 比例详情 |
| `/api/models/switch` | POST | 切换模型 `{model_id}` |
| `/api/loras` | GET | 已加载 LoRA 列表 |
| `/api/loras/load` | POST | 加载 LoRA `{path, weight}` |
| `/api/loras/unload` | POST | 卸载 LoRA `{lora_id}` |
| `/api/store/models` | GET | 模型商店热点模型（`?source=hf`） |
| `/api/store/loras` | GET | 模型商店热点 LoRA |
| `/api/store/download` | POST | 下载模型/LoRA 到本地 |
| `/api/gpu/status` | GET | GPU 显存状态 |
| `/api/generate/text2img` | POST | 文生图（可选 mode/model/style/param） |
| `/api/generate/img2img` | POST | 图生图（multipart） |

---

## 六、待办清单（按优先级）

- [ ] **P0** 补充 8 个风格化 SDXL LoRA 的 `download_url`（从 Civitai 挑选，需 token）
- [ ] **P0** 前端：增加「基调选择器」（Anime/写实/通用）
- [ ] **P0** 后端：在 `generate` 端点里，根据所选风格自动加载对应 LoRA（按架构匹配）
- [ ] **P1** 验证 FLUX.1-dev LoRA 在 FLUX.2-klein 上的兼容性
- [ ] **P1** 模型商店前端对接（浏览/下载热点模型）
- [ ] **P2** 无限画布上叠加生成结果（目前只在右侧面板展示）

---

## 七、本次会话重要文件清单

| 文件 | 状态 | 说明 |
|------|------|------|
| `/workspace/backend/config.py` | 已改 | 新增 `LORA_REGISTRY`、`DOWNLOADABLE_LORA_IDS`、补充 `LICENSE_INFO` |
| `/workspace/backend/lora_downloader.py` | 新增 | LoRA 批量下载脚本 |
| `/workspace/backend/model_manager.py` | 已建（上文） | 模型加载/切换/生成/LoRA 调度 |
| `/workspace/backend/engine.py` | 已建（上文） | 兼容门面，委托 ModelManager |
| `/workspace/backend/adapters/` | 已建（上文） | `base_adapter` / `sdxl_adapter` / `flux2klein_adapter` |
| `/workspace/backend/store_service.py` | 已建（上文） | 模型商店，聚合 HF/Civitai |
| `/workspace/backend/main.py` | 已改（上文） | 新增模型/LoRA/商店/生成端点 |
| `/workspace/CHANGELOG_LoRA.md` | 新增 | LoRA 集成专项变更记录（可与本文档合并） |

---

## 八、交接给 trae code 的明确指令

1. **先读 `HANDOVER.md`（原）掌握部署/踩坑/恢复 + 本文档（V2）掌握架构演进**
2. **当前最高优先级**：补全 8 个风格化 LoRA 的下载地址，并让 generate 端点按风格自动挂载 LoRA
3. **遵守设计约定**：基调（模型）由用户显式选，系统不自动猜；LoRA 按架构匹配，快速版降权
4. **FLUX 注意**：LoRA 是 FLUX.1-dev 的，需在服务器上验证 FLUX.2-klein 兼容性
5. **环境**：HF 镜像 `HF_ENDPOINT=https://hf-mirror.com`，模型缓存 `/persistent/hf_cache`，venv `/persistent/venv`
6. **代码风格**：中文注释，Python 类型标注，复用既有 `store_service.download_model`，不重复造轮子

---

## 九、用户偏好（延续自原文档）

- 用中文交流，技术术语可用英文
- 需要高级感、丝滑动效的 UI（参考即梦、Liblib）
- 重视比赛提交质量
- 修 bug 先在本地修好再部署
- 模型/参数选择：用户显式定，系统不自动猜；各取所长靠用户掌控
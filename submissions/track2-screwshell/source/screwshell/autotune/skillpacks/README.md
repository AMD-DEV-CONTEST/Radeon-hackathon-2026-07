# SkillPacks (L1)

每个底模 / LoRA 专家是一个**独立文件夹**，内含 `manifest.json`（adapter.gguf 由用户自行放入，本目录只放元数据，不打包权重）。

目录扫描生成路由阵容——这就是 README 承诺的 *"plug-and-play: drop a GGUF adapter in, gain a skill"*。新增一个社区 adapter = 丢一个文件夹进来，无需改 `SkillRouter.DEFAULT_SKILL_MAP`。

## manifest.json 字段

| 字段 | 含义 |
|---|---|
| `name` | 包名（= 引擎注册名 = `--lora` 挂载名） |
| `kind` | `lora` 或 `base` |
| `skill` | 它服务的规范技能标签：`tool/code/agent/security/doc/base` |
| `base_fingerprint` | **钉死的底模指纹**（如 `Qwen/Qwen3.6-27B`）。与部署底模不符的包会被 `build_skill_map` 直接丢弃——从机制上杜绝 hermes_s2 式静默错配 |
| `vram_gb` | 该 LoRA 额外占用的显存（GB），供 planner 算预算 |
| `domain_tags` / `route_keywords` | 领域标签与路由关键词（未来精细路由用） |
| `smoke_test` | 一条冒烟测试用例：`{prompt, expect_contains}` |

## 当前阵容（与 router.py 定稿一致）

- `btl3` → tool / code
- `teichai_plan` → agent
- `cybersec` → security
- `rag_n7` → doc（失败则回退纯基座）

下方四个 manifest 是示例元数据；真实 GGUF 需从上游仓库转好后放入对应文件夹。

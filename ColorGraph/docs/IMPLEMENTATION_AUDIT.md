# ColorGraph 当前实现审查

> 审查日期：2026-07-30
> 对照规格：[PROJECT_SPEC.md](PROJECT_SPEC.md)  
> 当前执行后端：NVIDIA GeForce RTX 5060 Ti + CUDA 13.0  
> 本轮范围：比赛提交材料和 AMD/ROCm 实机专项之外的本地 MVP；已合并 2026-07-28 算法正确性复审  
> 状态定义：**完成**＝真实链路可运行；**部分完成**＝已有可运行子集但未覆盖完整规格；**未完成**＝当前仓库无实现。

## 1. 结论

本轮定义的本地 MVP 已形成真实闭环，不再是静态前端概念稿：

但“闭环可运行”不代表专业色彩正确性或创意 Agent 默认上线门禁已经全部达标。Sony/显式色彩变换、输入元数据、CFR/VFR 高位深 PTS、逐场景 LUT、project 命令作用域和 mask 资产完整性已修复，完整 OCIO 2.5.2 / ACES 2 v3 运行时、v3 标准调色算子及离线创意 Agent Shadow Pipeline 已接入；CUDA 数值门禁已通过，真实来源摄取与严格 Gold Set 审计已实现。本地 Ollama 多模态 provider 已完成真实、非缓存 shadow，并跑通 Director → 3/3 Strategist → 真实候选 → 换位 Critic 的单 scene 技术链；该运行跳过 Reflection，正式评测只认定为 `no_reflection` 技术种子。默认仍关闭。ROCm 实机报告、达到配额并独立签核的人工 Gold Set、获许可检索语料和专家创意评测仍见 [TODO.md](TODO.md)。

```text
视频 + 可选参考图 + 自然语言
→ 媒体、镜头、色彩与本地 CLIP 分析
→ 跨镜头 Scene 归组与 Typed Grade Graph
→ SegFormer / Depth Anything 时序蒙版
→ CUDA 上的确定性调色、关键帧和组合 Mask Graph
→ 范围感知增量预览与本地候选 A/B
→ 视频渲染、技术质检、定向修复
→ MP4 + 33³ LUT + JSON + FFV1 蒙版 + 质量报告
```

本机已经用 640×360、25 FPS、6 秒、150 帧、3 个硬切镜头的回归视频完成浏览器端到端验证。项目可在刷新后自动恢复；真实双视频播放器以媒体时钟同步，统一时间线可任意 seek；Exposure 关键帧默认锁定并以草稿/提交事务编辑、取消和撤销。自然语言“天空……但不要改变山体”会编译为 `sky AND NOT mountain`，候选采用硬检查、意图规则和本地 CLIP 的成对比较。

比赛材料和 AMD/ROCm 实机专项仍按用户要求排除；仓库仅保留迁移接口、独立依赖入口和验收清单，不宣称 AMD 已验证。

## 2. 规格逐项状态

### 2.1 输入、媒体与时间结构

| 能力 | 状态 | 实现证据 / 边界 |
| --- | --- | --- |
| 本地视频上传与项目目录 | 完成 | FastAPI multipart 上传、隔离目录、原片本地保存 |
| 项目持久化与重新打开 | 完成（MVP） | 后端列出持久化项目；Web UI 启动时恢复最近项目 |
| FFprobe 媒体解析 | 完成 | 时长、宽高、FPS、帧数、编码、像素格式；range/primaries/transfer/matrix/bit depth/chroma；HDR mastering/CLL |
| 色彩元数据 provenance | 完成 | stream/container/pixel format/side data/user override/missing 来源、置信度、原始值与冲突状态随 Grade Graph 持久化 |
| 自动镜头检测 | 完成 | OpenCV 直方图/差分检测，回归片识别 3 个硬切 |
| 代表帧抽取 | 实现完成，待 Gold 验收 | 自适应 3/5/7 候选、转场边距、质量过滤、cosine medoid UI 帧和鲁棒均值 shot embedding；API/CLI 共用实现 |
| 曝光/白平衡统计 | 实现完成，待 Gold 验收 | 排除天空/雪地/霓虹/单一主色；鲁棒联合色度估计；逐帧及 shot 有效样本比例和不确定性 |
| 镜内光照变化点 | 实现完成，待 Gold 验收 | 不确定性加权 Huber + L1 robust trend filter、持续变化点和孤立闪烁门控 |
| Exposure/Temperature 关键帧 | 完成 | 自适应曲线简化、非均匀时间 PCHIP、旧 Catmull–Rom 兼容、速度/加速度约束 |
| 自动 Sub-shot 实体 | 部分完成 | 能建立 sub-shot 时间作用域；尚无独立 Sub-shot 列表编辑器 |
| 跨镜头 Scene 归组 | v2 shadow，待冻结 test | 鲁棒多帧 embedding + 色彩/语义/可选音频连续边界分数、calibration-only 阈值和全局解码；默认保留旧贪心 groups |
| 20–45 秒、3–8 镜头约束 | 部分完成 | 支持该范围，上传接口不做硬拒绝 |
| 显式 SDR/工作空间 | 完成（ACES v3） | sRGB、BT.709 OETF、Rec.1886、Linear Rec.709、ACES2065-1、ACEScg、ACEScct；不再用 `rec709` 混指传递函数 |
| 指定 Log | 完成 | Sony S-Log3 与 DJI D-Log 使用官方 OCIO camera input transform；v2 Mavic 3 display LUT 语义在迁移时显式告警；未知 profile 明确报错 |
| 可选参考图 | 完成 | JPG/PNG/WebP 上传、CLIP Look 排名与逐镜头相似度 |

### 2.2 Typed Grade Graph 与确定性调色

| 能力 | 状态 | 实现证据 / 边界 |
| --- | --- | --- |
| 严格 Typed Grade Graph | 完成 | Pydantic schema、枚举、引用/顺序校验、JSON 持久化、GET/PUT |
| Input/Working/Output Transform | 完成（renderer v3） | camera input→ACES2065-1→ACEScg、ACEScct creative、ACES 2 Output Transform；声明、顺序、作用域、profile 和版本配对严格校验；v1/v2 保持旧外观 |
| Project / Scene / Shot / Sub-shot 时间范围 | 完成 | 节点具有明确 temporal scope |
| 空间作用域与蒙版引用 | 完成 | 全局、语义、深度与组合 scope |
| 节点顺序与开关 | 完成 | 后端排序执行，前端修改并持久化 |
| Exposure / Temperature / Tint | 完成（v3 标准化） | ACEScg scene-linear exposure；CCT+Duv/xy + CAT16/Bradford 白平衡；v1/v2 兼容旧 RGB gain |
| ASC-CDL slope/offset/power | 完成（v3 标准化） | OCIO `CDL_NO_CLAMP` 负值语义，reference processor 对比通过 |
| Contrast / Saturation / Highlights | 完成（v3 encoding-aware） | ACEScct 18% pivot、AP1 灰轴及保持色相的高光曝光偏移 |
| 基础 tone curve | 完成（v3 encoding-aware） | ACEScct shadows/midtones/highlights 区域曝光偏移 |
| LUT 读取、插值与缓存 | 完成（v3 tetrahedral） | `.cube` 1D shaper/3D/组合、tetrahedral/trilinear、CLF/CTF OCIO processor；path/mtime/ctime/SHA-256/device/dtype 缓存键与文件替换失效 |
| 场景 Look | 完成（版本化实例） | Natural、Cool、Warm、Foggy 共享 `colorgraph.look-recipes/v1`；实例记录 base recipe、覆盖与脏状态 |
| 逐场景 LUT 导出 | 完成 | 每个 scene/look 独立 processor；Post Look 策略与空间、时间、size、interpolation 写入 v2 manifest |
| 时间关键帧逐帧渲染 | 完成（PCHIP） | hold/linear/非均匀时间 PCHIP；缓存分段系数、二分定位、单调不超调；旧 `cubic_spline` 保留兼容回放 |
| 单蒙版与组合 Mask Graph | 完成（MVP） | fuzzy AND/OR/NOT；目标名或 asset ID；安全小型 DSL |
| GPU 批量视频渲染 | 完成（CFR/VFR 高位深） | FFmpeg `rgb48le` + PyTorch FP32 + HEVC Main10；VFR 逐帧 PTS、BT.709 VUI、limited range、音频映射与 8-bit 代理隔离均有实测 |
| 音频保留 | 完成 | 原视频可选音轨映射与 AAC |
| OpenColorIO | 完成（v3） | 运行时固定 PyOpenColorIO 2.5.2 与 ACES 2 Studio Config；官方 Sony/DJI input processor、ACEScg/ACEScct 边界、SDR sRGB/Rec.1886 Output Transform、迁移预览和 reference golden comparison 均有回归 |
| 独立 CDL 文件导出 | 未完成 | CDL 参数已在 JSON，未单独输出 `.cdl`/`.ccc` |

### 2.3 本地多模态与蒙版

| 能力 | 状态 | 实现证据 / 边界 |
| --- | --- | --- |
| 本地多模态场景理解 | 完成（MVP） | CLIP 对 terrain/lighting/risk/look 排序并生成归一化 embedding |
| SigLIP2 scene/intent shadow | 工程路径完成，待 Gold/实机 | 单批图像/文本缓存、独立 sigmoid 多标签、unknown/OOD、raw cosine/logit 与 calibration-only 温度/阈值已实现；bootstrap 不授权替换 CLIP |
| 参考图理解 | 完成 | 参考图 Look 排名和代表帧余弦相似度 |
| 语义分割 | 完成 | 固定 revision SegFormer B0 ADE20K，GPU FP16；模型/映射/阈值证据持久化 |
| B5/OneFormer 语义 shadow | 三模型实机 runtime 完成，待 Gold | B0/B5/OneFormer exact revision 已真实推理；固定矩阵按 water/vegetation/mountain 逐类 IoU、Boundary-F、时序稳定性、FPS、VRAM 与许可哈希 fail-closed；OneFormer 另已生成 7423 帧正式资产 |
| SAM/Cutie/SEA-RAFT VOS shadow | 三模型实机 runtime 完成，待 Gold/平台 | SAM 2.1/Cutie/SEA-RAFT 已在 Windows CUDA 真实运行；SAM 2.1 另完成 7423 帧资产。五模型同域失败场景、许可分发与剩余平台矩阵继续 fail-closed |
| 正式模型来源/许可审计 | 完成（机器审计） | 9 个候选绑定官方 revision、许可、安装 SHA 与 runtime；6 个通过许可门、5 个 runtime-ready。SegFormer-B0/B5 非商业，SAM 3.1 checkpoint 仍 gated |
| 语义类别映射 | 完成（v2） | earth/land、vegetation、mountain、rock、cliff、sand 互斥可配置；缺失 checkpoint class 显式报告 |
| 天空/植被/水面/山体 | 完成 | 真实逐像素概率蒙版；confidence 明确为阈值内模型概率而非 accuracy |
| 雪地/道路/建筑 | 完成（模型层） | provider 可按请求生成；默认 UI 不批量生成 |
| 深度估计 | 两候选实机完成，待 Gold | DA-V2 Small shot 尺度/不确定性；VDA-S shot/重叠窗口 float depth 已真实运行；frame DA-V2 exact revision 已生成 7423 帧正式性能资产 |
| 蒙版时序传播 | 完成 | Farneback backward warp + 周期模型重锚定；明确 `bidirectional_consistency=false` |
| 蒙版逐帧资产 | 完成 | PNG/FFV1；frame count、尺寸、FPS、alias、SHA-256 与完整解码硬校验；OneFormer/DA-V2 五个 16-bit 和 SAM 2.1 一个生产长度资产已安装，缺帧默认报错 |
| Mask Graph 逻辑组合 | 完成（MVP） | `AND`、`OR`、`NOT`、括号与 fuzzy mask 运算 |
| 几何蒙版编辑器 | 未完成 | 尚无渐变、圆形、多边形和画笔 |
| HSL 颜色限定蒙版 | 未完成 | 尚无独立 qualifier |
| 提示式任意对象分割 | 部分完成 | SAM 2.1 语义 anchor + 有界视频传播已接入并完成 7423 帧资产；点/框交互编辑器与 Gold 默认授权仍未完成 |
| 人工蒙版修正 | 未完成 | UI 可查看，尚不能画笔修改 |

### 2.4 Agent、候选与增量修改

| 能力 | 状态 | 实现证据 / 边界 |
| --- | --- | --- |
| Landscape Grade Grammar | 完成（MVP） | 稳定模板、参数约束、作用域、保护项和解释 |
| 中英文自然语言指令 | 完成 | 区域、冷暖、曝光、保护项与时间词 |
| 时间段与镜头定位 | 完成（v2 grammar） | project 逐 shot 展开；scene/shot/前后半段使用精确范围并同步关键帧 |
| 缺失蒙版请求 | 完成 | planner 返回 targets，前端触发真实 mask job |
| 保护区域编译 | 完成 | “天空但不改变山体”生成 `sky AND NOT mountain` |
| 增量失效范围 | 完成 | 每项 edit 记录 affected range，project/scene/shot/sub-shot 与 invalidated ranges 一致 |
| 自然语言撤销 | 完成 | CommandPlan 精确前态；Web `Ctrl/Cmd+Z` 恢复并持久化 |
| 范围感知预览缓存 | 完成 | 仅对当前时间生效节点做内容寻址；其他镜头缓存不失效 |
| 最终视频分段缓存 | 未完成 | 最终交付视频仍整段重渲染 |
| 自动生成候选 | 完成（版本化） | 固定占位不伪造缩略图；四配方按当前真实帧渲染，返回前三并携带配方版本与 Graph 摘要 |
| 多模态 A/B 偏好评审 | 完成（MVP） | 硬检查优先、意图语法、CLIP 与成对胜场 |
| Look 切换与恢复 | 完成 | 完整五参数应用、脏覆盖确认、重复点击保留修改、显式恢复、过期候选阻止应用及 undo/redo |
| 多轮修改 | 完成（图状态） | 每轮修改累积到同一 Grade Graph |
| 长期偏好/对话存储 | 未完成 | 没有跨项目用户画像 |
| 生成式 7B/8B VLM | 未完成 | 当前采用 CLIP + 规则，刻意保持轻量、稳定、可解释 |
| 创意 provider runtime | 完成（默认关闭） | 角色独立 provider、严格 schema、预算/重试/取消/circuit、双重上传同意、离线 fallback、缓存与无密钥审计已完成；本地 Ollama 真实、非缓存单 scene shadow 已绑定能力、boundary、配置/实际 revision、运行摘要和 response receipt，并通过统一 readiness；云端或新部署身份仍须重新取证 |
| 闭卷 Creative Director / 创意 RAG | 部分完成（工程边界） | 三方向 typed brief、证据/反证和反俗套审计已完成；三路 possibility retrieval 支持许可硬过滤、OOD 空 bundle 与派生 embedding 删除；正式 corpus 摄取另要求独立内容/权利复核和内容绑定授权。已有 ACES/OCIO 官方文本 intake，但仍为未签核草案 |
| ColorStrategy / deterministic compiler | 完成 | baseline 与 creative 分层；typed strategy 经版本化 operation cards 编译为隔离候选，未知字段、越权 scope、保护冲突和 QC 绕过整批失败 |
| 有预算三方向搜索 | 完成 | 正式 renderer、1–3 代表帧、未钳位硬 QC、取消/恢复、幂等缓存、损坏重验及首选/第二名资产保留 |
| Visual Critic | 部分完成（工程门禁） | 盲化 A/B、强制换位、八维区域证据/反证和捷径探针已完成；正式 gate 从内容绑定专家 bundle 与冻结 Critic reports 重算相关性/偏差，重复/篡改/身份失配 fail-closed；无生产模型与专家冻结集时禁止自动选择 |
| 四门 Pareto 排序 / Reflection | 完成 | delivery→意图/保护→时序→项目偏好，后门不补偿前门；Reflection 最多一次最小 patch，退化或预算失败精确回滚 |
| 离线 Agent Shadow 编排 | 完成 | 真实多 scene 后台 pipeline、阶段快照、取消/恢复、显式 skipped stage、应用摘要锁与精确撤销；确认前当前图不变 |
| 创意 Agent 上线评测 | 部分完成（工程 evaluator） | 八维专家评价、规则/七类消融、Wilson CI、Fleiss κ、位置/自评偏差、硬失败非劣、red-team 与成本报告已实现；review freeze/assemble 将真实素材、候选、资格、独立盲序和原始提交内容绑定；统一 readiness 报告当前仍阻断 5 项，缺冻结生产集和至少 3 名真实合格专家 |

### 2.5 质量验证与修复

| 能力 | 状态 | 实现证据 / 边界 |
| --- | --- | --- |
| 高光剪裁、阴影压死 | 完成 | 数值阈值、状态和详情 |
| 过饱和 | 完成 | 像素占比 |
| 时间闪烁 | 完成（运动补偿 v1） | 以源视频光流分离 camera/object、云水、真实亮度、源曝光跳变与调色闪烁，并保存逐帧/区域证据 |
| 结构损失 | 完成 | 原片/结果边缘结构比较 |
| 蒙版抖动、光晕 | 完成（运动补偿 v1） | warp 后边界误差、有效 flow、连通区域和边缘亮度证据；转场与非刚体运动显式分类 |
| 天空色带 | 完成 | 天空区域梯度/量化统计 |
| 显式色域检查 | 部分完成 | 正式候选记录钳位前 finite/gamut 观测并作为硬门；尚无完整 gamut volume |
| LUT 连续性专项指标 | 未完成 | LUT reader 有格式校验，未写入质量报告 |
| Verifier 定向修复 | 完成（预算搜索） | 节点消融定位责任源，多轮局部候选绑定时间/区域、评估预算、缓存与回滚点 |
| 修复后择优 | 完成（硬门） | 目标必须改善，硬指标、非目标质量和意图漂移不得退化；否则原图/成片保持不变 |
| Gold Set 契约 | 部分完成 | strict manifest、授权/capture metadata、split 防泄漏、冻结 test、SHA-256、真实来源摄取、逐帧 PTS 工作包、版本化人工 provenance、P0 配额审计和程序化 bootstrap 已完成；6 个授权来源（含私有 DJI D-Log 片段）待标注，真实人工配额未满足 |
| 跨后端精度门禁 | 部分完成 | CPU FP32/CUDA FP32、preview、ΔE2000 与三次确定性报告已通过；ROCm 实机报告仍缺 |
| 统一评测报告 | 完成 | 镜头/scene/mask/depth/色彩/排序/工程指标；单命令报告记录版本、配置、硬件和素材哈希 |
| 专家盲测流程 | 完成 | 至少 3 名专家、显示校准、独立随机 A/B、身份 key、拒绝原因、Wilson 95% CI 与 Fleiss κ |

### 2.6 产品界面、API、CLI 与导出

| 能力 | 状态 | 实现证据 / 边界 |
| --- | --- | --- |
| React 调色工作台 | 完成 | 预览、时间线、节点、候选、质检、资产、命令，以及可审计 Agent Shadow run、scene/方向切换、显式应用与撤销 |
| 原片/结果 A/B | 完成 | 后端真实 JPEG |
| 真实设备与 FPS | 完成 | API 实时报送，不使用静态 Radeon 文案 |
| 真实镜头与缩略图 | 完成 | 后端动态回填 |
| 真实蒙版预览 | 完成 | 按帧读取模型输出；缺失时明确显示“未生成”，不画假蒙版 |
| 节点参数编辑 | 完成（核心子集） | Exposure、温度、对比、饱和、高光、Look strength；拖动松手单次持久化并进入图事务 undo/redo |
| 真实播放器与统一时间线 | 完成 | 双视频媒体时钟、暂停精确帧、A/B/静音/循环；任意位置鼠标/触控 seek、ARIA 播放指针和逐帧键盘 |
| 高分辨率与 Main10 播放档位 | 完成 | 540p/1080p/1440p/2160p、禁止放大、H.264/HEVC Main10 内容寻址缓存、MediaCapabilities + 实播回退、状态保持、自动策略与逐档本机遥测 |
| 关键帧可视化与编辑 | 完成（事务化） | 默认锁定、先选择后编辑、5 px 阈值、草稿不落盘、pointer-up 原子保存、Esc、精确输入、undo/redo |
| 后台任务与进度 | 完成 | Job API、轮询与 SSE |
| 最近项目恢复 | 完成（MVP） | `GET /api/projects` + localStorage 自动恢复 |
| 项目选择器 | 未完成 | 当前只自动恢复最近项目 |
| CLI | 完成 | doctor / analyze / render / Gold / evaluate / precision-gate / production-benchmark / sam2-mask-asset / tracked-mask-assets / research-watch-audit / formal-model-source-audit / shot-shadow-observe / shot-shadow-eval / vlm-shadow-calibrate / vlm-shadow-observe / semantic-shadow-observe / semantic-shadow-eval / vos-shadow-eval / creative-provider-shadow / creative-corpus-audit / creative-ablation-audit / creative-ablation-matrix-audit / creative-review-freeze / creative-review-assemble / creative-agent-eval / creative-critic-calibrate / creative-agent-readiness |
| 调色 MP4 | 完成 | CUDA 用 NVENC，CPU 用 x264 |
| `.cube` LUT | 完成 | 33×33×33，按 scene/look 独立输出 |
| Grade Graph / 质量报告 | 完成 | JSON schema、指标、阈值、详情 |
| 蒙版导出 | 完成 | FFV1，PNG 回退 |
| ZIP 交付包 | 完成 | manifest + 成片 + 可编辑资产 |
| 桌面应用/剪辑插件 | 未完成 | 当前交付形式为 Web UI + CLI |

## 3. 本机验证证据

### 3.1 环境

| 项目 | 实测 |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5060 Ti |
| 显存 | 16,311 MB |
| PyTorch | 2.12.1+cu130 |
| CUDA runtime | 13.0 |
| FFmpeg | 8.1 |
| 编码器 | `h264_nvenc`、`h264_amf`、`libx264` |

### 3.2 回归结果

| 验证 | 结果 |
| --- | --- |
| 镜头检测 | 3 个：0–2.04、2.04–4.08、4.08–6.00 秒 |
| 镜内轨道 | 6 条 Exposure/Temperature 轨道 |
| CLIP embedding | `[1, 512]`，L2 norm 1.0 |
| 参考图相似度 | 三镜头约 0.935 / 0.955 / 0.833 |
| 语义/深度蒙版 | 5 targets、150 帧、6–8 个模型锚点 |
| CUDA 无蒙版渲染 | 约 140.8 FPS |
| CUDA + FFV1 mask | 冷启动约 60.8 FPS，预热约 69.2 FPS |
| CPU 无蒙版渲染 | 约 87.8 FPS |
| 质量闭环 | 初始 46 分失败，定向修复后 94 分通过 |
| 候选 A/B | 清冷提示推荐 `cool`，胜场 3/3 |
| 组合蒙版 | `sky AND NOT mountain` 在 CUDA 预览成功 |
| 增量缓存 | 相同时间/图状态返回同一 key 且命中 |
| 关键帧编辑 | 1.50 → 1.45，UI、PUT 和磁盘 JSON 一致 |
| ZIP | 约 10.8 MB，含 MP4/LUT/JSON/report/5 路 mask |
| 浏览器 | 刷新恢复、编辑、命令、候选、导出通过；另完成 3-scene Agent 9 候选/27 帧、第二名应用和精确撤销 |

这些数字只用于当前工程基线，不代表 AMD、1080p 或 4K 性能。

## 4. 自动测试状态

已执行：

```text
ruff check backend/colorgraph backend/tests
pytest
npm run typecheck
npm run build
Playwright 真实浏览器端到端
```

结果：

- Ruff：全仓通过；
- Pytest：545 passed（84 个测试文件）；
- TypeScript：通过；
- Vite production build：通过；
- Playwright：既有工作台回归为 0 errors / 0 warnings；Agent 取消竞态中的过晚请求按契约返回 409，最终成功 run 无运行时错误；真实 provider opt-in 又在 1440×900 / 1024×768 验证默认关闭、双确认前禁用和 console 0 errors / 0 warnings。

自动测试覆盖 Grade Graph、设备抽象、调色/色彩管理、内容感知曝光/WB 与鲁棒轨迹、关键帧、逐场景 LUT、媒体、项目存储、planner、mask 资产完整性、场景归组、候选图修改、范围感知缓存、统一评测/盲测、质量报告 v2、运动补偿时序证据、创意约束、provider runtime/shadow、闭卷 Director、创意检索、授权 corpus 审计、typed strategy/compiler、候选 search、Critic、内容绑定 calibration、四门 ranking、Reflection、Agent UI/pipeline、专家 review freeze/assemble、创意 Agent evaluator/readiness、质量修复、生产长片矩阵门禁和研究观察项转正门禁。外部模型真实 shadow、生产模型权重、语料独立签核和专家评审仍分别受凭据/同意、资源、许可和人工门禁约束。

## 5. 仍未完成与算法审计新增阻塞项

算法审计已发现会影响专业色彩正确性的 P0 项，不能再归类为“不阻塞母版交付”。完整拆解和验收条件见 [TODO.md](TODO.md)，调研证据见 [ALGORITHM_RESEARCH.md](ALGORITHM_RESEARCH.md)。

1. 在受支持 ROCm 实机执行已实现的 FP32/ΔE2000/确定性门禁；本机 Raphael iGPU 不在官方支持矩阵内；
2. 基于当前 6 个授权来源继续扩充规模覆盖，并完成达到配额的独立人工真值；私有 DJI Log 来源在许可文本完成独立权利复核前不得公开再分发；
3. SAM 2 类点/框/文字提示式分割；
4. 几何蒙版、HSL qualifier 和画笔修正；
5. 最终视频的分段缓存与增量拼接；
6. 可选择的项目列表和跨自然语言命令的统一 undo/redo 历史栈（关键帧、Look、节点参数与开关的图事务已完成）；
7. 独立 CDL 导出、gamut volume 与 LUT 连续性指标；
8. 20–45 秒输入策略提示和 1080p/4K 自动基准；
9. 可选生成式本地 VLM 与长期偏好数据；
10. 桌面封装或 DaVinci/Premiere 插件。

## 6. 当前明确排除

- 比赛项目简介 PDF；
- PPT、海报；
- 3–5 分钟演示视频；
- AMD Radeon / ROCm 驱动安装、wheel 选择、实机性能与兼容验收。

ROCm 迁移接口和验收方案见 [ROCM_BACKEND.md](ROCM_BACKEND.md)。在清单完成前，任何文档或 UI 都不得标记为“AMD 已验证”。

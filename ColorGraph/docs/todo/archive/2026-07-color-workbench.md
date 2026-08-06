# 2026-07 Archive — 色彩质量与工作台

> [TODO 入口](../../TODO.md) · [任务目录](../README.md)
>
> 本文件归档 9 个已完成任务；仅在追溯实现、验收证据或历史依赖时加载。

## 色彩、关键帧与 LUT

- [x] **CG-COLOR-010 — 引入 OCIO 2.5.x 与 ACES 2 色彩管理**
  - 官方 camera input transform → ACES2065-1。
  - ACEScg 执行 scene-linear 操作，ACEScct 执行创意调色。
  - ACES 2 Output Transform 处理 tone、chroma、gamut 和 display encoding。
  - 保留 legacy renderer，提供项目迁移预览和版本化。
  - 依赖：CG-COLOR-001、CG-COLOR-002、CG-EVAL-003。
  - 完成标准：与 OCIO/ACES reference processor 的 golden comparison 达标。
  - 验收证据（2026-07-29）：
    - 新增配对的 `colorgraph.grade-graph/v3` / `colorgraph.renderer/v3`；新项目默认使用固定的 PyOpenColorIO `2.5.2` 和官方 `studio-config-v4.0.0_aces-v2.0_ocio-v2.5`，v1/v2 项目继续按原 renderer 回放。
    - Sony S-Log3/S-Gamut3.Cine 与 DJI D-Log/D-Gamut 由官方 OCIO camera input transform 先进入 ACES2065-1，再进入 ACEScg；BT.709 OETF/Rec.1886 先显式解码后通过 OCIO 进入同一 interchange/working 链。
    - Exposure/白平衡阶段位于 scene-linear ACEScg；CDL、contrast、saturation、highlight、tone 与 Look/Post Look 由显式 ACEScg↔ACEScct 边界包围；未声明 ACEScct 输入的旧 `.cube` LUT 会阻止自动迁移。
    - 输出由 ACEScg→ACES2065-1 后进入 ACES 2 SDR Display/View Transform，显式支持 sRGB Display 与 Rec.1886 Rec.709 Display；不再用逐通道 soft clip 代替 v3 输出变换。
    - `GET /api/projects/{id}/color-pipeline/migration-preview` 只生成迁移候选和风险；确认接口保存 `grade_graph.pre-aces-v3.json` 后才写入 v3，旧参数响应变化、旧 LUT 和 DJI display-LUT 语义均有明确警告或阻止条件。
    - 冻结的 10 组 ACES2065-1→sRGB Display / ACES 2.0 SDR 100 nits 向量与新运行时逐值比较在 `2e-6` 内通过；Sony/DJI 官方输入 processor cache、ACES2065-1/ACEScg 分段及 FP16→FP32 提升均有回归。
    - 后端全量当前 `180 passed`，全仓 Ruff、TypeScript 和 Vite production build 通过；`colorgraph doctor` 回报固定 OCIO/ACES 配置与全部 processor cache ID。

- [x] **CG-COLOR-011 — 用标准调色算子替换启发式实现**
  - ASC CDL 负值行为符合标准。
  - 白平衡使用 CCT+Duv/xy 和 Bradford/CAT16，而非经验 RGB gain。
  - 对比度、tone、highlight、saturation 使用 encoding-aware 算子。
  - 删除或隔离逐通道 heuristic soft clip。
  - 依赖：CG-COLOR-010。
  - 完成标准：灰轴、高光 hue、gamut sweep 和旧项目迁移对比通过。
  - 验收证据（2026-07-29）：
    - renderer v3 的 ASC CDL 使用 OCIO `CDL_NO_CLAMP` 语义：SOP 为负或零时跳过 power，正值执行逐通道 power；冻结样本与 PyOpenColorIO reference processor 在 `1e-4` 内一致。
    - ACEScg 白平衡将归一化 Temperature/Tint 显式映射为 CCT+Duv 和 CIE xy，默认使用 CAT16，并保留 Bradford 选项；零调整严格恒等，两种 CAT 都通过源/目标白点映射回归。
    - Contrast 以 ACEScct 编码中的 18% scene-linear 灰为 pivot；saturation 使用 AP1 luminance 灰轴；highlight/tone 使用 ACEScct 区域曝光偏移，保持通道差与高光色相。
    - v3 的扩展色域 sweep 保持有限值且不裁掉 `<0` / `>1` 数据；逐通道 soft clip 仅保留在 v1/v2 compatibility renderer，v3 交由 ACES 2 Output Transform。
    - 迁移对比直接渲染同一旧 v2 图：只读 preview 前后逐位一致，确认迁移后的 v3 外观差异被显式告警；v1/v2/v3 仍按版本独立回放。
    - 新增 7 项标准算子/迁移专项回归；后端全量当前 `180 passed`，全仓 Ruff、TypeScript、Vite production build 和 `colorgraph doctor` 均通过。

- [x] **CG-KF-001 — 以非均匀时间 PCHIP 替换默认 Catmull–Rom**
  - 支持实际 keyframe 时间间隔。
  - 保持平台/单调数据不超调。
  - 预计算区间系数并用二分或单调游标查找。
  - 增加非均匀时间、平台、边界、重复时间和导数连续测试。
  - 完成标准：已知过冲样例不再超过关键帧值域，性能不低于现状可接受范围。
  - 验收证据（2026-07-29）：
    - 新建 `ParameterTrack` 默认序列化为 `pchip`；既有显式 `cubic_spline` 继续按旧 uniform Catmull–Rom 回放，不静默改变保存项目。
    - 后端按真实秒数计算 Fritsch–Butland 加权调和切线和受限单边端点切线，预计算每个区间的 Hermite 三次系数，并通过 `bisect_right` 定位区间。
    - 单调/平台 sweep 始终留在关键帧值域，非均匀 `0/1/4 s` 冻结样例命中解析值 `446/297`，边界钳制、关键点精确命中、重复时间拒绝和内部一阶导数连续均通过。
    - 时间线 SVG 使用同一 PCHIP 切线生成精确 cubic Bézier，并按轨道分段；UI 标注改为 `PCHIP · 单调`，不再展示与渲染器不同的 Catmull–Rom 预览。
    - 100 个非均匀关键帧的缓存热态微基准约 `14.7 µs/eval`（25,000 次本机求值），相对逐帧 GPU 调色成本可忽略；6 项新增关键帧/兼容回归通过。
    - 后端全量当前 `180 passed`，全仓 Ruff、TypeScript 和 Vite production build 通过。

- [x] **CG-LUT-010 — 四面体 LUT、shaper/CLF/CTF 与设备缓存**
  - 支持 tetrahedral interpolation，并保留 trilinear compatibility mode。
  - 缓存键包含 path、mtime/摘要、device 和 dtype。
  - 支持 shaper+3D LUT；评估 CLF/CTF processor。
  - 增加非线性 LUT、轴序、domain、缓存失效、33³/65³ 和 HDR 测试。
  - 依赖：CG-COLOR-010。
  - 完成标准：质量模式使用明确插值；文件替换后不会读取旧缓存。
  - 验收证据（2026-07-29）：
    - `.cube` 原生 PyTorch 路径新增 tetrahedral sampler；非线性交叉项样本与 PyOpenColorIO `INTERP_TETRAHEDRAL` 在 `2e-6` 内一致，trilinear 作为显式 compatibility mode 保留。
    - parser 支持 1D shaper、3D LUT、组合 shaper+3D、`DOMAIN_MIN/MAX`、`LUT_1D_INPUT_RANGE` 与 `LUT_3D_INPUT_RANGE`；红最快轴序、扩展/HDR domain 和 33³/65³ identity 均有回归。
    - v3 新图在 Look 参数中显式写入 `lut_interpolation=tetrahedral` 与 `lut_input_space=acescct`；v1/v2 默认 trilinear，v2→v3 迁移也把合格旧 LUT 固定为 trilinear，避免暗改旧外观；导出 manifest 改为显式 tetrahedral。
    - CPU parse 与设备 tensor 分层缓存；文件签名包含绝对 path、size、mtime/ctime 和 SHA-256，设备键再包含 device/dtype。覆盖同一路径 LUT 后摘要与输出立即变化，FP32/FP64 产生独立设备缓存项。
    - `.clf` / `.ctf` 由固定 PyOpenColorIO 2.5.2 `FileTransform` 执行并缓存 Processor/CPUProcessor；两种格式的任意 OCIO exponent transform 与 reference 输出一致，cache ID 可审计。
    - 新增 8 项 LUT/迁移回归；后端全量 `180 passed`，全仓 Ruff、TypeScript 和 Vite production build 通过，CUDA precision gate 同时覆盖 tetrahedral 设备路径。

## 播放器与时间线

- [x] **CG-PLAYER-001 — 完善真实预览播放器与媒体时钟**
  - 播放/暂停必须控制真实媒体或连续调色代理，而不是只推进 React 内部计时器。
  - 以媒体时钟为时间码和播放指针的单一真值，统一处理播放、暂停、seek、结束、循环和空项目状态。
  - 分离暂停时的单帧调色预览与连续播放链路，修复高频时间更新持续取消延迟预览请求、导致画面静止的问题。
  - 明确原片/调色 A/B、静音、缓冲、加载失败和不支持编码时的 UI 状态；保留空格键播放控制。
  - 完成标准：真实项目点击播放后画面连续前进，时间码、播放指针和媒体帧同步；暂停/恢复/seek 不跳帧，不产生预览请求风暴，并有浏览器回归测试。
  - 验收证据（2026-07-29）：
    - 原片 `<video>` 成为唯一媒体时钟，使用 `requestVideoFrameCallback`（兼容回退为 `timeupdate` / RAF）驱动时间码和播放指针；调色代理视频作为从时钟同步播放，播放/暂停、seek、结束与循环均直接操作真实媒体。
    - 连续播放不再应用 CSS 近似调色，而是按当前完整 Grade Graph、清晰度和编码生成 4 秒内容寻址的真实调色分片；当前位置优先，连续缓冲达到 2 秒即可播放，之后串行维持约 12 秒前向缓存。seek 或图变化会废弃过期任务，首播等待不随视频总时长增长；暂停后仍以 220 ms 防抖请求后端精确原片/调色单帧。
    - 原片/调色拖拽 A/B、静音、循环、加载、缓冲、播放、精确单帧、失败和不支持编码状态均有明确 UI；空格键与按钮共享同一播放控制路径。
    - 预览 API 将超出原片时长的代理尾端时间钳制到 `(frame_count - 1) / fps`；真实 59.94 FPS ProRes 的最后有效帧为 `123.823700 s`，请求代理尾端 `123.866667 s` 返回 200，不再落到不可解码的 `123.832041 s`。
    - Playwright 真实项目回归：双视频 `readyState=4`，播放时钟差小于 24 ms；暂停与 60 秒 seek 后两路时间完全一致并恢复精确单帧；非循环尾端正确 ended，循环尾端回绕后继续播放；A/B 分隔线命中 25%，静音/循环和空格键均通过。
    - 最终冷启动浏览器会话 console `0 errors / 0 warnings`；后端全量 `181 passed`，全仓 Ruff、TypeScript 和 Vite production build 通过。

- [x] **CG-PLAYER-002 — 增加 10-bit HEVC 与更高分辨率预览档位**
  - 在现有 540p/1080p H.264 兼容档位之外，按源素材尺寸提供 1440p 与最高 2160p（4K）预览；不得放大低分辨率源素材。
  - 增加带 `hvc1` 标签、Main10 profile、`yuv420p10le` 像素格式和正确 range/primaries/transfer/matrix 元数据的 HEVC 10-bit 代理，代理缓存键必须包含 codec、profile、bit depth、分辨率和颜色标签。
  - 前端使用 `navigator.mediaCapabilities.decodingInfo()` 并结合实际播放结果检测解码能力、流畅度与功耗效率；不支持 HEVC Main10、10-bit 合成或目标分辨率时自动回退到 H.264 8-bit，不得出现黑屏或无限加载。
  - 分辨率、codec 或位深切换必须保持当前时间、播放/暂停状态、A/B 双路同步和暂停时的精确单帧；界面显示当前实际 codec、位深与分辨率，不把“可解码”表述为“端到端 10-bit 显示”。
  - 记录每个档位的代理体积、首帧等待、平均码率、解码丢帧、CPU/GPU 占用和双路播放稳定性，并为带宽、设备能力和省电模式提供可解释的自动档位策略。
  - 完成标准：`ffprobe` 验证 Main10 和颜色标签；受支持设备上的 10-bit ramp 相比 8-bit 代理无额外 banding；不支持设备可靠回退；1080p/1440p/4K 切换和播放状态恢复均有浏览器回归测试。
  - 验收证据（2026-07-29）：
    - 浏览器代理和真实调色播放缓存均支持 540p/1080p/1440p/2160p，按源宽高等比缩放并以 `min(1, ...)` 禁止放大；缓存键和 sidecar 固定 codec、profile、bit depth、pixel format、目标宽高/FPS、BT.709 limited 标签及 `avc1`/`hvc1`。
    - HEVC 路径输出 Main10、`yuv420p10le`、`hvc1`、limited range 和 BT.709 primaries/transfer/matrix；真实 libx265 fixture 与项目源/调色代理均经 ffprobe 回读一致。1024 级 ramp round-trip 中 H.264 8-bit 占用 219 个解码码值、Main10 占用 846 个，最大相邻步长由 517 降至 224，没有新增 banding。
    - 前端以 `navigator.mediaCapabilities.decodingInfo()` 检测 supported/smooth/powerEfficient，并以 `canPlayType` 兼容回退；实际媒体加载/解码失败会保持时间和播放状态后强制 H.264。Playwright 将 HEVC 源强制返回 415 时，双路恢复为 H.264、`readyState=4`，暂停点保持 `0.119825 s` 且同步误差为 0，没有黑屏或无限加载。
    - 清晰度增加“自动”偏好：省流模式、effective connection/downlink、device memory、hardware concurrency 和目标分辨率 MediaCapabilities 共同决定档位并显示原因；手动四档始终可选。当前浏览器低带宽提示自动选择 540p，4K 实播遥测捕获到缓冲风险，从而不会把“可解码”误当作“适合自动 4K”。
    - 每个项目持久化 `colorgraph.preview-playback-metrics/v1`，逐档记录原片/调色代理体积与平均码率、首帧 P50/P95、总帧/丢帧、缓冲、双路同步均值/P95/max、ready/stable 比例以及短采样 CPU、GPU、解码器和显存占用；短 4K fixture 已覆盖 540p、1080p H.264/HEVC、1440p 与 2160p，完整证据见 `output/evidence/player-profile-metrics.json`。
    - Playwright 在播放态完成 540p→1080p 恢复，在暂停态完成 1080p↔HEVC/H.264、1440p 和 2160p 切换；1440p/2160p 两路分别回读 2560×1440/3840×2160，并在 `1.45434 s` 完全同步。UI 显示实际 codec、位深和分辨率，HEVC 明示“显示链路未验证”，不宣称端到端 10-bit。
    - 最终 production build 冷启动会话 console `0 errors / 0 warnings`，视觉证据为 `output/playwright/player-profile-final.png`；后端全量 `189 passed`，全仓 Ruff、TypeScript 和 Vite production build 通过。

- [x] **CG-TIMELINE-001 — 支持任意位置 seek 和播放指针拖拽**
  - 将播放指针改为可聚焦、可命中的交互控件，使用 pointer capture 支持鼠标和触控连续拖动。
  - 时间标尺及轨道空白区域均可按横向位置 seek，不依赖镜头块、刻度按钮或参数关键帧。
  - seek 时间限制在 `0..duration`；帧吸附作为可选行为，并支持方向键逐帧微调。
  - 播放指针拖动与参数关键帧编辑必须有清晰的命中区域和事件隔离，拖动播放指针不得改动任何调色参数。
  - 完成标准：可从时间线任意位置点击或拖到任意合法时间，播放指针、预览帧和时间码一致；鼠标、触控和键盘路径均有回归测试。
  - 验收证据（2026-07-29）：
    - 标尺、Scene、镜头和参数轨道组成统一 seek surface；任意空白位置按轨道横向比例定位，拖动由 Pointer Events + pointer capture 持续跟踪，离开轨道后仍能完成并钳制到 `0..duration`。
    - 播放指针改为可聚焦的 ARIA slider，具备 19 px 命中宽度、明确 hover/focus/drag 状态；左右键按真实 `1 / fps` 微调，Home/End 到首尾，当前 59.94 FPS 项目的单步实测为 `0.016683 s`。
    - 帧吸附开启时，37.1% 标尺点击和 73% 指针拖动分别精确落在 `45.945900 s`、`90.406983 s`；关闭吸附后 33.333% 参数轨道点击落在 `41.279714 s`，与最近帧网格保持 `0.005147 s` 差值。
    - Chrome DevTools 触控注入从 20% 连续拖到 55%，精确得到 `68.112211 s`；越界鼠标拖动钳制为项目尾端 `123.840383 s`，释放后 scrubbing 状态正常清除。
    - 关键帧 circle 在 pointer/keyboard 路径上停止事件冒泡，播放指针、标尺、轨道空白的全部回归前后 Exposure keyframes JSON 完全一致；seek 与参数编辑命中区互不污染。
    - 慢速拖动 1.2 秒期间精确预览 POST 为 `0`，pointer up 后恰好 `1` 次；production build 冷启动会话 console `0 errors / 0 warnings`。
    - 后端全量 `180 passed`，全仓 Ruff、TypeScript 和 Vite production build 通过。

- [x] **CG-KF-UI-001 — 为参数轨道增加防误改、锁定与撤销**
  - 参数轨道默认只读，提供清晰的轨道锁定状态和显式“编辑关键帧”模式；未解锁时点击只负责 seek。
  - 关键帧先选中再编辑，并设置合理拖动阈值；普通点击、播放指针拖动和轻微指针抖动不得修改数值。
  - 拖动期间只做临时预览，在 pointer up 后原子提交；支持 `Esc` 取消、undo/redo，并在提交前后显示时间与参数值。
  - 自动保存只在一次编辑明确提交后触发，不得把 pointer move 中间态连续写入 Grade Graph。
  - 提供精确时间/数值输入、参数单位和轨道名称；当前仅实现 Exposure 时，不使用容易误解为任意参数的泛化标签。
  - 完成标准：锁定状态零误写；解锁后关键帧可精确编辑、取消和撤销，seek 与编辑互不冲突，并有持久化及浏览器交互回归测试。
  - 验收证据（2026-07-29）：
    - Exposure 轨道默认显示“已锁定”，锁定态拖动只 seek：Grade Graph PUT 为 `0`、关键帧 JSON 不变且不打开精确编辑器；解锁后必须先选择，第二次指针操作超过 `5 px` 阈值才进入编辑。
    - 关键帧 SVG 命中层高于播放指针但透明区域不截获 seek；精确编辑器内 Lucide 图标不再继承整轨 SVG 尺寸。真实命中测试中已选 circle 位于播放指针上时 `elementFromPoint` 仍返回关键帧，应用与取消按钮各自保持 `11 px` 图标和独立命中区。
    - 在播放指针已移到 `52.018633 s` 的边界场景中，慢拖 1.2 秒得到草稿 `96.1294 s / 0.5168 EV`；松手前后端仍为 `90.13333333333334 s / 0.07968 EV`，且 preview POST/Grade Graph PUT 均为 `0`；松手后各恰好 `1` 次并原子落盘。
    - `Esc` 取消恢复事务原图且 PUT 为 `0`；精确输入 `91.2500 s / 0.2500 EV` 由真实按钮点击原子提交；工具栏 undo/redo 恢复/重做完整图快照，最终回到原值。上述提交、取消和撤销全程 5 个蒙版资产 JSON 不变。
    - Production build 冷启动 Playwright 会话 console `0 errors / 0 warnings`；视觉验收截图为 `output/playwright/keyframe-transaction-final.png`。后端全量 `180 passed`，全仓 Ruff、TypeScript 和 Vite production build 通过。

- [x] **CG-LOOK-UI-001 — 明确候选 Look、实例覆盖与恢复语义**
  - 区分“尚未运行本地 A/B 的固定配方占位”与“基于当前真实帧渲染并排序的候选”，不得用 CSS 模拟缩略图冒充真实候选结果。
  - 前后端共享同一套版本化 Look recipe；点击候选时必须应用生成该缩略图所用的完整参数，包括 `strength`、`contrast`、`saturation`、`temperature` 和 `highlights`，禁止预览与实际应用参数不一致。
  - 将已选 Look 建模为 `base_recipe_id + user_overrides + dirty` 的项目实例；用户修改节点后持久化为实例覆盖，不得反向污染全局固定配方。
  - 再次点击当前已选 Look 默认不重置用户修改；提供独立、明确的“恢复原始 Look”操作，并纳入 undo/redo。
  - 切换到其他 Look 时只替换当前作用域的 Look 实例，保留 Balance、Tone、Mask 等无关节点；如会丢弃当前 Look 覆盖，必须明确提示。
  - 相关 Grade Graph 发生变化后标记候选缩略图过期，重新比较后更新真实缩略图、推荐结果和图摘要；界面显示“已修改”状态。
  - 完成标准：覆盖刷新恢复、重复点击、切换、显式恢复和撤销路径行为一致；候选缩略图与最终渲染像素一致，并有 API、持久化及浏览器回归测试。
  - 验收证据（2026-07-29）：
    - 后端以 `colorgraph.look-recipes/v1` / `2026-07-29.1` 提供唯一版本化配方目录，候选记录配方版本、完整五参数和稳定 Graph SHA-256；应用接口校验摘要与版本，禁止过期候选或预览/应用参数漂移。
    - Scene Look 持久化为 `colorgraph.look-instance/v1` 的 `base_recipe_id + user_overrides + dirty`；重复点击当前配方保持覆盖，显式恢复精确回到基准，切换脏实例返回结构化冲突并要求确认，仅替换当前 Scene Look，Balance、Tone 与 5 路 Mask 均保持不变。
    - Grade Graph 的节点参数、开关、关键帧、Look 切换/恢复统一进入图事务 undo/redo；滑杆拖动只在松手后产生一次 PUT，恢复、撤销和重做均原子持久化。
    - 未比较时四个固定配方为禁用占位，实测 `background-image: none`、`filter: none`；本地 A/B 后三张卡片使用后端生成的真实 JPEG URL，图变化或半帧时间差会立即标记过期，重新比较刷新摘要。
    - API/持久化回归覆盖脏状态冲突、确认切换、当前配方不重置、恢复、无关节点保留、摘要失效和 planner 新配方基准；后端全量 `180 passed`，全仓 Ruff、TypeScript 与 Vite production build 通过。
    - Production build 冷启动 Playwright 会话 console `0 errors / 0 warnings`；真实候选视觉验收见 `output/playwright/look-ui-final.png`，只读比较前后项目 Grade Graph SHA-256 完全一致。

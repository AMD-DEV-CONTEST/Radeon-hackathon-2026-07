# 2026-07 Archive — 质量分层与创意约束

> [TODO 入口](../../TODO.md) · [任务目录](../README.md)
>
> 本文件归档质量报告 v2 与创意例外边界的完成任务和验收证据。

- [x] **CG-QA-002 — 扩展 banding、结构和辅助感知评分**
  - 加入 CAMBI 或等价 banding 指标。
  - DOVER/TOPIQ 等只作为经本域校准的辅助分数。
  - 保留合法范围、NaN、clipping、gamut、metadata 等硬检查。
  - 依赖：CG-EVAL-002。
  - 完成标准：质量报告分离技术硬失败、感知风险和审美偏好。
  - 验收证据（2026-07-30）：
    - `colorgraph.quality-report/v2` 将 `hard_technical`、`perceptual_risk` 和校准后的辅助审美偏好拆成独立通道；审美分数不参与硬门禁，也不能补偿 metadata、PTS、有限值、合法范围、资产、编码、色彩管线或 clipping 失败。
    - 新增 `colorgraph.cambi-equivalent/v1` 多尺度等价指标，明确不冒充 Netflix CAMBI；平滑渐变、16 级 posterization 和纹理渐变冻结样本分数分别为 `0.0416664 / 0.3202342 / 0.0`。未带本域 calibration ID/digest 的 DOVER/TOPIQ 类分数直接拒绝。
    - 真实 DJI Main10 250 ms 输出抽样 8 帧：技术门禁通过、BT.709 metadata 完整、banding P95 为 0；旧合成成片则被正确判定为“缺交付色彩元数据”的技术失败，同时把 `mask_halo=0.185813` 单列为感知 warning。专项与约束集成 `14 passed`，报告见 `output/evidence/quality-report-v2-evaluation.json`。

- [x] **CG-AGENT-013 — 实现分层约束和有意例外策略**
  - 明确三层权限：交付约束不可豁免；高光剪切、黑位堵塞、肤色/雪色偏移、过饱和和细节损失属于默认保护；情绪、色彩关系、对比结构、视觉重心和风格组合属于创意空间。
  - 定义 typed `IntentionalException`：`kind`、理由、证据、时间/空间作用域、数值预算、受保护属性、自动/用户批准来源和失效条件；例外必须在渲染前声明，不能用渲染后的失败反向补理由。
  - 交付约束至少覆盖 color pipeline/schema、有限值、输入输出变换、资产完整性、帧/PTS、编码和元数据；任何 Agent 输出都不能豁免。
  - 默认保护只允许 allowlist 中的可测例外，例如局部 `controlled_highlight_bloom` 或限定范围的 `intentional_shadow_crush`；自动模式设置保守上限，更严重偏离要求用户确认。
  - QC 同时报告“允许范围内的有意偏离”和“超预算/扩散到保护对象的非预期损害”，不能因存在 reason 字段就直接通过。
  - 依赖：CG-AGENT-010、CG-QA-002。
  - 完成标准：同一 clipping 指标能稳定区分局部受控 bloom、全局失控剪切和不可豁免的非法输出；伪造理由、事后补例外和作用域外损害均被拒绝。
  - 验收证据（2026-07-30）：
    - `colorgraph.creative-constraint-policy/v1` 固定三层权限；typed `IntentionalException` 绑定 graph/candidate digest、已知证据、声明时间、时空/mask scope、数值预算、保护属性、批准来源、到期时间和失效条件。
    - 自动批准采用更保守的 metric cap；用户扩大范围必须携带 approval reference。理由文本本身没有豁免权，交付层永远不可豁免，创意维度只作为独立信号。
    - 同一 highlight clipping 指标稳定得到：局部预声明 bloom=`allowed_intentional_deviation`、全局扩散=`fail_unexpected_damage`、NaN/非法输出=`fail_delivery`。伪造证据、事后声明、越 scope、损害额外保护对象和超预算均拒绝；专项 `8 passed`，报告见 `output/evidence/creative-constraint-policy-v1.json`。

# GTM AI 员工全量界面实现报告 V1

日期：2026-08-01  
状态：本地高保真产品原型已实现并完成代表性浏览器验收  
目标：Web / B2B / 前台—中台—后台全链路

## 1. 产品主线

产品被统一为一套可检查、可审批、可追溯的 GTM Mission Control：证据进入系统后形成策略、创意、九渠道表达、实验与学习；所有高影响动作在发布前保留人工决策边界。

## 2. 已实现界面域

### 前台 / Operator

- Mission Home：任务脉冲、证据状态、人工优先队列与产品全景入口。
- Evidence / Brief / Create / Verify / Export：沿用并升级五道关卡工作流。
- Channel System：Amazon、Shopify、Meta、TikTok、LinkedIn、YouTube、Performance Max、Email、Landing Page 九渠道原生表达。
- Experiment Lab：预注册假设、控制组/处理组、样本与停止规则。
- Learning Room：性能、创意疲劳和受众学习的证据约束视图。
- Visual Studio：GPT 生图资产、原始输出与 8K 交付母版的来源边界。

### 中台 / Operations

- Mission Graph、Run Trajectory、Agent Topology。
- Memory & Knowledge、Evaluation Control、Approval Operations。
- AI FinOps、Asset Studio 与技术记录视图。

### 后台 / Governance

- Tenants & Access：租户、角色与访问矩阵。
- Policy Center：声明证据、渠道与地区、模型工具、审批发布、数据留存。
- Connector Registry：外部系统连接状态与权限边界。
- Runtime & Model Registry：运行时拓扑、模型和工具注册。
- Data Governance：分类、驻留、留存、删除与审计生命周期。

## 3. 视觉系统

- 方向：深矿物黑、冷青、紫晶、琥珀与薄荷状态色；编辑感衬线主叙事配合工业无衬线与等宽证据标签。
- 原创 GPT 图像作为“受治理的增长智能星图”，避免机器人、模板化 HUD 和伪造数据。
- 桌面端采用三栏控制台；移动端收敛为顶部五关卡导航和单列内容。
- 支持清晰焦点、44px 交互目标、高对比模式和减少动效偏好。

## 4. 图像交付

- 模型源文件：`web/assets/visuals/gtm-intelligence-constellation-gpt.png`，1672 × 941。
- 8K 交付母版：`web/assets/masters/gtm-intelligence-constellation-gpt-8k.png`，7680 × 4320。
- 真实性边界：8K 文件为确定性重采样交付母版，不宣称是模型原生 8K 输出。

## 5. 验证结果

- `npm run build`：通过；44 个路由、12 个交互契约、8 个同源 API 契约。
- `.venv/bin/python -m unittest tests.test_v10_gtm_employee`：7/7 通过。
- `.venv/bin/python -m unittest discover -s tests`：632/632 通过。
- 浏览器代表性验收：桌面首页、移动首页、前台九渠道、后台策略中心均已截图复核。
- 证据文件：`web/verification-evidence.json`。

## 6. 当前边界

这是本地高保真可交互实现。生产身份、租户数据库、外部连接器和生产模型尚未接入；真实广告/营销结论必须在来源证据及人工审批完成后才可释放。

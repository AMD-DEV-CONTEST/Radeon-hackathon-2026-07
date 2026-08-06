# ProofLaunch Klaviyo × Open Lovable 前台收尾记录 V1

日期：2026-08-06  
状态：产品前台已重构；Open Lovable 构建已验证；外部抓取/模型/沙箱调用待凭据注入当前进程。

## 1. 最终方向

本轮不再做“后台模板换色”。首页采用明亮、编辑式、产品证据优先的 GTM 品牌前台：

- 首屏用单一强主张、明确 CTA、五段执行链和事实边界解释产品；
- 中段用真实本地产品路由截图呈现生产工作室和生命周期 cockpit；
- 下段保留 B2B/B2C 冻结样例、13 个平台原生交付面、真人审阅队列和未证效果；
- 首页进入产品后继续复用既有 46 路由、58 个同源 API 合约、Graph/Loop/Harness 与人类发布闸门。

视觉节奏参考 2026-08-06 观察到的 Klaviyo 官网：留白首屏、单一高饱和视觉、真实产品 UI、珊瑚/酸性绿品牌区块、长页面产品叙事。Zendesk 仅用于信息层级与可理解性对照。

## 2. Open Lovable 开源魔改基座

- 上游：`https://github.com/firecrawl/open-lovable`
- 固定 commit：`69bd93bae7a9c97ef989eb70aabe6797fb3dac89`
- 许可证：MIT
- 本地验证：依赖安装完成；移除构建时 Google Font 网络依赖后，Next.js 生产构建通过；33 个静态/动态页面与 API 路由完成生成。
- 已验证 SDK：Firecrawl、Vercel Sandbox、E2B Code Interpreter。

Open Lovable 在本项目中的职责是“结构提取与响应式重构加速器”，不是直接替换 ProofLaunch 运行时。任何生成结果必须经过以下迁移闸门：

1. 不复制 Klaviyo 或 Zendesk 的商标、文案、客户 Logo、图片和专有代码；
2. 只迁移布局语法、节奏、信息层级和交互模式；
3. 使用 ProofLaunch 自有内容、自有图形和真实本地产品截图；
4. 不破坏 46 路由、58 API 合约、租户边界、真人发布闸门和事实状态；
5. 必须通过 DOM、静态资源、键盘、缩放、减少动效与回归测试后才能进入提交包。

## 3. 凭据边界

用户确认 Firecrawl、模型和 Vercel/E2B 凭据已经配置，但在本次 Codex 终端会话中，下列进程变量均不可见：

- `FIRECRAWL_API_KEY`
- `VERCEL_OIDC_TOKEN`
- `E2B_API_KEY`
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY`

本轮没有复制、打印或写入任何密钥，也没有伪造 Firecrawl、模型或沙箱调用成功。Open Lovable 已达到可构建状态；当凭据通过 `.env.local` 或进程环境注入时，可直接恢复抓取 → 品牌提取 → React 生成 → 沙箱预览链路。

## 4. 已完成验证

- ProofLaunch Web 构建：46 路由、58 同源 API 合约；
- UI 专项：17/17；
- 产品关键回归：827/827；
- Open Lovable 生产构建：通过；
- 真实产品截图：Frontier GTM production studio、GTM lifecycle cockpit；
- 事实边界：真人偏好、生产效果、具名产品胜出仍未观察，不升级为完成。

## 5. 仍需外部动作

1. 把现有 Firecrawl、模型与 Vercel/E2B 凭据注入启动 Open Lovable 的同一终端进程；
2. 对目标 URL 做一次小范围 Firecrawl scrape/screenshot，先验证额度和返回结构；
3. 运行源站身份剥离提示，生成 ProofLaunch 品牌版本；
4. 只把通过人工视觉审阅的结构差异移植到 `web/`；
5. 再次运行 17 项 UI、827 项产品关键回归和最终锁。


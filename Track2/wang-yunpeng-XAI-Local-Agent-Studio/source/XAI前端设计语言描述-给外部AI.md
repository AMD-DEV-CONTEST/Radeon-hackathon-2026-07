# XAI 数字员工控制台 · 前端设计语言完整描述（给外部 AI / Agent 产品复刻用）

> 本文档的目标读者是**另一个 AI**。你拿到这份文档后，无需看截图，就应该能复刻出与 XAI 控制台同等观感的界面。
> 所有数值均摘自真实生产代码（React 18 + Vite + TS + Tailwind v4 + framer-motion + lucide-react），非凭空描述。
> 如果你能读本地文件，权威源码在：`xai/frontend/src/liquid-glass.css`（792 行，设计令牌总源）、`theme.css`（主题桥接）、`effects.css`（动效层）、`App.tsx`（布局骨架）。

---

## 一、一句话定位（先建立心智模型）

**"macOS 26 Liquid Glass 风格的深空玻璃控制台"**：深空渐变底 + 半透明毛玻璃面板 + macOS 系统色点缀 + 克制的微动效。整体气质是"安静的高级感"——不靠炫技动画，靠**层次（blur/透明度）、光（内描边高光）、呼吸（微位移）**三件事撑住质感。

如果只能记住三条规则：
1. **所有表面都是半透明玻璃**（背景永远不用纯色块，用 `rgba + backdrop-filter: blur`）
2. **所有颜色都走 CSS 变量令牌**（双主题切换只换令牌，组件零改动）
3. **所有动效都只做位移和阴影，绝不缩放**（scale 会挤动布局，是明令禁止的）

---

## 二、配色系统（可直接复制的设计令牌）

### 2.1 深色主题（默认）——"深空玻璃"

**画布底色不是纯黑，是带两团彩色光晕的深空渐变**（这是高级感的第一来源）：

```css
/* 根容器背景：左上蓝光晕 + 右下紫光晕 + 近黑底 */
background:
  radial-gradient(1100px 720px at 12% 8%,  rgba(10, 132, 255, 0.12), transparent 60%),
  radial-gradient(900px  640px at 88% 92%, rgba(175, 82, 222, 0.12), transparent 60%),
  #0c0c0e;
```

核心令牌（暗色）：

```css
--color-bg: #0c0c0e;                          /* 底 */
--color-bg-elevated: #141416;                 /* 抬升面 */
--color-bg-card: rgba(32, 32, 35, 0.95);      /* 卡片 */
--color-text: rgba(255, 255, 255, 0.92);      /* 主文字：白但不是纯白 */
--color-text-muted: rgba(255, 255, 255, 0.55);
--color-text-subtle: rgba(255, 255, 255, 0.35);
--color-border: rgba(255, 255, 255, 0.08);    /* 边框极淡，靠光不靠线 */
--color-border-subtle: rgba(255, 255, 255, 0.04);
--color-accent: rgba(10, 132, 255, 0.95);     /* 主强调 = macOS 系统蓝 */
--color-accent-bg: rgba(10, 132, 255, 0.12);
--color-accent-border: rgba(10, 132, 255, 0.3);
/* 玻璃 */
--glass-blur: 20px;  --glass-blur-heavy: 30px;
--glass-bg: rgba(30, 30, 30, 0.75);
--glass-bg-light: rgba(40, 40, 40, 0.65);
--glass-border: rgba(255, 255, 255, 0.12);
/* 玻璃阴影：外投影 + 顶部 1px 内高光（模拟玻璃上沿受光，质感关键！）*/
--shadow-glass: 0 2px 16px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.08);
```

### 2.2 浅色主题——"白底紫晕"

```css
background:
  radial-gradient(1100px 720px at 12% 8%,  rgba(139, 92, 246, 0.14), transparent 60%),
  radial-gradient(900px  640px at 88% 92%, rgba(167, 139, 250, 0.12), transparent 60%),
  #ffffff;
--color-bg: #f5f5f7;                       /* macOS 灰白 */
--color-text: rgba(0, 0, 0, 0.85);
--color-accent: rgba(0, 122, 255, 0.95);
--glass-bg: rgba(255, 255, 255, 0.75);
--shadow-glass: 0 2px 16px rgba(0,0,0,0.08), inset 0 1px 0 rgba(255,255,255,0.6);
```

### 2.3 功能色 = macOS 系统色板（7 组"节点色"，语义化点缀）

每组三件套：主色（~0.85 透明度）/ 背景（0.1）/ 边框（0.22）。**功能色永远不大面积使用，只做徽章、图标、节点头、状态点**：

| 语义 | 暗色主值 | 用途 |
|---|---|---|
| input/信息 | `rgba(10,132,255,.9)` 蓝 | 输入、链接、激活态 |
| ai/智能 | `rgba(175,82,222,.85)` 紫 | AI/模型相关 |
| logic/成功 | `rgba(48,209,88,.85)` 绿 | 成功、逻辑节点 |
| data/警示 | `rgba(255,159,10,.85)` 橙 | 数据、警告 |
| file/文件 | `rgba(191,90,242,.85)` 亮紫 | 文件 |
| system/危险 | `rgba(255,69,58,.85)` 红 | 危险、系统级 |
| output/产出 | `rgba(50,215,75,.85)` 亮绿 | 输出 |

**配色纪律**：文字永远不用纯白/纯黑（用 0.92/0.85 透明度）；边框永远若隐若现（0.04–0.12 白）；彩色永远带透明度、永远小面积。

---

## 三、玻璃材质配方（高级感的核心工艺）

任何"面板/卡片/按钮/输入框"都用同一配方，只调三个参数（透明度、blur 强度、圆角）：

```css
.glass-panel {                                /* 标准玻璃面板 */
  background: var(--glass-bg);                /* 半透明底 */
  backdrop-filter: blur(20px);                /* 毛玻璃（面板 20px / 浮层 30px / 卡片 10-14px / 小件 6-8px）*/
  border: 1px solid var(--glass-border);      /* 1px 淡白描边 */
  border-radius: 1rem;                        /* 圆角体系: sm .5rem / md .75rem / lg 1rem / xl 1.25rem */
  box-shadow: var(--shadow-glass);            /* 外投影 + inset 顶部高光 */
  transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
}
```

层级规则（blur 越强 = 越"浮"在上层）：
- 底层内容区：**透明**，让深空渐变透出来（main 区域 `background: transparent`）
- 侧栏/面板：blur 20px
- 卡片：blur 10–14px
- 徽章/chip/小按钮：blur 6–12px
- 模态/抽屉/浮层：blur 30px + 更重阴影 `0 8px 32px rgba(0,0,0,0.4)`

**主按钮**是全局唯一的"实色"元素（macOS 蓝渐变），也要带玻璃工艺：

```css
.glass-btn-primary {
  background: linear-gradient(180deg, rgba(10,132,255,0.9) 0%, rgba(0,122,255,0.95) 100%);
  border: 1px solid rgba(10,132,255,0.5);
  border-radius: 9px; padding: 8px 14px; font-size: 13px; color: #fff;
  box-shadow: 0 1px 2px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.15);
}
.glass-btn-primary:hover { transform: translateY(-1px); /* 换更深渐变 + 更大阴影 */ }
```

---

## 四、布局骨架（三栏玻璃控制台）

```
┌───────────┬─────────────────────────────────┬───────────┐
│ 左侧导航栏  │  主内容区（透明，深空渐变透出）      │ 右侧状态栏 │
│ w-56      │  flex-1                          │ w-64      │
│ (224px)   │  页面切换带 framer-motion 过渡     │ (256px)   │
│ 玻璃面板   │                                  │ 玻璃面板   │
│ 固定不滚   │  内部各自滚动                      │ 可开关     │
└───────────┴─────────────────────────────────┴───────────┘
```

- **左侧栏**（224px，`border-right: 1px solid rgba(255,255,255,0.08)`）：品牌区 + 主导航（图标 14px + 12px 文字）+ 会话历史 + 底部设置。激活项用 accent 三件套（`--color-accent-bg` 底 + `--color-accent` 字 + `--color-accent-border` 框），**不用实色块**。
- **主区**：单页应用按索引切页；每页是独立组件；页面容器透明。
- **右侧状态栏**（256px，`glass-panel`）：实时状态 widget（引擎/模型/记忆/健康），可整栏折叠（PanelRight 图标切换）。
- 字体：`-apple-system, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif`；全局基准 **13px**（信息密度高的控制台字号，比常规 14–16px 更"工具感"）；辅助文字 11–12px；等宽区 `ui-monospace, Menlo`。
- 图标：lucide-react 全家桶，导航 14–16px 细线风格，绝不用 emoji 当图标。

---

## 五、动效系统（克制、物理感、可关闭）

### 5.1 三条动效铁律
1. **禁止 scale 缩放变换**（会挤动布局产生廉价感）——只允许 `translateY` 和 `rotateX/Y` 微角度
2. **统一缓动**：常规交互 `cubic-bezier(0.4, 0, 0.2, 1)`（150/200/300ms 三档）；带"回弹感"的入场/悬停用 `cubic-bezier(0.2, 0.8, 0.2, 1)`
3. **必须响应 `prefers-reduced-motion: reduce`**：全部 transform/animation 置 none，只保留颜色/阴影过渡

### 5.2 具体动效配方（数值可直接抄）

**页面切换**（framer-motion，快到几乎无感但消除了"闪切"）：
```jsx
<AnimatePresence mode="wait" initial={false}>
  <motion.div key={page}
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    exit={{ opacity: 0, y: -10 }}
    transition={{ duration: 0.22, ease: "easeOut" }} />
</AnimatePresence>
```

**卡片入场**（上浮淡入，backwards 填充让列表有序进场）：
```css
@keyframes xai-rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
.card { animation: xai-rise 0.45s cubic-bezier(0.2, 0.8, 0.2, 1) backwards; }
```

**悬停反馈**（全局按钮 -1px 上浮、卡片 -2px 上浮 + 阴影加深）：
```css
button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
.card:hover  { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.15); }
```

**3D 微倾（列表项高级款，OllamaFlow 风）**——父容器给 perspective，子项 hover 时倾 2.5 度并亮起左上"玻璃反光"：
```css
.stage { perspective: 1000px; perspective-origin: 50% 0%; }
.item  { transform-style: preserve-3d; will-change: transform; }
.item:hover { transform: rotateX(2.5deg) rotateY(-2.5deg); }
.item::before {  /* 左上受光面，hover 淡入 */
  background: linear-gradient(158deg, rgba(255,255,255,0.16) 0%, rgba(255,255,255,0.03) 34%, transparent 62%);
  opacity: 0; transition: opacity 200ms;
}
.item:hover::before { opacity: 1; }
```

**运行态脉冲**（执行中的节点/任务，用发光呼吸而非旋转）：
```css
@keyframes pulse-border-running {
  0%, 100% { box-shadow: 0 0 6px rgba(59,130,246,0.4); }
  50%      { box-shadow: 0 0 16px rgba(59,130,246,0.8); }
}
```

**玻璃质感循环动画**（重点面板可选）：`glass-shine`（斜向流光扫过，background-position 200%→-200%，3s）、`glass-refraction`（内高光强弱呼吸，4s）、`glass-pulse`（透明度 1↔0.95，2s）。

---

## 六、双主题工程实现（换肤零成本的架构）

- `<html>` 上挂 `.dark` / `.light` class（ThemeProvider 支持 system 跟随），**所有组件只消费 `var(--color-*)` / `var(--glass-*)` 令牌，永不写死色值**。
- Tailwind v4 场景要注册 class 驱动的 dark 变体：`@custom-variant dark (&:where(.dark, .dark *));`
- 历史遗留的硬编码色（如 Tailwind zinc 系）不逐个改组件，而是写一层"主题桥接 CSS"统一映射到令牌（见 `theme.css`：`.bg-zinc-900 → var(--color-bg-card)` 等约 40 条映射）。**这招让 19 个旧组件一行不改就换上了玻璃皮肤**。
- 主题切换本身加 `transition: background-color/border-color/color/box-shadow 200ms`，避免闪变。

---

## 七、给复刻者的"要做/别做"清单

**要做：**
- 深色底永远用"近黑 + 彩色 radial 光晕"，不用纯 #000
- 每块玻璃都要 inset 顶部 1px 白色高光（这是"像玻璃"和"像灰色块"的分水岭）
- 状态没数据就显示 unknown/灰，不要假装绿色（我们的产品哲学：诚实优先）
- 层级靠 blur 强度和透明度区分，不靠色块深浅
- 全局 13px 字号 + 高信息密度，控制台要"工具的严肃感"

**别做：**
- ❌ scale 缩放动画、弹跳动画、超过 0.5s 的入场动画
- ❌ 大面积饱和色块、彩色渐变按钮满屏飞
- ❌ 纯白文字 (#fff) / 纯黑文字 (#000) / 1px 实灰边框 (#ccc)
- ❌ 光晕/阴影堆太重（外阴影最深只到 `rgba(0,0,0,0.4)`）
- ❌ emoji 当功能图标

---

## 八、可直接投喂的复刻 Prompt（复制即用）

> 请构建一个 macOS 26 "Liquid Glass" 风格的 AI Agent 控制台前端。技术栈 React + Tailwind + framer-motion + lucide-react。
> **背景**：深色主题用 `#0c0c0e` 底 + 两团 radial-gradient 光晕（左上 `rgba(10,132,255,0.12)`、右下 `rgba(175,82,222,0.12)`，尺寸约 1100×720px，60% 处透明）；浅色主题用纯白底 + 紫色光晕 `rgba(139,92,246,0.14)`。
> **材质**：一切表面均为毛玻璃——`background: rgba(30,30,30,0.75)`（浅色 `rgba(255,255,255,0.75)`）+ `backdrop-filter: blur(20px)` + `1px solid rgba(255,255,255,0.12)` 描边 + 阴影 `0 2px 16px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.08)`（inset 顶部高光必须有）。圆角 0.75–1rem。主内容区背景透明让渐变透出。
> **配色**：文字 `rgba(255,255,255,0.92)`，次级 0.55、辅助 0.35；强调色 macOS 系统蓝 `rgba(10,132,255,0.95)`，激活态用 12% 透明度同色底 + 30% 边框；功能色用 macOS 系统色板（紫 175,82,222 / 绿 48,209,88 / 橙 255,159,10 / 红 255,69,58），全部小面积、带透明度。
> **布局**：三栏——左导航 224px 玻璃栏、中间自适应内容、右状态栏 256px 可折叠；全局字号 13px，字体 -apple-system/PingFang SC；图标用 lucide 细线 14–16px。
> **动效**：页面切换 framer-motion 淡入+y 位移 10px、0.22s easeOut；卡片入场 `translateY(10px)→0` 0.45s `cubic-bezier(0.2,0.8,0.2,1)`；按钮 hover 上浮 1px、卡片上浮 2px 并加深阴影；执行态用 box-shadow 呼吸脉冲。**严禁 scale 缩放**，必须支持 prefers-reduced-motion。
> 整体气质：安静、克制、信息密度高的"深空玻璃工作台"，高级感来自透明层次和内描边光，而非动画数量。

---

## 九、源码阅读路线（如果你能读本地文件）

1. `xai/frontend/src/liquid-glass.css` — 设计系统总源：全部令牌（L9–197）、玻璃组件类（L203+）、动画（L342–394）、共享 UI 原语（L480+）
2. `xai/frontend/src/theme.css` — 深空渐变背景（L12–26）+ zinc→glass 主题桥接手法
3. `xai/frontend/src/effects.css` — 3D 微倾/入场/悬停/脉冲全部动效参数 + reduced-motion 处理
4. `xai/frontend/src/App.tsx` — 三栏骨架 + framer-motion 页面过渡（L290–301）
5. `xai/frontend/src/LeftSidebar.tsx` — 导航栏实现（w-56、玻璃 style、激活 chip）
6. `xai/frontend/src/_ui.tsx` — 按钮/卡片/徽章/开关等原语的 React 封装

---

*生成于 2026-07-29 · 所有数值经真机代码核对 · XAI 数字员工项目*

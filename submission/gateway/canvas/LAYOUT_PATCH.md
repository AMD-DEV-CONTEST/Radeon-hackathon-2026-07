# Canvas 排列功能集成补丁

> 新文件已建：`canvas/src/LayoutToolbar.tsx`、`canvas/src/App.css`
> App.tsx 需要三处改动。以下是精确修改点。

---

## 改动 1：顶部 import 区域，加入 LayoutToolbar

```
# 在现有 import 行后面追加:
import { LayoutToolbar, applyLayout, type LayoutConfig } from './LayoutToolbar'
```

## 改动 2：组件内部，加入 layout 状态

```
# 在 useState 声明区域（约第 70-100 行附近），任意 useState 之后追加:

const [layout, setLayout] = useState<LayoutConfig>({
  mode: 'grid',
  sortBy: 'status',
  groupBy: 'none',
})
```

## 改动 3：节点生成处，应用 layout

```
# 找到 useMemo 中生成 nodes 的地方（约第 350-450 行），
# 在 return 之前包一层 applyLayout:

const positionedNodes = useMemo(() => {
  const rawNodes = ... // 现有的 nodes 生成逻辑
  return applyLayout(rawNodes, layout)
}, [tasks, agents, layout])
```

## 改动 4：画布顶部，渲染工具栏

```
# ReactFlow 组件之前（return 中的 JSX），加:

<LayoutToolbar config={layout} onChange={setLayout} />
```

---

## 验收

```bash
cd canvas
npm run build
```

三个按钮出现：Grid / List / Compact
排序：Status / Name / Type
分组：Flat / By Status / By Agent

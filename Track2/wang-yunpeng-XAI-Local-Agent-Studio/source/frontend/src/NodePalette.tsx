// NodePalette —— 画布节点拖拽面板（Phase 0）
// 数据源：/api/canvas/node-catalog（注册表驱动，前端不写死）
// 嵌在画布面板内部左侧，玻璃小卡风格，HTML5 原生 DnD，零新依赖。
import { useEffect, useState } from "react"
import { Bot, Wrench, Database, FileText, ChevronDown, ChevronRight, GripVertical } from "lucide-react"
import { fetchNodeCatalog, type NodeCatalog, type NodeTypeDef, type ToolInstanceDef } from "./lib/api"

const TYPE_ICON: Record<string, any> = { agent: Bot, tool: Wrench, memory: Database, text: FileText }
const TYPE_COLOR: Record<string, string> = { agent: "#8b5cf6", tool: "#06b6d4", memory: "#f59e0b", text: "#64748b" }

function startDrag(e: React.DragEvent, spec: { nodeType: string; label: string; data: any }) {
  e.dataTransfer.setData("application/xai-node", JSON.stringify(spec))
  e.dataTransfer.effectAllowed = "copy"
}

export default function NodePalette() {
  const [catalog, setCatalog] = useState<NodeCatalog | null>(null)
  const [open, setOpen] = useState<Record<string, boolean>>({ base: true, tool: false })
  const [err, setErr] = useState("")

  useEffect(() => {
    fetchNodeCatalog().then(setCatalog).catch((e) => setErr(String(e?.message || e)))
  }, [])

  if (err) return <div style={{ fontSize: 11, color: "var(--color-text-subtle)", padding: 8 }}>节点目录加载失败</div>
  if (!catalog) return <div style={{ fontSize: 11, color: "var(--color-text-subtle)", padding: 8 }}>加载节点目录…</div>

  return (
    <div style={{
      width: 168, flexShrink: 0, overflow: "auto", padding: 8,
      background: "var(--color-bg-elevated)", border: "1px solid var(--color-border-subtle)",
      borderRadius: 12, display: "flex", flexDirection: "column", gap: 6,
    }}>
      <Section title="基础节点" open={!!open.base} onToggle={() => setOpen((o) => ({ ...o, base: !o.base }))}>
        {catalog.nodeTypes.map((t: NodeTypeDef) => {
          const Icon = TYPE_ICON[t.type] || FileText
          return (
            <div key={t.type} draggable title={t.description}
              onDragStart={(e) => startDrag(e, { nodeType: t.type, label: t.label, data: t.defaultData })}
              style={itemStyle}>
              <GripVertical size={11} style={{ color: "var(--color-text-subtle)", flexShrink: 0 }} />
              <Icon size={13} style={{ color: TYPE_COLOR[t.type], flexShrink: 0 }} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.label}</span>
            </div>
          )
        })}
      </Section>
      <Section title={`工具实例 (${catalog.toolInstances.length})`} open={!!open.tool} onToggle={() => setOpen((o) => ({ ...o, tool: !o.tool }))}>
        {catalog.toolInstances.map((i: ToolInstanceDef) => (
          <div key={i.id} draggable title={i.description || i.label}
            onDragStart={(e) => startDrag(e, { nodeType: "tool", label: i.label, data: i.data })}
            style={itemStyle}>
            <GripVertical size={11} style={{ color: "var(--color-text-subtle)", flexShrink: 0 }} />
            <Wrench size={12} style={{ color: TYPE_COLOR.tool, flexShrink: 0 }} />
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{i.label}</span>
            <span style={{ fontSize: 9, color: "var(--color-text-subtle)", marginLeft: "auto", flexShrink: 0 }}>{i.source}</span>
          </div>
        ))}
        {catalog.toolInstances.length === 0 && (
          <div style={{ fontSize: 10.5, color: "var(--color-text-subtle)", padding: "2px 4px" }}>暂无工具实例</div>
        )}
      </Section>
      <div style={{ fontSize: 10, color: "var(--color-text-subtle)", padding: "4px 2px", lineHeight: 1.5 }}>
        拖动条目到画布即可创建节点
      </div>
    </div>
  )
}

const itemStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 5, padding: "5px 6px",
  borderRadius: 8, cursor: "grab", fontSize: 11.5, color: "var(--color-text)",
  background: "var(--color-bg-input)", border: "1px solid var(--color-border-subtle)",
}

function Section({ title, open, onToggle, children }: {
  title: string; open: boolean; onToggle: () => void; children: React.ReactNode;
}) {
  return (
    <div>
      <button onClick={onToggle} style={{
        display: "flex", alignItems: "center", gap: 4, width: "100%", padding: "3px 2px",
        border: "none", background: "transparent", cursor: "pointer",
        fontSize: 11, fontWeight: 600, color: "var(--color-text-subtle)",
      }}>
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />} {title}
      </button>
      {open && <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>{children}</div>}
    </div>
  )
}

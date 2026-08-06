// 消息内容渲染：把 AI 回复里的 ```mermaid 代码块渲染成图，其余按文本/代码展示。
// 设计标准：使用 var(--color-*) 变量，支持明暗双主题，无 emoji。

import { useEffect, useMemo, useRef, useState } from "react"
import mermaid from "mermaid"
import PrismCodeBlock from "./PrismCodeBlock"

type Seg =
  | { type: "text"; value: string }
  | { type: "mermaid"; value: string }
  | { type: "code"; lang: string; value: string }

function isDark(): boolean {
  if (typeof document === "undefined") return false
  const de = document.documentElement
  if (de.classList.contains("dark")) return true
  try {
    return !!window.matchMedia?.("(prefers-color-scheme: dark)").matches
  } catch {
    return false
  }
}

// 简单 Markdown 渲染 — 支持 **粗体** *斜体* `代码` 列表 --- 分隔线和标题
function renderMdLine(line: string): string {
  if (/^[-*_]{3,}$/.test(line.trim())) {
    return '<hr style="border:none;border-top:1px solid var(--color-border-subtle);margin:6px 0"/>'
  }
  if (/^[-*+]\s/.test(line)) {
    return `<li style="margin-left:16px;list-style:disc">${line.replace(/^[-*+]\s+/, "")}</li>`
  }
  if (/^\d+[.)]\s/.test(line)) {
    return `<li style="margin-left:16px;list-style:decimal">${line.replace(/^\d+[.)]\s+/, "")}</li>`
  }
  let html = line
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code style="background:var(--color-accent-bg);padding:1px 4px;border-radius:3px;font-size:12px;font-family:monospace">$1</code>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color:var(--color-accent);text-decoration:underline">$1</a>')
  if (/^##\s/.test(line)) return `<h3 style="font-size:15px;font-weight:700;margin:8px 0 4px">${html.replace(/^##\s+/, "")}</h3>`
  if (/^#\s/.test(line)) return `<h2 style="font-size:17px;font-weight:700;margin:10px 0 4px">${html.replace(/^#\s+/, "")}</h2>`
  return html
}
function renderMd(text: string): string {
  return text.split("\n").map(renderMdLine).join("<br/>")
}

// 解析内容：拆出 mermaid / 普通代码 / 文本三段
function parseContent(content: string): Seg[] {
  const segs: Seg[] = []
  const re = /```(\w*)\n([\s\S]*?)```/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(content))) {
    if (m.index > last) segs.push({ type: "text", value: content.slice(last, m.index) })
    const lang = (m[1] || "").toLowerCase()
    const code = m[2].replace(/\n$/, "")
    if (lang === "mermaid") segs.push({ type: "mermaid", value: code })
    else segs.push({ type: "code", lang, value: code })
    last = re.lastIndex
  }
  if (last < content.length) segs.push({ type: "text", value: content.slice(last) })
  return segs
}

function MermaidChart({ code }: { code: string }) {
  const [svg, setSvg] = useState("")
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const rid = `mmd-${Date.now()}-${Math.random().toString(36).slice(2)}`
    ;(async () => {
      try {
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "loose",
          theme: isDark() ? "dark" : "neutral",
        })
        const res = await mermaid.render(rid, code)
        if (!cancelled) {
          setSvg(res.svg)
          setErr(null)
        }
      } catch (e: any) {
        if (!cancelled) setErr(e?.message || String(e))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [code])

  if (err) {
    return (
      <pre style={{ fontSize: 12, color: "var(--color-text-muted)", whiteSpace: "pre-wrap", wordBreak: "break-word", padding: 10, background: "var(--color-bg-input)", borderRadius: 10, border: "1px solid var(--color-border-subtle)", margin: "6px 0" }}>
        {code}
        {"\n\n"}
        ⚠️ 图表渲染失败：{err}
      </pre>
    )
  }
  if (!svg) {
    return (
      <div style={{ padding: 10, fontSize: 12, color: "var(--color-text-subtle)", background: "var(--color-bg-input)", borderRadius: 10, border: "1px solid var(--color-border-subtle)", margin: "6px 0" }}>
        正在渲染图表…
      </div>
    )
  }
  return (
    <div
      className="mermaid-render"
      style={{ background: "var(--color-bg-input)", border: "1px solid var(--color-border-subtle)", borderRadius: 10, padding: 12, overflowX: "auto", margin: "6px 0" }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}

export default function MessageContent({ content }: { content: string }) {
  const segs = useMemo(() => parseContent(content || ""), [content])
  return (
    <>
      {segs.map((s, i) => {
        if (s.type === "mermaid") return <MermaidChart key={i} code={s.value} />
        if (s.type === "code") {
          return <PrismCodeBlock key={i} language={s.lang} code={s.value} />
        }
        return (
          <span key={i} style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}
            dangerouslySetInnerHTML={{ __html: renderMd(s.value) }}
          />
        )
      })}
    </>
  )
}

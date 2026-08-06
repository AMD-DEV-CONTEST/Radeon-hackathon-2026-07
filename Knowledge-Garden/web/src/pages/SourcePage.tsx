import { useEffect, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { api } from "../lib/api"
import { Card, CardBody, CardHeader } from "../components/ui/Card"
import { Spinner } from "../components/ui/Spinner"

// SourcePage — 源文档查看页（/skills/:skillId/source/:materialId）：
// 渲染上传的原始 Markdown 文件，供知识卡片跳转溯源。
export function SourcePage({ materialId, skillId, onBack }: {
  materialId: number
  skillId: number
  onBack: () => void
}) {
  const [doc, setDoc] = useState<{ filename: string; raw_text: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    setLoading(true); setError("")
    void api.getMaterial(materialId).then((d) => { setDoc(d); setLoading(false) })
      .catch((e) => { setError((e as Error).message); setLoading(false) })
  }, [materialId])

  if (loading) return <div className="flex min-h-dvh items-center justify-center"><Spinner className="h-6 w-6" /></div>
  if (error && !doc) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-10">
        <button onClick={onBack} className="mb-4 text-sm text-zinc-500 hover:text-accent">← 返回技能</button>
        <Card><CardBody className="py-12 text-center text-sm text-red-600">{error}</CardBody></Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-8 md:px-8">
      <button onClick={onBack} className="mb-4 text-sm text-zinc-500 hover:text-accent">← 返回技能</button>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-ink">源文档</h1>
          <p className="mt-1 text-sm text-zinc-500">技能 #{skillId} · 原始 Markdown 文件</p>
        </div>
        {doc?.filename && (
          <span className="max-w-[40%] truncate font-mono text-xs text-accent">{doc.filename}</span>
        )}
      </div>

      <Card>
        <CardHeader title={doc?.filename || "源文档内容"} sub="上传的原始文件，Markdown 渲染" />
        <CardBody>
          {/* 渲染不信任的 Markdown：react-markdown 默认不渲染原始 HTML、URL 走安全转换 */}
          <div className="prose-md space-y-2 text-sm leading-7 text-ink-soft [&_a]:text-accent [&_a]:underline [&_h1]:text-lg [&_h1]:font-bold [&_h1]:text-ink [&_h2]:text-base [&_h2]:font-bold [&_h2]:text-ink [&_h3]:font-semibold [&_h3]:text-ink [&_li]:list-disc [&_li]:pl-1 [&_ol_li]:list-decimal [&_code]:rounded [&_code]:bg-paper-soft [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-xs [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-zinc-900 [&_pre]:p-4 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_pre_code]:text-zinc-100 [&_blockquote]:border-l-2 [&_blockquote]:border-accent [&_blockquote]:pl-3 [&_blockquote]:text-zinc-500 [&_table]:w-full [&_table]:border-collapse [&_th]:border [&_th]:border-zinc-200 [&_th]:px-3 [&_th]:py-1.5 [&_th]:text-left [&_th]:text-xs [&_td]:border [&_td]:border-zinc-200 [&_td]:px-3 [&_td]:py-1.5">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{doc?.raw_text ?? ""}</ReactMarkdown>
          </div>
        </CardBody>
      </Card>
    </div>
  )
}

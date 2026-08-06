import { useRef, useState } from "react"
import { api } from "../lib/api"
import { Button } from "../components/ui/Button"
import { Card, CardBody, CardHeader } from "../components/ui/Card"
import { Input } from "../components/ui/Input"
import { Spinner } from "../components/ui/Spinner"

// UploadPage — Markdown 文件拖拽上传（仅 .md/.markdown）。
// 选择/拖入文件后不回显内容到输入框，只显示文件名；提交后跳转 /processing/:runId。
export function UploadPage({ onImported }: {
  onImported: (runId: number, skillId: number) => void
}) {
  const [skillName, setSkillName] = useState("")
  const [fileName, setFileName] = useState("")
  const [fileContent, setFileContent] = useState("")
  const [dragOver, setDragOver] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const fileRef = useRef<HTMLInputElement>(null)

  const ACCEPT = ".md,.markdown"

  const isMarkdown = (name: string) => /\.(md|markdown)$/i.test(name)

  const handleFile = (f: File | undefined) => {
    if (!f) return
    if (!isMarkdown(f.name)) {
      setError("仅支持 Markdown 文件（.md / .markdown）")
      return
    }
    setError("")
    setFileName(f.name)
    if (!skillName) setSkillName(f.name.replace(/\.(md|markdown)$/i, ""))
    const reader = new FileReader()
    reader.onload = () => setFileContent(String(reader.result ?? ""))
    reader.readAsText(f)
  }

  const run = async () => {
    if (!skillName.trim()) { setError("请填写技能名称"); return }
    if (fileContent.trim().length < 10) { setError("资料内容太短（至少 10 字）"); return }
    setError(""); setLoading(true)
    try {
      const r = await api.createMaterial(skillName.trim(), fileContent, fileName)
      onImported(r.run_id, r.skill_id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-8 md:px-8">
      <h1 className="text-2xl font-bold text-ink">上传学习资料</h1>
      <p className="mt-1 text-sm text-zinc-500">拖入或选择 Markdown 文件（.md），Agent 在本地 GPU 上抽取并验证学习单元。验证完成前不会解锁学习。</p>

      <Card className="mt-6">
        <CardHeader title="资料信息" />
        <CardBody className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-zinc-500" htmlFor="skill-name">技能名称</label>
            <Input id="skill-name" value={skillName} onChange={(e) => setSkillName(e.target.value)}
              placeholder="例如：Raft 共识算法" />
          </div>

          {/* 拖拽投放区：仅 Markdown；选择后不回显正文，只显示文件名 */}
          <div
            role="button"
            tabIndex={0}
            aria-label="上传 Markdown 文件"
            onClick={() => fileRef.current?.click()}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") fileRef.current?.click() }}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files?.[0]) }}
            className={`flex min-h-36 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors ${
              dragOver ? "border-accent bg-accent-dim" : "border-zinc-300 bg-paper-soft hover:border-zinc-400"
            }`}
          >
            <div className="text-3xl" aria-hidden="true">📄</div>
            <div className="text-sm font-medium text-ink-soft">
              {fileName || "拖拽 Markdown 文件到这里，或点击选择"}
            </div>
            {fileName && <div className="max-w-full truncate font-mono text-xs text-accent">{fileName}</div>}
            {!fileName && <div className="text-xs text-zinc-400">仅支持 .md / .markdown</div>}
          </div>
          <input ref={fileRef} type="file" accept={ACCEPT} className="hidden"
            onChange={(e) => handleFile(e.target.files?.[0])} />

          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={() => fileRef.current?.click()}>选择文件</Button>
            <Button onClick={() => run()} disabled={loading || !fileName}>
              {loading ? <><Spinner /> 创建导入…</> : "创建导入"}
            </Button>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </CardBody>
      </Card>
    </div>
  )
}

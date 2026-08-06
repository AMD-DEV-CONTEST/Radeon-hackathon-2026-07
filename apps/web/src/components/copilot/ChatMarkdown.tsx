import type { ReactNode } from 'react'

function parseInline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} className="font-semibold text-[hsl(var(--foreground))]">{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return <em key={i}>{part.slice(1, -1)}</em>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={i} className="rounded bg-[hsl(var(--muted))] px-1 py-0.5 text-xs font-mono">
          {part.slice(1, -1)}
        </code>
      )
    }
    return part
  })
}

function Block({ line }: { line: string }) {
  const trimmed = line.trim()
  if (!trimmed) return null

  const olMatch = trimmed.match(/^(\d+)\.\s+(.*)$/)
  if (olMatch) {
    return (
      <li className="ml-4 list-decimal marker:text-[hsl(var(--muted-foreground))]">
        {parseInline(olMatch[2])}
      </li>
    )
  }

  if (/^[-*]\s+/.test(trimmed)) {
    return (
      <li className="ml-4 list-disc marker:text-[hsl(var(--muted-foreground))]">
        {parseInline(trimmed.replace(/^[-*]\s+/, ''))}
      </li>
    )
  }

  if (trimmed.startsWith('### ')) {
    return <h4 className="font-semibold text-sm mt-2 mb-0.5">{parseInline(trimmed.slice(4))}</h4>
  }
  if (trimmed.startsWith('## ')) {
    return <h3 className="font-semibold text-sm mt-2 mb-0.5">{parseInline(trimmed.slice(3))}</h3>
  }

  return <p className="leading-relaxed">{parseInline(trimmed)}</p>
}

export function ChatMarkdown({ content }: { content: string }) {
  const blocks = content.split(/\n{2,}/)

  return (
    <div className="space-y-2 text-sm">
      {blocks.map((block, bi) => {
        const lines = block.split('\n').filter((l) => l.trim())
        const isOl = lines.every((l) => /^\d+\.\s+/.test(l.trim()))
        const isUl = lines.every((l) => /^[-*]\s+/.test(l.trim()))

        if (isOl && lines.length > 1) {
          return (
            <ol key={bi} className="space-y-1">
              {lines.map((line, li) => (
                <Block key={li} line={line} />
              ))}
            </ol>
          )
        }
        if (isUl && lines.length > 1) {
          return (
            <ul key={bi} className="space-y-1">
              {lines.map((line, li) => (
                <Block key={li} line={line} />
              ))}
            </ul>
          )
        }

        return (
          <div key={bi} className="space-y-1">
            {lines.map((line, li) => (
              <Block key={li} line={line} />
            ))}
          </div>
        )
      })}
    </div>
  )
}

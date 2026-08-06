/**
 * 社区与资源区块（全 runtime 共用，M45 打样）。
 *
 * 设计原则（用户指令：丰富内容、不过度复杂）：
 * - 每台机器人页面放同一款组件，数据由调用方传入（文档链接/社区入口/新手常见问题）
 * - 常见问题用 <details> 折叠，默认收起，不占首屏
 * - 链接全部外链（官方文档 / Discord / GitHub），平台不做搬运工
 */
import { ChevronDown, ExternalLink, MessageCircle, BookOpen } from 'lucide-react'

export interface CommunityResource {
  label: string
  url: string
}

export interface CommunityFaq {
  q: string
  a: string
}

interface CommunityResourcesProps {
  /** 一句话说明（可选） */
  intro?: string
  docs: CommunityResource[]
  communities: CommunityResource[]
  faqs: CommunityFaq[]
}

export function CommunityResources({ intro, docs, communities, faqs }: CommunityResourcesProps) {
  return (
    <section className="rounded-2xl border border-white/10 bg-black/20 p-5">
      <h2 className="font-display text-sm font-semibold tracking-tight text-[var(--paper)]">
        社区与资源
      </h2>
      {intro && <p className="mt-1 text-xs leading-relaxed text-stone-500">{intro}</p>}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {docs.length > 0 && (
          <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
            <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.16em] text-stone-500">
              <BookOpen className="h-3.5 w-3.5" />
              官方文档
            </p>
            <ul className="mt-2 space-y-1.5">
              {docs.map((d) => (
                <li key={d.url}>
                  <a
                    href={d.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-[var(--ember)] underline-offset-2 hover:underline"
                  >
                    {d.label}
                    <ExternalLink className="h-3 w-3 opacity-60" />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
        {communities.length > 0 && (
          <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
            <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.16em] text-stone-500">
              <MessageCircle className="h-3.5 w-3.5" />
              社区
            </p>
            <ul className="mt-2 space-y-1.5">
              {communities.map((c) => (
                <li key={c.url}>
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-[var(--ember)] underline-offset-2 hover:underline"
                  >
                    {c.label}
                    <ExternalLink className="h-3 w-3 opacity-60" />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {faqs.length > 0 && (
        <details className="group mt-4 rounded-xl border border-white/5 bg-white/[0.02] p-3">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs font-medium text-stone-300">
            新手常见问题（{faqs.length}）
            <ChevronDown className="h-3.5 w-3.5 text-stone-500 transition-transform group-open:rotate-180" />
          </summary>
          <div className="mt-2 space-y-3">
            {faqs.map((f) => (
              <div key={f.q} className="text-xs leading-relaxed">
                <p className="font-medium text-stone-200">{f.q}</p>
                <p className="mt-0.5 text-stone-500">{f.a}</p>
              </div>
            ))}
          </div>
        </details>
      )}
    </section>
  )
}

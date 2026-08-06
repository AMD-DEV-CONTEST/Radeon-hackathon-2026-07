import { Link } from 'react-router-dom'
import { ArrowRight, Compass } from 'lucide-react'
import { useTourOptional } from './TourProvider'

const PAGE_GUIDES: Record<
  string,
  { title: string; steps: string[]; cta: { label: string; href: string } }
> = {
  '/datasets': {
    title: '数据集从哪来？',
    steps: ['Robots → 进入向导 → 录制示教', 'B601 用户从 /robots/b601_rs 录数据', '录完的数据会自动出现在这里'],
    cta: { label: '去录制', href: '/robots/so101' },
  },
  '/training': {
    title: '怎么开始训练？',
    steps: ['先有数据集', '可选课程模板（抓取/放置/倒水）', '选算法 → 本地或云端训练'],
    cta: { label: '看数据集', href: '/datasets' },
  },
  '/skills': {
    title: 'Skills 是什么？',
    steps: ['装到机器人上的技能包', '先完成 SO-101 向导闭环，再来这里安装运行'],
    cta: { label: '从 Robots 开始', href: '/robots' },
  },
  '/workflow': {
    title: '工作流（内测）',
    steps: ['可视化编排：数据 → 训练 → 模型', '部分节点仍在开发，主路径请用 SO-101 向导'],
    cta: { label: '推荐：SO-101 向导', href: '/robots/so101' },
  },
}

export function PageGuideStrip() {
  const tour = useTourOptional()
  const path = typeof window !== 'undefined' ? window.location.pathname : ''
  const guide = Object.entries(PAGE_GUIDES).find(([p]) => path.startsWith(p))?.[1]
  if (!guide) return null

  return (
    <div className="mb-5 rounded-xl border border-[hsl(var(--primary))]/20 bg-[hsl(var(--primary))]/5 p-4 flex flex-col sm:flex-row sm:items-center gap-3">
      <div className="flex-1 min-w-0 space-y-1.5">
        <p className="text-sm font-semibold text-[hsl(var(--foreground))]">{guide.title}</p>
        <div className="flex flex-wrap gap-2">
          {guide.steps.map((s, i) => (
            <span
              key={s}
              className="inline-flex items-center gap-1 text-xs text-[hsl(var(--muted-foreground))]"
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[hsl(var(--primary))]/15 text-[10px] font-bold text-[hsl(var(--primary))]">
                {i + 1}
              </span>
              {s}
            </span>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap gap-2 shrink-0">
        <Link
          to={guide.cta.href}
          className="inline-flex items-center gap-1 rounded-full bg-[hsl(var(--primary))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary-foreground))]"
        >
          {guide.cta.label}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
        {tour && (
          <button
            type="button"
            onClick={() => tour.startTour()}
            className="inline-flex items-center gap-1 rounded-full border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium hover:bg-[hsl(var(--muted))]"
          >
            <Compass className="h-3.5 w-3.5" />
            新手引导
          </button>
        )}
      </div>
    </div>
  )
}

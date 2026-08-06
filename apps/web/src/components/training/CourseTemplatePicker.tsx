import { useEffect, useState } from 'react'
import { BookOpen } from 'lucide-react'
import { authJson } from '../../lib/auth'
import { useAuth } from '../../lib/authContext'

export interface CourseTemplate {
  id: string
  label: string
  single_task: string
  num_episodes: number
  episode_time_s: number
  reset_time_s?: number
  suggested_runtime?: string
  maturity?: string
}

export function CourseTemplatePicker({
  onSelect,
}: {
  onSelect: (template: CourseTemplate) => void
}) {
  const { token } = useAuth()
  const [templates, setTemplates] = useState<CourseTemplate[]>([])

  useEffect(() => {
    if (!token) return
    void authJson<{ templates: CourseTemplate[] }>('/api/v1/trainings/course-templates')
      .then((r) => setTemplates(r.templates ?? []))
      .catch(() => setTemplates([]))
  }, [token])

  if (templates.length === 0) return null

  return (
    <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/20 p-3 space-y-2">
      <div className="flex items-center gap-2 text-xs font-medium text-[hsl(var(--foreground))]">
        <BookOpen className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
        课程模板
      </div>
      <div className="flex flex-wrap gap-2">
        {templates.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => onSelect(t)}
            className="rounded-full border border-[hsl(var(--border))] px-3 py-1 text-xs hover:bg-[hsl(var(--muted))]"
          >
            {t.label}
            {t.maturity ? (
              <span className="ml-1 text-[10px] text-muted-foreground">· {t.maturity}</span>
            ) : null}
          </button>
        ))}
      </div>
      <p className="text-[10px] text-muted-foreground">
        选中后可在 B601 / SO-101 录制页使用相同任务描述与 episode 数。
      </p>
    </div>
  )
}

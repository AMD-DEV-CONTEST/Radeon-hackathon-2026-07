import type { ProjectFileEntry } from '../api/dto'

export interface ReportReadiness {
  ready: boolean
  message: string | null
}

/**
 * A browser-only guard for the common first-run mistakes. The API remains the
 * authority: this helper merely explains what is missing before a costly run.
 */
export function getReportReadiness(files: ProjectFileEntry[], taskCount: number): ReportReadiness {
  const hasReference = files.some((file) => !file.is_task_file)
  if (!hasReference) {
    return {
      ready: false,
      message: '请先上传至少一份可解析的项目资料（MD、TXT、PDF、DOCX 或 XLSX），再生成报告。',
    }
  }

  const hasTaskFile = files.some((file) => file.is_task_file)
  if (!hasTaskFile && taskCount === 0) {
    return {
      ready: false,
      message: '请上传任务 CSV/XLSX，或先在“任务工作台”创建任务，再生成报告。',
    }
  }

  return { ready: true, message: null }
}

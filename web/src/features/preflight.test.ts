// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { getReportReadiness } from './preflight'
import type { ProjectFileEntry } from '../api/dto'

function file(name: string, task = false): ProjectFileEntry {
  return {
    relative_path: `source/${name}`,
    filename: name,
    size_bytes: 1,
    updated_at: '2026-07-30T00:00:00Z',
    sha256: null,
    parse_version: null,
    index_version: null,
    processing_status: 'uploaded',
    is_task_file: task,
  }
}

describe('getReportReadiness', () => {
  it('requires a reference document before starting a run', () => {
    expect(getReportReadiness([file('tasks.csv', true)], 0)).toEqual({
      ready: false,
      message: '请先上传至少一份可解析的项目资料（MD、TXT、PDF、DOCX 或 XLSX），再生成报告。',
    })
  })

  it('accepts a reference document plus an uploaded task list', () => {
    expect(getReportReadiness([file('status.md'), file('tasks.csv', true)], 0)).toEqual({ ready: true, message: null })
  })

  it('also accepts tasks already maintained in the task workbench', () => {
    expect(getReportReadiness([file('status.md')], 1)).toEqual({ ready: true, message: null })
  })
})

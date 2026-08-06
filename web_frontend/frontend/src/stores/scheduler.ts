/**
 * Scheduler Store
 * 管理定时任务
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { SchedulerJobView, SchedulerToolOptionView } from '@/types/protocol'

export const useSchedulerStore = defineStore('scheduler', () => {
  const jobs = ref<SchedulerJobView[]>([])
  const selectedJobId = ref<string | null>(null)
  const runs = ref<any[]>([])
  const toolOptions = ref<SchedulerToolOptionView[]>([])

  function setJobs(newJobs: SchedulerJobView[]): void {
    jobs.value = newJobs
  }

  function selectJob(jobId: string | null): void {
    selectedJobId.value = jobId
    runs.value = []
  }

  function setRuns(newRuns: any[]): void {
    runs.value = newRuns
  }

  function setToolOptions(newToolOptions: SchedulerToolOptionView[]): void {
    toolOptions.value = newToolOptions
  }

  function reset(): void {
    jobs.value = []
    selectedJobId.value = null
    runs.value = []
    toolOptions.value = []
  }

  return {
    jobs,
    selectedJobId,
    runs,
    toolOptions,
    setJobs,
    selectJob,
    setRuns,
    setToolOptions,
    reset,
  }
})

import { schedulerApi } from '@/api/scheduler'
import { runtimeExecutionConfig } from '@/api/commands'
import type { SchedulerJobInput } from '@/api/resourceTypes'
import { useRuntimePreferencesStore } from '@/stores/runtimePreferences'
import { useCommandTransport } from './transport'

export function useSchedulerCommands() {
  const transport = useCommandTransport()
  const runtimePreferences = useRuntimePreferencesStore()

  const refreshSchedulerOptions = (packageId?: string) => {
    return transport.applyEventRequest(schedulerApi.options(packageId))
  }

  const refreshScheduler = (packageId?: string) => {
    return transport.applyEventRequest(schedulerApi.jobs(packageId))
  }

  const createSchedulerJob = (job: SchedulerJobInput, packageId?: string) => {
    const runtimeConfig = runtimeExecutionConfig({
      mainModelProfileId: runtimePreferences.mainModelProfileId,
      reasoningIntensity: runtimePreferences.reasoningIntensity,
      requestTimeoutSeconds: runtimePreferences.requestTimeoutSeconds,
      maxRetries: runtimePreferences.maxRetries,
      userConfig: {
        max_parallel_sub_agents: runtimePreferences.maxParallelSubAgents,
      },
    })
    return transport.applyEventRequest(schedulerApi.createJob({
      ...job,
      ...(runtimeConfig ? { runtime_config: runtimeConfig } : {}),
    }, packageId))
  }

  const pauseJob = (jobId: string, packageId?: string) => {
    return transport.applyEventRequest(schedulerApi.pause(jobId, packageId))
  }

  const resumeJob = (jobId: string, packageId?: string) => {
    return transport.applyEventRequest(schedulerApi.resume(jobId, packageId))
  }

  const deleteJob = (jobId: string, packageId?: string) => {
    return transport.applyEventRequest(schedulerApi.delete(jobId, packageId))
  }

  const listSchedulerRuns = (jobId?: string, limit = 20, packageId?: string) => {
    return transport.applyEventRequest(schedulerApi.runs(jobId, limit, packageId))
  }

  const runJobNow = (jobId: string, packageId?: string) => {
    void schedulerApi.runNow(jobId, packageId).catch(transport.reportError)
  }

  return {
    refreshSchedulerOptions,
    refreshScheduler,
    createSchedulerJob,
    pauseJob,
    resumeJob,
    deleteJob,
    listSchedulerRuns,
    runJobNow,
  }
}

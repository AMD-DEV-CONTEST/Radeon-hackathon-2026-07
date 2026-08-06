import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import { Button } from '../components/ui/button'
import { authJson } from '../lib/auth'
import { useAuth } from '../lib/authContext'
import { UpgradeModal } from '../components/billing/UpgradeModal'
import { useTrainingWebSocket } from '../hooks/useTrainingWebSocket'
import type { TrainingJobDTO } from '../types/training'
import type { DatasetSummary } from '../types/dataset'
import { WizardProgress } from '../components/training/WizardProgress'
import { TrainingHero } from '../components/training/TrainingHero'
import { DatasetStep } from '../components/training/DatasetStep'
import { GoalStep } from '../components/training/GoalStep'
import { PrepareStep } from '../components/training/PrepareStep'
import { ConfirmStep } from '../components/training/ConfirmStep'
import { AdvancedTrainingSettings } from '../components/training/AdvancedTrainingSettings'
import { ActiveTrainingPanel } from '../components/training/ActiveTrainingPanel'
import { TrainingHistoryPanel } from '../components/training/TrainingHistoryPanel'
import { WizardChoicesSummary } from '../components/training/WizardChoicesSummary'
import { WizardFooter } from '../components/training/WizardFooter'
import { TrainingJobsBanner } from '../components/training/TrainingJobsBanner'
import { CourseTemplatePicker } from '../components/training/CourseTemplatePicker'
import { wizardPrevious, WIZARD_FLOW } from '../components/training/wizardFlow'
import {
  type WizardStep,
  type TrainingGoal,
  type PrepareCheck,
  type AlgoOption,
  type QualiaInstance,
  type JobDetail,
  type DatasetReadiness,
  datasetTrainability,
  sortDatasetsForWizard,
} from '../components/training/types'
import { parseApiError } from '../components/training/utils'

interface JobListResponse {
  total: number
  items: TrainingJobDTO[]
}

function applyGoal(
  goal: TrainingGoal,
  algorithms: AlgoOption[],
): { algo: string; backend: 'local' | 'qualia' } {
  if (goal === 'recommended_cloud') {
    const cloud =
      algorithms.find((a) => a.id === 'pi05') ??
      algorithms.find((a) => a.id === 'smolvla') ??
      algorithms.find((a) => a.id === 'act') ??
      algorithms.find((a) => a.backend === 'qualia')
    if (cloud) return { algo: cloud.id, backend: 'qualia' }
  }
  if (goal === 'local_quick') {
    const local = algorithms.find((a) => a.id === 'mlp_baseline') ?? algorithms.find((a) => a.backend === 'local')
    if (local) return { algo: local.id, backend: 'local' }
  }
  const first = algorithms[0]
  return {
    algo: first?.id ?? 'mlp_baseline',
    backend: (first?.backend === 'qualia' ? 'qualia' : 'local') as 'local' | 'qualia',
  }
}

export function Training() {
  const { user, token } = useAuth()
  const [searchParams] = useSearchParams()
  const runtimePrefill = searchParams.get('runtime')
  const [upgradeOpen, setUpgradeOpen] = useState(false)
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [jobs, setJobs] = useState<TrainingJobDTO[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const [wizardStep, setWizardStep] = useState<WizardStep>('data')
  const [goal, setGoal] = useState<TrainingGoal>('recommended_cloud')
  const [goalTouched, setGoalTouched] = useState(false)
  const [jobsListExpanded, setJobsListExpanded] = useState(false)
  const [expertOpen, setExpertOpen] = useState(false)
  const [prepareChecks, setPrepareChecks] = useState<PrepareCheck[]>([])
  const [prepareRunning, setPrepareRunning] = useState(false)

  const [datasetId, setDatasetId] = useState('')
  const [algo, setAlgo] = useState('act')
  const [trainBackend, setTrainBackend] = useState<'local' | 'qualia'>('local')
  const [epochs, setEpochs] = useState(10)
  const [batchSize, setBatchSize] = useState(64)
  const [lr, setLr] = useState(0.001)
  const [hidden, setHidden] = useState(64)
  const [submitting, setSubmitting] = useState(false)
  const [courseTemplateHint, setCourseTemplateHint] = useState<string | null>(null)
  const [algorithms, setAlgorithms] = useState<AlgoOption[]>([])
  const [qualiaConfigured, setQualiaConfigured] = useState(false)

  const [hfDatasetId, setHfDatasetId] = useState('')
  const [qInstance, setQInstance] = useState('')
  const [qHours, setQHours] = useState(1.0)
  const [qBatch, setQBatch] = useState(32)
  const [qModelId, setQModelId] = useState('')
  const [qInstances, setQInstances] = useState<QualiaInstance[]>([])
  const [qCost, setQCost] = useState<{ estimated_credits: number } | null>(null)
  const [qKeyStatus, setQKeyStatus] = useState<{ ok: boolean; message: string } | null>(null)
  const [qCameraKeys, setQCameraKeys] = useState('')
  const [datasetReadiness, setDatasetReadiness] = useState<DatasetReadiness | null>(null)

  const [watchJobId, setWatchJobId] = useState<string | null>(null)
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null)
  const [jobDetail, setJobDetail] = useState<JobDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [cancellingId, setCancellingId] = useState<string | null>(null)
  const [initialBoot, setInitialBoot] = useState(false)

  const selectedDataset = datasets.find((d) => d.dataset_id === datasetId)
  const activeJob = jobs.find((j) => j.id === watchJobId) ?? jobs.find((j) => j.status === 'running' || j.status === 'queued')
  const { snapshot, lossHistory, done, error: wsErr } = useTrainingWebSocket(watchJobId)

  const qualiaLocked = user ? (user.entitlements?.limits.training_qualia_monthly ?? 0) === 0 : false

  const loadJobs = useCallback(async () => {
    if (!token) {
      setJobs([])
      return
    }
    try {
      try {
        await authJson('/api/v1/trainings/reconcile', { method: 'POST' })
      } catch {
        /* best-effort */
      }
      const data = await authJson<JobListResponse>('/api/v1/trainings')
      setJobs(data.items)
    } catch (e) {
      setErr(parseApiError((e as Error).message))
    }
  }, [token])

  const loadDatasets = useCallback(async () => {
    let apiItems: DatasetSummary[] = []
    let rtItems: DatasetSummary[] = []
    try {
      const rtRes = await fetch('/api/datasets')
      if (rtRes.ok) {
        const rt = (await rtRes.json()) as { items: DatasetSummary[] }
        rtItems = rt.items
      }
    } catch {
      /* ignore */
    }
    if (token) {
      try {
        const api = await authJson<{ items: DatasetSummary[] }>('/api/v1/datasets')
        apiItems = api.items
      } catch {
        apiItems = rtItems
      }
    } else {
      apiItems = rtItems
    }
    const rtById = new Map(rtItems.map((d) => [d.dataset_id, d]))
    const merged: DatasetSummary[] = []
    const seen = new Set<string>()
    for (const it of apiItems) {
      seen.add(it.dataset_id)
      const rt = rtById.get(it.dataset_id)
      const apiFrames = it.frame_count ?? 0
      const rtFrames = rt?.frame_count ?? 0
      const useRt = rt && (apiFrames <= 0 || (rtFrames > apiFrames && rt.fps_nominal))
      merged.push(
        useRt
          ? {
              ...it,
              frame_count: rt.frame_count,
              duration_s: rt.duration_s ?? it.duration_s,
              fps_nominal: rt.fps_nominal ?? it.fps_nominal,
              has_images: rt.has_images ?? it.has_images,
            }
          : it,
      )
    }
    for (const rt of rtItems) {
      if (!seen.has(rt.dataset_id)) merged.push(rt)
    }
    const sorted = sortDatasetsForWizard(merged)
    setDatasets(sorted)
    return sorted
  }, [token])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const urlDataset = params.get('dataset_id')
    const urlAlgo = params.get('algorithm')
    const urlHf = params.get('dataset_hf_id')

    ;(async () => {
      setLoading(true)
      try {
        const items = await loadDatasets()
        const algData = await authJson<{ algorithms: AlgoOption[]; qualia_configured: boolean }>(
          '/api/v1/trainings/algorithms',
        ).catch(() => ({
          algorithms: [{ id: 'mlp_baseline', name: 'MLP', backend: 'local', description: '' }],
          qualia_configured: false,
        }))
        setAlgorithms(algData.algorithms)
        setQualiaConfigured(algData.qualia_configured)

        if (token) {
          try {
            await loadJobs()
          } catch (e) {
            setErr(parseApiError((e as Error).message))
          }
        }

        let pick = urlDataset && items.some((x) => x.dataset_id === urlDataset) ? urlDataset : ''
        if (!pick && runtimePrefill === 'b601_rs') {
          const b601 = items.find(
            (d) => d.dataset_id.includes('b601') && datasetTrainability(d).level !== 'blocked',
          )
          pick = b601?.dataset_id || ''
        }
        if (!pick) {
          const ready = items.find((d) => datasetTrainability(d).level !== 'blocked')
          pick = ready?.dataset_id || items[0]?.dataset_id || ''
        }
        setDatasetId(pick)

        if (urlAlgo && algData.algorithms.some((a) => a.id === urlAlgo)) {
          setAlgo(urlAlgo)
          const backend = algData.algorithms.find((a) => a.id === urlAlgo)?.backend
          if (backend === 'qualia' || backend === 'local') setTrainBackend(backend)
          setGoalTouched(true)
          setGoal('expert')
          setExpertOpen(true)
        }
        if (urlHf) setHfDatasetId(urlHf)

        setWizardStep('data')
        if (!(urlAlgo && algData.algorithms.some((a) => a.id === urlAlgo))) {
          setGoalTouched(false)
        }
        setInitialBoot(true)
      } catch (e) {
        setErr(parseApiError((e as Error).message))
      } finally {
        setLoading(false)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- boot once
  }, [])

  useEffect(() => {
    if (!initialBoot || !goalTouched) return
    // expert / URL ?algorithm= keeps the user's (or deep-link) algo selection
    if (goal === 'expert') {
      setExpertOpen(true)
      return
    }
    const { algo: a, backend } = applyGoal(goal, algorithms)
    setAlgo(a)
    setTrainBackend(backend)
  }, [goal, algorithms, initialBoot, goalTouched])

  const loadQualiaInfo = useCallback(async () => {
    try {
      const body = await authJson<{ ok: boolean; instances: QualiaInstance[] }>(
        '/api/v1/trainings/qualia/instances',
      )
      if (body.ok) {
        setQInstances(body.instances)
        if (!qInstance && body.instances[0]) setQInstance(body.instances[0].id)
      }
    } catch { /* ignore */ }
    try {
      const v = await authJson<{ ok: boolean; message: string }>('/api/v1/trainings/qualia/validate', {
        method: 'POST',
      })
      setQKeyStatus(v)
    } catch (e) {
      setQKeyStatus({ ok: false, message: parseApiError((e as Error).message) })
    }
  }, [qInstance])

  const loadQualiaDefaults = useCallback(async (algoId: string) => {
    try {
      const body = await authJson<{
        defaults: { instance_type: string; hours: number; batch_size: number; model_id: string | null }
        cost_estimate: { estimated_credits: number }
      }>(`/api/v1/trainings/qualia/defaults?algorithm=${encodeURIComponent(algoId)}`)
      setQInstance(body.defaults.instance_type)
      setQHours(body.defaults.hours)
      setQBatch(body.defaults.batch_size)
      setQModelId(body.defaults.model_id ?? '')
      setQCost(body.cost_estimate)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    if (!goalTouched || trainBackend !== 'qualia') return
    void loadQualiaInfo()
  }, [goalTouched, trainBackend, loadQualiaInfo])

  useEffect(() => {
    if (!goalTouched || trainBackend !== 'qualia' || !algo) return
    void loadQualiaDefaults(algo)
  }, [goalTouched, trainBackend, algo, loadQualiaDefaults])

  const runPrepare = useCallback(async () => {
    setPrepareRunning(true)
    setErr(null)
    const checks: PrepareCheck[] = []
    const push = (c: PrepareCheck) => {
      checks.push(c)
      setPrepareChecks([...checks])
    }

    push({ id: 'login', label: '登录状态', status: token ? 'ok' : 'block', detail: token ? '已登录' : '请先登录' })

    if (!token) {
      setPrepareRunning(false)
      return
    }

    push({ id: 'dataset', label: '数据集检查', status: 'running' })
    let readiness: DatasetReadiness | null = null
    try {
      if (trainBackend === 'qualia' && datasetId) {
        readiness = await authJson<DatasetReadiness>(
          `/api/v1/trainings/dataset_readiness?dataset_id=${encodeURIComponent(datasetId)}`,
        )
        setDatasetReadiness(readiness)
        if (readiness.ready) {
          checks[checks.length - 1] = {
            id: 'dataset',
            label: '数据集检查',
            status: 'ok',
            detail: readiness.label,
          }
        } else {
          checks[checks.length - 1] = {
            id: 'dataset',
            label: '数据集检查',
            status: 'block',
            detail: readiness.label,
            actionLabel: '去采集带摄像头数据',
            actionHref: '/teleop',
          }
        }
      } else if (selectedDataset) {
        const t = datasetTrainability(selectedDataset)
        checks[checks.length - 1] = {
          id: 'dataset',
          label: '数据集检查',
          status: t.level === 'blocked' ? 'block' : 'ok',
          detail: t.hint,
          actionHref: t.level === 'blocked' ? '/teleop' : undefined,
          actionLabel: t.level === 'blocked' ? '去采集' : undefined,
        }
      }
    } catch {
      checks[checks.length - 1] = { id: 'dataset', label: '数据集检查', status: 'warn', detail: '暂时无法检查' }
    }
    setPrepareChecks([...checks])

    push({ id: 'quota', label: '训练名额', status: 'running' })
    try {
      const rec = await authJson<{ updated: number; active: number }>('/api/v1/trainings/reconcile', {
        method: 'POST',
      })
      const max = user?.entitlements?.limits.training_concurrent_max ?? 4
      if (rec.active >= max) {
        checks[checks.length - 1] = {
          id: 'quota',
          label: '训练名额',
          status: 'block',
          detail: `当前有 ${rec.active} 个任务在进行，最多 ${max} 个。请取消旧任务或等待完成。`,
        }
      } else {
        checks[checks.length - 1] = {
          id: 'quota',
          label: '训练名额',
          status: 'ok',
          detail: `可用（${rec.active}/${max}）`,
        }
      }
    } catch {
      checks[checks.length - 1] = { id: 'quota', label: '训练名额', status: 'warn', detail: '无法同步名额' }
    }
    setPrepareChecks([...checks])

    if (trainBackend === 'qualia') {
      push({
        id: 'qualia',
        label: '云端训练服务',
        status: qualiaConfigured && qKeyStatus?.ok ? 'ok' : 'block',
        detail: qKeyStatus?.ok ? 'Qualia 已就绪' : '云端训练暂不可用，请联系管理员或改用本地试跑',
      })
      setPrepareChecks([...checks])
    }

    setPrepareRunning(false)
  }, [token, trainBackend, datasetId, selectedDataset, qualiaConfigured, qKeyStatus, user])

  const startPrepare = useCallback(() => {
    void runPrepare()
  }, [runPrepare])

  useEffect(() => {
    if (!snapshot) return
    setJobs((prev) => prev.map((j) => (j.id === snapshot.id ? { ...j, ...snapshot } : j)))
    if (snapshot.status === 'succeeded') setWizardStep('done')
    if (snapshot.status === 'failed' && wizardStep === 'running') setWizardStep('running')
  }, [snapshot, wizardStep])

  useEffect(() => {
    if (done) loadJobs()
  }, [done, loadJobs])

  const canPickDataset = Boolean(
    datasetId && selectedDataset && datasetTrainability(selectedDataset).level !== 'blocked',
  )

  const prepareOk = prepareChecks.length > 0 && prepareChecks.every((c) => c.status === 'ok' || c.status === 'warn')

  const submitTraining = useCallback(async () => {
    if (!token || !datasetId) return
    setSubmitting(true)
    setErr(null)
    try {
      const payload: Record<string, unknown> = {
        dataset_id: datasetId,
        algo,
        train_backend: trainBackend,
        epochs,
        batch_size: trainBackend === 'qualia' ? qBatch : batchSize,
        lr,
        hidden,
      }
      if (trainBackend === 'qualia') {
        payload.instance_type = qInstance || undefined
        payload.hours = qHours
        if (qModelId) payload.model_id = qModelId
        if (expertOpen && hfDatasetId.trim()) payload.dataset_hf_id = hfDatasetId.trim()
        if (expertOpen && qCameraKeys.trim()) {
          payload.camera_keys = qCameraKeys.split(',').map((s) => s.trim()).filter(Boolean)
        }
      }
      const submitOnce = () =>
        authJson<TrainingJobDTO>('/api/v1/trainings', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
      let job: TrainingJobDTO
      try {
        job = await submitOnce()
      } catch (first) {
        const msg = (first as Error).message
        if (msg.includes('quota_training_concurrent')) {
          await authJson('/api/v1/trainings/reconcile', { method: 'POST' })
          job = await submitOnce()
        } else {
          throw first
        }
      }
      setJobs((prev) => [job, ...prev])
      setWatchJobId(job.id)
      if (job.status === 'failed') {
        setErr(job.error_msg || '训练提交失败')
        setWizardStep('confirm')
      } else {
        setWizardStep('running')
      }
    } catch (e) {
      setErr(parseApiError((e as Error).message))
      setWizardStep('confirm')
    } finally {
      setSubmitting(false)
    }
  }, [
    token,
    datasetId,
    algo,
    trainBackend,
    epochs,
    batchSize,
    lr,
    hidden,
    qBatch,
    qInstance,
    qHours,
    qModelId,
    expertOpen,
    hfDatasetId,
    qCameraKeys,
  ])

  const cancelJob = useCallback(
    async (jobId: string) => {
      if (!window.confirm('确认取消这个训练任务？')) return
      setCancellingId(jobId)
      try {
        const updated = await authJson<TrainingJobDTO>(`/api/v1/trainings/${jobId}/cancel`, {
          method: 'POST',
        })
        setJobs((prev) => prev.map((j) => (j.id === updated.id ? { ...j, ...updated } : j)))
        try {
          await authJson('/api/v1/trainings/reconcile', { method: 'POST' })
        } catch {
          /* best-effort */
        }
        await loadJobs()
        if (wizardStep === 'prepare' && prepareChecks.length > 0) {
          void runPrepare()
        }
        if (watchJobId === jobId && (wizardStep === 'running' || wizardStep === 'done')) {
          setWizardStep('data')
          setWatchJobId(null)
        }
      } catch (e) {
        setErr(parseApiError((e as Error).message))
      } finally {
        setCancellingId(null)
      }
    },
    [loadJobs, runPrepare, wizardStep, prepareChecks.length, watchJobId],
  )

  const handleRefresh = useCallback(async () => {
    setRefreshing(true)
    setErr(null)
    try {
      await loadDatasets()
      await loadJobs()
      if (wizardStep === 'prepare' && prepareChecks.length > 0) {
        await runPrepare()
      }
    } catch (e) {
      setErr(parseApiError((e as Error).message))
    } finally {
      setRefreshing(false)
    }
  }, [loadDatasets, loadJobs, runPrepare, wizardStep, prepareChecks.length])

  const toggleExpand = useCallback(
    async (jobId: string) => {
      if (expandedJobId === jobId) {
        setExpandedJobId(null)
        setJobDetail(null)
        return
      }
      setExpandedJobId(jobId)
      setDetailLoading(true)
      try {
        const detail = await authJson<JobDetail>(`/api/v1/trainings/${jobId}`)
        setJobDetail(detail)
      } catch {
        setJobDetail(null)
      } finally {
        setDetailLoading(false)
      }
    },
    [expandedJobId],
  )

  const qInstanceMeta = qInstances.find((i) => i.id === qInstance)
  const costLabel = useMemo(() => {
    if (trainBackend !== 'qualia') return null
    if (qInstanceMeta) {
      return `约 ${(qInstanceMeta.credits_per_hour * qHours).toFixed(1)} credits`
    }
    if (qCost) return `约 ${qCost.estimated_credits} credits`
    return null
  }, [trainBackend, qInstanceMeta, qHours, qCost])

  const wizardBack = useCallback(() => {
    const prev = wizardPrevious(wizardStep)
    if (prev) setWizardStep(prev)
  }, [wizardStep])

  const wizardJump = useCallback(
    (target: WizardStep) => {
      const cur = WIZARD_FLOW.indexOf(wizardStep)
      const tgt = WIZARD_FLOW.indexOf(target)
      if (tgt >= 0 && tgt < cur) setWizardStep(target)
    },
    [wizardStep],
  )

  const goalNextBlocked =
    !goalTouched || (goal === 'recommended_cloud' && qualiaLocked)

  const footerNext = useMemo(() => {
    if (wizardStep === 'data') {
      return {
        label: '下一步',
        action: () => setWizardStep('goal'),
        disabled: !canPickDataset,
        hint: !canPickDataset ? '请先选一个可训练的数据集' : undefined,
      }
    }
    if (wizardStep === 'goal') {
      return {
        label: '下一步',
        action: () => setWizardStep('prepare'),
        disabled: goalNextBlocked,
        hint: goalNextBlocked ? '请先选一种训练方式' : undefined,
      }
    }
    if (wizardStep === 'prepare') {
      return {
        label: '下一步',
        action: () => setWizardStep('confirm'),
        disabled: !prepareOk || prepareRunning,
        hint: prepareRunning ? '检查中…' : !prepareOk ? '请先通过检查' : undefined,
      }
    }
    return null
  }, [wizardStep, canPickDataset, goalNextBlocked, prepareOk, prepareRunning])

  const inWizard = WIZARD_FLOW.includes(wizardStep)

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <UpgradeModal
        open={upgradeOpen}
        onClose={() => setUpgradeOpen(false)}
        requiredTier="pro"
        reason="云端训练需要个人会员或创作者版"
      />

      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => void handleRefresh()} disabled={refreshing}>
          <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      <TrainingHero step={wizardStep} token={token} />

      <WizardProgress
        step={wizardStep}
        onJump={inWizard ? wizardJump : undefined}
      />

      {token && (
        <TrainingJobsBanner
          jobs={jobs}
          watchJobId={watchJobId}
          onWatch={(id) => {
            setWatchJobId(id)
            setWizardStep('running')
          }}
          showAll={jobsListExpanded}
          onShowAll={() => setJobsListExpanded(!jobsListExpanded)}
        />
      )}

      {inWizard && goalTouched && wizardStep !== 'data' && wizardStep !== 'goal' && (
        <WizardChoicesSummary
          dataset={selectedDataset}
          goal={goal}
          goalTouched={goalTouched}
          trainBackend={trainBackend}
          qHours={qHours}
          qInstance={qInstance}
          qInstances={qInstances}
          epochs={epochs}
          costLabel={costLabel}
        />
      )}

      {err && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {err}
          {err.includes('名额') && (
            <Button
              variant="outline"
              size="sm"
              className="mt-2 w-full"
              onClick={async () => {
                await authJson('/api/v1/trainings/reconcile', { method: 'POST' })
                await loadJobs()
                if (wizardStep === 'prepare' && prepareChecks.length > 0) {
                  await runPrepare()
                }
                setErr(null)
              }}
            >
              同步旧任务后重试
            </Button>
          )}
        </div>
      )}

      {(wizardStep === 'running' || wizardStep === 'done') && (
        <ActiveTrainingPanel
          job={activeJob ?? null}
          snapshot={snapshot}
          lossHistory={lossHistory}
          wsErr={wsErr}
          onCancel={() => activeJob && cancelJob(activeJob.id)}
          cancelling={Boolean(activeJob && cancellingId === activeJob.id)}
          onDone={() => {
            setWizardStep('data')
            setWatchJobId(null)
            setGoalTouched(false)
            setPrepareChecks([])
            setErr(null)
          }}
          onBack={() => {
            setWizardStep('data')
            setWatchJobId(null)
          }}
        />
      )}

      {wizardStep === 'data' && (
        <>
          <CourseTemplatePicker
            onSelect={(t) => {
              window.localStorage.setItem('botversex_course_template', JSON.stringify(t))
              setCourseTemplateHint(
                `已选「${t.label}」— 在 ${t.suggested_runtime === 'b601_rs' ? '/robots/b601_rs' : '/robots/so101'} 录制时使用任务：${t.single_task}`,
              )
            }}
          />
          {courseTemplateHint && (
            <p className="text-xs text-[hsl(var(--primary))]">{courseTemplateHint}</p>
          )}
          <DatasetStep
            datasets={datasets}
            selectedId={datasetId}
            onSelect={setDatasetId}
          />
        </>
      )}

      {wizardStep === 'goal' && (
        <>
          <GoalStep
            goal={goal}
            goalTouched={goalTouched}
            onSelect={(g) => {
              setGoal(g)
              setGoalTouched(true)
            }}
            qualiaLocked={qualiaLocked}
            onUpgrade={() => setUpgradeOpen(true)}
            qHours={qHours}
            setQHours={setQHours}
            qInstance={qInstance}
            setQInstance={setQInstance}
            qInstances={qInstances}
            costLabel={costLabel}
            epochs={epochs}
            setEpochs={setEpochs}
          />
          <AdvancedTrainingSettings
            open={expertOpen || goal === 'expert'}
            onToggle={() => setExpertOpen(!expertOpen)}
            algorithms={algorithms}
            algo={algo}
            onAlgoChange={(id) => {
              const a = algorithms.find((x) => x.id === id)
              setAlgo(id)
              if (a) setTrainBackend(a.backend === 'qualia' ? 'qualia' : 'local')
            }}
            trainBackend={trainBackend}
            epochs={epochs}
            setEpochs={setEpochs}
            batchSize={batchSize}
            setBatchSize={setBatchSize}
            lr={lr}
            setLr={setLr}
            hidden={hidden}
            setHidden={setHidden}
            qInstance={qInstance}
            setQInstance={setQInstance}
            qHours={qHours}
            setQHours={setQHours}
            qBatch={qBatch}
            setQBatch={setQBatch}
            qInstances={qInstances}
            hfDatasetId={hfDatasetId}
            setHfDatasetId={setHfDatasetId}
            qCameraKeys={qCameraKeys}
            setQCameraKeys={setQCameraKeys}
            qModelId={qModelId}
            setQModelId={setQModelId}
          />
        </>
      )}

      {wizardStep === 'prepare' && (
        <PrepareStep
          checks={prepareChecks}
          running={prepareRunning}
          started={prepareChecks.length > 0}
          onStart={startPrepare}
          blockAction={
            prepareChecks.some((c) => c.id === 'dataset' && c.status === 'block')
              ? { label: '去采集带摄像头数据', href: '/teleop' }
              : undefined
          }
        />
      )}

      {wizardStep === 'confirm' && (
        <>
          <ConfirmStep
            dataset={selectedDataset}
            goal={goal}
            trainBackend={trainBackend}
            qHours={qHours}
            qInstance={qInstance}
            qInstances={qInstances}
            epochs={epochs}
            algo={algo}
            costLabel={trainBackend === 'qualia' ? costLabel : null}
            submitting={submitting}
            onSubmit={() => void submitTraining()}
            disabled={!token || (trainBackend === 'qualia' && datasetReadiness !== null && !datasetReadiness.ready)}
          />
          {!token && (
            <div className="text-center">
              <Link to="/login">
                <Button>登录后开始训练</Button>
              </Link>
            </div>
          )}
        </>
      )}

      {(wizardStep === 'confirm' || (inWizard && footerNext)) && (
        <WizardFooter
          showBack={wizardStep !== 'data'}
          onBack={wizardBack}
          showNext={wizardStep !== 'confirm' && Boolean(footerNext)}
          nextLabel={footerNext?.label ?? ''}
          onNext={footerNext?.action ?? (() => {})}
          nextDisabled={footerNext?.disabled}
          hint={footerNext?.hint}
        />
      )}
    </div>
  )
}

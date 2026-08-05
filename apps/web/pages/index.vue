<script setup lang="ts">
import type {
  AnalysisRunResponse,
  ImageSummary,
  MessageRecord,
  MemoryProposal,
  MemoryRecord,
  StreamEvent,
  SystemStatus,
  ThreadDetail,
  ToolTrace
} from '~/types/api'

interface UploadedImage extends ImageSummary {
  previewUrl: string
}

const api = useXiangLensApi()
const apiBaseInput = ref('')
const connectionError = ref('')
const actionError = ref('')
const system = ref<SystemStatus | null>(null)
const threadId = ref('')
const images = ref<UploadedImage[]>([])
const result = ref<AnalysisRunResponse | null>(null)
const events = ref<ToolTrace[]>([])
const plan = ref<string[]>([])
const memories = ref<MemoryRecord[]>([])
const messages = ref<MessageRecord[]>([])
const followUpMessage = ref('')
const initialReportMarkdown = ref('')
const activeRunIsFollowUp = ref(false)
const connecting = ref(false)
const uploading = ref(false)
const analyzing = ref(false)
const previewMode = ref(false)

const contextPresets = {
  GitHub: {
    audience: 'International open-source collaborators',
    goals: 'credible, approachable, distinctive'
  },
  LinkedIn: {
    audience: 'Recruiters, professional peers, and potential collaborators',
    goals: 'credible, polished, approachable'
  },
  Discord: {
    audience: 'Online community members, teammates, and moderators',
    goals: 'approachable, recognizable, community-friendly'
  },
  'Hackathon profile': {
    audience: 'International judges, mentors, sponsors, and fellow builders',
    goals: 'innovative, credible, memorable'
  },
  General: {
    audience: 'General online audiences across mixed contexts',
    goals: 'clear, approachable, context-appropriate'
  }
} as const

type TargetContext = keyof typeof contextPresets
const contextOptions = Object.keys(contextPresets) as TargetContext[]

const form = reactive({
  platform: 'GitHub' as TargetContext,
  ...contextPresets.GitHub,
  message: 'Compare these profile images and recommend the safest fit for my selected context.',
  enablePrivateLens: false,
  enabledPacks: [
    'profile_basics',
    'privacy_safety',
    'global_professional_context',
    'open_chinese_symbolism'
  ]
})

watch(() => form.platform, (platform: TargetContext) => {
  const preset = contextPresets[platform]
  form.audience = preset.audience
  form.goals = preset.goals
})

const packOptions = [
  ['profile_basics', 'Profile basics'],
  ['privacy_safety', 'Privacy safety'],
  ['global_professional_context', 'Professional context'],
  ['open_chinese_symbolism', 'Chinese symbolism']
]

const canAnalyze = computed(() => (
  images.value.length > 0
  && messages.value.length === 0
  && !analyzing.value
  && !previewMode.value
))
const canFollowUp = computed(() => (
  followUpMessage.value.trim().length >= 3
  && images.value.length > 0
  && !analyzing.value
  && !previewMode.value
))
const followUpMessages = computed(() => messages.value.slice(2))
const followUpTurns = computed(() => Math.ceil(followUpMessages.value.length / 2))
const modelState = computed(() => {
  if (previewMode.value) return 'Interface preview'
  if (!system.value) return 'Not checked'
  if (system.value.model_reachable === true) return 'Reachable'
  if (system.value.model_reachable === false) return 'Unreachable'
  return system.value.model_configured ? 'Configured' : 'Not configured'
})

onMounted(async () => {
  apiBaseInput.value = sessionStorage.getItem('xianglens-api-base') || api.apiBase.value
  api.setApiBase(apiBaseInput.value)
  api.restoreSession()
  if (apiBaseInput.value) await connect()
})

onBeforeUnmount(() => {
  for (const image of images.value as UploadedImage[]) URL.revokeObjectURL(image.previewUrl)
})

async function connect() {
  connecting.value = true
  connectionError.value = ''
  previewMode.value = false
  api.setApiBase(apiBaseInput.value)
  sessionStorage.setItem('xianglens-api-base', api.apiBase.value)
  try {
    await api.openSession()
    system.value = await api.request<SystemStatus>('/api/v1/system/status?probe_model=true')
    await loadMemories()
  } catch (error) {
    connectionError.value = error instanceof Error ? error.message : String(error)
    system.value = null
  } finally {
    connecting.value = false
  }
}

function previewWorkspace() {
  connectionError.value = ''
  previewMode.value = true
  system.value = {
    app: 'XiangLens',
    version: 'preview',
    environment: 'static-preview',
    deployment_mode: 'development-remote',
    auth_enabled: false,
    model_configured: false,
    model_reachable: null,
    model_endpoint: 'Connect XiangLens FastAPI to run analysis',
    model_name: 'Qwen3.6 35B A3B Fable 5 Distill Q6_K',
    inference_ownership: 'static interface preview — no image or prompt leaves this browser',
    submission_topology_compliant: false,
    milvus_ready: false,
    private_lens_available: true,
    private_lens_name: 'Private 108-Technique Lens'
  }
}

async function ensureThread(): Promise<string> {
  if (threadId.value) return threadId.value
  if (!api.sessionId.value) throw new Error('No active access session')
  const thread = await api.request<{ id: string }>('/api/v1/threads', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: api.sessionId.value })
  })
  threadId.value = thread.id
  return thread.id
}

async function selectFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const selected = Array.from(input.files || []).slice(0, 4 - images.value.length)
  if (!selected.length) return
  uploading.value = true
  actionError.value = ''
  try {
    if (previewMode.value) {
      for (const file of selected) {
        const bitmap = await createImageBitmap(file)
        images.value.push({
          id: `preview-${crypto.randomUUID()}`,
          thread_id: 'static-preview',
          original_name: file.name,
          mime_type: file.type,
          width: bitmap.width,
          height: bitmap.height,
          sha256: 'computed by the API after connection',
          created_at: new Date().toISOString(),
          previewUrl: URL.createObjectURL(file)
        })
        bitmap.close()
      }
      return
    }
    const currentThread = await ensureThread()
    for (const file of selected) {
      const data = new FormData()
      data.append('image', file)
      const uploaded = await api.request<ImageSummary>(
        `/api/v1/threads/${currentThread}/images`,
        { method: 'POST', body: data }
      )
      images.value.push({ ...uploaded, previewUrl: URL.createObjectURL(file) })
    }
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    uploading.value = false
    input.value = ''
  }
}

function consumeEvent(streamEvent: StreamEvent) {
  if (streamEvent.event === 'node.completed') {
    const trace = streamEvent.data.trace as ToolTrace | null
    if (trace) events.value.push(trace)
    const nextPlan = streamEvent.data.plan
    if (Array.isArray(nextPlan) && nextPlan.every(item => typeof item === 'string')) {
      plan.value = nextPlan
    }
  }
  if (streamEvent.event === 'run.completed') {
    const completed = streamEvent.data as unknown as AnalysisRunResponse
    result.value = completed
    if (!activeRunIsFollowUp.value) initialReportMarkdown.value = completed.report_markdown
    plan.value = completed.plan
    events.value = completed.tool_trace
  }
  if (streamEvent.event === 'run.failed') {
    actionError.value = String(streamEvent.data.error || 'Analysis failed')
  }
}

async function loadThreadState() {
  if (!threadId.value) return
  const state = await api.request<ThreadDetail>(`/api/v1/threads/${threadId.value}/state`)
  messages.value = state.messages
}

async function runAnalysis(message: string, clearPreviousResult: boolean): Promise<boolean> {
  activeRunIsFollowUp.value = !clearPreviousResult
  analyzing.value = true
  actionError.value = ''
  if (clearPreviousResult) result.value = null
  events.value = []
  plan.value = []
  try {
    const currentThread = await ensureThread()
    const runPath = `/api/v1/threads/${currentThread}/runs`
    const payload = {
      message,
      platform: form.platform,
      audience: form.audience,
      intent_keywords: form.goals.split(',').map((value: string) => value.trim()).filter(Boolean),
      image_ids: images.value.map((image: UploadedImage) => image.id),
      enabled_packs: form.enabledPacks,
      enable_private_lens: form.enablePrivateLens,
      reuse_latest_analysis: !clearPreviousResult
    }
    if (api.runTransport.value === 'poll') {
      await api.pollRun(runPath, payload, consumeEvent)
    } else {
      await api.stream(`${runPath}/stream`, payload, consumeEvent)
    }
    await loadThreadState()
    return true
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
    return false
  } finally {
    analyzing.value = false
    activeRunIsFollowUp.value = false
  }
}

async function analyze() {
  if (!canAnalyze.value) return
  await runAnalysis(form.message, true)
}

async function sendFollowUp() {
  if (!canFollowUp.value) return
  const message = followUpMessage.value.trim()
  if (await runAnalysis(message, false)) followUpMessage.value = ''
}

async function decideMemory(proposal: MemoryProposal, action: 'approve' | 'reject') {
  actionError.value = ''
  try {
    const updated = await api.request<MemoryProposal>(
      `/api/v1/consents/${proposal.consent_id}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
      }
    )
    if (result.value?.memory_proposal) result.value.memory_proposal = updated
    await loadMemories()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  }
}

async function loadMemories() {
  if (!api.sessionId.value) return
  memories.value = await api.request<MemoryRecord[]>(
    `/api/v1/memories?user_id=${encodeURIComponent(api.sessionId.value)}`
  )
}

async function deleteMemory(memoryId: string) {
  actionError.value = ''
  try {
    await api.request<void>(
      `/api/v1/memories/${memoryId}?user_id=${encodeURIComponent(api.sessionId.value)}`,
      {
      method: 'DELETE'
      }
    )
    memories.value = memories.value.filter((memory: MemoryRecord) => memory.id !== memoryId)
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  }
}

async function exportSafeCopy(imageId: string) {
  if (!threadId.value) return
  try {
    const blob = await api.download(
      `/api/v1/threads/${threadId.value}/images/${imageId}/safe-copy`
    )
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `xianglens-safe-${imageId}.jpg`
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  }
}

async function newSession() {
  if (threadId.value && !window.confirm('Delete this thread and its uploaded images?')) return
  actionError.value = ''
  const wasConnected = !previewMode.value && Boolean(system.value)
  try {
    if (threadId.value && !previewMode.value) {
      await api.request<void>(`/api/v1/threads/${threadId.value}`, { method: 'DELETE' })
    }
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
    return
  }
  for (const image of images.value as UploadedImage[]) URL.revokeObjectURL(image.previewUrl)
  images.value = []
  threadId.value = ''
  result.value = null
  events.value = []
  plan.value = []
  messages.value = []
  followUpMessage.value = ''
  initialReportMarkdown.value = ''
  actionError.value = ''
  if (wasConnected) {
    api.clearSession()
    try {
      await api.openSession(true)
      await loadMemories()
    } catch (error) {
      system.value = null
      connectionError.value = error instanceof Error ? error.message : String(error)
    }
  }
}

async function forgetMe() {
  if (previewMode.value) return
  if (!api.sessionId.value) return
  if (!window.confirm('Delete all data created in this private session?')) return
  actionError.value = ''
  try {
    await api.request(
      `/api/v1/privacy/forget-me?user_id=${encodeURIComponent(api.sessionId.value)}`,
      { method: 'DELETE' }
    )
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
    return
  }
  for (const image of images.value as UploadedImage[]) URL.revokeObjectURL(image.previewUrl)
  images.value = []
  memories.value = []
  threadId.value = ''
  result.value = null
  events.value = []
  plan.value = []
  messages.value = []
  followUpMessage.value = ''
  initialReportMarkdown.value = ''
}

function imageName(imageId: string): string {
  return result.value?.image_labels?.[imageId]
    || images.value.find((image: UploadedImage) => image.id === imageId)?.original_name
    || imageId.slice(0, 8)
}

function scoreWidth(score: number): string {
  return `${Math.max(0, Math.min(5, score)) * 20}%`
}

function formatDuration(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value.toFixed(0)} ms`
}
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand-block">
        <div class="brand-mark">XL</div>
        <div>
          <p class="eyebrow">AMD Radeon private agent</p>
          <h1>XiangLens</h1>
        </div>
      </div>
      <div class="runtime-badges">
        <span class="badge" :class="system?.model_reachable ? 'good' : ''">
          <span class="status-dot" /> {{ modelState }}
        </span>
        <span class="badge">{{ system?.milvus_ready ? 'Milvus ready' : 'Milvus unchecked' }}</span>
        <span v-if="system?.private_lens_available" class="badge private-ready">Private lens mounted</span>
        <button class="ghost-button" type="button" @click="newSession">New private session</button>
      </div>
    </header>

    <section v-if="!system" class="connection-card">
      <div>
        <p class="eyebrow">Short-lived access</p>
        <h2>Open a private workspace</h2>
        <p>
          XiangLens requests a temporary Bearer token. The permanent credential never enters
          this page, browser storage, or the generated GitHub Pages bundle.
        </p>
      </div>
      <form class="connection-form" @submit.prevent="connect">
        <div class="connection-endpoint">
          <span>Configured XiangLens API</span>
          <strong>{{ api.apiBase.value || 'Not configured' }}</strong>
        </div>
        <div class="connection-actions">
          <button class="primary-button" type="submit" :disabled="connecting || !apiBaseInput">
            {{ connecting ? 'Opening…' : 'Open secure session' }}
          </button>
          <button class="secondary-button" type="button" @click="previewWorkspace">
            Preview workspace
          </button>
        </div>
        <details class="advanced-settings">
          <summary>Advanced settings</summary>
          <label>
            <span>Override API base URL</span>
            <input
              v-model="apiBaseInput"
              type="url"
              autocomplete="url"
              placeholder="https://your-xianglens-api.example"
            >
          </label>
          <small>The deployment default is injected through <code>NUXT_PUBLIC_API_BASE</code>.</small>
        </details>
      </form>
      <p v-if="connectionError" class="error-text">{{ connectionError }}</p>
    </section>

    <main v-else class="workspace">
      <aside class="panel setup-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">01 · Intent</p>
            <h2>Review setup</h2>
          </div>
          <span class="privacy-chip">Session only</span>
        </div>

        <label class="field-label">Target context</label>
        <select v-model="form.platform">
          <option v-for="context in contextOptions" :key="context" :value="context">
            {{ context }}
          </option>
        </select>

        <label class="field-label">Audience</label>
        <input v-model="form.audience" type="text">

        <label class="field-label">Intended signals</label>
        <input v-model="form.goals" type="text" placeholder="credible, approachable, distinctive">

        <label class="field-label">Request</label>
        <textarea v-model="form.message" rows="5" />

        <label class="field-label">Enabled Lens Packs</label>
        <div class="check-grid">
          <label v-for="pack in packOptions" :key="pack[0]" class="check-row">
            <input v-model="form.enabledPacks" type="checkbox" :value="pack[0]">
            <span>{{ pack[1] }}</span>
          </label>
        </div>

        <label v-if="system.private_lens_available" class="private-lens-toggle">
          <input v-model="form.enablePrivateLens" type="checkbox">
          <span>
            <strong>{{ system.private_lens_name }}</strong>
            <small>Opt-in · runtime-only source · safety-filtered output</small>
          </span>
        </label>

        <div class="upload-zone">
          <input
            id="image-input"
            class="file-input"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            multiple
            :disabled="images.length >= 4 || uploading"
            @change="selectFiles"
          >
          <label for="image-input">
            <strong>{{ uploading ? 'Uploading…' : 'Add profile images' }}</strong>
            <span>JPEG, PNG, or WebP · up to four candidates</span>
          </label>
        </div>

        <div v-if="images.length" class="image-grid">
          <article v-for="image in images" :key="image.id" class="image-card">
            <img :src="image.previewUrl" :alt="image.original_name">
            <div>
              <strong>{{ image.original_name }}</strong>
              <span>{{ image.width }} × {{ image.height }}</span>
            </div>
            <button v-if="!previewMode" type="button" @click="exportSafeCopy(image.id)">Safe copy</button>
          </article>
        </div>

        <button class="primary-button analyze-button" type="button" :disabled="!canAnalyze" @click="analyze">
          {{ previewMode ? 'Connect API to run analysis' : analyzing ? 'Agent running…' : messages.length ? 'Use follow-up below' : images.length > 1 ? 'Compare candidates' : 'Review image' }}
        </button>
        <p v-if="actionError" class="error-text">{{ actionError }}</p>
      </aside>

      <section class="panel report-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">02 · Result</p>
            <h2>Evidence-backed report</h2>
          </div>
          <span v-if="result" class="status-label">{{ result.status }}</span>
        </div>

        <div v-if="!result && !analyzing" class="empty-state">
          <div class="empty-symbol">◎</div>
          <h3>Your review will appear here</h3>
          <p>Add one to four candidates, define the audience, and run the bounded agent workflow.</p>
        </div>

        <div v-if="analyzing" class="running-state">
          <div class="pulse-ring" />
          <div>
            <h3>Private analysis in progress</h3>
            <p>{{ events.at(-1)?.summary || 'Creating the bounded plan…' }}</p>
          </div>
        </div>

        <template v-if="result">
          <div class="metric-strip">
            <div><span>Total</span><strong>{{ formatDuration(result.performance_metrics.total_duration_ms) }}</strong></div>
            <div><span>Model</span><strong>{{ formatDuration(result.performance_metrics.model_duration_ms) }}</strong></div>
            <div><span>RAG</span><strong>{{ formatDuration(result.performance_metrics.retrieval_duration_ms) }}</strong></div>
            <div><span>Sources</span><strong>{{ result.performance_metrics.evidence_count }}</strong></div>
          </div>

          <section v-if="result.comparison" class="result-section">
            <h3>Candidate comparison</h3>
            <p class="recommendation-line">
              Recommended: <strong>{{ imageName(result.comparison.recommended_image_id) }}</strong>
            </p>
            <article v-for="candidate in result.comparison.candidates" :key="candidate.image_id" class="score-card">
              <div class="score-heading">
                <strong>{{ imageName(candidate.image_id) }}</strong>
                <span v-if="candidate.image_id === result.comparison.recommended_image_id">Recommended</span>
              </div>
              <div class="score-row"><span>Crop resilience</span><i><b :style="{ width: scoreWidth(candidate.crop_resilience) }" /></i><em>{{ candidate.crop_resilience }}/5</em></div>
              <div class="score-row"><span>Small-size clarity</span><i><b :style="{ width: scoreWidth(candidate.small_size_clarity) }" /></i><em>{{ candidate.small_size_clarity }}/5</em></div>
              <div class="score-row"><span>Privacy safety</span><i><b :style="{ width: scoreWidth(candidate.privacy_safety) }" /></i><em>{{ candidate.privacy_safety }}/5</em></div>
              <div class="score-row"><span>Intent alignment</span><i><b :style="{ width: scoreWidth(candidate.intent_alignment) }" /></i><em>{{ candidate.intent_alignment }}/5</em></div>
              <div class="score-row"><span>Low ambiguity</span><i><b :style="{ width: scoreWidth(5 - candidate.contextual_ambiguity) }" /></i><em>{{ candidate.contextual_ambiguity }}/5</em></div>
              <p>{{ candidate.rationale }}</p>
            </article>
          </section>

          <section v-if="result.privacy_findings.length" class="result-section">
            <h3>Privacy findings</h3>
            <div class="finding-list">
              <article v-for="(finding, index) in result.privacy_findings" :key="index" class="finding-card">
                <span>{{ String(finding.severity || 'info') }}</span>
                <div>
                  <strong v-if="finding.image_id">{{ imageName(String(finding.image_id)) }}</strong>
                  <p>{{ String(finding.summary || finding.type) }}</p>
                </div>
              </article>
            </div>
          </section>

          <section v-if="result.private_lens_readings.length" class="result-section private-lens-results">
            <p class="eyebrow">Runtime-only extension</p>
            <h3>Private Lens Tool</h3>
            <article v-for="reading in result.private_lens_readings" :key="reading.image_id">
              <div class="private-reading-heading">
                <strong>{{ imageName(reading.image_id) }}</strong>
                <span>{{ reading.technique_references.join(' · ') || 'No technique ID' }}</span>
              </div>
              <p v-for="association in reading.symbolic_associations" :key="association">
                {{ association }}
              </p>
              <small>Symbolic course context only—not a factual or sensitive-trait inference.</small>
            </article>
          </section>

          <section v-if="result.memory_proposal" class="memory-proposal">
            <div>
              <p class="eyebrow">Permission required</p>
              <h3>Save a reusable correction?</h3>
              <p>“{{ result.memory_proposal.text }}”</p>
            </div>
            <div v-if="result.memory_proposal.status === 'pending'" class="proposal-actions">
              <button type="button" class="secondary-button" @click="decideMemory(result.memory_proposal, 'reject')">Skip</button>
              <button type="button" class="primary-button" @click="decideMemory(result.memory_proposal, 'approve')">Approve memory</button>
            </div>
            <span v-else class="status-label">{{ result.memory_proposal.status }}</span>
          </section>

          <section class="result-section report-copy">
            <h3>Full report</h3>
            <SafeMarkdown :source="initialReportMarkdown || result.report_markdown" />
          </section>

          <section class="result-section conversation-section">
            <div class="conversation-heading">
              <div>
                <p class="eyebrow">Same-thread context</p>
                <h3>Continue the conversation</h3>
              </div>
              <span>{{ followUpTurns }} follow-up {{ followUpTurns === 1 ? 'turn' : 'turns' }}</span>
            </div>

            <div class="conversation-list" aria-live="polite">
              <p v-if="!followUpMessages.length" class="muted-copy">
                The original request and full report are shown above. Follow-up turns appear here.
              </p>
              <article
                v-for="(message, index) in followUpMessages"
                :key="`${message.created_at}-${index}`"
                class="conversation-message"
                :class="message.role"
              >
                <div class="message-meta">
                  <strong>{{ message.role === 'user' ? 'You' : 'XiangLens' }}</strong>
                  <small>{{ message.role === 'user' ? `Turn ${Math.floor(index / 2) + 2}` : 'Cached-analysis response' }}</small>
                </div>
                <p v-if="message.role === 'user'">{{ message.content }}</p>
                <SafeMarkdown v-else :source="message.content" />
              </article>
            </div>

            <form class="follow-up-form" @submit.prevent="sendFollowUp">
              <label for="follow-up-message">Ask a follow-up in this thread</label>
              <textarea
                id="follow-up-message"
                v-model="followUpMessage"
                rows="3"
                maxlength="4000"
                placeholder="Why is Candidate A safer? Reconsider the same images for LinkedIn."
                @keydown.ctrl.enter.prevent="sendFollowUp"
              />
              <div>
                <small>Reuses verified analysis; the vision model is not called again. Ctrl + Enter to send.</small>
                <button class="primary-button" type="submit" :disabled="!canFollowUp">
                  {{ analyzing ? 'Agent running…' : 'Send follow-up' }}
                </button>
              </div>
            </form>
          </section>
        </template>
      </section>

      <aside class="panel evidence-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">03 · Trace</p>
            <h2>Agent evidence</h2>
          </div>
        </div>

        <section v-if="plan.length" class="side-section">
          <h3>Bounded plan</h3>
          <ol class="plan-list">
            <li v-for="step in plan" :key="step">{{ step }}</li>
          </ol>
        </section>

        <section class="side-section">
          <h3>Workflow</h3>
          <ol class="trace-list">
            <li v-for="(trace, index) in events" :key="`${trace.node}-${index}`">
              <span :class="trace.status" />
              <div><strong>{{ trace.node.replaceAll('_', ' ') }}</strong><small>{{ trace.summary }}</small></div>
              <em>{{ formatDuration(trace.duration_ms) }}</em>
            </li>
          </ol>
          <p v-if="!events.length" class="muted-copy">Node events will appear while the agent runs.</p>
        </section>

        <section class="side-section">
          <h3>Retrieved sources</h3>
          <a
            v-for="card in result?.evidence || []"
            :key="card.card_id"
            class="evidence-link"
            :href="card.source_url"
            target="_blank"
            rel="noreferrer"
          >
            <span>{{ card.pack.replaceAll('_', ' ') }}</span>
            <strong>{{ card.source_title }}</strong>
            <small>{{ card.text }}</small>
          </a>
          <p v-if="!result?.evidence.length" class="muted-copy">No evidence has been retrieved yet.</p>
        </section>

        <section class="side-section memory-list">
          <div class="section-title-row">
            <h3>Approved memory</h3>
            <button type="button" @click="loadMemories">Refresh</button>
          </div>
          <article v-for="memory in memories" :key="memory.id">
            <div class="memory-heading">
              <span>{{ memory.memory_type }}</span>
              <button type="button" @click="deleteMemory(memory.id)">Delete</button>
            </div>
            <p>{{ memory.text }}</p>
          </article>
          <p v-if="!memories.length" class="muted-copy">Nothing is stored in long-term memory.</p>
          <button class="danger-button" type="button" :disabled="previewMode" @click="forgetMe">Forget all private state</button>
        </section>

        <section class="runtime-card">
          <span>Inference ownership</span>
          <strong>{{ system.inference_ownership }}</strong>
          <small>{{ system.model_endpoint }}</small>
        </section>
      </aside>
    </main>
  </div>
</template>

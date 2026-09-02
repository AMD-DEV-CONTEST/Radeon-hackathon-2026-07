import { API_PATHS } from './paths'
import { ApiError, mapError, NETWORK_ERROR_STATUS } from './errors'
import type {
  LoginRequest,
  TokenResponse,
  UserProfile,
  Project,
  ProjectCreate,
  ProjectOverview,
  RunProgress,
  RunState,
  ProjectFileEntry,
  UploadResult,
  TaskRecord,
  TaskCreate,
  TaskUpdate,
  TaskStatusTransition,
  TaskChangeRecord,
  ConfirmationRecord,
  ConfirmationAction,
  TaskImportDiff,
  TaskImportResult,
  OperationAuditRecord,
  TaskExtractionRequest,
  TaskExtractionResult,
  RiskCenterEntry, RiskAssignmentRequest, RiskLifecycleUpdate,
  ReportDraftEntry, ReportDraftCreate, ReportDraftUpdate, ReportApprovalRequest, ReportApprovalEntry,
  ProjectMemberEntry, ProjectMemberAdd, CommentCreate, CommentEntry, NotificationEntry,
  ScmPreviewRequest, ScmPreviewResponse, IntegrationExecutionResult, AdminHealth, QueueMetrics, CacheMetrics, BackupEntry,
} from './dto'

export interface ApiClientOptions {
  /** Base URL prepended to every request path. Empty string = same-origin. */
  baseUrl?: string
  /** Request timeout in milliseconds. */
  timeoutMs?: number
  /** Returns the current Bearer token, or null when unauthenticated. */
  getToken?: () => string | null
  /** Injectable fetch (mainly for tests). Defaults to global fetch. */
  fetchImpl?: typeof fetch
}

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

/**
 * Unified API client for the workbench.
 *
 * Responsibilities (UI-0 acceptance):
 *  - Prefix every request with `baseUrl`.
 *  - Attach `Authorization: Bearer <token>` when a token is available.
 *  - Enforce a request timeout (AbortController) and translate aborts into a
 *    network `ApiError`.
 *  - Map HTTP status (401/403/404/409/422/5xx) and network failures into a
 *    single `ApiError` with a user-readable message.
 */
export class ApiClient {
  readonly baseUrl: string
  readonly timeoutMs: number
  private readonly getToken: () => string | null
  private readonly fetchImpl: typeof fetch

  constructor(opts: ApiClientOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? '').replace(/\/+$/, '')
    this.timeoutMs = opts.timeoutMs ?? 15000
    this.getToken = opts.getToken ?? (() => null)
    this.fetchImpl = opts.fetchImpl ?? ((...a: Parameters<typeof fetch>) => fetch(...a))
  }

  private buildHeaders(json = true): Record<string, string> {
    const headers: Record<string, string> = {}
    if (json) headers['Content-Type'] = 'application/json'
    const token = this.getToken()
    // SECURITY: the token is read from storage and sent over the wire only.
    // It is never written to console, logs, or anywhere else.
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    return headers
  }

  private async request<T>(
    method: HttpMethod,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeoutMs)

    let response: Response
    try {
      response = await this.fetchImpl(url, {
        method,
        headers: this.buildHeaders(),
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      })
    } catch {
      clearTimeout(timer)
      throw new ApiError(NETWORK_ERROR_STATUS, {
        message: 'Network request failed. Please check your connection.',
      })
    } finally {
      clearTimeout(timer)
    }

    if (!response.ok) {
      let parsed: unknown = null
      try {
        parsed = await response.json()
      } catch {
        // body may be empty or non-JSON; fall back to status-only mapping
      }
      throw mapError(response.status, parsed)
    }

    if (response.status === 204) {
      return undefined as T
    }
    try {
      return (await response.json()) as T
    } catch {
      return undefined as T
    }
  }

  private async requestBlob(path: string): Promise<{ blob: Blob; filename: string }> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeoutMs)
    let response: Response
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method: 'GET',
        headers: this.buildHeaders(false),
        signal: controller.signal,
      })
    } catch {
      throw new ApiError(NETWORK_ERROR_STATUS, {
        message: 'Network request failed. Please check your connection.',
      })
    } finally {
      clearTimeout(timer)
    }
    if (!response.ok) {
      let parsed: unknown = null
      try {
        parsed = await response.json()
      } catch {
        // The error response may be an empty file response.
      }
      throw mapError(response.status, parsed)
    }
    const disposition = response.headers.get('content-disposition') ?? ''
    const filename = /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? 'artifact'
    return { blob: await response.blob(), filename }
  }

  private async requestForm<T>(path: string, form: FormData): Promise<T> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeoutMs)
    let response: Response
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method: 'POST', headers: this.buildHeaders(false), body: form, signal: controller.signal,
      })
    } catch {
      throw new ApiError(NETWORK_ERROR_STATUS, { message: 'Network request failed. Please check your connection.' })
    } finally {
      clearTimeout(timer)
    }
    if (!response.ok) {
      let parsed: unknown = null
      try { parsed = await response.json() } catch { /* status-only fallback */ }
      throw mapError(response.status, parsed)
    }
    return (await response.json()) as T
  }

  // ----- Auth -----

  login(req: LoginRequest): Promise<TokenResponse> {
    return this.request<TokenResponse>('POST', API_PATHS.login, req)
  }

  getMe(): Promise<UserProfile> {
    return this.request<UserProfile>('GET', API_PATHS.me)
  }

  // ----- Projects -----

  listProjects(): Promise<Project[]> {
    return this.request<Project[]>('GET', API_PATHS.projects)
  }

  createProject(body: ProjectCreate): Promise<Project> {
    return this.request<Project>('POST', API_PATHS.projects, body)
  }

  getProject(projectId: string): Promise<Project> {
    return this.request<Project>('GET', API_PATHS.projectDetail(projectId))
  }

  getOverview(projectId: string): Promise<ProjectOverview> {
    return this.request<ProjectOverview>('GET', API_PATHS.overview(projectId))
  }

  // ----- Project files -----

  listProjectFiles(projectId: string): Promise<ProjectFileEntry[]> {
    return this.request('GET', API_PATHS.files(projectId))
  }

  uploadProjectFile(projectId: string, file: File, taskFile = false): Promise<UploadResult> {
    const form = new FormData()
    form.append('file', file, file.name)
    form.append('task_file', String(taskFile))
    return this.requestForm(API_PATHS.files(projectId), form)
  }

  downloadProjectFile(projectId: string, relativePath: string): Promise<{ blob: Blob; filename: string }> {
    const sourcePrefix = 'source/'
    const filename = relativePath.startsWith(sourcePrefix) ? relativePath.slice(sourcePrefix.length) : relativePath
    return this.requestBlob(API_PATHS.downloadFile(projectId, filename))
  }

  // ----- Runs -----

  listRuns(projectId: string): Promise<RunState[]> {
    return this.request('GET', API_PATHS.runs(projectId))
  }

  getRun(projectId: string, runId: string): Promise<RunState> {
    return this.request('GET', API_PATHS.runDetail(projectId, runId))
  }

  getRunProgress(projectId: string, runId: string): Promise<RunProgress> {
    return this.request('GET', API_PATHS.runProgress(projectId, runId))
  }

  createRun(projectId: string): Promise<RunState> {
    return this.request('POST', API_PATHS.runs(projectId))
  }

  executeRun(projectId: string, runId: string): Promise<RunState> {
    return this.request('POST', API_PATHS.executeRun(projectId, runId))
  }

  cancelRun(projectId: string, runId: string): Promise<RunState> {
    return this.request('DELETE', API_PATHS.runDetail(projectId, runId))
  }

  retryRun(projectId: string, runId: string): Promise<RunState> {
    return this.request('POST', API_PATHS.retryRun(projectId, runId))
  }

  downloadRunArtifact(
    projectId: string,
    runId: string,
    artifactName: string,
  ): Promise<{ blob: Blob; filename: string }> {
    return this.requestBlob(API_PATHS.runArtifact(projectId, runId, artifactName))
  }

  // ----- Tasks (UI-2: task workbench & human confirmation) -----

  listTasks(projectId: string, status?: string): Promise<TaskRecord[]> {
    const query = status ? `?status=${encodeURIComponent(status)}` : ''
    return this.request('GET', `${API_PATHS.tasks(projectId)}${query}`)
  }

  getTask(projectId: string, taskId: string): Promise<TaskRecord> {
    return this.request('GET', API_PATHS.taskDetail(projectId, taskId))
  }

  createTask(projectId: string, body: TaskCreate): Promise<TaskRecord> {
    return this.request('POST', API_PATHS.tasks(projectId), body)
  }

  updateTask(projectId: string, taskId: string, body: TaskUpdate): Promise<TaskRecord> {
    return this.request('PATCH', API_PATHS.taskDetail(projectId, taskId), body)
  }

  /** Request a status change. The SERVER decides validity; invalid moves
   * surface as ApiError (TASK_INVALID_TRANSITION / TASK_CANCELLED_FINAL). */
  transitionTask(
    projectId: string,
    taskId: string,
    body: TaskStatusTransition,
  ): Promise<TaskRecord> {
    return this.request('POST', API_PATHS.taskTransition(projectId, taskId), body)
  }

  getTaskHistory(projectId: string, taskId: string): Promise<TaskChangeRecord[]> {
    return this.request('GET', API_PATHS.taskHistory(projectId, taskId))
  }

  listConfirmationQueue(
    projectId: string,
    status?: 'pending' | 'accepted' | 'ignored',
  ): Promise<ConfirmationRecord[]> {
    const query = status ? `?status=${encodeURIComponent(status)}` : ''
    return this.request('GET', `${API_PATHS.taskConfirmationQueue(projectId)}${query}`)
  }

  processConfirmation(
    projectId: string,
    taskId: string,
    body: ConfirmationAction,
  ): Promise<ConfirmationRecord> {
    return this.request('POST', API_PATHS.taskConfirmation(projectId, taskId), body)
  }

  getTaskAuditLog(projectId: string, limit = 100): Promise<OperationAuditRecord[]> {
    return this.request('GET', `${API_PATHS.taskAuditLog(projectId)}?limit=${limit}`)
  }

  extractTasks(projectId: string, body: TaskExtractionRequest): Promise<TaskExtractionResult> {
    return this.request('POST', API_PATHS.taskExtract(projectId), body)
  }

  submitCandidates(
    projectId: string,
    body: TaskExtractionResult,
  ): Promise<ConfirmationRecord[]> {
    return this.request('POST', API_PATHS.taskSubmitCandidates(projectId), body)
  }

  /** Dry-run preview of a CSV/XLSX import — nothing is persisted server-side. */
  previewTaskImport(projectId: string, file: File): Promise<TaskImportDiff> {
    const form = new FormData()
    form.append('file', file, file.name)
    return this.requestForm(API_PATHS.taskImportPreview(projectId), form)
  }

  confirmTaskImport(
    projectId: string,
    file: File,
    skipDuplicates = true,
    overwriteConflicts = false,
  ): Promise<TaskImportResult> {
    const form = new FormData()
    form.append('file', file, file.name)
    form.append('skip_duplicates', String(skipDuplicates))
    form.append('overwrite_conflicts', String(overwriteConflicts))
    return this.requestForm(API_PATHS.taskImportConfirm(projectId), form)
  }

  // ----- Risks, reports, and project discussion (UI-3) -----

  listRisks(projectId: string, severity?: string, lifecycle?: string): Promise<RiskCenterEntry[]> {
    const query = new URLSearchParams()
    if (severity) query.set('severity', severity)
    if (lifecycle) query.set('lifecycle', lifecycle)
    return this.request('GET', `${API_PATHS.risks(projectId)}${query.size ? `?${query}` : ''}`)
  }

  assignRisk(projectId: string, riskId: string, body: RiskAssignmentRequest): Promise<Record<string, string>> {
    return this.request('PUT', API_PATHS.riskAssign(projectId, riskId), body)
  }

  updateRiskLifecycle(projectId: string, riskId: string, body: RiskLifecycleUpdate): Promise<Record<string, string>> {
    return this.request('PUT', API_PATHS.riskLifecycle(projectId, riskId), body)
  }

  listReportDrafts(projectId: string, status?: string): Promise<ReportDraftEntry[]> {
    return this.request('GET', `${API_PATHS.reports(projectId)}${status ? `?status=${encodeURIComponent(status)}` : ''}`)
  }

  createReportDraft(projectId: string, body: ReportDraftCreate): Promise<ReportDraftEntry> {
    return this.request('POST', API_PATHS.reports(projectId), body)
  }

  updateReportDraft(projectId: string, draftId: string, body: ReportDraftUpdate): Promise<ReportDraftEntry> {
    return this.request('PUT', API_PATHS.reportDetail(projectId, draftId), body)
  }

  submitReport(projectId: string, draftId: string): Promise<ReportDraftEntry> {
    return this.request('POST', API_PATHS.reportSubmit(projectId, draftId))
  }

  decideReport(projectId: string, draftId: string, body: ReportApprovalRequest): Promise<ReportDraftEntry> {
    return this.request('POST', API_PATHS.reportApprove(projectId, draftId), body)
  }

  getReportApprovals(projectId: string, draftId: string): Promise<ReportApprovalEntry[]> {
    return this.request('GET', API_PATHS.reportApprovals(projectId, draftId))
  }

  downloadReport(projectId: string, draftId: string, format: 'pdf' | 'docx'): Promise<{ blob: Blob; filename: string }> {
    return this.requestBlob(format === 'pdf' ? API_PATHS.reportPdf(projectId, draftId) : API_PATHS.reportDocx(projectId, draftId))
  }

  listMembers(projectId: string): Promise<ProjectMemberEntry[]> {
    return this.request('GET', API_PATHS.members(projectId))
  }

  addMember(projectId: string, body: ProjectMemberAdd): Promise<ProjectMemberEntry> {
    return this.request('POST', API_PATHS.members(projectId), body)
  }

  updateMemberRole(projectId: string, userId: string, body: ProjectMemberAdd): Promise<ProjectMemberEntry> {
    return this.request('PUT', API_PATHS.memberDetail(projectId, userId), body)
  }

  removeMember(projectId: string, userId: string): Promise<void> {
    return this.request('DELETE', API_PATHS.memberDetail(projectId, userId))
  }

  listComments(projectId: string, entityType: string, entityId: string): Promise<CommentEntry[]> {
    return this.request('GET', `${API_PATHS.comments(projectId)}?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}`)
  }

  createComment(projectId: string, body: CommentCreate): Promise<CommentEntry> {
    return this.request('POST', API_PATHS.comments(projectId), body)
  }

  listNotifications(unreadOnly = false, limit = 50): Promise<NotificationEntry[]> {
    return this.request('GET', `${API_PATHS.notifications}?unread_only=${unreadOnly}&limit=${limit}`)
  }

  markNotificationRead(notificationId: string): Promise<NotificationEntry> {
    return this.request('PUT', API_PATHS.notificationRead(notificationId))
  }

  markAllNotificationsRead(): Promise<{ marked_read: number }> {
    return this.request('PUT', API_PATHS.notificationReadAll)
  }

  // ----- Controlled integrations and system operations (UI-5) -----

  previewScmChange(body: ScmPreviewRequest): Promise<ScmPreviewResponse> {
    return this.request('POST', API_PATHS.scmPreview, body)
  }

  executeScmChange(body: ScmPreviewRequest, confirmationId: string): Promise<IntegrationExecutionResult> {
    return this.request('POST', API_PATHS.scmExecute, { ...body, confirmation_id: confirmationId })
  }

  getAdminHealth(): Promise<AdminHealth> {
    return this.request('GET', API_PATHS.monitorHealth)
  }

  getAdminQueue(): Promise<QueueMetrics> {
    return this.request('GET', API_PATHS.monitorQueue)
  }

  getAdminCache(): Promise<CacheMetrics> {
    return this.request('GET', API_PATHS.monitorCache)
  }

  listBackups(): Promise<BackupEntry[]> {
    return this.request('GET', API_PATHS.adminBackups)
  }

  invalidateCache(body: { project_id?: string; category?: 'index' | 'embedding' | 'report'; key_prefix?: string }): Promise<{ removed: number }> {
    return this.request('POST', API_PATHS.monitorInvalidateCache, body)
  }
}

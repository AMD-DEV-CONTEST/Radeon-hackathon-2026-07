import type {VisualAnalysis} from '../types';

export type AIAction =
  | 'send_message'
  | 'attach_asset'
  | 'confirm_plan'
  | 'select_candidate'
  | 'finalize'
  | 'download_final'
  | 'refresh'
  | 'cancel';

export interface AISessionMessage {
  messageId: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  createdAt: string;
}

export interface AISessionBrief {
  event: {
    title: string;
    artist?: string;
    date: string;
    time: string;
    venue: string;
    presalePrice?: string;
    doorPrice?: string;
  };
  branding: {
    artistLogoAssetId?: string;
    eventLogoAssetId?: string;
    sponsorLogoAssetIds?: string[];
  };
  visual: {
    style: string;
    theme: string;
    musicGenre?: string;
    mood?: string[];
    preferredColors?: string[];
    referenceAssetId?: string;
    controlStrength?: number;
  };
}

export interface AIDesignPlan {
  sessionId: string;
  planId: string;
  selected: boolean;
  plan: {
    id: string;
    name: string;
    concept: string;
    palette: string[];
    composition: {
      subject: string;
      symmetry: string;
      titleSafeZone: string;
      informationSafeZone: string;
    };
    composerTemplate: string;
  };
}

export interface AICandidate {
  candidateId: string;
  variantKey: string;
  variantName: string;
  status: string;
  attempt: number;
  seed?: number;
  selected: boolean;
  imageUrl?: string;
  error?: string;
  visualAnalysis?: VisualAnalysis;
  spec?: {
    motif?: string;
    composition?: string;
    camera?: string;
    materials?: string[];
    palette?: string[];
    lighting?: string;
    visualAnalysis?: VisualAnalysis;
  };
}

export interface AISession {
  sessionId: string;
  status: string;
  availableActions: AIAction[];
  brief: AISessionBrief;
  missingFields: string[] | null;
  selectedPlanId?: string;
  posterId?: string;
  error?: string;
  reviewSummary?: {
    finalized: boolean;
    accepted: boolean;
    rounds: number;
    bestRound?: number;
    bestScore?: number;
    latestDecision?: string;
    warning?: string;
  };
  messages: AISessionMessage[];
  plans: AIDesignPlan[] | null;
  assetUsages?: AIAssetUsage[];
  generationStages?: AIGenerationStage[];
  metrics?: AIMetrics;
  capabilities?: Record<string, unknown>;
  assets?: AISessionAsset[] | null;
  poster?: {
    posterId: string;
    status: string;
    selectedCandidateId?: string;
    resultUrl?: string;
    thumbnailUrl?: string;
    candidates: AICandidate[];
    progress: {
      completed: number;
      total: number;
      stage?: string;
      percent?: number;
      elapsedSeconds?: number;
      etaSeconds?: number;
    };
    error?: string;
  };
}

export interface RemoteAsset {
  assetId: string;
  kind: 'person' | 'logo' | 'reference';
  originalName: string;
  contentUrl: string;
  status?: 'uploaded' | 'validating' | 'processing' | 'ready' | 'rejected' | 'failed';
  previewUrl?: string;
  rejectionCode?: string;
  width?: number;
  height?: number;
  processStatus?: string;
  filename?: string;
  sizeBytes?: number;
  sha256?: string;
  createdAt?: string;
  cutout?: {
    status: 'pending' | 'ready' | 'opaque' | 'unsupported' | 'failed';
    hasAlpha?: boolean;
  };
}

export interface AISessionAsset {
  assetId: string;
  purpose: string;
  kind?: RemoteAsset['kind'];
  originalName?: string;
  mimeType?: string;
  width?: number;
  height?: number;
  actuallyUsed?: boolean;
  usedInStage?: string[];
  usageNote?: string;
  processStatus?: string;
  processing?: {
    cutout?: 'queued' | 'running' | 'ready' | 'failed' | 'not_required';
    logoTransparency?: 'queued' | 'running' | 'ready' | 'failed' | 'not_required';
    referenceAnalysis?: 'queued' | 'running' | 'ready' | 'failed' | 'not_required';
    error?: string;
  };
  createdAt?: string;
}

export interface AIAssetUsage {
  assetId: string;
  purpose: string;
  stage?: string;
  used?: boolean;
  status?: string;
  message?: string;
}

export interface AIGenerationStage {
  id?: string;
  key?: string;
  label: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'skipped';
  progress?: number;
  message?: string;
  etaSeconds?: number;
}

export interface AIMetrics {
  gpu?: string;
  model?: string;
  precision?: string;
  rocm?: string;
  workflowVersion?: string;
  coldStartMs?: number;
  inferenceMs?: number;
  peakVramMb?: number;
  latencyMs?: number;
  promptTokens?: number;
  completionTokens?: number;
}

export interface BackendHealth {
  status: string;
  gpu?: {model?: string; vramTotalGB?: number; vramUsedGB?: number};
  comfyui?: {status?: string; workflowVersion?: string};
  vlm?: {status?: string; model?: string; sleeping?: boolean};
}

export interface BackendCapability {
  available: boolean;
  reason?: string;
  influences?: string[];
  controlMode?: string;
  patch?: string;
  strength?: {default?: number; min?: number; max?: number};
}

export interface BackendDependencies {
  status: string;
  capabilities?: {
    backgroundRemoval?: BackendCapability;
    personSimilarityMetric?: BackendCapability;
    referenceImageConditioning?: BackendCapability;
    negativePrompt?: BackendCapability & {cfg?: number; node?: string};
  };
}

const configuredBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)
  ?? (import.meta.env.VITE_API_URL as string | undefined)
  ?? 'http://127.0.0.1:8080';

export const AI_API_BASE_URL = configuredBase.replace(/\/$/, '');

async function fetchWithRetry(input: RequestInfo | URL, init?: RequestInit) {
  let lastError: unknown;
  const method = (init?.method ?? 'GET').toUpperCase();
  const maxAttempts = method === 'GET' || method === 'HEAD' ? 4 : 1;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const timeout = new AbortController();
    // Planning, generation and review can legitimately take several minutes
    // on the remote ROCm worker. Keep one non-idempotent POST alive instead of
    // aborting it and encouraging an accidental duplicate submission.
    const timeoutId = window.setTimeout(() => timeout.abort(), 300_000);
    const signal = init?.signal
      ? AbortSignal.any([init.signal, timeout.signal])
      : timeout.signal;
    try {
      const response = await fetch(input, {...init, signal});
      if ((response.status >= 500 || response.status === 429) && attempt < maxAttempts - 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 700 * (2 ** attempt)));
        continue;
      }
      return response;
    } catch (error) {
      lastError = error;
      if (attempt < maxAttempts - 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 700 * (2 ** attempt)));
      }
    } finally {
      window.clearTimeout(timeoutId);
    }
  }
  throw lastError instanceof Error ? lastError : new Error('StagePoster API 暂时不可用');
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetchWithRetry(`${AI_API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.body ? {'Content-Type': 'application/json'} : {}),
      ...init.headers,
    },
  });
  const body = await response.json().catch(() => null) as {error?: string} | null;
  if (!response.ok) {
    throw new Error(body?.error || `StagePoster API 请求失败（HTTP ${response.status}）`);
  }
  return body as T;
}

export function absoluteAIImageUrl(path?: string): string | undefined {
  if (!path) return undefined;
  if (/^https?:\/\//i.test(path)) return path;
  return `${AI_API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

export const aiSessionApi = {
  health: () => request<BackendHealth>('/health'),
  dependencies: () => request<BackendDependencies>('/api/system/dependencies'),
  create: (brief?: AISessionBrief, assets?: {assetId: string; purpose: string}[]) => request<AISession>('/api/ai/sessions', {
    method: 'POST',
    body: JSON.stringify({brief: brief ?? {
      event: {title: '', date: '', time: '', venue: ''},
      branding: {},
      visual: {style: '', theme: ''},
    }, ...(assets?.length ? {assets} : {})}),
  }),
  get: (sessionId: string) => request<AISession>(`/api/ai/sessions/${sessionId}`),
  async sendMessage(sessionId: string, content: string) {
    const response = await request<{session: AISession; metrics?: AIMetrics}>(`/api/ai/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify({content}),
    });
    return response.metrics
      ? {...response.session, metrics: {...response.session.metrics, ...response.metrics}}
      : response.session;
  },
  async uploadAsset(blob: Blob, filename: string, kind: RemoteAsset['kind']) {
    let lastError = '';
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const form = new FormData();
      form.append('file', blob, filename);
      form.append('kind', kind);
      const response = await fetchWithRetry(`${AI_API_BASE_URL}/api/assets`, {method: 'POST', body: form});
      const body = await response.json().catch(() => null) as (RemoteAsset & {error?: string}) | null;
      if (response.ok) return body as RemoteAsset;
      lastError = body?.error || `素材上传失败（HTTP ${response.status}）`;
      const transientUploadTimeout = /timeout|temporar|connection/i.test(lastError);
      if (!transientUploadTimeout || attempt === 1) break;
      await new Promise((resolve) => window.setTimeout(resolve, 1200));
    }
    throw new Error(lastError);
  },
  getAsset: (assetId: string) => request<RemoteAsset>(`/api/assets/${encodeURIComponent(assetId)}`),
  bindAssets: (sessionId: string, assets: {assetId: string; purpose: string}[]) => request<AISession>(
    `/api/ai/sessions/${sessionId}/assets`,
    {method: 'POST', body: JSON.stringify({assets})},
  ),
  confirmPlan: (sessionId: string, planId: string) => request<AISession>(
    `/api/ai/sessions/${sessionId}/plans/${encodeURIComponent(planId)}/confirm`,
    {method: 'POST', body: JSON.stringify({})},
  ),
  selectCandidate: (sessionId: string, candidateId: string) => request<AISession>(
    `/api/ai/sessions/${sessionId}/candidates/${encodeURIComponent(candidateId)}/select`,
    {method: 'POST', body: JSON.stringify({})},
  ),
  finalize: (sessionId: string) => request<AISession>(`/api/ai/sessions/${sessionId}/finalize`, {
    method: 'POST',
    body: JSON.stringify({}),
  }),
  cancel: (sessionId: string) => request<AISession>(`/api/ai/sessions/${sessionId}/cancel`, {
    method: 'POST',
    body: JSON.stringify({}),
  }),
  retryFinalize: (sessionId: string) => request<AISession>(`/api/ai/sessions/${sessionId}/finalize`, {
    method: 'POST',
    body: JSON.stringify({}),
  }),
  async retryCandidate(sessionId: string, posterId: string, candidateId: string) {
    await request(`/api/posters/${encodeURIComponent(posterId)}/candidates/${encodeURIComponent(candidateId)}/retry`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
    return request<AISession>(`/api/ai/sessions/${sessionId}`);
  },
};

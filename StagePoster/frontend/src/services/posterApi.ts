import type {
  GenerationCandidate,
  GenerationTask,
  PosterReview,
  PosterTimeline,
  PosterProject,
  RuntimeEvidence,
  UploadedAsset,
} from '../types';
import {formatPosterLocation} from '../utils/posterLanguage';

const BASE = ((import.meta.env.VITE_API_BASE_URL as string | undefined)
  ?? (import.meta.env.VITE_API_URL as string | undefined)
  ?? 'http://127.0.0.1:8080').replace(/\/$/, '');
const TOKEN = (import.meta.env.VITE_POSTER_TOKEN as string | undefined) ?? '';

const metrics = {
  gpu: 'AMD Radeon Pro W7900',
  rocm: '远程 GPU 节点',
  resolution: '1024 × 1536',
  duration: 'W7900 推理中…',
  peakVram: '由 GPU 服务管理',
};

interface RemoteAsset {
  assetId: string;
}

interface PosterResponse {
  posterId: string;
  status: string;
  resultUrl?: string;
  error?: string;
  progress?: {
    completed?: number;
    total?: number;
    stage?: string;
    percent?: number;
    elapsedSeconds?: number;
    etaSeconds?: number;
  };
  candidates?: GenerationCandidate[];
  selectedCandidateId?: string;
}

function authHeaders(): Record<string, string> {
  return TOKEN ? {'X-Poster-Token': TOKEN} : {};
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase();
  const attempts = method === 'GET' || method === 'HEAD' ? 3 : 1;
  let lastError: unknown;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 300_000);
    try {
      const response = await fetch(`${BASE}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          Accept: 'application/json',
          ...authHeaders(),
          ...init.headers,
        },
      });
      const body = await response.json().catch(() => null) as ({error?: string} & T) | null;
      if (response.ok) return body as T;
      throw new Error(body?.error || `StagePoster API ${response.status}`);
    } catch (error) {
      lastError = error;
      if (attempt < attempts - 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 700 * (attempt + 1)));
      }
    } finally {
      window.clearTimeout(timer);
    }
  }
  throw lastError instanceof Error ? lastError : new Error('StagePoster API 暂时不可用');
}

async function uploadBlob(asset: UploadedAsset): Promise<Blob> {
  const response = await fetch(asset.dataUrl);
  const source = await response.blob();
  if (source.type === 'image/png' || source.type === 'image/jpeg') return source;
  const image = new Image();
  image.src = asset.dataUrl;
  await image.decode();
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, image.naturalWidth || 1024);
  canvas.height = Math.max(1, image.naturalHeight || 1024);
  const context = canvas.getContext('2d');
  if (!context) throw new Error('无法准备素材上传');
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('素材转码失败')), 'image/png');
  });
}

async function uploadAsset(projectId: string, asset: UploadedAsset, kind: 'logo' | 'reference') {
  const cacheKey = `poster-remote-assets:${projectId}`;
  const cache = JSON.parse(localStorage.getItem(cacheKey) ?? '{}') as Record<string, string>;
  if (cache[asset.id]) return cache[asset.id];
  const form = new FormData();
  form.append('file', await uploadBlob(asset), asset.name.replace(/\.[^.]+$/, '.png'));
  form.append('kind', kind);
  const uploaded = await request<RemoteAsset>('/api/assets', {method: 'POST', body: form});
  cache[asset.id] = uploaded.assetId;
  localStorage.setItem(cacheKey, JSON.stringify(cache));
  return uploaded.assetId;
}

function posterTask(projectId: string, response: PosterResponse, startedAt: number): GenerationTask {
  const complete = response.status === 'succeeded';
  const failed = response.status === 'failed' || response.status === 'canceled';
  const progress = response.progress?.percent ?? (complete ? 100 : 20);
  const step = complete ? 5 : progress >= 65 ? 3 : progress >= 60 ? 2 : 1;
  return {
    id: response.posterId,
    projectId,
    step,
    progress,
    status: failed ? 'failed' : complete ? 'complete' : 'running',
    startedAt,
    metrics: {
      ...metrics,
      duration: complete
        ? `${response.progress?.elapsedSeconds ?? Math.round((Date.now() - startedAt) / 1000)} s · W7900`
        : 'W7900 推理中…',
    },
    outputUrl: complete ? `${BASE}${response.resultUrl ?? `/api/posters/${response.posterId}/result`}` : undefined,
    error: failed ? response.error ?? `任务已${response.status === 'canceled' ? '取消' : '失败'}` : undefined,
    source: 'w7900',
    remoteStatus: response.progress?.stage ?? response.status,
    candidates: response.candidates ?? [],
    elapsedSeconds: response.progress?.elapsedSeconds,
    etaSeconds: response.progress?.etaSeconds,
    selectedCandidateId: response.selectedCandidateId,
  };
}

const styleColors: Record<string, string[]> = {
  rock: ['oxide red', 'ink black', 'dirty bone white'],
  cyber: ['electric cyan', 'deep violet', 'ink black'],
  editorial: ['warm off-white', 'charcoal', 'muted rust'],
};

export const posterApi = {
  health: () => request<RuntimeEvidence & {tokenRequired?: boolean}>('/health'),
  dependencies: () => request<{status?: string; dependencies?: Record<string, {status?: string; model?: string}>; capabilities?: Record<string, {available?: boolean; reason?: string; influences?: string[]; controlMode?: string}>}>('/api/system/dependencies'),
  timeline: (posterId: string) => request<PosterTimeline>(`/api/posters/${encodeURIComponent(posterId)}/timeline`),
  reviews: async (posterId: string) => {
    const response = await request<{items?: PosterReview[]; reviews?: PosterReview[]}>(`/api/posters/${encodeURIComponent(posterId)}/reviews?limit=20&offset=0`);
    return response.items ?? response.reviews ?? [];
  },

  async submit(project: PosterProject): Promise<GenerationTask> {
    const referenceAssetId = project.assets.reference
      ? await uploadAsset(project.id, project.assets.reference, 'reference')
      : undefined;
    const artistLogo = project.bands.find((band) => band.logo)?.logo;
    const artistLogoAssetId = artistLogo
      ? await uploadAsset(project.id, artistLogo, 'logo')
      : undefined;
    const eventLogoAssetId = project.assets.organizerLogo
      ? await uploadAsset(project.id, project.assets.organizerLogo, 'logo')
      : undefined;
    const [date = '', time = ''] = project.dateTime.trim().split(/\s+/, 2);
    const payload = {
      event: {
        title: project.title,
        artist: project.bands.map((band) => band.name).filter(Boolean).join(' & ') || project.subject,
        date,
        time,
        venue: formatPosterLocation(project.city, project.venue),
        presalePrice: project.price,
      },
      visual: {
        style: 'metal-gothic-v1',
        theme: project.theme,
        musicGenre: project.bands.map((band) => band.genre).filter(Boolean).join(' / '),
        mood: [project.theme, project.subject].filter(Boolean),
        preferredColors: styleColors[project.styleId] ?? styleColors.rock,
        ...(referenceAssetId ? {referenceAssetId, controlStrength: 0.35} : {}),
      },
      branding: {
        ...(artistLogoAssetId ? {artistLogoAssetId} : {}),
        ...(eventLogoAssetId ? {eventLogoAssetId} : {}),
      },
    };
    const startedAt = Date.now();
    const created = await request<PosterResponse>('/api/posters', {
      method: 'POST',
      headers: {'Content-Type': 'application/json; charset=utf-8'},
      body: JSON.stringify(payload),
    });
    return posterTask(project.id, created, startedAt);
  },

  async getPoster(task: GenerationTask): Promise<GenerationTask> {
    const response = await request<PosterResponse>(`/api/posters/${encodeURIComponent(task.id)}`);
    return posterTask(task.projectId, response, task.startedAt);
  },

  async selectCandidate(task: GenerationTask, candidateId: string): Promise<GenerationTask> {
    const response = await request<PosterResponse>(`/api/posters/${encodeURIComponent(task.id)}/select`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json; charset=utf-8'},
      body: JSON.stringify({candidateId}),
    });
    return posterTask(task.projectId, response, task.startedAt);
  },

  async cancel(task: GenerationTask): Promise<GenerationTask> {
    const response = await request<PosterResponse>(`/api/posters/${encodeURIComponent(task.id)}/cancel`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json; charset=utf-8'},
      body: JSON.stringify({}),
    });
    return posterTask(task.projectId, response, task.startedAt);
  },

  async retryCandidate(task: GenerationTask, candidateId: string): Promise<GenerationTask> {
    const response = await request<PosterResponse>(`/api/posters/${encodeURIComponent(task.id)}/candidates/${encodeURIComponent(candidateId)}/retry`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json; charset=utf-8'},
      body: JSON.stringify({}),
    });
    return posterTask(task.projectId, response, task.startedAt);
  },

  async resultBlob(task: GenerationTask) {
    const selectedVisual = task.candidates?.find((candidate) => candidate.selected && candidate.imageUrl)
      ?? task.candidates?.find((candidate) => candidate.status === 'ready' && candidate.imageUrl);
    const path = selectedVisual?.imageUrl
      ? (/^https?:\/\//i.test(selectedVisual.imageUrl) ? selectedVisual.imageUrl : `${BASE}${selectedVisual.imageUrl}`)
      : `${BASE}/api/posters/${encodeURIComponent(task.id)}/result`;
    const response = await fetch(path, {
      headers: authHeaders(),
    });
    if (!response.ok) throw new Error(`Result ${response.status}`);
    return response.blob();
  },

  async imageMetadata(task: GenerationTask) {
    const blob = await this.resultBlob(task);
    const url = URL.createObjectURL(blob);
    try {
      const image = new Image();
      image.src = url;
      await image.decode();
      const divisor = greatestCommonDivisor(image.naturalWidth, image.naturalHeight);
      return {width: image.naturalWidth, height: image.naturalHeight, format: blob.type || 'image/png', sizeBytes: blob.size, aspectRatio: `${image.naturalWidth / divisor}:${image.naturalHeight / divisor}`};
    } finally {
      URL.revokeObjectURL(url);
    }
  },

  resultUrl: (posterId: string) => `${BASE}/api/posters/${encodeURIComponent(posterId)}/result`,
  imageUrl: (path?: string) => path ? (/^https?:\/\//i.test(path) ? path : `${BASE}${path}`) : undefined,
};

function greatestCommonDivisor(a: number, b: number): number {
  let left = Math.abs(a);
  let right = Math.abs(b);
  while (right) [left, right] = [right, left % right];
  return left || 1;
}

export function localMockTask(projectId: string): GenerationTask {
  return {
    id: projectId,
    projectId,
    step: 0,
    progress: 4,
    status: 'running',
    startedAt: Date.now(),
    metrics: {gpu: '浏览器本地 Mock', rocm: '未连接', resolution: '1024 × 1536', duration: '本地 Mock', peakVram: '—'},
    source: 'local',
  };
}

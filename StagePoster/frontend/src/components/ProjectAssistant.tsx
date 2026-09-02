import {useEffect, useMemo, useRef, useState} from 'react';
import {Bot, Check, CheckCircle2, CornerDownLeft, Download, LoaderCircle, Maximize2, RefreshCw, Send, Sparkles, UserRound, X} from 'lucide-react';
import {toPng} from 'html-to-image';
import {useNavigate} from 'react-router-dom';
import type {GenerationTask, Participant, PosterProject, UploadedAsset} from '../types';
import {useStore} from '../store';
import {
  absoluteAIImageUrl,
  aiSessionApi,
  type AISession,
  type AISessionBrief,
  type BackendDependencies,
  type BackendHealth,
} from '../services/aiSessionApi';
import AssetUpload from './AssetUpload';
import PosterLanguageToggle from './PosterLanguageToggle';
import PublishPoster from './PublishPoster';
import {formatPosterLocation, localizedPosterCopy} from '../utils/posterLanguage';
import {useSiteLanguage} from '../hooks/useSiteLanguage';

export type ProjectDraft = Partial<Omit<PosterProject, 'bands'>> & {bands?: Participant[]};

const fieldLabels: Record<string, string> = {
  'event.title': '活动标题', 'event.artist': '艺人 / 乐队', 'event.date': '日期',
  'event.time': '时间', 'event.venue': '场地', 'visual.style': '视觉风格',
  'visual.theme': '视觉主题', 'visual.musicGenre': '音乐类型', 'visual.mood': '情绪关键词',
};

function extractEnglishTitle(content: string) {
  return content.match(/(?:英文标题|English title)\s*[:：]\s*([A-Za-z0-9][A-Za-z0-9 '&.-]{2,})(?=[。；，,\n]|$)/i)?.[1]?.trim();
}

async function renderPublishPng(node: HTMLElement): Promise<string> {
  const width = Math.max(node.getBoundingClientRect().width, 1);
  const source = await toPng(node, {
    pixelRatio: Math.max(2, 1024 / width),
    cacheBust: false,
  });

  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = 1024;
      canvas.height = 1536;
      const context = canvas.getContext('2d');
      if (!context) {
        reject(new Error('浏览器无法创建 PNG 画布'));
        return;
      }
      context.imageSmoothingEnabled = true;
      context.imageSmoothingQuality = 'high';
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      resolve(canvas.toDataURL('image/png'));
    };
    image.onerror = () => reject(new Error('发布版海报栅格化失败'));
    image.src = source;
  });
}

function briefToDraft(session: AISession, project: PosterProject): ProjectDraft {
  const {event, visual} = session.brief;
  const names = (event.artist ?? '').split(/\s*(?:&|×|x|\/|、|,|，| and )\s*/i).filter(Boolean);
  return {
    scene: project.scene ?? 'concert',
    title: event.title || project.title,
    theme: visual.theme || project.theme,
    subject: event.artist || project.subject,
    dateTime: [event.date, event.time].filter(Boolean).join(' '),
    venue: event.venue || project.venue,
    price: event.presalePrice || event.doorPrice || '',
    ticketInfo: '',
    bands: names.length ? names.map((name, index) => {
      const normalized = name.toLocaleLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]/g, '');
      const existing = project.bands.find((band) => {
        const candidates = [band.name, band.nameEn].filter(Boolean).map((value) => value!.toLocaleLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]/g, ''));
        return candidates.some((candidate) => candidate === normalized || candidate.includes(normalized) || normalized.includes(candidate));
      }) ?? project.bands[index];
      return existing ? {...existing, name, genre: existing.genre || visual.musicGenre || ''} : {
        id: crypto.randomUUID(), name, genre: visual.musicGenre ?? '',
      };
    }) : project.bands,
  };
}

/**
 * The deployed agent can return a partial brief while it is still collecting
 * details. Keep the local form authoritative for values the user already
 * entered so “同步到表单” never drops them when the model parser misses a
 * Chinese label or an optional field.
 */
function mergeLocalBrief(session: AISession, project: PosterProject): AISession {
  const event = session.brief.event;
  const visual = session.brief.visual;
  const artist = event.artist || project.bands.map((band) => band.name).filter(Boolean).join(' & ') || project.subject;
  const mergedBrief = {
    ...session.brief,
    event: {
      ...event,
      title: event.title || project.title,
      artist,
      date: event.date || project.dateTime.split(/\s+/)[0] || '',
      time: event.time || project.dateTime.split(/\s+/)[1] || '',
      venue: event.venue || formatPosterLocation(project.city, project.venue),
    },
    visual: {
      ...visual,
      style: visual.style || project.styleId,
      theme: visual.theme || project.theme,
      musicGenre: visual.musicGenre || project.bands.map((band) => band.genre).filter(Boolean).join(' / '),
      mood: visual.mood?.length ? visual.mood : (project.theme ? [project.theme] : undefined),
    },
  };
  const values: Record<string, string> = {
    'event.title': mergedBrief.event.title,
    'event.artist': mergedBrief.event.artist ?? '',
    'event.date': mergedBrief.event.date,
    'event.time': mergedBrief.event.time,
    'event.venue': mergedBrief.event.venue,
    'visual.style': mergedBrief.visual.style,
    'visual.theme': mergedBrief.visual.theme,
    'visual.musicGenre': mergedBrief.visual.musicGenre ?? '',
    'visual.mood': mergedBrief.visual.mood?.join(' / ') ?? '',
  };
  const missingFields = (session.missingFields ?? []).filter((field) => !values[field]);
  return {...session, brief: mergedBrief, missingFields: missingFields.length ? missingFields : null};
}

function projectToSessionBrief(project: PosterProject, referenceAssetId?: string, controlStrength?: number): AISessionBrief {
  const [date = '', time = ''] = project.dateTime.trim().split(/\s+/, 2);
  return {
    event: {
      title: project.title,
      artist: project.bands.map((band) => band.name).filter(Boolean).join(' & ') || project.subject,
      date,
      time,
      venue: formatPosterLocation(project.city, project.venue),
      presalePrice: project.price,
    },
    branding: {
      artistLogoAssetId: undefined,
    },
    visual: {
      // The deployed GPU workflow currently exposes one real style key.
      // UI presets remain prompt directions and must not be sent as model IDs.
      style: 'metal-gothic-v1',
      theme: project.theme,
      musicGenre: project.bands.map((band) => band.genre).filter(Boolean).join(' / '),
      mood: project.theme ? [project.theme] : undefined,
      ...(referenceAssetId ? {referenceAssetId, controlStrength} : {}),
    },
  };
}

type AssetBinding = {asset: UploadedAsset; kind: 'person' | 'logo' | 'reference'; purpose: string};

function projectAssetBindings(project: PosterProject): AssetBinding[] {
  const bindings: AssetBinding[] = [];
  project.bands.forEach((band) => {
    if (band.groupPhoto) bindings.push({asset: band.groupPhoto, kind: 'person', purpose: 'performer'});
    if (band.keyPhoto) bindings.push({asset: band.keyPhoto, kind: 'person', purpose: 'performer'});
    if (band.logo) bindings.push({asset: band.logo, kind: 'logo', purpose: 'artist_logo'});
  });
  if (project.assets.speaker) bindings.push({asset: project.assets.speaker, kind: 'person', purpose: 'performer'});
  if (project.assets.organizerLogo) bindings.push({asset: project.assets.organizerLogo, kind: 'logo', purpose: 'event_logo'});
  if (project.assets.reference) bindings.push({asset: project.assets.reference, kind: 'reference', purpose: 'reference'});
  if (project.assets.venue) bindings.push({asset: project.assets.venue, kind: 'reference', purpose: 'reference'});
  return bindings;
}

async function dataUrlBlob(asset: UploadedAsset): Promise<Blob> {
  const response = await fetch(asset.dataUrl);
  const source = await response.blob();
  // The deployed asset endpoint accepts PNG/JPEG. Rasterize SVG/WebP/GIF
  // client-side while keeping the original local asset for the final poster.
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

export default function ProjectAssistant({project, onApply}: {
  project: PosterProject;
  onApply: (draft: ProjectDraft) => void;
}) {
  const {english} = useSiteLanguage();
  const t = (zh: string, en: string) => english ? en : zh;
  const navigate = useNavigate();
  const {saveTask} = useStore();
  const storageKey = `poster-ai-session:${project.id}`;
  const [session, setSession] = useState<AISession | null>(null);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [imageErrors, setImageErrors] = useState<Record<string, boolean>>({});
  const [lightbox, setLightbox] = useState<{src: string; alt: string} | null>(null);
  const [boundAssetCount, setBoundAssetCount] = useState(0);
  const [uploadProgress, setUploadProgress] = useState('');
  const [pendingMessage, setPendingMessage] = useState('');
  const [backendHealth, setBackendHealth] = useState<BackendHealth | null>(null);
  const [backendDependencies, setBackendDependencies] = useState<BackendDependencies | null>(null);
  const [referenceStrength] = useState(0.35);
  const [assetWarnings, setAssetWarnings] = useState<string[]>([]);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const publishRef = useRef<HTMLDivElement>(null);
  const projectRef = useRef(project);
  projectRef.current = project;
  const actions = session?.availableActions ?? [];
  const canMessage = !session || actions.includes('send_message');
  const canAttach = !!session && !['succeeded', 'completed_with_warnings', 'failed', 'canceled', 'cancelled'].includes(session.status);
  const candidates = session?.poster?.candidates ?? [];
  const shouldPoll = !!session && (
    actions.includes('refresh') ||
    session.status === 'generating_candidates' ||
    session.status === 'looping'
  );

  useEffect(() => {
    if (!session?.poster || !['succeeded', 'completed_with_warnings'].includes(session.status)) return;
    const poster = session.poster;
    const evidenceTask: GenerationTask = {
      id: poster.posterId,
      projectId: project.id,
      step: 5,
      progress: 100,
      status: 'complete',
      startedAt: Date.now() - (poster.progress.elapsedSeconds ?? 0) * 1000,
      metrics: {
        gpu: session.metrics?.gpu ?? backendHealth?.gpu?.model ?? '未提供',
        rocm: session.metrics?.rocm ?? '未提供',
        resolution: '1024 × 1536',
        duration: session.metrics?.inferenceMs != null ? `${Math.round(session.metrics.inferenceMs / 1000)}s` : poster.progress.elapsedSeconds != null ? `${poster.progress.elapsedSeconds}s` : '未提供',
        peakVram: session.metrics?.peakVramMb != null ? `${Math.round(session.metrics.peakVramMb / 1024 * 10) / 10} GB` : '未提供',
      },
      source: 'w7900',
      remoteStatus: session.status,
      candidates: poster.candidates,
      selectedCandidateId: poster.selectedCandidateId,
      composerTemplate: session.plans?.find((plan) => plan.selected || plan.planId === session.selectedPlanId)?.plan.composerTemplate,
      palette: poster.candidates.find((candidate) => candidate.selected || candidate.candidateId === poster.selectedCandidateId)?.spec?.palette
        ?? session.plans?.find((plan) => plan.selected || plan.planId === session.selectedPlanId)?.plan.palette,
      elapsedSeconds: poster.progress.elapsedSeconds,
      etaSeconds: poster.progress.etaSeconds,
      outputUrl: absoluteAIImageUrl(poster.resultUrl),
    };
    saveTask(evidenceTask);
  }, [backendHealth?.gpu?.model, project.id, saveTask, session]);

  useEffect(() => {
    aiSessionApi.health().then(setBackendHealth).catch(() => setBackendHealth(null));
    aiSessionApi.dependencies().then(setBackendDependencies).catch(() => setBackendDependencies(null));
  }, []);

  useEffect(() => {
    const id = localStorage.getItem(storageKey);
    if (!id) return;
    aiSessionApi.get(id)
      .then((next) => setSession(mergeLocalBrief(next, projectRef.current)))
      .catch(() => localStorage.removeItem(storageKey));
  }, [storageKey]);

  useEffect(() => {
    if (!shouldPoll || !session) return;
    const timer = window.setInterval(() => {
      aiSessionApi.get(session.sessionId).then(setSession).catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : '刷新 AI Session 失败');
      });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [session, shouldPoll]);

  useEffect(() => {
    messagesRef.current?.scrollTo({top: messagesRef.current.scrollHeight, behavior: 'smooth'});
  }, [session?.messages.length, pendingMessage, busy]);

  const readiness = useMemo(() => {
    const missing = session ? (session.missingFields?.length ?? 0) : 9;
    return Math.max(0, Math.round((9 - missing) / 9 * 100));
  }, [session]);

  const run = async (operation: () => Promise<AISession>) => {
    setBusy(true); setError('');
    try {
      const next = await operation();
      setSession(next);
      localStorage.setItem(storageKey, next.sessionId);
      return next;
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'AI 服务暂时不可用';
      setError(/failed to fetch|networkerror|load failed/i.test(message)
        ? '生成服务连接中断，Session 与已上传素材仍然保留。请稍后安全重试，无需重新填写。'
        : message);
      return null;
    } finally { setBusy(false); }
  };

  const finalizeAndFollowReview = async () => {
    if (!session) return;
    setBusy(true); setError('');
    try {
      let next = await aiSessionApi.finalize(session.sessionId);
      setSession(next);
      // Final review can continue after the POST has returned. Follow the
      // authoritative session until finalize disappears from availableActions.
      for (let attempt = 0; attempt < 48; attempt += 1) {
        if (!next.availableActions.includes('finalize')
          && ['succeeded', 'completed_with_warnings', 'failed', 'canceled', 'cancelled'].includes(next.status)) break;
        await new Promise((resolve) => window.setTimeout(resolve, 2500));
        next = await aiSessionApi.get(next.sessionId);
        setSession(next);
      }
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '视觉审查暂时不可用';
      setError(/failed to fetch|networkerror|load failed/i.test(message)
        ? '视觉审查连接中断，当前最佳版本已保留。请安全重试审查。'
        : message);
    } finally { setBusy(false); }
  };

  const prepareRemoteAssets = async () => {
    const bindings = projectAssetBindings(project);
    const cacheKey = `poster-remote-assets:${project.id}`;
    const cache = JSON.parse(localStorage.getItem(cacheKey) ?? '{}') as Record<string, string>;
    const remoteBindings: {
      assetId: string;
      purpose: string;
      localAssetId: string;
      kind: AssetBinding['kind'];
    }[] = [];
    const failures: string[] = [];
    const warnings: string[] = [];

    for (const binding of bindings) {
      setUploadProgress(`正在处理 ${binding.asset.name}…`);
      try {
        let assetId = cache[binding.asset.id];
        if (!assetId) {
          const uploaded = await aiSessionApi.uploadAsset(
            await dataUrlBlob(binding.asset), binding.asset.name.replace(/\.[^.]+$/, '.png'), binding.kind,
          );
          assetId = uploaded.assetId;
          cache[binding.asset.id] = assetId;
        }
        remoteBindings.push({
          assetId,
          purpose: binding.purpose,
          localAssetId: binding.asset.id,
          kind: binding.kind,
        });

        if (binding.kind === 'logo') {
          let inspected = await aiSessionApi.getAsset(assetId);
          for (let attempt = 0; inspected.cutout?.status === 'pending' && attempt < 4; attempt += 1) {
            await new Promise((resolve) => window.setTimeout(resolve, 1200));
            inspected = await aiSessionApi.getAsset(assetId);
          }
          if (inspected.cutout?.status === 'opaque' || inspected.cutout?.hasAlpha === false) {
            warnings.push(`${binding.asset.name} 没有透明通道，将以矩形底图叠加；建议换成透明 PNG。`);
          } else if (inspected.cutout?.status === 'pending') {
            warnings.push(`${binding.asset.name} 的透明度仍在检测中。`);
          }
        }
      } catch (reason) {
        failures.push(`${binding.asset.name}：${reason instanceof Error ? reason.message : '上传失败'}`);
      }
    }

    localStorage.setItem(cacheKey, JSON.stringify(cache));
    setAssetWarnings(warnings);
    return {remoteBindings, failures};
  };

  const send = async (preset?: string) => {
    const content = (preset ?? input).trim();
    if (!content || busy) return;
    const englishTitle = extractEnglishTitle(content);
    if (englishTitle && !project.titleEn?.trim()) onApply({titleEn: englishTitle, posterLanguage: 'en'});
    setInput(''); setPendingMessage(content); setBusy(true); setError('');
    try {
      let current = session;
      if (!current) {
        const bindings = projectAssetBindings(project);
        let remoteBindings: Awaited<ReturnType<typeof prepareRemoteAssets>>['remoteBindings'] = [];
        let failures: string[] = [];
        if (bindings.length) {
          setUploadProgress(`先上传 ${bindings.length} 项附件，再交给 AI…`);
          ({remoteBindings, failures} = await prepareRemoteAssets());
        }
        if (failures.length) {
          throw new Error(`附件上传失败，已阻止创建无素材 Session：${failures.join('；')}`);
        }
        const referenceAssetId = remoteBindings.find((binding) => (
          binding.purpose === 'reference' && binding.localAssetId === project.assets.reference?.id
        ))?.assetId;
        const referenceAvailable = backendDependencies?.capabilities?.referenceImageConditioning?.available === true;
        current = await aiSessionApi.create(
          projectToSessionBrief(
            project,
            referenceAvailable ? referenceAssetId : undefined,
            referenceAvailable && referenceAssetId ? referenceStrength : undefined,
          ),
          remoteBindings.map(({assetId, purpose}) => ({assetId, purpose})),
        );
        setBoundAssetCount(remoteBindings.length);
        if (failures.length) setError(`部分附件未上传：${failures.join('；')}`);
        localStorage.setItem(storageKey, current.sessionId);
        setSession(current);
      }
      const next = await aiSessionApi.sendMessage(current.sessionId, content);
      setSession(mergeLocalBrief(next, project));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '发送消息失败');
      setInput(content);
    } finally { setBusy(false); setPendingMessage(''); setUploadProgress(''); }
  };

  const applyBrief = () => {
    if (!session) return;
    onApply(briefToDraft(session, project));
    inputRef.current?.focus();
  };

  const selectCandidateSafely = async (candidateId: string) => {
    if (!session) throw new Error('AI Session 尚未建立。');
    const fresh = await aiSessionApi.get(session.sessionId);
    setSession(fresh);
    if (!fresh.availableActions.includes('select_candidate')) {
      throw new Error('候选图仍在校验中，已同步最新状态，请稍后再选择。');
    }
    return aiSessionApi.selectCandidate(fresh.sessionId, candidateId);
  };

  const reset = () => {
    localStorage.removeItem(storageKey);
    setSession(null); setError(''); setInput(''); setImageErrors({}); setBoundAssetCount(0);
  };

  const finalUrl = absoluteAIImageUrl(session?.poster?.resultUrl);
  const posterCopy = localizedPosterCopy(project);
  const selectedCandidate = candidates.find((candidate) => candidate.selected)
    ?? candidates.find((candidate) => candidate.candidateId === session?.poster?.selectedCandidateId);
  const selectedPlan = session?.plans?.find((plan) => plan.selected || plan.planId === session.selectedPlanId);
  const selectedVisualUrl = absoluteAIImageUrl(selectedCandidate?.imageUrl);
  const assetBindings = projectAssetBindings(project);
  const usageEvidence = session?.assetUsages?.length
    ? session.assetUsages
    : (session?.assets ?? []).map((asset) => ({
      assetId: asset.assetId,
      purpose: asset.purpose,
      stage: asset.usedInStage?.join(' / ') || (asset.actuallyUsed ? '生成流程' : undefined),
      used: asset.actuallyUsed,
      status: asset.processStatus,
      message: asset.usageNote || asset.processing?.error,
    }));
  const generationHasOutput = candidates.some((candidate) => candidate.status === 'ready')
    || Boolean(session?.poster?.resultUrl);
  const boundEvidenceCount = session?.assets?.length ?? boundAssetCount;
  const hasUnusedBoundAssets = generationHasOutput
    && boundEvidenceCount > 0
    && !usageEvidence.some((item) => item.used);
  const publishFactsConfirmed = Boolean(
    project.title.trim()
    && project.dateTime.trim()
    && project.venue.trim()
    && (project.subject.trim() || project.bands.some((band) => band.name.trim())),
  );

  const setConversationAsset = (kind: 'person' | 'logo' | 'reference', asset?: UploadedAsset) => {
    if (kind === 'reference') {
      onApply({assets: {...project.assets, reference: asset}});
      return;
    }
    const currentBands = project.bands.length ? project.bands : [{
      id: crypto.randomUUID(),
      name: session?.brief.event.artist || '表演者',
      genre: session?.brief.visual.musicGenre || '',
    }];
    onApply({bands: currentBands.map((band, index) => index === 0
      ? {...band, ...(kind === 'person' ? {groupPhoto: asset} : {logo: asset})}
      : band)});
  };

  const previewPublishedPoster = async () => {
    if (!publishRef.current) return;
    setBusy(true); setError('');
    try {
      const src = await renderPublishPng(publishRef.current);
      setLightbox({src, alt: '最终发布版海报'});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '海报预览生成失败');
    } finally { setBusy(false); }
  };

  const downloadPublishedPoster = async () => {
    if (!publishRef.current) return;
    setBusy(true); setError('');
    try {
      const dataUrl = await renderPublishPng(publishRef.current);
      const anchor = document.createElement('a');
      anchor.download = `${project.title || session?.brief.event.title || 'poster'}-publish.png`;
      anchor.href = dataUrl;
      anchor.style.display = 'none';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '发布版导出失败');
    } finally { setBusy(false); }
  };

  const uploadAndBindAssets = async () => {
    if (!session || !assetBindings.length) return;
    setBusy(true); setError('');
    setUploadProgress(`准备上传 ${assetBindings.length} 项素材…`);
    try {
      const {remoteBindings, failures} = await prepareRemoteAssets();
      if (remoteBindings.length) {
        const next = await aiSessionApi.bindAssets(
          session.sessionId,
          remoteBindings.map(({assetId, purpose}) => ({assetId, purpose})),
        );
        setSession(next);
        setBoundAssetCount(remoteBindings.length);
      }
      if (failures.length) setError(`部分素材未绑定：${failures.join('；')}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '素材上传失败');
    } finally { setBusy(false); setUploadProgress(''); }
  };

  return <aside className="assistant-panel assistant-live" id="project-assistant">
    <header className="assistant-head">
      <div><span><Bot size={16}/> AI CREATIVE AGENT</span><b>{t('与 AI 一起完成海报', 'Build the poster with AI')}</b></div>
      <em>LIVE API</em>
    </header>
    <div className="assistant-context">
      <Sparkles size={14}/><span>{session ? session.status : t('等待开始', 'Ready to start')}</span>
      <b>{readiness}% READY</b>
    </div>
    {session && <div className="assistant-telemetry" aria-label="生成运行状态">
      <div><small>GPU</small><b>{session.metrics?.gpu ?? backendHealth?.gpu?.model ?? t('AMD GPU 节点', 'AMD GPU node')}</b></div>
      <div><small>ROCm</small><b>{session.metrics?.rocm ?? t('后端未透出', 'Not provided')}</b></div>
      <div><small>WORKFLOW</small><b>{backendHealth?.comfyui?.workflowVersion ?? t('实时读取中', 'Loading live')}</b></div>
      <div><small>{t('阶段', 'STAGE')}</small><b>{session.generationStages?.find((stage) => stage.status === 'running')?.label ?? session.status}</b></div>
      <div><small>{t('进度', 'PROGRESS')}</small><b>{session.poster ? `${session.poster.progress.completed}/${session.poster.progress.total}` : t('等待任务', 'Waiting')}</b></div>
    </div>}
    {backendDependencies?.capabilities && <details className="assistant-capabilities">
      <summary>
        <span>{t('生成能力检查', 'Capability check')}</span>
        <small>{backendDependencies.status === 'healthy' ? t('后端在线', 'Backend online') : backendDependencies.status}</small>
      </summary>
      <div>
        {([
          [t('负向提示词', 'Negative prompt'), backendDependencies.capabilities.negativePrompt],
          [t('人物 / Logo 抠图', 'People / logo cutout'), backendDependencies.capabilities.backgroundRemoval],
          [t('人物相似度', 'Identity similarity'), backendDependencies.capabilities.personSimilarityMetric],
          [t('参考图条件化', 'Reference conditioning'), backendDependencies.capabilities.referenceImageConditioning],
        ] as const).map(([label, capability]) => capability && <p key={label}>
          <b className={capability.available ? 'ok' : 'muted'}>{capability.available ? t('可用', 'Available') : t('未接入', 'Unavailable')}</b>
          <span>{label}</span>
          {!capability.available && capability.reason && <small title={capability.reason}>{capability.reason}</small>}
        </p>)}
      </div>
    </details>}

    <div className="assistant-messages" ref={messagesRef} aria-live="polite">
      {!session?.messages.length && <div className="assistant-message assistant"><i><Bot/></i><p>{t('告诉我演出、活动或品牌故事。我会逐步追问，并由后端 AI 生成可确认的设计方案。', 'Tell me about the performance, event or brand story. I will ask for missing facts and produce confirmable design plans.')}</p></div>}
      {session?.messages.map((message) => <div key={message.messageId} className={`assistant-message ${message.role}`}>
        <i>{message.role === 'user' ? <UserRound/> : <Bot/>}</i><p>{message.content}</p>
      </div>)}
      {pendingMessage && !session?.messages.some((message) => message.role === 'user' && message.content === pendingMessage) && <div className="assistant-message user pending"><i><UserRound/></i><p>{pendingMessage}<small>{t('正在送达 AI…', 'Sending to AI…')}</small></p></div>}
      {busy && <div className="assistant-message assistant"><i><Bot/></i><p className="assistant-typing"><span/><span/><span/></p></div>}
    </div>

    {error && <div className="assistant-error"><b>{t('连接或生成失败', 'Connection or generation failed')}</b><span>{error}</span><button onClick={() => setError('')}>{t('关闭', 'Close')}</button></div>}

    {!!session?.missingFields?.length && <section className="assistant-missing">
      <header><b>{t('还需要补充', 'Still needed')}</b><span>{session.missingFields.length} {t('项', 'items')}</span></header>
      <div>{session.missingFields.map((field) => <span key={field}>{fieldLabels[field] ?? field}</span>)}</div>
    </section>}

    {!!usageEvidence.length && <section className="assistant-asset-status">
      <header><b>{t('素材处理与使用证据', 'Asset processing & usage evidence')}</b><span>{usageEvidence.filter((item) => item.used).length} {t('项已使用', 'used')}</span></header>
      {usageEvidence.map((item) => <div key={`${item.assetId}-${item.purpose}`} title={item.message}><span>{item.purpose}</span><b className={item.used ? 'ok' : 'muted'}>{item.used ? `已用于 ${item.stage ?? '生成'}` : item.message ?? (generationHasOutput ? '已绑定 · 条件化未启用' : '已绑定 · 等待生成')}</b></div>)}
    </section>}
    {hasUnusedBoundAssets && <div className="assistant-error" role="alert">
      <b>{t('真实素材尚未参与本次生成', 'Real assets were not used in this generation')}</b>
      <span>{t('后端已接收素材，但没有返回任何实际使用证据。当前候选图不能视为人物保持或风格参考已生效。', 'The backend received the assets but returned no usage evidence. Identity preservation or reference conditioning cannot be claimed for these candidates.')}</span>
    </div>}

    {session && <button className="assistant-sync" onClick={applyBrief}><Check/> {t('将 AI 已理解的信息同步到表单', 'Sync confirmed AI facts to form')}</button>}
    {canAttach && assetBindings.length > 0 && <button className="assistant-assets" disabled={busy} onClick={() => void uploadAndBindAssets()}>
      {boundAssetCount ? <Check/> : <Sparkles/>} {boundAssetCount ? `已绑定 ${boundAssetCount} 项真实素材` : `上传并绑定 ${assetBindings.length} 项真实素材`}
    </button>}
    {uploadProgress && <div className="assistant-upload-progress" role="status"><LoaderCircle/> {uploadProgress}<small>后端正在校验和预处理，可能需要几十秒</small></div>}

    {actions.includes('confirm_plan') && !!session?.plans?.length && <section className="assistant-plans">
      <header><b>{t('选择一个设计方向', 'Choose a design direction')}</b><span>{session.plans.length} {t('个真实方案', 'real plans')}</span></header>
      {!publishFactsConfirmed && <p className="assistant-plan-gate" role="status">{t('先点击“将 AI 已理解的信息同步到表单”，确认标题、时间和地点后再生成。', 'Sync the AI brief to the form and confirm title, date and venue before generation.')}</p>}
      {session.plans.map(({planId, plan}) => <article key={planId}>
        <div className="plan-palette">{plan.palette.map((color) => <i key={color} style={{background: color}}/>)}</div>
        <b>{plan.name}</b><p>{plan.concept}</p><small>{plan.composerTemplate} · {plan.composition.symmetry}</small>
        <button disabled={busy || !publishFactsConfirmed} onClick={() => run(() => aiSessionApi.confirmPlan(session.sessionId, planId))}>{publishFactsConfirmed ? t('确认此方案', 'Confirm this plan') : t('请先确认活动信息', 'Confirm event facts first')}</button>
      </article>)}
    </section>}

    {session?.poster && <section className="assistant-generation">
      <header><b>{t('候选视觉', 'Candidate visuals')}</b><span>{session.poster.progress.percent != null ? `${session.poster.progress.percent}%` : `${session.poster.progress.completed} / ${session.poster.progress.total}`}</span></header>
      <div className="assistant-pipeline-progress" aria-label="生成总进度">
        <i style={{width: `${session.poster.progress.percent ?? (session.poster.progress.completed / Math.max(1, session.poster.progress.total) * 65)}%`}}/>
      </div>
      <div className="assistant-pipeline-meta">
        <span>{session.poster.progress.stage ?? session.status}</span>
        <span>{session.poster.progress.elapsedSeconds != null ? `已用 ${session.poster.progress.elapsedSeconds}s` : ''}</span>
        <span>{session.poster.progress.etaSeconds != null ? `预计剩余 ${session.poster.progress.etaSeconds}s` : ''}</span>
      </div>
      {shouldPoll && <div className="generation-live"><LoaderCircle/> {t('AMD GPU 正在生成候选图，页面会自动刷新', 'AMD GPU is generating candidates; this page refreshes automatically')}</div>}
      <div className="candidate-grid">{candidates.map((candidate) => {
        const imageUrl = absoluteAIImageUrl(candidate.imageUrl);
        const visualAnalysis = candidate.visualAnalysis ?? candidate.spec?.visualAnalysis;
        return <article key={candidate.candidateId} className={candidate.selected ? 'selected' : ''}>
          {imageUrl && !imageErrors[candidate.candidateId]
            ? <button className="candidate-image-button" type="button" onClick={() => setLightbox({src: imageUrl, alt: candidate.variantName})} aria-label={`放大查看 ${candidate.variantName}`}><img src={imageUrl} alt={candidate.variantName} onError={() => setImageErrors((current) => ({...current, [candidate.candidateId]: true}))}/><Maximize2/></button>
            : <div className="candidate-placeholder"><LoaderCircle/><span>{candidate.status}</span></div>}
          <b>{candidate.variantName}</b><small>AI 主视觉 · Attempt {candidate.attempt} · Seed {candidate.seed ?? '—'} · {candidate.status}</small>
          {candidate.spec && <details className="candidate-spec"><summary>查看视觉参数</summary>
            {candidate.spec.motif && <p>{candidate.spec.motif}</p>}
            {candidate.spec.camera && <small>{candidate.spec.camera}</small>}
            {!!candidate.spec.palette?.length && <div>{candidate.spec.palette.map((color) => <i key={color} style={{background: color}} title={color}/>)}</div>}
          </details>}
          {visualAnalysis && <div className="candidate-analysis" aria-label="背景与排版分析">
            <span className={visualAnalysis.hasGeneratedText === false ? 'ok' : 'warning'}>{visualAnalysis.hasGeneratedText === false ? '无模型文字' : '检测到文字'}</span>
            <span>{visualAnalysis.textSafeZones?.length ?? 0} 个安全区</span>
            <span>{visualAnalysis.subjectBounds?.length ?? 0} 个主体区域</span>
          </div>}
          {actions.includes('select_candidate') && candidate.status === 'ready' && <button disabled={busy} onClick={() => run(() => selectCandidateSafely(candidate.candidateId))}>{t('选择这张', 'Select')}</button>}
          {candidate.status === 'failed' && session.poster && <button disabled={busy} onClick={() => run(() => aiSessionApi.retryCandidate(session.sessionId, session.poster!.posterId, candidate.candidateId))}>{t('仅重试这张', 'Retry this candidate')}</button>}
        </article>;
      })}</div>
      {!!session.generationStages?.length && <div className="assistant-stage-trace">{session.generationStages.map((stage) => <div key={stage.id ?? stage.key ?? stage.label} className={stage.status}><span>{stage.label}</span><b>{stage.progress ?? (stage.status === 'completed' ? 100 : 0)}%</b>{stage.etaSeconds != null && <small>约 {stage.etaSeconds}s</small>}</div>)}</div>}
    </section>}

    {actions.includes('finalize') && session && <button className="button assistant-finalize" disabled={busy} onClick={() => void finalizeAndFollowReview()}><RefreshCw/> {t('启动 AI 视觉审查与优化', 'Run AI visual review & optimization')}</button>}
    {session && actions.includes('cancel') && <button className="ghost-button assistant-cancel" disabled={busy} onClick={() => run(() => aiSessionApi.cancel(session.sessionId))}>{t('取消当前生成', 'Cancel generation')}</button>}
    {session?.reviewSummary?.warning && actions.includes('finalize') && <button className="ghost-button assistant-retry" disabled={busy} onClick={() => run(() => aiSessionApi.retryFinalize(session.sessionId))}><RefreshCw/> 安全重试审查</button>}
    {finalUrl && <section className="assistant-final">
      <header><b>{t('发布版海报', 'Publish-ready poster')}</b><span>{t('真实信息程序化叠加', 'Verified facts composed programmatically')}</span></header>
      <PosterLanguageToggle value={posterCopy.language} onChange={(language) => onApply({posterLanguage: language})}/>
      {selectedVisualUrl && <PublishPoster project={project} visualUrl={selectedVisualUrl} nodeRef={publishRef} palette={selectedCandidate?.spec?.palette ?? selectedPlan?.plan.palette} template={selectedPlan?.plan.composerTemplate} analysis={selectedCandidate?.visualAnalysis ?? selectedCandidate?.spec?.visualAnalysis}/>}
      {selectedVisualUrl && <button className="button assistant-publish-download" disabled={busy} onClick={() => void downloadPublishedPoster()}><Download/> {t('导出精确信息发布版', 'Export publish-ready PNG')}</button>}
      {selectedVisualUrl && <button className="ghost-button assistant-publish-preview" disabled={busy} onClick={() => void previewPublishedPoster()}><Maximize2/> {t('放大查看最终发布版', 'Open final poster')}</button>}
      {selectedVisualUrl && session?.poster && ['succeeded', 'completed_with_warnings'].includes(session.status) && <button className="ghost-button assistant-quality-link" onClick={() => navigate(`/result/${encodeURIComponent(project.id)}`)}><CheckCircle2/> {t('查看完整质量与性能报告', 'Open quality & performance report')}</button>}
      {session?.reviewSummary?.warning && <p className="assistant-review-warning">评分 {session.reviewSummary.bestScore ?? '—'} · {session.reviewSummary.warning}</p>}
      {actions.includes('download_final') && <details><summary>查看后端原始合成结果</summary><img src={finalUrl} alt="后端合成的最终海报"/><a className="button" href={finalUrl} target="_blank" rel="noreferrer"><Download/> 下载后端结果</a></details>}
    </section>}

    {canMessage && <>
      <details className="assistant-upload-studio assistant-attachment-tray">
        <summary><span>＋ {t('添加附件（可选）', 'Add attachments (optional)')}</span><small>{assetBindings.length ? `${assetBindings.length} ${t('项素材', 'assets')}` : t('人物 / Logo / 风格参考', 'People / logo / style reference')}</small></summary>
        <p>{t('所有附件均非必填。上传参考海报后，系统会自动理解它的视觉语言并安全生成新的主视觉。', 'All attachments are optional. A reference poster can guide the visual language without exposing internal controls.')}</p>
        <div className="assistant-upload-grid">
          <AssetUpload label={t('人物 / 乐队照片（可选）', 'People / band photo (optional)')} kind="person" value={project.bands[0]?.groupPhoto} onChange={(asset) => setConversationAsset('person', asset)}/>
          <AssetUpload label={t('乐队原始 Logo（可选）', 'Original band logo (optional)')} kind="logo" value={project.bands[0]?.logo} onChange={(asset) => setConversationAsset('logo', asset)}/>
          <AssetUpload label={t('添加参考海报（可选）', 'Reference poster (optional)')} kind="reference" value={project.assets.reference} onChange={(asset) => setConversationAsset('reference', asset)}/>
        </div>
        {project.assets.reference && backendDependencies?.capabilities?.referenceImageConditioning?.available && <div className="assistant-reference-ready"><CheckCircle2/><span>参考海报已就绪</span><small>系统将自动选择安全的参考方式</small></div>}
        {!session && assetBindings.length > 0 && <small className="assistant-asset-hint">发送第一条消息时会先上传附件，并把参考图 ID 与强度写入生成 Brief。</small>}
        {session && project.assets.reference && !session.brief.visual.referenceAssetId && <small className="assistant-asset-hint warning">当前会话创建时没有参考图。请开始新的 AI 会话，让参考图真正进入生成 Brief。</small>}
        {!!assetWarnings.length && <div className="assistant-asset-warnings">{assetWarnings.map((warning) => <small key={warning}>{warning}</small>)}</div>}
      </details>
      <div className="assistant-prompts">
        <button onClick={() => send(english ? 'Create an underground metal concert poster. Ask me for any missing facts.' : '我要做一张地下金属演出海报。标题是长安双雄，艺人是内网穿透 NATP 与示例金属乐队，2026 年 8 月 8 日 20:00，在西安大雁塔附近演出。视觉是黑色、骨白、氧化红的手工复印拼贴，工业金属风，情绪原始、黑暗、仪式感、高能量。')}>{t('地下金属演出', 'Underground metal')}</button>
        <button onClick={() => send(english ? 'I need an independent music festival poster. Ask for the missing facts one by one.' : '我要做一张独立音乐节海报，请逐项问我还缺少什么。')}>{t('逐步问我', 'Guide me')}</button>
      </div>
      <div className="assistant-compose">
        <textarea ref={inputRef} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => {if (event.key === 'Enter' && !event.shiftKey) {event.preventDefault(); void send();}}} placeholder={t('描述活动，或继续回答 AI 的问题……', 'Describe the event or answer the AI…')}/>
        <button onClick={() => void send()} disabled={!input.trim() || busy} aria-label={t('发送消息', 'Send message')}><Send/></button>
        <small><CornerDownLeft/> {t('Enter 发送 · Shift + Enter 换行', 'Enter to send · Shift + Enter for new line')}</small>
      </div>
    </>}
    {session && <button className="assistant-reset" onClick={reset}>{t('开始新的 AI 会话', 'Start a new AI session')}</button>}
    {lightbox && <div className="poster-lightbox" role="dialog" aria-modal="true" aria-label={lightbox.alt} onClick={() => setLightbox(null)}>
      <button type="button" onClick={() => setLightbox(null)} aria-label="关闭大图"><X/></button>
      <img src={lightbox.src} alt={lightbox.alt} onClick={(event) => event.stopPropagation()}/>
      <a href={lightbox.src} download={`${lightbox.alt}.png`} onClick={(event) => event.stopPropagation()}><Download/> 下载图片</a>
    </div>}
  </aside>;
}

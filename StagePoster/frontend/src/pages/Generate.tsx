import {useEffect, useState} from 'react';
import {AlertTriangle, Check, Clock3, Cpu, LoaderCircle, Maximize2, RefreshCw, X} from 'lucide-react';
import {useNavigate, useParams} from 'react-router-dom';
import Brand from '../components/Brand';
import PosterPreview from '../components/PosterPreview';
import SiteLanguageToggle from '../components/SiteLanguageToggle';
import {posterApi} from '../services/posterApi';
import {useStore} from '../store';
import type {GenerationTask} from '../types';
import {useSiteLanguage} from '../hooks/useSiteLanguage';

const stages = ['分析活动信息', '规划海报构图', 'W7900 生成主视觉', '获取生成图片', '质量检查', '生成完成'];

function failedTask(projectId: string, reason: unknown): GenerationTask {
  return {
    id: projectId,
    projectId,
    step: 0,
    progress: 0,
    status: 'failed',
    startedAt: Date.now(),
    metrics: {gpu: 'AMD Radeon Pro W7900', rocm: '远程 GPU 节点', resolution: '等待服务端输出', duration: '提交失败', peakVram: '—'},
    source: 'w7900',
    error: reason instanceof Error ? reason.message : '真实生成接口不可用',
  };
}

export default function Generate() {
  const {english} = useSiteLanguage();
  const {id = ''} = useParams();
  const {projects, tasks, saveTask} = useStore();
  const nav = useNavigate();
  const task = tasks[id];
  const project = projects[task?.projectId ?? id];
  const [lightbox, setLightbox] = useState('');
  const [selecting, setSelecting] = useState('');
  const [actionError, setActionError] = useState('');

  useEffect(() => {
    if (!project) return;
    if (!task) {
      let active = true;
      posterApi.submit(project)
        .then((remote) => { if (active) { saveTask(remote); nav(`/generate/${remote.id}`, {replace: true}); } })
        .catch((reason: unknown) => { if (active) saveTask(failedTask(project.id, reason)); });
      return () => { active = false; };
    }
    if (task.status === 'complete') {
      const done = window.setTimeout(() => nav(`/result/${task.projectId}`), 700);
      return () => window.clearTimeout(done);
    }
    if (task.status === 'failed') return;
    const poll = window.setInterval(() => {
      posterApi.getPoster(task).then(saveTask).catch((reason: unknown) => saveTask({...task, status: 'failed', error: reason instanceof Error ? reason.message : '任务轮询失败'}));
    }, 3500);
    return () => window.clearInterval(poll);
  }, [id, nav, project, saveTask, task]);

  const selectCandidate = async (candidateId: string) => {
    if (!task || selecting) return;
    setSelecting(candidateId);
    try {
      saveTask(await posterApi.selectCandidate(task, candidateId));
    } catch (reason) {
      saveTask({...task, status: 'failed', error: reason instanceof Error ? reason.message : '候选图合成失败'});
    } finally {
      setSelecting('');
    }
  };
  const cancelGeneration = async () => {
    if (!task) return;
    try { saveTask(await posterApi.cancel(task)); nav(`/create?project=${encodeURIComponent(project.id)}`); }
    catch (reason) { setActionError(reason instanceof Error ? reason.message : '取消任务失败'); }
  };
  const retryCandidate = async (candidateId: string) => {
    if (!task) return;
    setSelecting(candidateId);
    try { saveTask(await posterApi.retryCandidate(task, candidateId)); }
    catch (reason) { setActionError(reason instanceof Error ? reason.message : '候选图重试失败'); }
    finally { setSelecting(''); }
  };

  if (!project) return <main className="center-state"><h1>项目不存在</h1><button className="button" onClick={() => nav('/create')}>创建新项目</button></main>;
  if (!task) return <main className="center-state"><LoaderCircle className="spin"/><h1>正在连接 W7900 GPU</h1><p>正在提交 Prompt 和 Seed…</p></main>;
  if (task.status === 'failed') return <main className="center-state"><AlertTriangle/><h1>真实生成失败</h1><p>{task.error}</p><button className="button" onClick={() => nav('/create')}>返回修改</button></main>;

  return <main className="generation">
    <nav><Brand/><span>AMD W7900 / ROCm LIVE</span><div className="workspace-top-actions"><SiteLanguageToggle/><button className="ghost-button" onClick={() => nav(`/create?project=${encodeURIComponent(project.id)}`)}>{english ? 'Back to edit' : '返回编辑'}</button></div></nav>
    <div className="generation-layout">
      <section>
        <p className="eyebrow">AMD ACCELERATED WORKFLOW</p><h1>正在构建你的主视觉</h1>
        <p>任务已提交至远程 AMD W7900，页面正在每 3.5 秒轮询真实状态。</p>
        <div className="progress-ring" style={{'--progress': `${task.progress * 3.6}deg`} as React.CSSProperties}><div><b>{task.progress}%</b><span>总进度</span></div></div>
        <div className="generation-meta">
          <span>{task.remoteStatus ?? '正在连接生成流水线'}</span>
          {task.elapsedSeconds != null && <span>已用 {task.elapsedSeconds}s</span>}
          {task.etaSeconds != null && <span>预计剩余 {task.etaSeconds}s</span>}
        </div>
        {actionError && <div className="assistant-error" role="alert"><b>{english ? 'Action failed' : '操作失败'}</b><span>{actionError}</span><button onClick={() => setActionError('')}>×</button></div>}
        <div className="stage-list">{stages.map((stage, index) => <div key={stage} className={index < task.step ? 'done' : index === task.step ? 'running' : ''}><i>{index < task.step ? <Check/> : index === task.step ? <LoaderCircle/> : <Clock3/>}</i><span><b>{stage}</b><small>{index < task.step ? '已完成' : index === task.step ? '运行中' : '等待中'}</small></span></div>)}</div>
        {!!task.candidates?.length && <section className="manual-candidates">
          <header><b>W7900 候选主视觉</b><span>{task.candidates.filter((candidate) => candidate.status === 'ready').length} / {task.candidates.length}</span></header>
          <div>{task.candidates.map((candidate) => {
            const imageUrl = posterApi.imageUrl(candidate.imageUrl);
            return <article key={candidate.candidateId}>
              {imageUrl && candidate.status === 'ready'
                ? <button className="candidate-image-button" onClick={() => setLightbox(imageUrl)} aria-label={`放大查看 ${candidate.variantName}`}><img src={imageUrl} alt={candidate.variantName}/><Maximize2/></button>
                : <div className="candidate-placeholder"><LoaderCircle/><span>{candidate.status}</span></div>}
              <b>{candidate.variantName}</b>
              <small>Attempt {candidate.attempt} · Seed {candidate.seed ?? '—'} · {candidate.status}</small>
              {candidate.spec && <details className="candidate-spec"><summary>{english ? 'Visual specification' : '视觉参数'}</summary>{candidate.spec.motif && <p>{candidate.spec.motif}</p>}{candidate.spec.composition && <p>{candidate.spec.composition}</p>}{candidate.spec.camera && <small>{candidate.spec.camera}</small>}{candidate.spec.materials?.length && <p>{candidate.spec.materials.join(' · ')}</p>}{candidate.spec.palette?.length && <div>{candidate.spec.palette.map((color) => <i key={color} title={color} style={{background: color}}/>)}</div>}</details>}
              {candidate.error && <p className="candidate-error">{candidate.error}</p>}
              {candidate.status === 'failed' && <button disabled={Boolean(selecting)} onClick={() => void retryCandidate(candidate.candidateId)}><RefreshCw/> {english ? 'Retry this candidate' : '仅重试这张'}</button>}
              {task.remoteStatus === 'awaiting_selection' && candidate.status === 'ready' && <button
                disabled={Boolean(selecting)}
                onClick={() => void selectCandidate(candidate.candidateId)}
              >{selecting === candidate.candidateId ? '正在合成…' : '选择这张并合成'}</button>}
            </article>;
          })}</div>
        </section>}
        {!['awaiting_selection', 'succeeded', 'failed', 'canceled'].includes(task.remoteStatus ?? '') && <button className="ghost-button generation-cancel" onClick={() => void cancelGeneration()}>{english ? 'Cancel generation' : '取消当前生成'}</button>}
      </section>
      <aside><PosterPreview project={project}/><div className="metric-grid">{([[Cpu, 'GPU', task.metrics.gpu], [Cpu, 'ROCm', task.metrics.rocm], [Cpu, '输出', task.metrics.resolution], [Cpu, '耗时', task.metrics.duration], [Cpu, '显存', task.metrics.peakVram]] as const).map(([Icon, key, value]) => <div key={key}><Icon/><small>{key}</small><b>{value}</b></div>)}</div><p className="mock-note">已连接 StagePoster 公网 API 与 ROCm GPU 服务；失败时不会伪造本地生成结果。</p></aside>
    </div>
    {lightbox && <div className="poster-lightbox" role="dialog" aria-modal="true" aria-label="候选主视觉大图" onClick={() => setLightbox('')}>
      <button aria-label="关闭大图" onClick={() => setLightbox('')}><X/></button>
      <img src={lightbox} alt="候选主视觉大图" onClick={(event) => event.stopPropagation()}/>
      <a href={lightbox} download onClick={(event) => event.stopPropagation()}>下载候选图</a>
    </div>}
  </main>;
}

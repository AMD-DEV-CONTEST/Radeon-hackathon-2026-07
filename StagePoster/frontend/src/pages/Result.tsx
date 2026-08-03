import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Download,
  Maximize2,
  RefreshCw,
  ShieldCheck,
  X,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { toPng } from "html-to-image";
import AssetUpload from "../components/AssetUpload";
import Brand from "../components/Brand";
import PosterPreview from "../components/PosterPreview";
import PosterLanguageToggle from "../components/PosterLanguageToggle";
import PublishPoster from "../components/PublishPoster";
import SiteLanguageToggle from "../components/SiteLanguageToggle";
import { posterApi } from "../services/posterApi";
import { useStore } from "../store";
import type { Participant, PosterProject } from "../types";
import type {ImageMetadata, PosterReview, PosterTimeline, RuntimeEvidence} from "../types";
import { localizedPosterCopy } from "../utils/posterLanguage";
import {useSiteLanguage} from "../hooks/useSiteLanguage";

async function renderElementPublishPng(node: HTMLElement) {
  await document.fonts.ready;
  for (const image of Array.from(node.querySelectorAll('img'))) {
    if (!image.complete) await image.decode();
  }
  const source = await toPng(node, {
    pixelRatio: Math.max(2, 1024 / Math.max(1, node.clientWidth)),
    cacheBust: false,
  });
  const rendered = new Image();
  rendered.src = source;
  await rendered.decode();
  const canvas = document.createElement('canvas');
  canvas.width = 1024;
  canvas.height = 1536;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('浏览器无法创建海报画布');
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = 'high';
  context.drawImage(rendered, 0, 0, 1024, 1536);
  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('海报导出失败')), 'image/png');
  });
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number) {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) =>
      window.setTimeout(() => reject(new Error("海报合成超时")), timeoutMs),
    ),
  ]);
}

async function downloadDataUrl(href: string) {
  if (href.startsWith("data:")) return href;
  const response = await fetch(href);
  const blob = await response.blob();
  return await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("无法准备下载文件"));
    reader.readAsDataURL(blob);
  });
}

export default function Result() {
  const {english} = useSiteLanguage();
  const { id = "" } = useParams();
  const { projects, tasks, save } = useStore();
  const nav = useNavigate();
  const [tab, setTab] = useState<"check" | "edit" | "metrics">("check");
  const [busy, setBusy] = useState(false);
  const [imageUrl, setImageUrl] = useState("");
  const [imageError, setImageError] = useState("");
  const [exportError, setExportError] = useState("");
  const [resultAttempt, setResultAttempt] = useState(0);
  const [lightbox, setLightbox] = useState("");
  const [lightboxScale, setLightboxScale] = useState(1);
  const [timeline, setTimeline] = useState<PosterTimeline>();
  const [reviews, setReviews] = useState<PosterReview[]>([]);
  const [runtime, setRuntime] = useState<RuntimeEvidence>();
  const [dependencies, setDependencies] = useState<Record<string, {status?: string; model?: string}>>();
  const [imageMetadata, setImageMetadata] = useState<ImageMetadata>();
  const [evidenceError, setEvidenceError] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const project = projects[id];
  const task = useMemo(
    () => Object.values(tasks)
      .filter((item) => item.projectId === id && item.status === "complete")
      .sort((a, b) => b.startedAt - a.startedAt)[0],
    [tasks, id],
  );
  useEffect(() => {
    if (!task || task.source !== "w7900") return;
    let url = "";
    let active = true;
    setImageError("");
    posterApi.resultBlob(task).then((blob) => {
      if (active) {
        url = URL.createObjectURL(blob);
        setImageUrl(url);
      }
    }).catch((reason: unknown) => {
      if (active) setImageError(reason instanceof Error ? reason.message : "生成图片获取失败");
    });
    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [task, resultAttempt]);
  useEffect(() => {
    if (!task || task.source !== 'w7900') return;
    let active = true;
    Promise.allSettled([
      posterApi.timeline(task.id),
      posterApi.reviews(task.id),
      posterApi.health(),
      posterApi.dependencies(),
      posterApi.imageMetadata(task),
    ]).then((results) => {
      if (!active) return;
      if (results[0].status === 'fulfilled') setTimeline(results[0].value);
      if (results[1].status === 'fulfilled') setReviews(results[1].value);
      if (results[2].status === 'fulfilled') setRuntime(results[2].value);
      if (results[3].status === 'fulfilled') setDependencies(results[3].value.dependencies);
      if (results[4].status === 'fulfilled') setImageMetadata(results[4].value);
      const failures = results.filter((result) => result.status === 'rejected').length;
      setEvidenceError(failures ? `${failures} ${english ? 'evidence sources unavailable' : '项证据暂不可用'}` : '');
    });
    return () => { active = false; };
  }, [task, resultAttempt, english]);
  if (!project)
    return (
      <main className="center-state">
        <h1>结果不存在</h1>
        <button className="button" onClick={() => nav("/create")}>
          返回创建
        </button>
      </main>
    );
  const posterCopy = localizedPosterCopy(project);
  const set = <K extends keyof PosterProject>(
    key: K,
    value: PosterProject[K],
  ) => save({ ...project, [key]: value });
  const exportPng = async () => {
    setBusy(true);
    setExportError("");
    try {
      let href = "";
      if (task?.source === "w7900" && imageUrl) {
        try {
          if (!ref.current) throw new Error('发布版尚未准备好');
          const blob = await withTimeout(renderElementPublishPng(ref.current), 15_000);
          href = URL.createObjectURL(blob);
        } catch (reason) {
          throw new Error(reason instanceof Error
            ? `发布版导出失败：${reason.message}`
            : '发布版导出失败，请稍后重试');
        }
      } else if (ref.current) {
        href = await toPng(ref.current, {
          pixelRatio: 2,
          cacheBust: true,
        });
      }
      if (!href) throw new Error("海报尚未准备好，请稍后重试");
      const downloadHref = await withTimeout(downloadDataUrl(href), 20_000);
      const a = document.createElement("a");
      a.download = `poster-${project.title || project.id}.png`;
      a.href = downloadHref;
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      a.remove();
      if (href.startsWith("blob:") && href !== imageUrl) {
        window.setTimeout(() => URL.revokeObjectURL(href), 1000);
      }
    } catch (reason) {
      setExportError(reason instanceof Error ? reason.message : "PNG 导出失败，请重试");
    } finally {
      setBusy(false);
    }
  };
  const previewLarge = async () => {
    if (!ref.current && !(task?.source === "w7900" && imageUrl)) return;
    setBusy(true);
    try {
      if (task?.source === "w7900" && imageUrl) {
        const blob = await renderElementPublishPng(ref.current!);
        setLightbox(URL.createObjectURL(blob));
      } else {
        setLightbox(await toPng(ref.current!, {pixelRatio: 2, cacheBust: true}));
      }
    }
    finally { setBusy(false); }
  };
  const replaceFirstLogo = (asset?: Participant["logo"]) =>
    set(
      "bands",
      project.bands.map((band, index) =>
        index === 0 ? { ...band, logo: asset } : band,
      ),
    );
  const editUrl = `/create?project=${encodeURIComponent(project.id)}`;
  const isRemoteResult = task?.source === "w7900";
  const checks = [
    [isRemoteResult ? "主视觉已从 W7900 生成服务获取" : "本地主视觉 Mock 已生成", isRemoteResult ? "通过" : "Mock"],
    ["标题、时间和地点保留表单原文", "通过"],
    ["Logo 与二维码使用原始素材图层", "通过"],
    ["输出可下载为 PNG", "通过"],
  ];
  const evidenceReviews = reviews.length ? reviews : timeline?.reviews ?? [];
  const latestReview = evidenceReviews.reduce<PosterReview | undefined>((best, review) => !best || review.totalScore > best.totalScore ? review : best, undefined);
  const reviewScores = latestReview?.scores ?? latestReview?.result?.scores;
  const reviewFailures = latestReview?.hardFailures ?? latestReview?.result?.hardFailures;
  const reviewIssues = latestReview?.issues ?? latestReview?.result?.issues;
  const evidenceMetrics = timeline?.metrics;
  const selectedCandidate = task?.candidates?.find((candidate) => candidate.candidateId === task.selectedCandidateId)
    ?? task?.candidates?.find((candidate) => candidate.selected);
  const selectedAnalysis = selectedCandidate?.visualAnalysis ?? selectedCandidate?.spec?.visualAnalysis;
  const scoreRows: Array<[string, number | undefined]> = [
    [english ? 'Requirement alignment' : '需求匹配', reviewScores?.requirementAlignment],
    [english ? 'Composition' : '构图', reviewScores?.composition],
    [english ? 'Typography' : '排版', reviewScores?.typography],
    [english ? 'Readability' : '可读性', reviewScores?.readability],
    [english ? 'Visual quality' : '视觉质量', reviewScores?.visualQuality],
    [english ? 'Brand consistency' : '品牌一致性', reviewScores?.brandConsistency],
  ];
  const displayScore = (score?: number) => score == null ? 0 : score <= 1 ? Math.round(score * 100) : Math.round(score);
  return (
    <main className="result">
      <nav>
        <Brand />
        <span>RESULT / {id.slice(0, 8).toUpperCase()}</span>
        <div className="workspace-top-actions"><SiteLanguageToggle/><button className="ghost-button" onClick={() => nav(editUrl)}>
          <ArrowLeft /> {english ? 'Back to edit' : '返回编辑'}
        </button></div>
      </nav>
      <div className="result-layout">
        <section className="result-canvas">
          <PosterLanguageToggle
            value={posterCopy.language}
            onChange={(language) => set("posterLanguage", language)}
          />
          <div className="result-status">
            <CheckCircle2 /> 生成完成{" "}
            <span>
              {task?.source === "w7900"
                ? "AMD W7900 主视觉 · 精确信息层"
                : "本地 Mock 输出"}
            </span>
          </div>
          {task?.source === "w7900" ? (
            imageUrl ? (
              <PublishPoster project={project} visualUrl={imageUrl} nodeRef={ref} palette={task?.palette ?? selectedCandidate?.spec?.palette} template={task?.composerTemplate} analysis={selectedCandidate?.visualAnalysis ?? selectedCandidate?.spec?.visualAnalysis}/>
            ) : imageError ? (
              <div className="gpu-result loading-result error-state" role="alert">
                <AlertTriangle />
                <b>生成图片获取失败</b>
                <span>{imageError}</span>
                <button className="ghost-button" onClick={() => setResultAttempt((attempt) => attempt + 1)}>重新获取</button>
              </div>
            ) : (
              <div className="gpu-result loading-result">
                正在安全获取生成图片…
              </div>
            )
          ) : (
            <PosterPreview project={project} nodeRef={ref} />
          )}
          <div className="result-actions">
            <button className="ghost-button" onClick={() => nav(editUrl)}>
              <RefreshCw /> 重新生成主视觉
            </button>
            <button className="button" onClick={exportPng} disabled={busy}>
              <Download />
              {busy ? "正在导出…" : "导出 PNG"}
            </button>
            {imageUrl && <a className="ghost-button" href={imageUrl} download={`poster-${project.title}-visual.png`}><Download/> {english ? 'Raw visual' : '原始主视觉'}</a>}
            <button className="ghost-button" onClick={() => void previewLarge()} disabled={busy}><Maximize2/> 放大</button>
          </div>
          {exportError && <div className="assistant-error" role="alert"><b>导出失败</b><span>{exportError}</span><button onClick={() => setExportError("")}>关闭</button></div>}
        </section>
        <aside className="result-panel">
          <div className="tabs">
            <button
              className={tab === "check" ? "active" : ""}
              onClick={() => setTab("check")}
            >
              检查结果
            </button>
            <button
              className={tab === "edit" ? "active" : ""}
              onClick={() => setTab("edit")}
            >
              编辑信息
            </button>
            <button
              className={tab === "metrics" ? "active" : ""}
              onClick={() => setTab("metrics")}
            >
              性能数据
            </button>
          </div>
          {tab === "check" && (
            <div className="tab-content">
              <p className="eyebrow">PRE-FLIGHT CHECK</p>
              <h2>{isRemoteResult ? "可以进入发布检查" : "Mock 预览已完成"}</h2>
              {checks.map(([text, status]) => (
                <div className="check-row" key={text}>
                  <ShieldCheck />
                  {text}
                  <b>{status}</b>
                </div>
              ))}
              {!isRemoteResult && <div className="warning-box"><b>当前不是 GPU 实际输出</b><p>此页面用于检查信息图层、布局与 PNG 导出；连接远程生成服务后才能进行最终发布检查。</p></div>}
              {isRemoteResult && <section className="adaptive-evidence" aria-label="Adaptive compositor evidence">
                <header><div><small>ADAPTIVE COMPOSITOR</small><h3>{english ? 'Background-aware typography' : '背景驱动排版证据'}</h3></div><strong className={selectedAnalysis?.hasGeneratedText === false ? 'accepted' : 'warning'}>{selectedAnalysis ? (selectedAnalysis.hasGeneratedText === false ? 'CLEAN' : 'CHECK') : 'N/A'}</strong></header>
                {selectedAnalysis ? <>
                  <div className="adaptive-metrics">
                    <div><small>{english ? 'Text-safe zones' : '文字安全区'}</small><b>{selectedAnalysis.textSafeZones?.length ?? 0}</b></div>
                    <div><small>{english ? 'Protected subjects' : '主体保护区'}</small><b>{selectedAnalysis.subjectBounds?.length ?? 0}</b></div>
                    <div><small>{english ? 'Contrast' : '背景对比度'}</small><b>{selectedAnalysis.contrast ?? '—'}</b></div>
                    <div><small>{english ? 'OCR detections' : 'OCR 文字'}</small><b>{selectedAnalysis.ocrDetections?.length ?? 0}</b></div>
                  </div>
                  <div className="adaptive-palette">{(selectedAnalysis.palette ?? selectedAnalysis.dominantColors ?? selectedCandidate?.spec?.palette ?? []).map((color) => <i key={color} style={{background: color}} title={color}/>)}</div>
                  <p>{selectedAnalysis.texture || selectedAnalysis.style || (english ? 'Backend analysed layout is active.' : '已使用后端分析结果选择字体、颜色和文字位置。')}</p>
                  {selectedAnalysis.hasGeneratedText !== false && <div className="warning-box"><b>{english ? 'Generated text needs review' : '检测到模型文字风险'}</b><p>{english ? 'Inspect the raw visual before publishing.' : '请在发布前检查原始主视觉；前端不会将此状态伪装为通过。'}</p></div>}
                </> : <p>{english ? 'The backend did not provide visual analysis for this legacy result. Conservative layout is active.' : '该历史结果未提供视觉分析，当前使用保守安全布局。'}</p>}
              </section>}
              {isRemoteResult && <section className="quality-review" aria-label="AI quality review">
                <header><div><small>AI QUALITY REVIEW</small><h3>{english ? 'Visual quality evidence' : '视觉质量证据'}</h3></div><strong className={latestReview && /accept/i.test(latestReview.decision) ? 'accepted' : 'warning'}>{latestReview ? `${latestReview.totalScore}/100` : '—'}</strong></header>
                {latestReview ? <>
                  <div className="quality-score-grid">{scoreRows.map(([label, score]) => <div key={label}><span>{label}<b>{score == null ? '—' : displayScore(score)}</b></span><i><em style={{width: `${displayScore(score)}%`}}/></i></div>)}</div>
                  <p className="quality-decision"><b>{latestReview.decision}</b> · {/accept/i.test(latestReview.decision) ? (english ? 'Accepted for publish' : '达到发布标准') : (english ? 'Best available result retained; review the advice before publishing' : '已保留当前最佳版本，发布前请检查优化建议')}</p>
                  {!!reviewFailures?.length && <div className="quality-failures"><b>{english ? 'Hard failures' : '硬失败项'}</b>{reviewFailures.map((failure) => <p key={failure.code}><strong>{failure.code}</strong>{failure.description}</p>)}</div>}
                  {!!reviewIssues?.length && <div className="quality-issues"><b>{english ? 'Review findings' : '审查发现'}</b>{reviewIssues.map((issue) => <article key={`${issue.code}-${issue.description}`}><span>{issue.severity}</span><strong>{issue.description}</strong>{issue.suggestion && <p>{issue.suggestion}</p>}</article>)}</div>}
                </> : <p>{english ? 'No visual review has been recorded yet.' : '尚未产生视觉复审记录。'}</p>}
                {evidenceError && <small className="evidence-error">{evidenceError}</small>}
              </section>}
            </div>
          )}
          {tab === "edit" && (
            <div className="tab-content">
              <p>
                文字修改会即时更新精确信息图层；GPU 只提供无字主视觉。
              </p>
              <label className="field">
                <span>{posterCopy.language === "en" ? "活动标题 / TITLE" : "活动标题"}</span>
                <input
                  value={posterCopy.language === "en" ? project.titleEn ?? "" : project.title}
                  onChange={(e) => posterCopy.language === "en" ? set("titleEn", e.target.value) : set("title", e.target.value)}
                />
              </label>
              <label className="field">
                <span>{posterCopy.language === "en" ? "主题文案 / TAGLINE" : "主题文案"}</span>
                <input
                  value={posterCopy.language === "en" ? project.themeEn ?? "" : project.theme}
                  onChange={(e) => posterCopy.language === "en" ? set("themeEn", e.target.value) : set("theme", e.target.value)}
                />
              </label>
              <label className="field">
                <span>时间</span>
                <input
                  value={project.dateTime}
                  onChange={(e) => set("dateTime", e.target.value)}
                />
              </label>
              <label className="field">
                <span>{posterCopy.language === "en" ? "地点 / VENUE" : "地点"}</span>
                <input
                  value={posterCopy.language === "en" ? project.venueEn ?? "" : project.venue}
                  onChange={(e) => posterCopy.language === "en" ? set("venueEn", e.target.value) : set("venue", e.target.value)}
                />
              </label>
              {project.bands[0] && (
                <AssetUpload
                  label={`${project.bands[0].name} Logo`}
                  kind="logo"
                  value={project.bands[0].logo}
                  onChange={replaceFirstLogo}
                />
              )}
            </div>
          )}
          {tab === "metrics" && (
            <div className="tab-content metrics-list">
              {Object.entries(task?.metrics ?? {}).map(([key, value]) => (
                <div key={key}>
                  <span>
                    {
                      (
                        {
                          gpu: "GPU 型号",
                          rocm: "运行环境",
                          resolution: "输出分辨率",
                          duration: "推理耗时",
                          peakVram: "显存",
                        } as Record<string, string>
                      )[key]
                    }
                  </span>
                  <b>{value}</b>
                </div>
              ))}
              <details className="technical-evidence">
                <summary>{english ? 'Generation details' : '生成详情'} <small>{english ? 'ROCm evidence' : 'ROCm 推理证据'}</small></summary>
                <div className="evidence-grid">
                  <div><span>GPU</span><b>{runtime?.gpu?.model ?? '未提供'}</b></div>
                  <div><span>{english ? 'VRAM' : '显存'}</span><b>{runtime?.gpu?.vramUsedGB != null ? `${runtime.gpu.vramUsedGB} / ${runtime.gpu.vramTotalGB ?? '—'} GB` : '未提供'}</b></div>
                  <div><span>ROCm</span><b>{task?.metrics.rocm || '未提供'}</b></div>
                  <div><span>ComfyUI</span><b>{runtime?.comfyui?.workflowVersion ?? dependencies?.comfyui?.status ?? '未提供'}</b></div>
                  <div><span>VLM</span><b>{runtime?.vlm?.model ?? dependencies?.vlm?.model ?? '未提供'}</b></div>
                  <div><span>{english ? 'Wall clock' : '总耗时'}</span><b>{evidenceMetrics?.wallClockSeconds != null ? `${evidenceMetrics.wallClockSeconds}s` : task?.elapsedSeconds != null ? `${task.elapsedSeconds}s` : '未提供'}</b></div>
                  <div><span>{english ? 'Review latency' : '复审耗时'}</span><b>{evidenceMetrics?.reviewLatencyMs != null ? `${Math.round(evidenceMetrics.reviewLatencyMs / 1000)}s` : '未提供'}</b></div>
                  <div><span>Tokens</span><b>{evidenceMetrics?.totalTokens ?? '未提供'}</b></div>
                  <div><span>{english ? 'Review rounds' : '复审轮次'}</span><b>{evidenceMetrics?.reviewRounds ?? '未提供'}</b></div>
                  <div><span>{english ? 'Candidate' : '候选图'}</span><b>{selectedCandidate?.variantName ?? '未提供'}</b></div>
                  <div><span>Seed / Attempt</span><b>{selectedCandidate?.seed ?? '—'} / {selectedCandidate?.attempt ?? '—'}</b></div>
                  <div><span>{english ? 'Image' : '图片质量'}</span><b>{imageMetadata ? `${imageMetadata.width} × ${imageMetadata.height} · ${imageMetadata.aspectRatio} · ${(imageMetadata.sizeBytes / 1024 / 1024).toFixed(2)} MB` : '未提供'}</b></div>
                </div>
              </details>
            </div>
          )}
        </aside>
      </div>
      {lightbox && <div className="poster-lightbox" role="dialog" aria-modal="true" aria-label="最终海报大图" onClick={() => {setLightbox(""); setLightboxScale(1);}}>
        <button type="button" onClick={() => setLightbox("")} aria-label="关闭大图"><X/></button>
        <div className="lightbox-zoom" onClick={(event) => event.stopPropagation()}><button type="button" onClick={() => setLightboxScale((scale) => Math.max(.5, scale - .25))}>−</button><b>{Math.round(lightboxScale * 100)}%</b><button type="button" onClick={() => setLightboxScale((scale) => Math.min(3, scale + .25))}>＋</button></div>
        <img src={lightbox} alt={`${project.title} 最终发布版`} style={{transform: `scale(${lightboxScale})`}} onClick={(event) => event.stopPropagation()}/>
        <a href={lightbox} download={`poster-${project.title}.png`} onClick={(event) => event.stopPropagation()}><Download/> 下载图片</a>
      </div>}
    </main>
  );
}

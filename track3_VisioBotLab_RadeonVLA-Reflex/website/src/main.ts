import architectureEn from "./assets/architecture-en.jpg";
import architectureZh from "./assets/architecture-zh.jpg";
import heroImage from "./assets/radeonvla-reflex-hero-v2.png";
import {
  collectionClips,
  copy,
  demos,
  evaluationMetrics,
  features,
  navItems,
  projectLinks,
  t,
  taskRows,
  teamMembers,
  type Locale,
  verifiedMetrics,
} from "./content";
import "./styles.css";

const app = document.querySelector<HTMLDivElement>("#app");

if (!app) {
  throw new Error("Missing #app mount point");
}

const localeKey = "radeonvla-reflex-locale";
const storedLocale = localStorage.getItem(localeKey);
let locale: Locale = storedLocale === "zh" ? "zh" : "en";

function iconArrow(): string {
  return '<span aria-hidden="true">↗</span>';
}

function publicAsset(path: string): string {
  return `${import.meta.env.BASE_URL}${path}`;
}

function render(): void {
  document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
  document.title = t(copy.pageTitle, locale);
  document.querySelector<HTMLAnchorElement>(".skip-link")!.textContent = t(copy.skipLink, locale);
  document.querySelector<HTMLMetaElement>('meta[name="description"]')!.content = t(copy.pageDescription, locale);

  app!.innerHTML = `
    <header class="site-header">
      <a class="wordmark" href="#top" aria-label="${t(copy.homeLabel, locale)}">
        <span class="wordmark-mark" aria-hidden="true"><i></i><i></i></span>
        <span>
          <strong>RadeonVLA</strong><em>Reflex</em>
          <small>${t(copy.brandKicker, locale)}</small>
        </span>
      </a>
      <nav class="site-nav" aria-label="${t(copy.primaryNav, locale)}">
        ${navItems.map((item) => `<a href="${item.href}">${t(item.label, locale)}</a>`).join("")}
      </nav>
      <div class="locale-switch" role="group" aria-label="${t(copy.languageLabel, locale)}">
        <button type="button" data-locale="en" aria-pressed="${locale === "en"}">EN</button>
        <span aria-hidden="true">/</span>
        <button type="button" data-locale="zh" aria-pressed="${locale === "zh"}">中</button>
      </div>
    </header>

    <main id="main">
      <section class="hero section-shell" id="top" aria-labelledby="hero-title">
        <div class="hero-grid">
          <div class="hero-copy reveal">
            <p class="badge"><span></span>${t(copy.heroBadge, locale)}</p>
            <h1 id="hero-title">
              <span>${t(copy.heroTitleA, locale)}</span>
              <em>${t(copy.heroTitleB, locale)}</em>
            </h1>
            <p class="hero-lede">${t(copy.heroBody, locale)}</p>
            <div class="hero-actions">
              <a class="button button-primary" href="${projectLinks.source}" target="_blank" rel="noreferrer">
                ${t(copy.sourceCta, locale)} ${iconArrow()}
              </a>
              <a class="button button-quiet" href="#demo">${t(copy.demoCta, locale)} <span aria-hidden="true">↓</span></a>
              <a class="button button-console" href="${publicAsset("console.html")}">${t(copy.consoleCta, locale)} <span aria-hidden="true">→</span></a>
            </div>
          </div>
          <div class="hero-stage reveal">
            <figure class="hero-visual" aria-labelledby="hero-visual-caption">
              <img src="${heroImage}" alt="${t(copy.heroAlt, locale)}" decoding="async" fetchpriority="high" />
              <figcaption id="hero-visual-caption">
                <span class="live-dot" aria-hidden="true"></span>
                ${t(copy.placeholder, locale)}
              </figcaption>
            </figure>
            <div class="hero-telemetry" aria-hidden="true">
              <div class="telemetry-card telemetry-command">
                <small>COMMAND SESSION</small>
                <strong>v2</strong>
                <span>stale chunk → invalid</span>
              </div>
              <div class="telemetry-card telemetry-state">
                <small>RUNTIME STATE</small>
                <strong>INTERRUPTED</strong>
                <span>safe hold active</span>
              </div>
            </div>
          </div>
        </div>
        <div class="hero-index" aria-hidden="true">RVR—26</div>
      </section>

      <section class="overview section-shell section-block" id="overview" aria-labelledby="overview-title">
        <div class="section-intro reveal">
          <p class="eyebrow">${t(copy.overviewKicker, locale)}</p>
          <h2 id="overview-title">${t(copy.overviewTitle, locale)}</h2>
          <p>${t(copy.overviewBody, locale)}</p>
        </div>
        <div class="overview-grid">
          ${copy.overviewPoints
            .map(
              (point) => `
                <article class="overview-card reveal">
                  <h3>${t(point.title, locale)}</h3>
                  <p>${t(point.body, locale)}</p>
                </article>`,
            )
            .join("")}
        </div>
      </section>

      <section class="proof-band" aria-labelledby="proof-heading">
        <div class="section-shell">
          <div class="proof-heading reveal">
            <p class="eyebrow" id="proof-heading">${t(copy.proofLabel, locale)}</p>
            <p>${t(copy.proofNote, locale)}</p>
          </div>
          <div class="metric-grid">
            ${verifiedMetrics
              .map(
                (metric) => `
                  <article class="metric reveal">
                    <strong>${metric.value}</strong>
                    <h2>${t(metric.label, locale)}</h2>
                    <p>${t(metric.detail, locale)}</p>
                  </article>`,
              )
              .join("")}
          </div>
        </div>
      </section>

      <section class="demo section-shell section-block" id="demo" aria-labelledby="demo-title">
        <div class="section-intro reveal">
          <p class="eyebrow">${t(copy.sectionDemoKicker, locale)}</p>
          <h2 id="demo-title">${t(copy.sectionDemoTitle, locale)}</h2>
          <p>${t(copy.sectionDemoBody, locale)}</p>
        </div>
        <figure class="policy-video reveal">
          <video
            controls
            playsinline
            preload="metadata"
            poster="${publicAsset("videos/dataset-banana-white-right.webp")}"
            aria-label="${t(copy.videoPending, locale)}"
          >
            <source src="${publicAsset("videos/radeonvla-reflex-3min.mp4")}" type="video/mp4" />
            <track kind="subtitles" src="${publicAsset("videos/radeonvla-reflex-3min.vtt")}" srclang="en" label="English" />
            ${t(copy.clipFallback, locale)}
          </video>
          <figcaption>
            <small>${t(copy.videoLabel, locale)}</small>
            <strong>${t(copy.videoPending, locale)}</strong>
            <p>${t(copy.videoBody, locale)}</p>
          </figcaption>
        </figure>
        <div class="demo-grid">
          ${demos
            .map(
              (demo) => `
                <article class="demo-card reveal">
                  <div class="demo-card-top">
                    <span>${demo.index}</span>
                    <span class="state state-${demo.state.toLowerCase()}">${demo.state}</span>
                  </div>
                  <div class="signal" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>
                  <p class="eyebrow">${t(copy.plannedEvidence, locale)}</p>
                  <h3>${t(demo.title, locale)}</h3>
                  <p>${t(demo.body, locale)}</p>
                  <code>${t(demo.event, locale)}</code>
                </article>`,
            )
            .join("")}
        </div>
      </section>

      <section class="runtime section-block" id="runtime" aria-labelledby="runtime-title">
        <div class="section-shell">
          <div class="section-intro reveal">
            <p class="eyebrow">${t(copy.runtimeKicker, locale)}</p>
            <h2 id="runtime-title">${t(copy.runtimeTitle, locale)}</h2>
            <p>${t(copy.runtimeBody, locale)}</p>
          </div>
          <figure class="architecture-diagram reveal">
            <img
              src="${locale === "zh" ? architectureZh : architectureEn}"
              alt="${t(copy.architectureDiagramAlt, locale)}"
              loading="lazy"
              decoding="async"
            />
            <figcaption>${t(copy.architectureDiagramCaption, locale)}</figcaption>
          </figure>
          <div class="architecture reveal" aria-label="${t(copy.architectureLabel, locale)}">
            <div class="architecture-track" aria-hidden="true"></div>
            <div class="architecture-node input-node">
              <span>INPUT</span>
              <strong>${t(copy.architectureInput, locale)}</strong>
            </div>
            <span class="architecture-arrow" aria-hidden="true">→</span>
            <div class="architecture-node policy-node">
              <span>LEARNED</span>
              <strong>${t(copy.architecturePolicy, locale)}</strong>
            </div>
            <span class="architecture-arrow" aria-hidden="true">→</span>
            <div class="architecture-node reflex-node">
              <span>DETERMINISTIC</span>
              <strong>${t(copy.architectureReflex, locale)}</strong>
              <small>${t(copy.architectureSafety, locale)}</small>
            </div>
            <span class="architecture-arrow" aria-hidden="true">→</span>
            <div class="architecture-node sim-node">
              <span>CONTROL</span>
              <strong>${t(copy.architectureSim, locale)}</strong>
            </div>
          </div>
          <div class="feature-grid">
            ${features
              .map(
                (feature) => `
                  <article class="feature reveal">
                    <p class="eyebrow">${feature.eyebrow}</p>
                    <h3>${t(feature.title, locale)}</h3>
                    <p>${t(feature.body, locale)}</p>
                  </article>`,
              )
              .join("")}
          </div>
        </div>
      </section>

      <section class="benchmark section-shell section-block" id="benchmark" aria-labelledby="benchmark-title">
        <div class="section-intro reveal">
          <p class="eyebrow">${t(copy.benchmarkKicker, locale)}</p>
          <h2 id="benchmark-title">${t(copy.benchmarkTitle, locale)}</h2>
          <p>${t(copy.benchmarkBody, locale)}</p>
        </div>
        <div class="task-table-wrap reveal" tabindex="0" role="region" aria-label="L1 task matrix">
          <table class="task-table">
            <thead>
              <tr>
                <th scope="col">${t(copy.objectLabel, locale)}</th>
                <th scope="col">${t(copy.targetLabel, locale)} 01</th>
                <th scope="col">${t(copy.targetLabel, locale)} 02</th>
                <th scope="col">${t(copy.targetLabel, locale)} 03</th>
                <th scope="col">${t(copy.targetLabel, locale)} 04</th>
              </tr>
            </thead>
            <tbody>
              ${taskRows
                .map(
                  (row, rowIndex) => `
                    <tr>
                      <th scope="row"><span class="fruit-index">0${rowIndex + 1}</span>${t(row.fruit, locale)}</th>
                      ${row.targets
                        .map(
                          (target) => `
                            <td>
                              <span class="bowl bowl-${target.color}" aria-hidden="true"></span>
                              ${t(target.label, locale)}
                              <small>${t(copy.demosLabel, locale)}</small>
                            </td>`,
                        )
                        .join("")}
                    </tr>`,
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </section>

      <section class="evidence section-block" aria-labelledby="evidence-title">
        <div class="section-shell">
          <div class="section-intro reveal">
            <p class="eyebrow">${t(copy.evidenceKicker, locale)}</p>
            <h2 id="evidence-title">${t(copy.evidenceTitle, locale)}</h2>
            <p>${t(copy.evidenceBody, locale)}</p>
          </div>
          <div class="pending-results">
            ${evaluationMetrics
              .map(
                (metric, index) => `
                  <article class="pending-result reveal">
                    <span>0${index + 1}</span>
                    <h3>${t(metric.label, locale)}</h3>
                    <strong>${metric.value}</strong>
                    <p>${t(metric.detail, locale)}</p>
                  </article>`,
              )
              .join("")}
          </div>
          <div class="release-grid">
            <article class="release-card release-target reveal">
              <p class="eyebrow">${t(copy.releaseTarget, locale)}</p>
              <h3>${t(copy.releaseTargetValue, locale)}</h3>
              <p>${t(copy.releaseTargetBody, locale)}</p>
              <a href="${projectLinks.dataset}" target="_blank" rel="noreferrer">
                ${t(copy.datasetCta, locale)} ${iconArrow()}
              </a>
            </article>
            <article class="release-card release-target reveal">
              <p class="eyebrow">${locale === "zh" ? "已发布训练数据集" : "Released training dataset"}</p>
              <h3>Physical-1K</h3>
              <p>${locale === "zh" ? "20 项任务 × 50 条，共 1,000 条严格物理演示。" : "Twenty tasks × fifty episodes: 1,000 strict-physics demonstrations."}</p>
              <a href="${projectLinks.dataset1k}" target="_blank" rel="noreferrer">${locale === "zh" ? "下载 Physical-1K" : "Download Physical-1K"} ${iconArrow()}</a>
            </article>
            <article class="release-card release-model reveal">
              <p class="eyebrow">${locale === "zh" ? "主要展示权重" : "Primary showcase checkpoint"}</p>
              <h3>SmolVLA · 20K</h3>
              <p>${locale === "zh" ? "成功香蕉和柠檬回放使用的公开 Physical-1K 权重。" : "Public Physical-1K checkpoint used by the successful banana and lemon replays."}</p>
              <a href="${projectLinks.model20k}" target="_blank" rel="noreferrer">
                ${t(copy.trainedModelCta, locale)} ${iconArrow()}
              </a>
            </article>
            <article class="release-card release-videos reveal">
              <p class="eyebrow">${locale === "zh" ? "中间权重" : "Intermediate checkpoint"}</p>
              <h3>SmolVLA · 50K</h3>
              <p>${locale === "zh" ? "Physical-1K 续训中间版本，保留用于复现与对比。" : "Physical-1K continuation checkpoint retained for reproducibility and comparison."}</p>
              <a href="${projectLinks.model50k}" target="_blank" rel="noreferrer">${locale === "zh" ? "下载 50K 权重" : "Download 50K weights"} ${iconArrow()}</a>
            </article>
            <article class="release-card release-videos reveal">
              <p class="eyebrow">${locale === "zh" ? "完整续训权重" : "Full continuation checkpoint"}</p>
              <h3>SmolVLA · 200K</h3>
              <p>${locale === "zh" ? "Physical-2K 累计约 200K 步权重，作为独立版本保留。" : "Physical-2K cumulative 200K-step checkpoint, retained as a separate release."}</p>
              <a href="${projectLinks.finalModel}" target="_blank" rel="noreferrer">${locale === "zh" ? "下载 200K 权重" : "Download 200K weights"} ${iconArrow()}</a>
            </article>
            <article class="release-card release-videos reveal">
              <p class="eyebrow">${t(copy.evaluationVideosLabel, locale)}</p>
              <h3>${t(copy.evaluationVideosValue, locale)}</h3>
              <p>${t(copy.evaluationVideosBody, locale)}</p>
              <a href="${projectLinks.evaluationVideos}" target="_blank" rel="noreferrer">
                ${t(copy.evaluationVideosCta, locale)} ${iconArrow()}
              </a>
            </article>
            <article class="release-card release-target reveal">
              <p class="eyebrow">${locale === "zh" ? "项目源码" : "Project source"}</p>
              <h3>GitHub</h3>
              <p>${locale === "zh" ? "完整训练、评测、网站和复现脚本。" : "Training, evaluation, website, and reproducibility scripts."}</p>
              <a href="${projectLinks.source}" target="_blank" rel="noreferrer">${locale === "zh" ? "打开源码" : "Open source"} ${iconArrow()}</a>
            </article>
            <article class="release-card release-target reveal">
              <p class="eyebrow">${locale === "zh" ? "官方项目成片" : "Official project film"}</p>
              <h3>Bilibili · 200 s</h3>
              <p>${locale === "zh" ? "1080p 英文演讲、中英双语字幕，完整呈现系统、数据、训练与成功执行。" : "A 1080p English-narrated film with bilingual captions, spanning the system, data, training, and successful execution."}</p>
              <a href="${projectLinks.bilibili}" target="_blank" rel="noreferrer">${locale === "zh" ? "在 B 站观看" : "Watch on Bilibili"} ${iconArrow()}</a>
              <a href="${publicAsset("videos/radeonvla-reflex-3min.mp4")}" target="_blank" rel="noreferrer">${locale === "zh" ? "下载原片" : "Download film"} ${iconArrow()}</a>
            </article>
          </div>
        </div>
      </section>

      <section class="collection-appendix section-shell section-block" id="data-smoke" aria-labelledby="collection-title">
        <div class="collection-appendix-intro reveal">
          <p class="eyebrow">${t(copy.collectionKicker, locale)}</p>
          <div>
            <h2 id="collection-title">${t(copy.collectionTitle, locale)}</h2>
            <p>${t(copy.collectionBody, locale)}</p>
          </div>
        </div>
        <div class="collection-showcase collection-showcase-compact">
          <div class="collection-head reveal">
            <div class="collection-head-label">
              <span class="live-dot" aria-hidden="true"></span>
              <small>${t(copy.videoCollectionLabel, locale)}</small>
            </div>
            <div>
              <strong>${t(copy.videoCollectionPending, locale)}</strong>
              <p>${t(copy.videoCollectionBody, locale)}</p>
            </div>
          </div>
          <div class="collection-stat-row reveal" aria-label="Local smoke collection stats">
            ${copy.collectionStats
              .map(
                (stat) => `
                  <div class="collection-stat">
                    <strong>${stat.value}</strong>
                    <span>${t(stat.label, locale)}</span>
                  </div>`,
              )
              .join("")}
          </div>
          <div class="collection-video-grid">
            ${collectionClips
              .map(
                (clip) => `
                  <article class="collection-video-card reveal" aria-labelledby="collection-title-${clip.episode}">
                    <div class="collection-video-frame">
                      <video
                        controls
                        playsinline
                        preload="none"
                        poster="${publicAsset(clip.poster)}"
                        aria-label="${t(copy.clipPlayLabel, locale)}: ${t(clip.title, locale)}"
                      >
                        <source src="${publicAsset(clip.video)}" type="video/mp4" />
                        ${t(copy.clipFallback, locale)}
                      </video>
                      <span class="camera-pill">${t(clip.camera, locale)}</span>
                      <span class="duration-pill">${clip.duration}</span>
                    </div>
                    <div class="collection-video-copy">
                      <div class="collection-video-state">
                        <span>${clip.index}</span>
                        <strong>${t(clip.state, locale)}</strong>
                      </div>
                      <h3 id="collection-title-${clip.episode}">${t(clip.title, locale)}</h3>
                      <p>${t(clip.instruction, locale)}</p>
                      <div class="collection-video-meta">
                        <span>EP ${clip.episode}</span>
                        <span>${t(clip.frames, locale)}</span>
                      </div>
                    </div>
                  </article>`,
              )
              .join("")}
          </div>
          <aside class="collection-note reveal">
            <strong>${t(copy.collectionScopeTitle, locale)}</strong>
            <p>${t(copy.collectionScopeBody, locale)}</p>
          </aside>
        </div>
      </section>

      <section class="reproduce section-shell section-block" id="reproduce" aria-labelledby="reproduce-title">
        <div class="reproduce-grid">
          <div class="section-intro reveal">
            <p class="eyebrow">${t(copy.reproduceKicker, locale)}</p>
            <h2 id="reproduce-title">${t(copy.reproduceTitle, locale)}</h2>
            <p>${t(copy.reproduceBody, locale)}</p>
          </div>
          <ol class="pipeline reveal">
            ${copy.pipelineSteps
              .map(
                (step, index) => `
                  <li>
                    <span>${String(index + 1).padStart(2, "0")}</span>
                    <strong>${t(step, locale)}</strong>
                  </li>`,
              )
              .join("")}
          </ol>
        </div>
        <div class="command-panel reveal">
          <div>
            <span class="terminal-dots" aria-hidden="true"><i></i><i></i><i></i></span>
            <small>${t(copy.commandLabel, locale)}</small>
          </div>
          <code><span>$</span> python -m pytest -q<br /><span>$</span> python -m ruff check src tests<br /><span>$</span> python -m radeonvla.download_artifacts --artifact physical-1k model-20k<br /><span>$</span> python -m radeonvla.submission_audit</code>
        </div>
        <aside class="limitation reveal">
          <strong>${t(copy.limitationLabel, locale)}</strong>
          <p>${t(copy.limitationBody, locale)}</p>
        </aside>
      </section>

      <section class="team section-block" id="team" aria-labelledby="team-title">
        <div class="section-shell">
          <div class="team-header reveal">
            <div>
              <p class="eyebrow">${t(copy.teamKicker, locale)}</p>
              <h2 id="team-title">${t(copy.teamTitle, locale)}</h2>
              <p>${t(copy.teamBody, locale)}</p>
            </div>
            <div class="team-actions">
              <a class="button button-light" href="${projectLinks.contest}" target="_blank" rel="noreferrer">
                ${t(copy.contestCta, locale)} ${iconArrow()}
              </a>
              <a class="button button-outline-light" href="${projectLinks.source}" target="_blank" rel="noreferrer">
                GitHub ${iconArrow()}
              </a>
              <a class="button button-outline-light" href="${projectLinks.submission}" target="_blank" rel="noreferrer">
                ${locale === "zh" ? "比赛提交" : "Submission PR"} ${iconArrow()}
              </a>
            </div>
          </div>
          <div class="team-grid">
            ${teamMembers
              .map(
                (member) => `
                  <article class="team-card reveal ${member.lead ? "team-card-lead" : ""}">
                    <div class="team-card-top">
                      <span>${member.lead ? t(copy.teamLeadLabel, locale) : t(copy.teamMemberLabel, locale)}</span>
                    </div>
                    <h3>${t(member.name, locale)}</h3>
                    <p class="team-role">${t(member.role, locale)}</p>
                    <p class="team-focus">${t(member.focus, locale)}</p>
                  </article>`,
              )
              .join("")}
          </div>
        </div>
      </section>
    </main>

    <footer class="site-footer section-shell">
      <p>${t(copy.footer, locale)}</p>
      <p>${t(copy.attribution, locale)}</p>
    </footer>
  `;

  bindLocaleControls();
  enableReveal();
}

function bindLocaleControls(): void {
  document.querySelectorAll<HTMLButtonElement>("[data-locale]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextLocale = button.dataset.locale;
      if (nextLocale !== "en" && nextLocale !== "zh") return;
      locale = nextLocale;
      localStorage.setItem(localeKey, locale);
      render();
    });
  });
}

function enableReveal(): void {
  const items = document.querySelectorAll<HTMLElement>(".reveal");

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !("IntersectionObserver" in window)) {
    items.forEach((item) => item.classList.add("is-visible"));
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    { rootMargin: "0px 0px -8%", threshold: 0.08 },
  );

  items.forEach((item) => observer.observe(item));
}

render();

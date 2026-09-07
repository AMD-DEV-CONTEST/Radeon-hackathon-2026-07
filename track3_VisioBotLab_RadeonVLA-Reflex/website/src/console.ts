import { projectLinks } from "./content";
import "./console.css";

type FruitId = "apple" | "banana" | "lemon" | "orange" | "plum";
type Locale = "en" | "zh";
type DestinationId = "white-left" | "blue-left" | "white-right" | "blue-right";

interface TaskResult {
  learned: number;
  final: number;
}

interface FruitResult {
  id: FruitId;
  icon: string;
  label: Record<Locale, string>;
  learned: number;
  final: number;
  tasks: Record<DestinationId, TaskResult>;
  exampleEpisodeBase: number;
  exampleSeedBase: number;
}

const destinationOffset: Record<DestinationId, number> = {
  "blue-left": 0,
  "blue-right": 1,
  "white-left": 2,
  "white-right": 3,
};

const results: FruitResult[] = [
  {
    id: "apple",
    icon: "●",
    label: { en: "Apple", zh: "苹果" },
    learned: 8,
    final: 20,
    exampleEpisodeBase: 0,
    exampleSeedBase: 21000,
    tasks: {
      "white-left": { learned: 2, final: 5 },
      "blue-left": { learned: 3, final: 5 },
      "white-right": { learned: 3, final: 5 },
      "blue-right": { learned: 0, final: 5 },
    },
  },
  {
    id: "banana",
    icon: "⌒",
    label: { en: "Banana", zh: "香蕉" },
    learned: 9,
    final: 19,
    exampleEpisodeBase: 192,
    exampleSeedBase: 22000,
    tasks: {
      "white-left": { learned: 3, final: 4 },
      "blue-left": { learned: 2, final: 5 },
      "white-right": { learned: 1, final: 5 },
      "blue-right": { learned: 3, final: 5 },
    },
  },
  {
    id: "lemon",
    icon: "◆",
    label: { en: "Lemon", zh: "柠檬" },
    learned: 5,
    final: 19,
    exampleEpisodeBase: 384,
    exampleSeedBase: 23000,
    tasks: {
      "white-left": { learned: 0, final: 5 },
      "blue-left": { learned: 2, final: 5 },
      "white-right": { learned: 2, final: 5 },
      "blue-right": { learned: 1, final: 4 },
    },
  },
  {
    id: "orange",
    icon: "●",
    label: { en: "Orange", zh: "橙子" },
    learned: 7,
    final: 17,
    exampleEpisodeBase: 576,
    exampleSeedBase: 24000,
    tasks: {
      "white-left": { learned: 2, final: 5 },
      "blue-left": { learned: 2, final: 5 },
      "white-right": { learned: 1, final: 3 },
      "blue-right": { learned: 2, final: 4 },
    },
  },
  {
    id: "plum",
    icon: "●",
    label: { en: "Plum", zh: "李子" },
    learned: 7,
    final: 16,
    exampleEpisodeBase: 768,
    exampleSeedBase: 25000,
    tasks: {
      "white-left": { learned: 2, final: 3 },
      "blue-left": { learned: 1, final: 3 },
      "white-right": { learned: 2, final: 5 },
      "blue-right": { learned: 2, final: 5 },
    },
  },
];

const labels = {
  en: {
    back: "Back to project",
    kicker: "INTERACTIVE EVIDENCE CONSOLE",
    title: "Inspect the result behind the headline.",
    intro:
      "Explore the released 100-rollout benchmark by exact task. All twenty fruit-and-destination selections include a certified Physical-2K success example.",
    fruit: "Select fruit",
    destination: "Destination",
    run: "Load evidence",
    session: "Command session",
    selected: "Selected slice",
    learned: "Learned first attempts",
    final: "Final system success",
    recovery: "Additional final successes",
    outOf: "out of five fixed-seed rollouts for this exact task",
    trace: "Execution trace",
    traceItems: ["task slice selected", "five fixed seeds loaded", "first attempts counted", "final results verified"],
    video: "Certified strict-physics success",
    release: "Release endpoints",
    scope:
      "Benchmark numbers come from formal evaluation. The attached examples are certified Physical-2K collection trajectories, not substitutes for benchmark rollouts.",
  },
  zh: {
    back: "返回项目首页",
    kicker: "交互式证据控制台",
    title: "查看总分背后的真实结果。",
    intro: "按精确任务浏览已发布的 100 次评测。20 个“水果 × 目标碗”选择均附一段经认证的 Physical-2K 成功样例。",
    fruit: "选择水果",
    destination: "目标盘位",
    run: "载入证据",
    session: "指令会话",
    selected: "当前结果切片",
    learned: "学习策略首次成功",
    final: "最终系统成功",
    recovery: "额外最终成功",
    outOf: "该精确任务共 5 次固定 seed 评测",
    trace: "执行轨迹",
    traceItems: ["选择任务切片", "载入五个固定 seed", "统计首次执行", "核验最终结果"],
    video: "严格物理成功示例",
    release: "公开发布地址",
    scope: "数值来自正式评测；附带视频是经认证的 Physical-2K 数据采集轨迹，不替代正式评测回合。",
  },
} as const;

const app = document.querySelector<HTMLDivElement>("#console-app");
if (!app) throw new Error("Missing #console-app mount point");

const base = import.meta.env.BASE_URL;
let locale: Locale = localStorage.getItem("radeonvla-reflex-locale") === "zh" ? "zh" : "en";
let selectedFruit: FruitId = "banana";
let destination: DestinationId = "white-left";
let commandVersion = 1;

function render(): void {
  const l = labels[locale];
  const selected = results.find((item) => item.id === selectedFruit) ?? results[0];
  const task = selected.tasks[destination];
  const recovered = task.final - task.learned;
  const offset = destinationOffset[destination];
  const exampleTaskId = `${selected.id}_${destination.replace("-", "_")}`;
  const exampleEpisode = selected.exampleEpisodeBase + offset;
  const exampleSeed = selected.exampleSeedBase + offset;
  const exampleLabel =
    locale === "zh"
      ? `Physical-2K 严格物理采集成功 · ${exampleTaskId} · episode ${String(exampleEpisode).padStart(4, "0")} · seed ${exampleSeed}`
      : `Physical-2K strict-physics collection success · ${exampleTaskId} · episode ${String(exampleEpisode).padStart(4, "0")} · seed ${exampleSeed}`;
  document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";

  app!.innerHTML = `
    <header class="console-header">
      <a class="console-brand" href="${base}index.html"><span></span><strong>RadeonVLA</strong><em>Reflex</em></a>
      <div class="console-header-actions">
        <div class="console-locale" role="group" aria-label="Language">
          <button data-locale="en" aria-pressed="${locale === "en"}">EN</button>
          <button data-locale="zh" aria-pressed="${locale === "zh"}">中</button>
        </div>
        <a href="${base}index.html">← ${l.back}</a>
      </div>
    </header>

    <main>
      <section class="console-hero">
        <p>${l.kicker}</p>
        <h1>${l.title}</h1>
        <div class="console-hero-bottom">
          <p>${l.intro}</p>
          <div><span>CHECKPOINT</span><strong>Physical-2K · 200K</strong></div>
          <div><span>FORMAL SUITE</span><strong>20 tasks × 5 seeds</strong></div>
        </div>
      </section>

      <section class="console-workspace">
        <aside class="console-controls">
          <div class="control-heading"><span>01</span><strong>${l.fruit}</strong></div>
          <div class="fruit-picker">
            ${results
              .map(
                (item) => `<button class="fruit-button fruit-${item.id}" data-fruit="${item.id}" aria-pressed="${
                  selected.id === item.id
                }"><i>${item.icon}</i><span>${item.label[locale]}</span><small>${item.final}/20</small></button>`,
              )
              .join("")}
          </div>
          <label class="destination-control">
            <span>${l.destination}</span>
            <select id="destination">
              <option value="white-left" ${destination === "white-left" ? "selected" : ""}>white · left</option>
              <option value="blue-left" ${destination === "blue-left" ? "selected" : ""}>blue · left</option>
              <option value="white-right" ${destination === "white-right" ? "selected" : ""}>white · right</option>
              <option value="blue-right" ${destination === "blue-right" ? "selected" : ""}>blue · right</option>
            </select>
          </label>
          <button class="load-button" id="load-evidence">${l.run}<span>→</span></button>
          <p class="console-scope">${l.scope}</p>
        </aside>

        <div class="console-output">
          <div class="session-bar"><span class="pulse"></span><small>${l.session}</small><strong>v${commandVersion}</strong><code>${selected.id}_${destination.replace("-", "_")}</code><span class="verified">VERIFIED</span></div>
          <div class="result-grid">
            <article class="result-summary">
              <p>${l.selected}</p>
              <h2>${selected.label[locale]} <span>/ ${destination.replace("-", " · ")}</span></h2>
              <div class="score-row">
                <div><strong>${task.learned}<small>/5</small></strong><span>${l.learned}</span></div>
                <div><strong>${task.final}<small>/5</small></strong><span>${l.final}</span></div>
                <div><strong>+${recovered}</strong><span>${l.recovery}</span></div>
              </div>
              <p class="sample-note">${l.outOf}</p>
            </article>
            <article class="trace-panel">
              <p>${l.trace}</p>
              <ol>
                ${l.traceItems
                  .map(
                    (item, index) => `<li class="active"><span>0${index + 1}</span><i></i><strong>${item}</strong></li>`,
                  )
                  .join("")}
              </ol>
            </article>
          </div>
          <article class="replay-panel">
            <div class="replay-copy"><small>02 / REPLAY</small><h2>${l.video}</h2><p>${exampleLabel}</p></div>
            <video controls muted playsinline preload="metadata" poster="${base}videos/task-success-world/${exampleTaskId}.webp" src="${base}videos/task-success-world/${exampleTaskId}.mp4"></video>
          </article>
        </div>
      </section>

      <section class="release-strip">
        <p>${l.release}</p>
        <a href="${projectLinks.dataset1k}" target="_blank" rel="noreferrer"><span>DATASET</span><strong>Physical-1K</strong><small>1,000 demos ↗</small></a>
        <a href="${projectLinks.dataset}" target="_blank" rel="noreferrer"><span>DATASET</span><strong>Physical-2K</strong><small>2,000 demos ↗</small></a>
        <a href="${projectLinks.model20k}" target="_blank" rel="noreferrer"><span>MODEL</span><strong>SmolVLA · 20K</strong><small>primary showcase ↗</small></a>
        <a href="${projectLinks.model50k}" target="_blank" rel="noreferrer"><span>MODEL</span><strong>SmolVLA · 50K</strong><small>checkpoint ↗</small></a>
        <a href="${projectLinks.finalModel}" target="_blank" rel="noreferrer"><span>MODEL</span><strong>SmolVLA · 200K</strong><small>checkpoint ↗</small></a>
        <a href="${projectLinks.evaluationVideos}" target="_blank" rel="noreferrer"><span>VIDEOS</span><strong>Evaluation evidence</strong><small>Hugging Face ↗</small></a>
        <a href="${projectLinks.source}" target="_blank" rel="noreferrer"><span>CODE</span><strong>GitHub source</strong><small>repository ↗</small></a>
      </section>
    </main>
  `;

  bindEvents();
}

function bindEvents(): void {
  document.querySelectorAll<HTMLButtonElement>("[data-locale]").forEach((button) => {
    button.addEventListener("click", () => {
      locale = button.dataset.locale === "zh" ? "zh" : "en";
      localStorage.setItem("radeonvla-reflex-locale", locale);
      render();
    });
  });

  document.querySelectorAll<HTMLButtonElement>("[data-fruit]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedFruit = button.dataset.fruit as FruitId;
      commandVersion += 1;
      render();
    });
  });

  document.querySelector<HTMLSelectElement>("#destination")?.addEventListener("change", (event) => {
    destination = (event.currentTarget as HTMLSelectElement).value as DestinationId;
  });

  document.querySelector<HTMLButtonElement>("#load-evidence")?.addEventListener("click", () => {
    destination = (document.querySelector<HTMLSelectElement>("#destination")?.value ?? destination) as DestinationId;
    commandVersion += 1;
    render();
  });
}

render();

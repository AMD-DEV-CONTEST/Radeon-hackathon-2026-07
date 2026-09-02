"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import {
  writeSpecFile,
  invokeSafe,
  isTauri,
  discoverIdea,
  converseIdea,
  generateSpec,
  refineSpec,
  startSession,
  assessIdeaContext,
} from "@/lib/api";
import {
  Zap,
  Play,
  RefreshCw,
  MessageSquare,
  Send,
  Sparkles,
  ChevronRight,
  ChevronLeft,
  Paperclip,
  X,
  Image as ImageIcon,
  Shield,
} from "lucide-react";
import { GlossaryTerm } from "@/components/GlossaryTerm";
import { MatrixRain } from "@/components/MatrixRain";
import {
  specGenerationBlockMessage,
  resolveLocalModelTag,
  type WorkReadiness,
} from "@/lib/work-readiness";

// Same live multi-agent chat + corpus/oracle-feedback entity as the Chat
// tab -- Ryan: "the same set up should be in the work part, the concept
// lab, etc. this chat should be layered throughout." One implementation,
// mounted here as a collapsible side rail (see the ConceptLab wrapper at
// the bottom of this file) rather than a second chat surface to keep in
// sync. ssr:false matches page.tsx's own dynamic import of this component
// (it talks to the Tauri IPC bridge, which doesn't exist during SSR).
const AgentChatPanel = dynamic(
  () => import("@/components/AgentChatPanel").then((m) => m.AgentChatPanel),
  { ssr: false, loading: () => <div className="h-full w-full bg-[var(--dtx-code-bg)]" /> }
);

// ─────────────────────────────────────────────────────────────────────────────
// RUNTIME GUARD — shown when browser dev server runs without Tauri
// ─────────────────────────────────────────────────────────────────────────────

function NativeRuntimeRequired() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-5 px-6 text-center select-none">
      <div className="w-12 h-12 rounded-2xl bg-amber-950/60 border border-amber-600/40 flex items-center justify-center shadow-[0_0_20px_rgba(245,158,11,0.15)]">
        <Shield size={22} className="text-amber-400" />
      </div>
      <div className="flex flex-col gap-2 max-w-xs">
        <p className="text-body font-black text-amber-300 tracking-tight">
          Native Runtime Required
        </p>
        <p className="text-label text-gray-500 leading-relaxed">
          The Hive Oracle requires the Tauri native bridge. This browser preview cannot reach Ollama
          or the Determinex backend.
        </p>
        <p className="text-label font-mono text-gray-700 mt-1">
          Launch via <span className="text-amber-500/80">boot.bat</span> to get the full native app.
        </p>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

interface Attachment {
  id: string;
  name: string;
  dataUrl: string; // base64 data URL — used for display and sending to LLM
  mimeType: string;
  colors?: string[]; // dominant colors extracted client-side
}

export type Message = { role: "user" | "oracle"; text: string; attachments?: Attachment[] };

/** Extract dominant colors from an image data URL by downsampling to a tiny canvas. */
async function extractColors(dataUrl: string, count = 6): Promise<string[]> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const size = 64;
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        resolve([]);
        return;
      }
      ctx.drawImage(img, 0, 0, size, size);
      const data = ctx.getImageData(0, 0, size, size).data;
      const buckets = new Map<string, number>();
      for (let i = 0; i < data.length; i += 4) {
        if (data[i + 3] < 128) continue;
        // Quantize to 32-step grid
        const r = Math.round(data[i] / 32) * 32;
        const g = Math.round(data[i + 1] / 32) * 32;
        const b = Math.round(data[i + 2] / 32) * 32;
        const key = `${r},${g},${b}`;
        buckets.set(key, (buckets.get(key) ?? 0) + 1);
      }
      const sorted = [...buckets.entries()].sort((a, b) => b[1] - a[1]);
      const hex = sorted.slice(0, count).map(([k]) => {
        const [r, g, b] = k.split(",").map(Number);
        return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
      });
      resolve(hex);
    };
    img.onerror = () => resolve([]);
    img.src = dataUrl;
  });
}

/** Read a File as a base64 data URL. */
function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export interface PathInfo {
  id: string;
  name: string;
  description: string;
  bestFor: string;
  stack: string;
  complexity: "low" | "medium" | "high";
  complexityReason?: string;
  buildTime: string;
  timelineReason?: string;
  prerequisites?: string[];
  color: string;
}

type Step = "idea" | "discovery" | "specReady" | "launching";

// ─────────────────────────────────────────────────────────────────────────────
// REFINEMENT CHIPS (shown in specReady for spot changes)
// ─────────────────────────────────────────────────────────────────────────────

const REFINEMENT_SUGGESTIONS = [
  { label: "Add auth", text: "Add JWT authentication with refresh tokens" },
  { label: "PostgreSQL", text: "Use PostgreSQL instead of SQLite" },
  { label: "Async", text: "Make all I/O non-blocking / async" },
  { label: "Rate limit", text: "Add rate limiting (100 req/min per user)" },
  { label: "Redis cache", text: "Add a Redis caching layer for hot data" },
  { label: "Logging", text: "Add structured JSON logging with log levels" },
  { label: "Tests", text: "Add unit and integration tests" },
  { label: "Docker", text: "Add Dockerfile and docker-compose" },
  { label: "OpenAPI", text: "Add OpenAPI / Swagger docs for all endpoints" },
  { label: "Metrics", text: "Expose Prometheus metrics at /metrics" },
];

// ─────────────────────────────────────────────────────────────────────────────
// GUIDED QUESTION BANKS
// ─────────────────────────────────────────────────────────────────────────────

const QUESTION_BANKS: Record<string, string[]> = {
  "Web + Mobile App": [
    "What is the core product people use on both web and mobile?",
    "Should the mobile app share the same backend and account system as the website?",
    "Which mobile targets matter first: iOS, Android, or both?",
    "What screens must exist on day one across web and mobile?",
  ],
  "CLI Tool": [
    "What commands should it have? (e.g. `run`, `list`, `delete`)",
    "Does it read or write files, a database, or call an external API?",
    "Any OS or platform constraints? (Windows-only, Linux daemon, etc.)",
    "Should it support a config file or environment variables?",
  ],
  "REST API": [
    "What data does it serve? (e.g. users, orders, sensor readings)",
    "Who consumes the API? (frontend app, mobile app, other services)",
    "Does it need authentication? (API key, JWT, OAuth — or none)",
    "Any rate limiting, versioning, or security requirements?",
  ],
  "Web App": [
    "What is the main action a user takes in the app?",
    "Who are the users — public visitors, authenticated accounts, or internal staff?",
    "Desktop, mobile, or both? Any browser requirements?",
    "What is the core data model? (e.g. posts, tasks, products, bookings)",
  ],
  Game: [
    "What is the core game loop — what does the player do every turn or second?",
    "2D or 3D? Turn-based or real-time?",
    "Single player, local multiplayer, or online multiplayer?",
    "What platform is the target? (desktop, browser, mobile)",
  ],
  Library: [
    "What problem does the library solve for the developer who imports it?",
    "What is the public API surface? (key functions, structs, or classes)",
    "Which language and ecosystem does it target?",
    "Any performance, compatibility, or licensing constraints?",
  ],
  "Data Pipeline": [
    "What is the data source? (database, API, files, streams)",
    "What transformations or enrichments happen to the data?",
    "Where does the output go? (database, file, message queue, dashboard)",
    "Does it run on a schedule, in real-time, or triggered by events?",
  ],
  "Developer Tool": [
    "What problem does it solve for developers?",
    "How is it invoked? (CLI, IDE extension, language server, build plugin)",
    "What languages or ecosystems does it integrate with?",
    "Any performance requirements? (must run in under N ms, must not block)",
  ],
  "Mobile App": [
    "What is the main purpose of the mobile app?",
    "Is the target platform Android, iOS, or both?",
    "What is the core user flow or primary screen?",
    "Does it need to connect to a backend API or handle offline storage?",
  ],
};

const BROAD_PATH_CHOICES: Omit<PathInfo, "id">[] = [
  {
    name: "Web + Mobile App",
    description:
      "A shared product delivered as a website plus native or cross-platform mobile apps.",
    bestFor: "Consumer products, SaaS companions, marketplaces, social apps",
    stack: "Next.js + API + React Native or Flutter",
    complexity: "high",
    complexityReason:
      "Needs shared backend, responsive web UX, mobile navigation, auth, and release packaging.",
    buildTime: "3-6 weeks",
    timelineReason:
      "Cross-platform flows and mobile packaging need more validation than a single surface.",
    color: "#2dd4bf",
  },
  {
    name: "Web App",
    description: "A browser-based product with screens, workflows, and persistent state.",
    bestFor: "Dashboards, internal tools, portals, SaaS workflows",
    stack: "Next.js + API + database",
    complexity: "medium",
    complexityReason: "Needs UI, routing, state, data storage, and verification.",
    buildTime: "1-2 weeks",
    timelineReason: "Most time goes into screens, data model, and end-to-end behavior.",
    color: "var(--dtx-alt-2)",
  },
  {
    name: "Developer Tool",
    description: "A workflow helper for engineers, scripts, builds, or IDE integration.",
    bestFor: "CLIs, formatters, code analyzers, project automation",
    stack: "Python, Rust, Go, or Node",
    complexity: "medium",
    complexityReason: "Needs reliable command behavior and testable edge cases.",
    buildTime: "2-5 days",
    timelineReason: "Scope depends on integrations and command surface.",
    color: "var(--dtx-alt)",
  },
  {
    name: "Data Pipeline",
    description: "A repeatable ingest, transform, validate, and export workflow.",
    bestFor: "ETL, reports, sync jobs, event processing",
    stack: "Python + SQL + scheduler",
    complexity: "medium",
    complexityReason: "Needs source contracts, validation, retries, and observability.",
    buildTime: "3-7 days",
    timelineReason: "Connectors and data quality checks drive the schedule.",
    color: "var(--dtx-ok)",
  },
  {
    name: "Game",
    description: "An interactive game loop with rules, state, input, and feedback.",
    bestFor: "Browser games, prototypes, simulations",
    stack: "Canvas, Three.js, or a game engine",
    complexity: "medium",
    complexityReason: "Needs interaction, rules, pacing, and visual feedback.",
    buildTime: "1-2 weeks",
    timelineReason: "Gameplay feel and asset polish take iteration.",
    color: "var(--dtx-warn)",
  },
  {
    name: "Library",
    description: "A reusable package with a documented public API.",
    bestFor: "SDKs, packages, shared logic, framework helpers",
    stack: "Package-native language and tests",
    complexity: "low",
    complexityReason: "Small surface area if the API is well-defined.",
    buildTime: "1-4 days",
    timelineReason: "Testing and docs are usually the main work.",
    color: "var(--dtx-info)",
  },
  {
    name: "Mobile App",
    description: "A phone-first app with screens, local state, and optional backend sync.",
    bestFor: "Consumer apps, field tools, companion apps",
    stack: "React Native, Flutter, Swift, or Kotlin",
    complexity: "high",
    complexityReason: "Needs device UX, platform constraints, and release packaging.",
    buildTime: "2-4 weeks",
    timelineReason: "Native polish, testing, and deployment add time.",
    color: "var(--dtx-alt)",
  },
];

export function requestedProjectTypes(ideaText: string): string[] {
  const text = ideaText.toLowerCase();
  const wantsWeb =
    /\b(web ?site|site|web app|webapp|frontend|browser|dashboard|portal|landing page|saas)\b/.test(
      text
    );
  const wantsMobile =
    /\b(mobile|phone|ios|android|native app|mobile app|app store|play store)\b/.test(text);
  const wantsCli = /\b(cli|command.?line|terminal tool|shell command|console app)\b/.test(text);
  const wantsApi = /\b(api|backend|server|service|endpoint|rest|graphql)\b/.test(text);
  const wantsGame = /\b(game|gameplay|player|level|3d|2d)\b/.test(text);
  const wantsPipeline = /\b(pipeline|etl|ingest|stream|warehouse|data flow|dataflow)\b/.test(text);

  const types: string[] = [];
  if (wantsWeb && wantsMobile) types.push("Web + Mobile App");
  if (wantsWeb) types.push("Web App");
  if (wantsMobile) types.push("Mobile App");
  if (wantsApi) types.push("REST API");
  if (wantsGame) types.push("Game");
  if (wantsPipeline) types.push("Data Pipeline");
  if (wantsCli) types.push("CLI Tool");
  return [...new Set(types)];
}

function pathChoiceForType(type: string): Omit<PathInfo, "id"> | null {
  if (type === "CLI Tool") {
    return {
      name: "CLI Tool",
      description: "A command-line tool for scripted or terminal-driven workflows.",
      bestFor: "Automation, local utilities, developer workflows",
      stack: "Rust, Go, Python, or Node",
      complexity: "low",
      complexityReason: "Small interaction surface and deterministic command behavior.",
      buildTime: "1-3 days",
      timelineReason: "Most effort goes into command parsing, file/API behavior, and tests.",
      color: "#fb923c",
    };
  }
  if (type === "REST API") {
    return {
      name: "REST API",
      description: "A backend service with endpoints, data contracts, and verification.",
      bestFor: "Mobile/web backends, integrations, internal services",
      stack: "FastAPI, Axum, Gin, Express, or similar",
      complexity: "medium",
      complexityReason: "Needs data modeling, auth decisions, endpoint tests, and deploy shape.",
      buildTime: "1-2 weeks",
      timelineReason: "Data contracts and security checks define the schedule.",
      color: "var(--dtx-info)",
    };
  }
  return BROAD_PATH_CHOICES.find((p) => p.name === type) ?? null;
}

export function prioritizePathChoices(discovered: PathInfo[], ideaText: string): PathInfo[] {
  const requested = requestedProjectTypes(ideaText);
  const requestedNames = new Set(requested.map((name) => name.toLowerCase()));
  const cliRequested = requestedNames.has("cli tool");
  const nonCliRequested = requested.length > 0 && !cliRequested;

  const requestedPaths = requested
    .map(pathChoiceForType)
    .filter((p): p is Omit<PathInfo, "id"> => Boolean(p))
    .map((p, i) => ({ ...p, id: `intent-${p.name.toLowerCase().replace(/\s|\+/g, "-")}-${i}` }));

  const normalizedDiscovered = discovered.filter((p) => {
    if (!nonCliRequested) return true;
    return p.name.toLowerCase() !== "cli tool";
  });

  const base = [...requestedPaths, ...normalizedDiscovered];
  const existing = new Set(base.map((p) => p.name.toLowerCase()));
  const extras = BROAD_PATH_CHOICES.filter((p) => !existing.has(p.name.toLowerCase())).map(
    (p, i) => ({ ...p, id: `manual-${p.name.toLowerCase().replace(/\s+/g, "-")}-${i}` })
  );
  return [...base, ...extras].slice(0, Math.max(6, base.length));
}

export function detectProjectType(paths: PathInfo[], ideaText = ""): string {
  const requested = requestedProjectTypes(ideaText);
  if (requested.length > 0) return requested[0];

  const primary = paths[0];
  const text = primary
    ? `${primary.name} ${primary.stack} ${primary.description}`.toLowerCase()
    : "";
  if (/\b(web \+ mobile|website.+mobile|mobile.+website)\b/.test(text)) return "Web + Mobile App";
  if (/\bcli\b|command.?line|terminal tool|shell script/.test(text)) return "CLI Tool";
  if (/\brest\b|\bapi\b|\bfastapi\b|\baxum\b|\bgin\b|\bexpress\b|http server/.test(text))
    return "REST API";
  if (/\b(mobile|android|ios|react native|flutter|kotlin)\b/.test(text)) return "Mobile App";
  if (/web app|next\.js|\breact\b|\bvite\b|\bsvelte\b|frontend/.test(text)) return "Web App";
  if (/\bgame\b|godot|unity|bevy|gameplay/.test(text)) return "Game";
  if (/\blibrary\b|\bcrate\b|\bpackage\b|\bsdk\b|framework/.test(text)) return "Library";
  if (/pipeline|\betl\b|data.?flow|ingestion|stream/.test(text)) return "Data Pipeline";
  if (/dev tool|\blsp\b|linter|formatter|build plugin/.test(text)) return "Developer Tool";
  return paths[0]?.name ?? "";
}

function userSafeSpecError(error: string | undefined): string {
  const raw = (error || "").trim();
  if (!raw) return "Spec generation failed. Check model setup and retry.";

  const userError = raw.match(/USER_ERROR:\s*([\s\S]+)/);
  if (userError?.[1]?.trim()) return userError[1].trim();

  const lower = raw.toLowerCase();
  if (lower.includes("ollama") && lower.includes("model") && lower.includes("not found")) {
    return "Spec generation could not continue because the selected Ollama model is not installed. Open Settings -> Models to repair local models, or pull the missing model in Ollama.";
  }
  if (
    lower.includes("ollama") &&
    (lower.includes("connection") || lower.includes("refused") || lower.includes("unreachable"))
  ) {
    return "Spec generation could not continue because Ollama is not reachable. Start Ollama, then retry.";
  }
  if (
    lower.includes("cloud model blocked") ||
    lower.includes("determinex_allow_cloud_fallback") ||
    lower.includes("determinex_allow_cloud_fallback")
  ) {
    return "Spec generation tried to use a cloud model, but cloud fallback is disabled. Choose a local model in Settings -> Models or explicitly enable cloud fallback.";
  }

  const useful = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(
      (line) =>
        line &&
        !line.includes("LiteLLM") &&
        !line.includes("botocore") &&
        !line.toLowerCase().includes("sagemaker") &&
        !line.toLowerCase().includes("bedrock") &&
        !line.includes("[SAFETY]")
    );

  return useful.length > 0
    ? `Spec generation failed. ${useful[useful.length - 1]}`
    : "Spec generation failed. Check model setup and retry.";
}

// ─────────────────────────────────────────────────────────────────────────────
// PATH CARD
// ─────────────────────────────────────────────────────────────────────────────

function PathCard({
  path,
  selected,
  dimmed,
  onClick,
}: {
  path: PathInfo;
  selected: boolean;
  dimmed?: boolean;
  onClick: () => void;
}) {
  const complexityColor =
    path.complexity === "low"
      ? "var(--dtx-ok)"
      : path.complexity === "medium"
        ? "var(--dtx-warn)"
        : "var(--dtx-fail)";
  return (
    <button
      onClick={onClick}
      className="text-left rounded-xl border p-2.5 transition-all hover:scale-[1.02] active:scale-[0.98] cursor-pointer"
      style={{
        opacity: dimmed ? 0.25 : 1,
        transform: dimmed ? "scale(0.97)" : undefined,
        borderColor: selected ? `${path.color}bb` : `${path.color}28`,
        background: selected ? `${path.color}14` : `${path.color}07`,
        boxShadow: selected ? `0 0 12px ${path.color}25` : "none",
      }}
    >
      <div className="text-label font-black tracking-wide" style={{ color: path.color }}>
        {path.name}
      </div>
      <div className="text-meta text-gray-400 mt-0.5 leading-snug">{path.description}</div>
      <div className="text-meta text-gray-600 mt-1 font-mono">{path.stack}</div>
      <div className="flex items-center justify-between mt-2">
        <span className="text-meta text-gray-600">{path.buildTime}</span>
        <span
          className="text-meta px-1.5 py-0.5 rounded-full font-bold"
          style={{ color: complexityColor, background: `${complexityColor}18` }}
        >
          {path.complexity}
        </span>
      </div>
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TYPING INDICATOR — three animated dots
// ─────────────────────────────────────────────────────────────────────────────

export function TypingIndicator() {
  return (
    <div className="flex gap-2 items-start">
      <div className="w-5 h-5 rounded-full bg-cyan-900/60 border border-cyan-500/40 flex items-center justify-center shrink-0 mt-0.5">
        <Sparkles size={9} className="text-cyan-400" />
      </div>
      <div className="bg-[var(--dtx-code-panel)] border border-cyan-500/20 rounded-xl rounded-tl-sm px-4 py-3 flex gap-1.5 items-center">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-bounce"
            style={{ animationDelay: `${i * 0.15}s`, animationDuration: "0.9s" }}
          />
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MESSAGE BUBBLE — supports typewriter-in-progress text
// ─────────────────────────────────────────────────────────────────────────────

export function MessageBubble({ msg }: { msg: Message }) {
  const isOracle = msg.role === "oracle";

  const lines = msg.text.split("\n");
  const rendered = lines.map((line, li) => {
    const parts = line.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).map((p, j) => {
      if (p.startsWith("**") && p.endsWith("**"))
        return (
          <strong key={j} className="text-white font-bold">
            {p.slice(2, -2)}
          </strong>
        );
      if (p.startsWith("*") && p.endsWith("*"))
        return (
          <em key={j} className="text-gray-400 italic">
            {p.slice(1, -1)}
          </em>
        );
      return p;
    });
    return (
      <span key={li}>
        {parts}
        {li < lines.length - 1 && <br />}
      </span>
    );
  });

  if (isOracle) {
    return (
      <div className="flex gap-2 items-start">
        <div className="w-5 h-5 rounded-full bg-cyan-900/60 border border-cyan-500/40 flex items-center justify-center shrink-0 mt-0.5">
          <Sparkles size={9} className="text-cyan-400" />
        </div>
        <div className="flex-1 bg-[var(--dtx-code-panel)] border border-cyan-500/20 rounded-xl rounded-tl-sm px-3 py-2.5 text-label text-gray-300 leading-relaxed">
          {rendered}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-end">
      <div className="max-w-[92%] flex flex-col gap-1.5 items-end">
        {msg.attachments && msg.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 justify-end">
            {msg.attachments.map((att) => (
              <div key={att.id} className="relative">
                <img
                  src={att.dataUrl}
                  alt={att.name}
                  className="w-20 h-20 object-cover rounded-xl border border-[var(--dtx-code-border)]"
                />
                {att.colors && att.colors.length > 0 && (
                  <div className="absolute bottom-1 left-1 flex gap-0.5">
                    {att.colors.slice(0, 4).map((c, i) => (
                      <div
                        key={i}
                        className="w-2.5 h-2.5 rounded-sm border border-black/30"
                        style={{ background: c }}
                      />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <div className="bg-[#1c2128] border border-[var(--dtx-code-border)] rounded-xl rounded-tr-sm px-3 py-2.5 text-label text-gray-400 leading-relaxed">
          {msg.text}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// PROPS
// ─────────────────────────────────────────────────────────────────────────────

interface ConceptLabProps {
  onSessionLaunched?: (sessionId: string) => void;
  onSpecChange?: (spec: string) => void;
  onPathPreview?: (path: PathInfo | null) => void;
  confirmedPath?: PathInfo | null;
  selectedProjectName?: string;
  projectPath?: string;
  selectedModel?: string;
  onOpenProjectLibrary?: () => void;
  onAnsweredCountChange?: (count: number) => void;
  onConsultingChange?: (active: boolean) => void;
  /** Pre-fill the idea textarea from outside (e.g. Zone 2 example clicks) */
  externalIdea?: string;
  /**
   * Fired when Quick Verify finishes, so the run can be recorded as evidence.
   * Without it the verdict never leaves this component and the Proof ledger stays empty
   * after a successful verified build.
   */
  onVerified?: (result: {
    solved: boolean;
    checks: number | null;
    proof: string | null;
    idea: string;
  }) => void;
  /** Dominant colors extracted from user-attached images — used to tint the wireframe preview */
  onColorHintsChange?: (colors: string[]) => void;
  workReadiness?: WorkReadiness;
  onOpenModelSettings?: () => void;
  /** Model-route picker, rendered next to the submit action. Passed in as a
      node (not built here) so this component stays decoupled from the
      routing/AiRouteSelect internals -- page.tsx owns which control that is. */
  modelPicker?: React.ReactNode;
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN COMPONENT
// ─────────────────────────────────────────────────────────────────────────────

function ConceptLabInner({
  onSessionLaunched,
  onSpecChange,
  onPathPreview,
  confirmedPath,
  selectedProjectName = "Current project",
  projectPath = "",
  selectedModel = "auto",
  onOpenProjectLibrary,
  onAnsweredCountChange,
  onConsultingChange,
  externalIdea,
  onVerified,
  onColorHintsChange,
  workReadiness,
  onOpenModelSettings,
  modelPicker,
}: ConceptLabProps) {
  // ── Runtime gate — bail early when there is no Tauri IPC bridge ───────────
  // Checking here (component body, not module scope) because Next.js evaluates
  // module-level code during SSR before window.__TAURI_INTERNALS__ is injected.
  const [step, setStep] = useState<Step>("idea");

  // Idea step
  const [idea, setIdea] = useState("");
  const [consulting, setConsulting] = useState(false);

  // Quick Verify: the instant, single-function idea->sound-oracle->verified-
  // program path (scripts/determinex_synthesize.py + determinex_build_from_idea.py
  // via the preview_idea_oracle/build_idea Tauri commands). Previously this
  // capability only existed on a separate, buried "Idea Lab" addon page with
  // its own bare textarea -- Ryan, live: "the work tab should be the same
  // thing as idea lab... i dont understand why the main functionality is
  // buried in favor of... a watered down version of something else on the
  // side." Folded in here as a second action on the SAME textarea instead of
  // a second place to type an idea. Full-project conversational discovery
  // (handleConsult, below) is untouched -- this is additive, for when the
  // idea is small enough to have concrete input/output examples.
  const [quickVerifying, setQuickVerifying] = useState<"preview" | "build" | null>(null);
  const [quickPreview, setQuickPreview] = useState<Record<string, unknown> | null>(null);
  const [quickBuild, setQuickBuild] = useState<Record<string, unknown> | null>(null);
  const [quickError, setQuickError] = useState<string | null>(null);

  const runQuickPreview = useCallback(async () => {
    if (!idea.trim()) return;
    setQuickVerifying("preview");
    setQuickError(null);
    setQuickBuild(null);
    try {
      const res = await invokeSafe<{ status?: string; payload?: Record<string, unknown> }>(
        "preview_idea_oracle",
        { ideaText: idea, modelId: resolveLocalModelTag(selectedModel) }
      );
      if (!res) {
        setQuickError("Quick Verify is unavailable right now (native backend not reachable).");
        return;
      }
      setQuickPreview({ status: res.status, ...(res.payload ?? {}) });
    } catch (e) {
      setQuickError(`Preview failed: ${e}`);
    } finally {
      setQuickVerifying(null);
    }
  }, [idea, selectedModel]);

  const runQuickBuild = useCallback(async () => {
    if (!idea.trim()) return;
    setQuickVerifying("build");
    setQuickError(null);
    try {
      const res = await invokeSafe<{ status?: string; payload?: Record<string, unknown> }>(
        "build_idea",
        { ideaText: idea, optIn: true, modelId: resolveLocalModelTag(selectedModel) }
      );
      if (!res) {
        setQuickError("Build is unavailable right now (native backend not reachable).");
        return;
      }
      const built: Record<string, unknown> = { status: res.status, ...(res.payload ?? {}) };
      setQuickBuild(built);
      // Report the verdict OUT, so the run leaves evidence where the product says evidence
      // lives. Until now this result stayed local to this component: a program that had
      // genuinely passed a synthesized oracle produced no matrixLogs line and no
      // agentStatus.verdict, so the Proof panel -- fed by exactly those two -- rendered "No
      // runs yet / No evidence yet" immediately after a successful verified build. For a
      // system whose whole claim is that nothing is accepted without proof, a verified build
      // recording no proof is a gap, not a design choice.
      const solved = built.solved === true || /solved|verified|passes/i.test(String(built.status ?? ""));
      onVerified?.({
        solved,
        checks: typeof built.n_checks === "number" ? built.n_checks : null,
        proof: typeof built.proof === "string" ? built.proof : null,
        idea,
      });
    } catch (e) {
      setQuickError(`Build failed: ${e}`);
    } finally {
      setQuickVerifying(null);
    }
  }, [idea, selectedModel, onVerified]);

  // Sync externalIdea (from Zone 2 example clicks) into local idea state
  useEffect(() => {
    if (externalIdea && step === "idea") setIdea(externalIdea);
  }, [externalIdea, step]);

  // Discovery step
  const [paths, setPaths] = useState<PathInfo[]>([]);
  //: Directions the user's own answers removed, kept so the UI can SAY why rather than
  //: silently shrinking the grid.
  const [ruledOut, setRuledOut] = useState<{ name: string; why: string }[]>([]);
  const [selectedPathId, setSelectedPathId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [oracleThinking, setOracleThinking] = useState(false); // waiting for response
  const [oracleTyping, setOracleTyping] = useState<string | null>(null); // typewriter text
  // Count how many user turns have happened in discovery (proxy for answered Oracle questions)
  const [userTurnCount, setUserTurnCount] = useState(0);

  // Guided mode state
  const [guidedMode, setGuidedMode] = useState(false);
  const [guidedType, setGuidedType] = useState("");
  const [guidedQuestions, setGuidedQuestions] = useState<string[]>([]);
  const [currentQuestionIdx, setCurrentQuestionIdx] = useState(0);
  const [guidedAnswers, setGuidedAnswers] = useState<{ q: string; a: string }[]>([]);
  const [freeFormMode, setFreeFormMode] = useState(false);
  // What the interview has actually established, and what it still lacks. Carried across
  // rounds so a round that satisfies nothing new can be recognised as stalled rather than
  // answered with the same question in different words.
  const [contextSatisfied, setContextSatisfied] = useState<string[]>([]);
  const [contextMissing, setContextMissing] = useState<string[]>([]);

  // specReady step
  const [spec, setSpec] = useState("");
  const [specInput, setSpecInput] = useState("");
  const [specRefining, setSpecRefining] = useState(false);
  const [specOracleTyping, setSpecOracleTyping] = useState<string | null>(null);
  const [specMessages, setSpecMessages] = useState<Message[]>([]);

  // Launch
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);

  // Attachments for the idea step (sent with discover_idea)
  const [ideaAttachments, setIdeaAttachments] = useState<Attachment[]>([]);
  // Attachments staged for the current discovery message (cleared after send)
  const [pendingAttachments, setPendingAttachments] = useState<Attachment[]>([]);
  // Drag-over state for drop targets
  const [ideaDragOver, setIdeaDragOver] = useState(false);
  const [discDragOver, setDiscDragOver] = useState(false);

  const ideaFileRef = useRef<HTMLInputElement>(null);
  const ideaTextareaRef = useRef<HTMLTextAreaElement>(null);
  const discFileRef = useRef<HTMLInputElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const specChatEndRef = useRef<HTMLDivElement>(null);
  const typewriterRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, oracleThinking, oracleTyping]);

  useEffect(() => {
    specChatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [specMessages, specOracleTyping]);

  // When the user confirms a path from Zone 2, pre-fill the input and focus it
  useEffect(() => {
    if (!confirmedPath) return;
    const canPrefill =
      step === "idea" ||
      (step === "discovery" &&
        !guidedMode &&
        oracleTyping === null &&
        messages.length === 0 &&
        !input.trim());
    if (canPrefill) {
      const prereqLine = confirmedPath.prerequisites?.length
        ? ` I understand I'll need: ${confirmedPath.prerequisites.map((p) => p.split("—")[0].trim()).join(", ")}.`
        : "";
      setInput(
        `I'd like to go with the ${confirmedPath.name} approach — ${confirmedPath.description}${prereqLine} What questions do you have?`
      );
    }
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [confirmedPath, guidedMode, input, messages.length, oracleTyping, step]);

  // Sync state to OracleArena in Zone 2
  useEffect(() => {
    window.dispatchEvent(
      new CustomEvent("oracle-sync", {
        detail: {
          step,
          messages,
          oracleThinking,
          oracleTyping,
          paths,
          guidedMode,
          guidedType,
          guidedQuestions,
          currentQuestionIdx,
          guidedAnswers,
        },
      })
    );
  }, [
    step,
    messages,
    oracleThinking,
    oracleTyping,
    paths,
    guidedMode,
    guidedType,
    guidedQuestions,
    currentQuestionIdx,
    guidedAnswers,
  ]);

  // Typewriter effect — animates Oracle text character by character
  const typewriterAnimate = useCallback(
    (
      text: string | null | undefined,
      setTyping: (t: string | null) => void,
      onComplete: (text: string) => void
    ) => {
      const safeText = text ?? "";
      if (typewriterRef.current) clearTimeout(typewriterRef.current);
      if (!safeText) {
        setTyping(null);
        onComplete("");
        return;
      }
      let i = 0;
      // Speed: finish in ≤2.5s regardless of length
      const delay = Math.max(6, Math.min(18, 2500 / safeText.length));

      const tick = () => {
        i++;
        if (i <= safeText.length) {
          setTyping(safeText.slice(0, i));
          typewriterRef.current = setTimeout(tick, delay);
        } else {
          setTyping(null);
          onComplete(safeText);
        }
      };
      setTyping("");
      typewriterRef.current = setTimeout(tick, delay);
    },
    []
  );

  // Add a completed Oracle message to the discovery chat
  const pushOracleMessage = useCallback((text: string) => {
    setMessages((prev) => [...prev, { role: "oracle", text }]);
  }, []);

  // Add a completed Oracle message to the spec chat
  const pushSpecOracleMessage = useCallback((text: string) => {
    setSpecMessages((prev) => [...prev, { role: "oracle", text }]);
  }, []);

  // ── Attachment handling ───────────────────────────────────────────────────

  // Emit color hints whenever attachments change — useEffect avoids setState-in-render
  useEffect(() => {
    const allColors = [...ideaAttachments, ...pendingAttachments].flatMap((a) => a.colors ?? []);
    onColorHintsChange?.(allColors.slice(0, 6));
  }, [ideaAttachments, pendingAttachments, onColorHintsChange]);

  const processFiles = useCallback(
    async (files: FileList | File[], target: "idea" | "discovery") => {
      const accepted = Array.from(files).filter((f) => f.type.startsWith("image/"));
      if (!accepted.length) return;

      const newAttachments: Attachment[] = [];
      for (const file of accepted) {
        const dataUrl = await readFileAsDataUrl(file);
        const colors = await extractColors(dataUrl);
        newAttachments.push({
          id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
          name: file.name,
          dataUrl,
          mimeType: file.type,
          colors,
        });
      }

      if (target === "idea") {
        setIdeaAttachments((prev) => [...prev, ...newAttachments].slice(0, 4));
      } else {
        setPendingAttachments((prev) => [...prev, ...newAttachments].slice(0, 4));
      }
    },
    []
  );

  const removeIdeaAttachment = (id: string) => {
    setIdeaAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  const removePendingAttachment = (id: string) => {
    setPendingAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  // ── Step 1: Consult Oracle — discover paths ────────────────────────────────

  const handleConsult = async () => {
    if (!idea.trim()) return;
    setConsulting(true);
    onConsultingChange?.(true);
    try {
      const discoverPromise = discoverIdea(
        idea,
        ideaAttachments.map((a) => ({
          name: a.name,
          mime_type: a.mimeType,
          data: a.dataUrl.split(",")[1] ?? "",
        })),
        selectedModel
      );

      // 180s, not 45s.
      //
      // Measured 2026-08-02 on this machine: a warm local 7B answers `discover_idea` in 21
      // seconds, consistently, through this exact IPC path. A 45s budget left barely two
      // seconds of margin over the real cost, so ordinary variance -- a cold Python spawn, a
      // litellm import, another model briefly sharing the GPU -- tipped it over. The user
      // was then told "Is the model loaded?" about a model that was loaded and working.
      // Blaming the model for our own budget is the same error as reporting a timeout as a
      // defect in the user's code.
      const timeoutPromise = new Promise<{ ok: boolean; data?: any; error?: string }>((_, reject) =>
        setTimeout(
          () =>
            reject(
              new Error(
                "The Oracle did not answer within 3 minutes. A local model on modest " +
                  "hardware can take 20-60s; if this keeps happening, choose a smaller " +
                  "model in Settings or point Determinex at a faster endpoint."
              )
            ),
          180000
        )
      );

      const res = await Promise.race([discoverPromise, timeoutPromise]);
      if (res.ok && res.data) {
        const discoveredPaths = (res.data.paths ?? []) as PathInfo[];
        const visiblePaths = prioritizePathChoices(discoveredPaths, idea);
        setPaths(visiblePaths);
        setMessages([]);
        setOracleThinking(false);
        setStep("discovery");
        onPathPreview?.(null);

        // Activate guided mode if we have a question bank for this project type
        const detectedType = detectProjectType(visiblePaths, idea);
        const bank = QUESTION_BANKS[detectedType];
        if (bank && bank.length > 0) {
          setGuidedType(detectedType);
          setGuidedQuestions(bank);
          setCurrentQuestionIdx(0);
          setGuidedAnswers([]);
          setGuidedMode(true);
          setFreeFormMode(false);
          // Oracle introduces guided mode instead of generic message
          const intro = `I've identified this as a **${detectedType}** project. I'll ask you ${bank.length} quick questions so I can write an accurate spec — no guessing required.\n\n${bank[0]}`;
          typewriterAnimate(intro, setOracleTyping, pushOracleMessage);
        } else {
          // No bank matched — fall back to free-form conversation
          setGuidedMode(false);
          typewriterAnimate(res.data.message, setOracleTyping, pushOracleMessage);
        }
      } else {
        // Fallback: go straight to discovery with error shown as Oracle message
        setStep("discovery");
        pushOracleMessage(
          `Couldn't analyze your idea (${res.error}). Describe more and I'll ask questions.`
        );
      }
    } catch (e) {
      setStep("discovery");
      pushOracleMessage(
        `Connection error: ${e}. Describe your idea more and we'll work through it.`
      );
    } finally {
      setConsulting(false);
      onConsultingChange?.(false);
    }
  };

  // ── Step 2: Converse — back and forth until ready ─────────────────────────

  const handleConverse = async () => {
    const userText = input.trim();
    if (!userText && pendingAttachments.length === 0) return;
    setInput("");

    const sentAttachments = [...pendingAttachments];
    setPendingAttachments([]);

    const newMessages: Message[] = [
      ...messages,
      { role: "user", text: userText, attachments: sentAttachments },
    ];
    setMessages(newMessages);
    const nextCount = userTurnCount + 1;
    setUserTurnCount(nextCount);
    onAnsweredCountChange?.(Math.min(nextCount, 5));
    setOracleThinking(true);

    try {
      const payload = {
        idea,
        messages: newMessages.map((m) => ({ role: m.role, text: m.text })),
        user_message: userText,
        attachments: sentAttachments.map((a) => ({
          name: a.name,
          mime_type: a.mimeType,
          data: a.dataUrl.split(",")[1] ?? "",
        })),
        model_override: selectedModel,
      };
      const conversePromise = converseIdea(payload);
      const timeoutPromise = new Promise<{ ok: boolean; data?: any; error?: string }>((_, reject) =>
        setTimeout(
          // Same 45s -> 180s correction as the discover call above; a conversational turn
          // costs the same local model roughly the same time.
          () =>
            reject(
              new Error(
                "The Oracle did not answer within 3 minutes. A local model on modest " +
                  "hardware can take 20-60s per turn."
              )
            ),
          180000
        )
      );

      const res = await Promise.race([conversePromise, timeoutPromise]);

      setOracleThinking(false);

      if (res.ok && res.data) {
        const { response, ready_to_spec, spec_summary } = res.data;

        // NARROW THE GRID AS THE ANSWERS ARRIVE. The direction cards were computed once at
        // discovery and never touched again, so a user could answer "terminal only, no
        // browser" and keep staring at "Web + Mobile App, 3-6 weeks, high". The backend
        // re-derives the surviving directions from the idea PLUS everything said since, and
        // returns what it removed with a reason -- a card that vanishes silently reads as a
        // bug rather than as the system listening.
        const narrowed = res.data.paths;
        if (narrowed && narrowed.length > 0) {
          setPaths((prev) => (narrowed.length < prev.length || prev.length === 0 ? narrowed : prev));
          const dropped = res.data.ruled_out ?? [];
          if (dropped.length > 0) {
            setRuledOut(dropped);
          }
        }

        typewriterAnimate(response, setOracleTyping, (text) => {
          pushOracleMessage(text);
          if (ready_to_spec) {
            // Generate the spec from full conversation context
            generateSpecFromContext(spec_summary ?? "");
          }
        });
      } else {
        pushOracleMessage(`Something went wrong: ${res.error ?? "unknown"}`);
      }
    } catch (e) {
      setOracleThinking(false);
      pushOracleMessage(`Connection error: ${e}`);
    }
  };

  // When Oracle says ready_to_spec, build context and call generate_spec
  const generateSpecFromContext = async (specSummary: string) => {
    const readinessBlock = specGenerationBlockMessage(workReadiness);
    if (readinessBlock) {
      setOracleThinking(false);
      pushOracleMessage(readinessBlock);
      onOpenModelSettings?.();
      return;
    }

    setOracleThinking(true);

    const historyText = messages
      .map((m) => `${m.role === "user" ? "User" : "Oracle"}: ${m.text}`)
      .join("\n\n");

    const contextPrompt =
      `GENERATE FROM DISCOVERY CONVERSATION\n\n` +
      `Original idea: ${idea}\n\n` +
      `Discovery conversation:\n${historyText}\n\n` +
      (specSummary ? `Oracle's summary: ${specSummary}\n\n` : "") +
      `Based on this conversation, generate the formal Determinex MD spec. ` +
      `Be specific and concrete — use exactly what was discussed. Do not assume or invent details that were not covered.`;

    try {
      const res = await generateSpec(contextPrompt, selectedModel);
      setOracleThinking(false);
      if (res.ok && res.data) {
        const newSpec = (res.data.spec ?? "").trim();
        if (!newSpec) {
          pushOracleMessage(
            "Spec generation returned empty. Try describing your idea in more detail."
          );
          return;
        }
        setSpec(newSpec);
        onSpecChange?.(newSpec);
        setSpecMessages([
          {
            role: "oracle",
            text: "Your spec is ready. I've written it based on everything we discussed — review it on the right. You can make spot changes here, or hit **Build It** when you're happy.",
          },
        ]);
        setStep("specReady");
      } else {
        pushOracleMessage(userSafeSpecError(res.error));
      }
    } catch (e) {
      setOracleThinking(false);
      pushOracleMessage(userSafeSpecError(String(e)));
    }
  };

  // ── Step 3: Spec ready — spot changes only ────────────────────────────────

  const handleSpecRefineWith = async (requestText: string) => {
    if (!requestText.trim() || !spec.trim() || specRefining || launching) return;
    setSpecInput("");
    setSpecRefining(true);
    setSpecMessages((prev) => [...prev, { role: "user", text: requestText }]);
    try {
      const res = await refineSpec(spec, requestText, selectedModel);
      setSpecRefining(false);
      if (res.ok && res.data) {
        setSpec(res.data.spec);
        onSpecChange?.(res.data.spec);
        typewriterAnimate(res.data.response, setSpecOracleTyping, pushSpecOracleMessage);
      } else {
        pushSpecOracleMessage(`Something went wrong: ${res.error ?? "unknown"}`);
      }
    } catch (e) {
      setSpecRefining(false);
      pushSpecOracleMessage(`Error: ${e}`);
    }
  };

  // Guided mode: record answer and advance to next question (or trigger spec gen)
  const handleGuidedAnswer = async () => {
    const userText = input.trim();
    if (!userText) return;
    setInput("");

    const newAnswer = { q: guidedQuestions[currentQuestionIdx], a: userText };
    const allAnswers = [...guidedAnswers, newAnswer];
    setGuidedAnswers(allAnswers);

    // Add to visible chat for context
    setMessages((prev) => [...prev, { role: "user", text: userText }]);

    const nextIdx = currentQuestionIdx + 1;
    setUserTurnCount(nextIdx);
    onAnsweredCountChange?.(Math.min(nextIdx, guidedQuestions.length));

    if (nextIdx < guidedQuestions.length) {
      // Show next question as Oracle message
      setCurrentQuestionIdx(nextIdx);
      const nextQ = guidedQuestions[nextIdx];
      typewriterAnimate(nextQ, setOracleTyping, pushOracleMessage);
    } else {
      // The static bank is exhausted. That is NOT the same as knowing enough.
      //
      // This used to generate the spec here unconditionally, so four thoughtful answers
      // that happened to contain no checkable behaviour still produced a spec, a build,
      // and a green compiler oracle that proved nothing -- compiling is not the same as
      // being what was asked for. Now we ask whether a SOUND ORACLE can actually be
      // synthesized from what we have, and keep interviewing while the answer is no.
      setCurrentQuestionIdx(nextIdx);
      void continueUntilContextIsSufficient(allAnswers);
    }
  };

  /**
   * Keep interviewing until the answers can produce a sound oracle.
   *
   * Termination is not a counter. It is one of three real conditions:
   *   - the backend reports the context sufficient (a sound oracle is synthesizable);
   *   - a whole round establishes nothing new (`stalled`) -- say so and offer to build;
   *   - the assessment is unavailable, in which case proceed rather than trapping the user
   *     behind a check that cannot run.
   */
  const continueUntilContextIsSufficient = async (
    allAnswers: { q: string; a: string }[]
  ) => {
    const buildSpec = (note?: string) => {
      const answersText = allAnswers
        .filter(({ a }) => a && a !== "(skipped)")
        .map(({ q, a }) => `Q: ${q}\nA: ${a}`)
        .join("\n\n");
      typewriterAnimate(
        note ?? "All set — I have what I need. Generating your specification now...",
        setOracleTyping,
        (text) => {
          pushOracleMessage(text);
          generateSpecFromContext(
            `GUIDED SETUP COMPLETE\n\n` +
              `Project type: ${guidedType}\n` +
              `Original idea: ${idea}\n\n` +
              `[GUIDED ANSWERS]\n${answersText}\n\n` +
              `Based on these answers, generate the formal Determinex MD spec. ` +
              `Be specific and concrete. Do not invent details beyond what was provided.`
          );
        }
      );
    };

    const res = await assessIdeaContext({
      idea,
      answers: allAnswers.map(({ a }) => a),
      asked: allAnswers.map(({ q }) => q),
      previous_satisfied: contextSatisfied,
    });

    if (!res.ok || !res.data) {
      // The check is an improvement, not a gate to hold the user hostage to.
      buildSpec();
      return;
    }

    const a = res.data;
    setContextSatisfied(a.satisfied);
    setContextMissing(a.missing);

    if (a.sufficient) {
      buildSpec(`I have enough now — ${a.rationale}. Generating your specification...`);
      return;
    }

    if (a.stalled || a.questions.length === 0) {
      buildSpec(
        "That last round didn't add anything new, so I'll stop asking and build with " +
          `what we have. Note that I still don't have: ${a.missing.join(", ")}.`
      );
      return;
    }

    // Genuinely more to learn: extend the interview with questions derived from what is
    // ABSENT, so a question can only be asked while the thing it asks for is missing.
    setGuidedQuestions((prev) => [...prev, ...a.questions]);
    typewriterAnimate(a.questions[0], setOracleTyping, pushOracleMessage);
  };

  const handleSkipQuestion = () => {
    const skippedAnswer = { q: guidedQuestions[currentQuestionIdx], a: "(skipped)" };
    const allAnswers = [...guidedAnswers, skippedAnswer];
    setGuidedAnswers(allAnswers);

    const nextIdx = currentQuestionIdx + 1;
    setCurrentQuestionIdx(nextIdx);
    onAnsweredCountChange?.(Math.min(nextIdx, guidedQuestions.length));

    if (nextIdx < guidedQuestions.length) {
      const nextQ = guidedQuestions[nextIdx];
      typewriterAnimate(nextQ, setOracleTyping, pushOracleMessage);
    } else {
      // Same completeness check as the answer path. Skipping four questions must not be a
      // way to "complete" the interview -- a skipped answer contributes no context, so the
      // assessment will simply keep asking for what is still genuinely missing.
      void continueUntilContextIsSufficient(allAnswers);
    }
  };

  // ── Build ─────────────────────────────────────────────────────────────────

  const handleBuild = async () => {
    if (!spec.trim()) return;
    setLaunching(true);
    setLaunchError(null);
    try {
      const specPath = await writeSpecFile(spec);
      // Extract language from ## Language section; fall back to "rust"
      const langMatch = spec.match(/^##\s*Language\s*\n([a-zA-Z0-9_-]+)/m);
      const lang = langMatch ? langMatch[1].trim().toLowerCase() : "rust";
      const res = await startSession(specPath, lang, 2.0, selectedModel);
      if (res.ok && res.data) {
        onSessionLaunched?.(res.data.session_id);
      } else {
        setLaunchError(res.error || "Failed to start session");
        setLaunching(false);
      }
    } catch (e) {
      setLaunchError(String(e));
      setLaunching(false);
    }
  };

  const handleReset = () => {
    setStep("idea");
    setIdea("");
    setPaths([]);
    setSelectedPathId(null);
    setMessages([]);
    setInput("");
    setOracleThinking(false);
    setOracleTyping(null);
    setUserTurnCount(0);
    setSpec("");
    setSpecMessages([]);
    setSpecInput("");
    setSpecRefining(false);
    setSpecOracleTyping(null);
    setLaunchError(null);
    setLaunching(false);
    setIdeaAttachments([]);
    setPendingAttachments([]);
    // Guided mode
    setGuidedMode(false);
    setGuidedType("");
    setGuidedQuestions([]);
    setCurrentQuestionIdx(0);
    setGuidedAnswers([]);
    setFreeFormMode(false);
    onPathPreview?.(null);
    onAnsweredCountChange?.(0);
    onColorHintsChange?.([]);
    if (typewriterRef.current) clearTimeout(typewriterRef.current);
  };

  const selectPath = (path: PathInfo) => {
    setSelectedPathId(path.id);
    onPathPreview?.(path);
  };

  // ─────────────────────────────────────────────────────────────────────────
  // RENDER: IDEA STEP
  // ─────────────────────────────────────────────────────────────────────────

  if (!isTauri()) {
    return <NativeRuntimeRequired />;
  }

  if (step === "idea") {
    return (
      <div className="flex flex-col h-full bg-[var(--dtx-code-bg)] text-gray-300 overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)] shrink-0">
          <h2 className="text-body font-black uppercase tracking-widest text-cyan-400 flex items-center gap-2">
            <Zap size={13} /> What are you building?
          </h2>
          <p className="text-label text-gray-500 mt-1">
            Start something new, continue an existing project, or point Determinex at a codebase to
            scan before code is written.
          </p>
        </div>

        <div className="flex-1 flex flex-col p-4 gap-3 min-h-0 overflow-hidden">
          <div className="shrink-0 rounded-xl border border-cyan-500/20 bg-cyan-950/10 p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-eyebrow font-black uppercase tracking-widest text-cyan-300">
                  Active project
                </div>
                <div className="mt-1 truncate text-body font-black text-gray-100">
                  {selectedProjectName}
                </div>
                <div className="mt-1 truncate font-mono text-meta text-gray-600">
                  {projectPath ||
                    "No folder selected yet. Add a project cover or describe a new build."}
                </div>
              </div>
              {onOpenProjectLibrary && (
                <button
                  type="button"
                  onClick={onOpenProjectLibrary}
                  className="shrink-0 rounded-lg border border-cyan-400/30 bg-cyan-950/30 px-3 py-2 text-eyebrow font-black uppercase tracking-widest text-cyan-300 transition-colors hover:bg-cyan-900/40"
                >
                  Choose project
                </button>
              )}
            </div>
            <div className="mt-3 grid grid-cols-3 gap-1.5">
              {(
                [
                  [
                    "New idea",
                    "Describe the product or fix.",
                    () => ideaTextareaRef.current?.focus(),
                  ],
                  [
                    "Existing repo",
                    "Select a project or folder first.",
                    () => onOpenProjectLibrary?.(),
                  ],
                  [
                    "Imported app",
                    "Paste docs, URL notes, or screenshots.",
                    // Previously identical to "New idea" (just focused the
                    // textarea) despite promising screenshot import -- the
                    // attach picker already exists (the Paperclip button
                    // below, wired to ideaFileRef) but this tile never
                    // triggered it. "Docs"/"URL notes" are still just
                    // free text in the same textarea (honest: no doc/URL
                    // parser exists), but "screenshots" now does something
                    // real and distinct from "New idea".
                    () => ideaFileRef.current?.click(),
                  ],
                ] as const
              ).map(([label, detail, onTileClick]) => (
                <button
                  key={label}
                  type="button"
                  onClick={onTileClick}
                  className="rounded-lg border border-white/8 bg-black/25 px-2 py-2 text-left transition-colors hover:border-cyan-500/40 hover:bg-cyan-950/20"
                >
                  <div className="text-eyebrow font-black uppercase tracking-widest text-gray-300">
                    {label}
                  </div>
                  <div className="mt-1 text-meta leading-snug text-gray-600">{detail}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Example prompts -- real clickable chips, not unreachable placeholder text.
              Only shown before the user has typed anything; clicking fills the textarea. */}
          {!idea && (
            <div className="shrink-0 flex flex-wrap gap-1.5">
              {[
                "A website and mobile app for booking local services",
                "A dashboard for tracking field operations",
                "A backend API for customer accounts and payments",
              ].map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => {
                    setIdea(example);
                    ideaTextareaRef.current?.focus();
                  }}
                  className="rounded-full border border-white/8 bg-black/25 px-2.5 py-1 text-meta text-gray-500 transition-colors hover:border-cyan-500/40 hover:text-cyan-300"
                >
                  {example}
                </button>
              ))}
            </div>
          )}

          {/* Drag-and-drop textarea */}
          <div
            className={`flex-1 min-h-[100px] relative rounded-xl border transition-colors ${ideaDragOver ? "border-cyan-500/60 bg-cyan-950/20" : "border-[var(--dtx-code-border)]"}`}
            onDragOver={(e) => {
              e.preventDefault();
              setIdeaDragOver(true);
            }}
            onDragLeave={() => setIdeaDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setIdeaDragOver(false);
              processFiles(e.dataTransfer.files, "idea");
            }}
          >
            <textarea
              ref={ideaTextareaRef}
              className="w-full h-full bg-transparent p-4 text-body font-mono focus:outline-none resize-none placeholder-gray-700 text-gray-200 leading-relaxed"
              placeholder="Describe what you want to build..."
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              disabled={consulting}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) handleConsult();
              }}
            />
            {ideaDragOver && (
              <div className="absolute inset-0 rounded-xl flex items-center justify-center pointer-events-none">
                <div className="flex flex-col items-center gap-1.5">
                  <ImageIcon size={20} className="text-cyan-400" />
                  <span className="text-label text-cyan-300 font-mono">Drop image here</span>
                </div>
              </div>
            )}
          </div>

          {/* Attachment strip */}
          {ideaAttachments.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {ideaAttachments.map((att) => (
                <div key={att.id} className="relative group">
                  <img
                    src={att.dataUrl}
                    alt={att.name}
                    className="w-14 h-14 object-cover rounded-xl border border-[var(--dtx-code-border)]"
                  />
                  {att.colors && att.colors.length > 0 && (
                    <div className="absolute bottom-0.5 left-0.5 flex gap-0.5">
                      {att.colors.slice(0, 4).map((c, i) => (
                        <div
                          key={i}
                          className="w-2 h-2 rounded-sm border border-black/40"
                          style={{ background: c }}
                        />
                      ))}
                    </div>
                  )}
                  <button
                    onClick={() => removeIdeaAttachment(att.id)}
                    className="absolute -top-1 -right-1 w-4 h-4 bg-red-500/90 rounded-full text-white text-meta flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X size={8} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Model picker sits right above the submit action, not up in the
              panel header -- it affects THIS request, so it belongs next to
              where the request gets sent. Ryan: "i dont like the router at
              the top, it should be elsewhere." */}
          {modelPicker && <div className="mb-2 flex justify-end">{modelPicker}</div>}

          {/* Action row */}
          <div className="flex gap-2">
            <input
              ref={ideaFileRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => {
                if (e.target.files) {
                  processFiles(e.target.files, "idea");
                  e.target.value = "";
                }
              }}
            />
            <button
              onClick={() => ideaFileRef.current?.click()}
              disabled={consulting}
              title="Attach image (color scheme, UI reference)"
              className="h-10 w-10 flex items-center justify-center border border-[var(--dtx-code-border)] hover:border-cyan-500/40 rounded-xl text-gray-600 hover:text-cyan-400 transition-colors disabled:opacity-40 shrink-0"
            >
              <Paperclip size={14} />
            </button>
            <button
              onClick={handleConsult}
              disabled={!idea.trim() || consulting}
              className="flex-1 py-2.5 bg-cyan-900/30 border border-cyan-500/50 hover:bg-cyan-900/60 text-cyan-300 text-meta font-bold uppercase tracking-wider rounded-xl transition-colors disabled:opacity-40 flex items-center justify-center gap-2"
            >
              {consulting ? (
                <>
                  <div className="w-3.5 h-3.5 border border-cyan-400 border-t-transparent rounded-full animate-spin" />{" "}
                  Consulting Oracle...
                </>
              ) : (
                <>
                  <Sparkles size={13} /> Consult Oracle — See Your Options
                </>
              )}
            </button>
          </div>

          {/* Quick Verify -- the instant single-function path, folded into
              the same textarea/action area as the conversational flow above
              instead of living on its own buried page. Secondary/smaller
              styling on purpose: this is for a small idea with concrete
              examples ("write add(a,b), examples: add(2,3)==5"), not a
              replacement for "Consult Oracle" on a whole app. */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => void runQuickPreview()}
              disabled={!idea.trim() || quickVerifying !== null}
              title="For a small, example-driven idea: synthesize a sound oracle and check it right now -- no conversation needed."
              className="flex-1 py-2 border border-white/8 hover:border-emerald-500/40 text-gray-500 hover:text-emerald-300 text-meta font-bold uppercase tracking-wider rounded-lg transition-colors disabled:opacity-40 flex items-center justify-center gap-1.5"
            >
              {quickVerifying === "preview" ? (
                <>
                  <div className="w-3 h-3 border border-emerald-400 border-t-transparent rounded-full animate-spin" />
                  Checking...
                </>
              ) : (
                <>
                  <Zap size={12} /> Quick Verify (single function + examples)
                </>
              )}
            </button>
            {quickPreview && (
              <button
                onClick={() => void runQuickBuild()}
                disabled={quickVerifying !== null}
                className="flex-1 py-2 bg-emerald-900/20 border border-emerald-500/40 hover:bg-emerald-900/40 text-emerald-300 text-meta font-bold uppercase tracking-wider rounded-lg transition-colors disabled:opacity-40 flex items-center justify-center gap-1.5"
              >
                {quickVerifying === "build" ? (
                  <>
                    <div className="w-3 h-3 border border-emerald-400 border-t-transparent rounded-full animate-spin" />
                    Building...
                  </>
                ) : (
                  <>Build Verified Program</>
                )}
              </button>
            )}
          </div>

          {quickError && (
            <div className="rounded-lg border border-red-500/20 bg-red-950/10 px-3 py-2 text-label text-red-300">
              {quickError}
            </div>
          )}

          {(quickPreview || quickBuild) && (
            <div className="rounded-lg border border-emerald-500/15 bg-emerald-950/10 px-3 py-2.5 text-label font-mono text-gray-400">
              {quickPreview && !quickBuild && (
                <>
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    <span>status: {String(quickPreview.status ?? "unknown")}</span>
                    <span>checks: {String(quickPreview.n_checks ?? "0")}</span>
                    <span>sound: {String(quickPreview.oracle_sound ?? "unknown")}</span>
                  </div>
                  {typeof quickPreview.oracle_tests === "string" && (
                    <pre className="mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap text-meta text-gray-500">
                      {quickPreview.oracle_tests}
                    </pre>
                  )}
                </>
              )}
              {quickBuild && (
                <>
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    <span>status: {String(quickBuild.status ?? "unknown")}</span>
                    <span>solved: {String(quickBuild.solved ?? "unknown")}</span>
                    <span>proof: {String(quickBuild.proof ?? "")}</span>
                  </div>
                  {typeof quickBuild.program === "string" && quickBuild.program.length > 0 && (
                    <pre className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap text-meta text-gray-500">
                      {quickBuild.program}
                    </pre>
                  )}
                </>
              )}
              <p className="mt-2 text-meta text-gray-600">
                Source mutation authorized: false. A solved result is temp-only until a separate
                human-approved apply gate exists.
              </p>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // RENDER: DISCOVERY STEP — paths + conversation, no inner header
  // ─────────────────────────────────────────────────────────────────────────

  if (step === "discovery") {
    return (
      <div className="flex flex-col h-full bg-[var(--dtx-code-bg)] text-gray-300 overflow-hidden">
        {/* Path cards — collapse to compact banner once confirmed, dim unselected when one is clicked */}
        {paths.length > 0 &&
          (confirmedPath ? (
            /* Compact chosen banner — replaces the grid */
            <div className="shrink-0 border-b border-[var(--dtx-code-border)] px-3 py-2 flex items-center gap-2">
              <div
                className="w-2 h-2 rounded-full shrink-0"
                style={{ background: confirmedPath.color }}
              />
              <span
                className="text-label font-black truncate"
                style={{ color: confirmedPath.color }}
              >
                {confirmedPath.name}
              </span>
              <span className="text-meta font-mono text-gray-600 truncate">
                {confirmedPath.stack}
              </span>
              <button
                onClick={handleReset}
                className="ml-auto text-meta text-gray-700 hover:text-gray-500 shrink-0 flex items-center gap-1"
              >
                <RefreshCw size={7} /> Change
              </button>
            </div>
          ) : (
            /* Full grid — dim unselected cards when one is clicked */
            <div className="shrink-0 border-b border-[var(--dtx-code-border)] px-3 pt-3 pb-2.5">
              <p className="text-eyebrow uppercase font-bold tracking-widest text-gray-600 mb-2 flex items-center gap-1">
                <ChevronRight size={9} /> Choose your direction
              </p>
              <div className="grid grid-cols-2 gap-2">
                {paths.map((path) => (
                  <PathCard
                    key={path.id}
                    path={path}
                    selected={selectedPathId === path.id}
                    dimmed={selectedPathId !== null && selectedPathId !== path.id}
                    onClick={() => selectPath(path)}
                  />
                ))}
              </div>
              <p className="text-meta text-gray-700 mt-2">
                Click a card to explore it — details open on the right.
              </p>
            </div>
          ))}

        {/* Oracle conversation — flex-1 */}
        <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-3 p-3">
          {messages.map((msg, i) => (
            <MessageBubble key={i} msg={msg} />
          ))}
          {oracleTyping !== null && (
            <MessageBubble msg={{ role: "oracle", text: oracleTyping || "▌" }} />
          )}
          {oracleThinking && oracleTyping === null && <TypingIndicator />}
          <div ref={chatEndRef} />
        </div>

        {/* Input area — guided mode vs free-form */}
        <div
          className={`shrink-0 border-t transition-colors ${discDragOver ? "border-cyan-500/50 bg-cyan-950/10" : "border-[var(--dtx-code-border)]"}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDiscDragOver(true);
          }}
          onDragLeave={() => setDiscDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDiscDragOver(false);
            processFiles(e.dataTransfer.files, "discovery");
          }}
        >
          {/* ── GUIDED MODE header ── */}
          {guidedMode && !freeFormMode && currentQuestionIdx < guidedQuestions.length && (
            <div className="px-3 pt-2.5 pb-1.5 border-b border-[var(--dtx-code-border)]/60">
              {/* Progress bar */}
              <div className="flex items-center gap-2 mb-2">
                <div className="flex-1 h-1 bg-[var(--dtx-code-panel)] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-cyan-500 rounded-full transition-all duration-500"
                    style={{ width: `${(currentQuestionIdx / guidedQuestions.length) * 100}%` }}
                  />
                </div>
                <span className="text-meta font-mono text-gray-600 flex-shrink-0">
                  Q {currentQuestionIdx + 1}/{guidedQuestions.length}
                </span>
              </div>
              {/* WHY it is still asking.
                  The interview no longer stops at a fixed count -- it runs until a sound
                  oracle can be synthesized from the answers. An open-ended number of
                  questions with no stated reason feels like an interrogation, so name what
                  is still missing. This appears only once the static bank is exhausted,
                  i.e. exactly when the old build would already have given up and
                  generated a spec from whatever it had. */}
              {contextMissing.length > 0 && currentQuestionIdx >= 4 && (
                <div className="text-meta text-amber-500/80 mb-2 leading-relaxed">
                  Still needed for a verifiable build:{" "}
                  <span className="font-mono">{contextMissing.join(", ")}</span>
                </div>
              )}
              {/* Type badge + skip + free-form toggle */}
              <div className="flex items-center gap-2">
                <span className="text-eyebrow font-bold uppercase tracking-widest text-cyan-500/60 px-1.5 py-0.5 rounded border border-cyan-800/30 bg-cyan-950/20">
                  {guidedType}
                </span>
                <button
                  onClick={handleSkipQuestion}
                  disabled={oracleThinking || oracleTyping !== null}
                  className="text-meta text-gray-600 hover:text-gray-400 transition-colors disabled:opacity-40 ml-auto"
                >
                  Skip →
                </button>
                <button
                  onClick={() => setFreeFormMode(true)}
                  className="text-meta text-gray-600 hover:text-cyan-400 transition-colors"
                  title="Switch to free-form conversation"
                >
                  💬 Free-form
                </button>
              </div>
            </div>
          )}

          {/* Free-form toggle banner */}
          {guidedMode && freeFormMode && (
            <div className="px-3 pt-2 pb-1.5 border-b border-[var(--dtx-code-border)]/60 flex items-center gap-2">
              <span className="text-meta text-gray-600 font-mono flex-1">Free-form mode</span>
              <button
                onClick={() => setFreeFormMode(false)}
                className="text-meta text-cyan-500 hover:text-cyan-400 transition-colors"
              >
                ← Resume guided
              </button>
            </div>
          )}
          {/* Pending attachment thumbnails */}
          {pendingAttachments.length > 0 && (
            <div className="flex gap-2 px-3 pt-2 flex-wrap">
              {pendingAttachments.map((att) => (
                <div key={att.id} className="relative group">
                  <img
                    src={att.dataUrl}
                    alt={att.name}
                    className="w-12 h-12 object-cover rounded-lg border border-[var(--dtx-code-border)]"
                  />
                  {att.colors && att.colors.length > 0 && (
                    <div className="absolute bottom-0.5 left-0.5 flex gap-0.5">
                      {att.colors.slice(0, 3).map((c, i) => (
                        <div
                          key={i}
                          className="w-1.5 h-1.5 rounded-sm border border-black/40"
                          style={{ background: c }}
                        />
                      ))}
                    </div>
                  )}
                  <button
                    onClick={() => removePendingAttachment(att.id)}
                    className="absolute -top-1 -right-1 w-4 h-4 bg-red-500/90 rounded-full text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X size={8} />
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="px-3 py-2 flex gap-2 items-end">
            <input
              ref={discFileRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => {
                if (e.target.files) {
                  processFiles(e.target.files, "discovery");
                  e.target.value = "";
                }
              }}
            />
            <button
              onClick={() => discFileRef.current?.click()}
              disabled={oracleThinking || oracleTyping !== null}
              title="Attach image"
              className="h-9 w-9 flex items-center justify-center border border-[var(--dtx-code-border)] hover:border-cyan-500/40 rounded-xl text-gray-600 hover:text-cyan-400 transition-colors disabled:opacity-40 shrink-0"
            >
              <Paperclip size={12} />
            </button>
            <textarea
              ref={inputRef}
              className="flex-1 min-h-[52px] max-h-[100px] bg-[var(--dtx-code-bg-deep)] border border-[var(--dtx-code-border)] rounded-xl p-2.5 text-label font-mono focus:border-cyan-500/60 focus:outline-none resize-none placeholder-gray-700 text-gray-300 leading-relaxed"
              placeholder={
                guidedMode && !freeFormMode && currentQuestionIdx < guidedQuestions.length
                  ? "Your answer... (Enter to advance)"
                  : "Answer the Oracle's question... (Enter to send)"
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={oracleThinking || oracleTyping !== null}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  if (guidedMode && !freeFormMode && currentQuestionIdx < guidedQuestions.length) {
                    handleGuidedAnswer();
                  } else {
                    handleConverse();
                  }
                }
              }}
            />
            <button
              onClick={() => {
                if (guidedMode && !freeFormMode && currentQuestionIdx < guidedQuestions.length) {
                  handleGuidedAnswer();
                } else {
                  handleConverse();
                }
              }}
              disabled={
                (!input.trim() && pendingAttachments.length === 0) ||
                oracleThinking ||
                oracleTyping !== null
              }
              className="h-9 w-9 flex items-center justify-center bg-cyan-900/30 border border-cyan-500/40 hover:bg-cyan-900/60 text-cyan-300 rounded-xl transition-colors disabled:opacity-40 shrink-0"
            >
              {oracleThinking ? (
                <div className="w-3.5 h-3.5 border border-cyan-400 border-t-transparent rounded-full animate-spin" />
              ) : (
                <Send size={12} />
              )}
            </button>
          </div>
        </div>

        {/* Reset */}
        <div className="shrink-0 px-3 pb-2 flex justify-end">
          <button
            onClick={handleReset}
            className="text-meta text-gray-700 hover:text-gray-500 flex items-center gap-1"
          >
            <RefreshCw size={8} /> Start over
          </button>
        </div>
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // RENDER: SPEC READY — spec editor + spot-change chat + build button
  // ─────────────────────────────────────────────────────────────────────────

  if (step === "specReady") {
    return (
      <div className="flex flex-col h-full bg-[var(--dtx-code-bg)] text-gray-300 overflow-hidden">
        {/* Spec editor — takes the majority of the panel */}
        <div
          className="flex flex-col border-b border-[var(--dtx-code-border)] relative"
          style={{ flex: "1 1 0", minHeight: 0 }}
        >
          <MatrixRain active={specRefining} label="Updating spec..." />
          <div className="px-3 py-1.5 bg-[var(--dtx-code-panel)] border-b border-[var(--dtx-code-border)] flex items-center justify-between shrink-0">
            <span className="text-eyebrow uppercase font-bold tracking-widest text-purple-400">
              Formal Specification
            </span>
            <span className="text-meta text-emerald-400 font-mono border border-emerald-500/30 px-1.5 py-0.5 rounded bg-emerald-950/30">
              READY
            </span>
          </div>
          <textarea
            className="flex-1 min-h-0 bg-[var(--dtx-code-bg-deep)] p-3 text-label font-mono focus:outline-none resize-none text-gray-300 leading-relaxed overflow-y-auto"
            value={spec}
            onChange={(e) => {
              setSpec(e.target.value);
              onSpecChange?.(e.target.value);
            }}
            disabled={specRefining || launching}
          />
        </div>

        {/* Clarifying chat — compact, fixed height */}
        <div
          className="shrink-0 overflow-y-auto flex flex-col gap-2 px-3 py-2 border-b border-[var(--dtx-code-border)]"
          style={{ maxHeight: "110px" }}
        >
          {specMessages.map((msg, i) => (
            <MessageBubble key={i} msg={msg} />
          ))}
          {specOracleTyping !== null && (
            <MessageBubble msg={{ role: "oracle", text: specOracleTyping || "▌" }} />
          )}
          {specRefining && specOracleTyping === null && <TypingIndicator />}
          <div ref={specChatEndRef} />
        </div>

        {/* Quick-add chips — click immediately submits */}
        <div className="shrink-0 px-3 pt-2 pb-1.5">
          <p className="text-eyebrow uppercase font-bold tracking-widest text-amber-500/60 mb-1.5 flex items-center gap-1">
            <MessageSquare size={8} /> Quick additions — click to apply
          </p>
          <div className="flex flex-wrap gap-1.5">
            {REFINEMENT_SUGGESTIONS.map((s) => (
              <button
                key={s.label}
                onClick={() => handleSpecRefineWith(s.text)}
                disabled={specRefining || launching}
                className="px-2 py-0.5 rounded-md border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] hover:border-amber-500/50 hover:bg-amber-950/30 text-meta text-gray-500 hover:text-amber-300 transition-all disabled:opacity-30 active:scale-95"
              >
                + {s.label}
              </button>
            ))}
          </div>
        </div>

        {/* Spot-change input */}
        <div className="shrink-0 px-3 pb-2 flex gap-2 items-end">
          <textarea
            className="flex-1 min-h-[40px] max-h-[72px] bg-[var(--dtx-code-bg-deep)] border border-[var(--dtx-code-border)] rounded-xl p-2.5 text-label font-mono focus:border-purple-500/60 focus:outline-none resize-none placeholder-gray-700 text-gray-300 leading-relaxed"
            placeholder="Request a spot change... (Enter to send)"
            value={specInput}
            onChange={(e) => setSpecInput(e.target.value)}
            disabled={specRefining || launching}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSpecRefineWith(specInput);
              }
            }}
          />
          <button
            onClick={() => handleSpecRefineWith(specInput)}
            disabled={!specInput.trim() || specRefining || launching}
            className="h-9 w-9 flex items-center justify-center bg-purple-900/30 border border-purple-500/40 hover:bg-purple-900/60 text-purple-300 rounded-xl transition-colors disabled:opacity-40 shrink-0"
          >
            {specRefining ? (
              <div className="w-3 h-3 border border-purple-400 border-t-transparent rounded-full animate-spin" />
            ) : (
              <Send size={12} />
            )}
          </button>
        </div>

        {/* Error */}
        {launchError && (
          <div className="text-label text-red-400 bg-red-900/20 border border-red-800/40 rounded-lg mx-3 mb-2 px-3 py-2 shrink-0">
            {launchError}
          </div>
        )}

        {/* Build footer */}
        <div className="border-t border-[var(--dtx-code-border)] px-3 py-2.5 shrink-0 bg-[var(--dtx-code-bg)]">
          <button
            onClick={handleBuild}
            disabled={!spec.trim() || launching || specRefining}
            className="w-full py-3 bg-emerald-900/30 border border-emerald-500/50 hover:bg-emerald-900/60 text-emerald-300 text-body font-bold uppercase tracking-wider rounded-xl transition-colors disabled:opacity-40 flex items-center justify-center gap-2"
          >
            {launching ? (
              <>
                <div className="w-3.5 h-3.5 border border-emerald-400 border-t-transparent rounded-full animate-spin" />{" "}
                Launching...
              </>
            ) : (
              <>
                <Play size={13} /> Build It — Launch Hive Mind
              </>
            )}
          </button>
          <div className="flex items-center justify-between mt-1.5">
            <p className="text-meta text-gray-600">
              <GlossaryTerm
                term="Oracle"
                definition="First AI role. Reads your spec and encodes the full intent — what the software should do, why, and what constraints apply. All other roles inherit this semantic context."
              >
                Oracle
              </GlossaryTerm>
              {" → "}
              <GlossaryTerm
                term="Architect"
                definition="Second AI role. Takes the Oracle's intent and creates a dependency-ordered step plan (the DAG). Decides which files to create, in what order, and what each step produces."
              >
                Architect
              </GlossaryTerm>
              {" → "}
              <GlossaryTerm
                term="Builder"
                definition="Third AI role. Executes one step at a time — generates the actual code for each step in the Architect's plan. Works against the current state of the file, not from scratch."
              >
                Builder
              </GlossaryTerm>
              {" → "}
              <GlossaryTerm
                term="Compiler Oracle"
                definition="Not an AI. The actual compiler — rustc, go build, or python. Zero hallucinations. If code doesn't compile, the step fails and retries regardless of what any model says. Final arbiter of correctness."
              >
                Compiler Oracle
              </GlossaryTerm>
            </p>
            <button
              onClick={handleReset}
              className="text-meta text-gray-700 hover:text-gray-500 flex items-center gap-1 shrink-0 ml-2"
            >
              <RefreshCw size={8} /> Restart
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Launching spinner
  return (
    <div className="flex flex-col h-full items-center justify-center gap-4 bg-[var(--dtx-code-bg)]">
      <div className="w-8 h-8 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
      <p className="text-label text-emerald-400 font-mono">Initializing session...</p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Outer wrapper: collapsible multi-agent chat + corpus/oracle-feedback rail.
// Wraps ALL of ConceptLabInner's step branches uniformly (idea/consulting/
// launched/spec-ready/etc. all have their own early `return` above) instead
// of threading a rail into each one individually. Session is keyed to the
// same workspace ConceptLab itself is working in, so the chat's oracle
// verification and @corpus history are about the SAME project the user is
// building here -- not a disconnected side conversation.
//
// Rendered via a PORTAL (document.body), not a normal flex sibling or an
// in-place absolute overlay -- found live 2026-07-22: page.tsx's "WORK"
// drawer (activeSidebar === "hive") has a hard `w-[460px]` on its own
// container AND its body wrapper is `overflow-y-auto` with no explicit
// overflow-x, which the CSS spec computes to `overflow-x: auto` too (a
// browser can't leave one axis `visible` while the other scrolls) -- so
// ANY horizontal overflow past the drawer's right edge, in-flow OR
// absolutely-positioned, gets clipped/squeezed by that ancestor. A portal
// escapes that ancestor chain entirely; position is computed from the
// container's own getBoundingClientRect() so the rail still visually anchors
// beside ConceptLab regardless of which page layout it's embedded in.
// ─────────────────────────────────────────────────────────────────────────────
// Ryan, live: "that multiagent room is kinda small and harder to see, it
// should be able to be adjusted." Default width bumped up from the original
// 380px, and the rail is now user-resizable (drag the left edge) with the
// chosen width remembered across restarts -- same drag-to-resize posture as
// page.tsx's addon dock windows (startAddonDockResize), just a single
// horizontal dimension since this rail's height/position already track the
// ConceptLab container it's anchored to.
const _RAIL_WIDTH_KEY = "determinex-work-chat-rail-width";
const _RAIL_MIN_W = 340;
const _RAIL_DEFAULT_W = 480;

function _loadRailWidth(): number {
  if (typeof window === "undefined") return _RAIL_DEFAULT_W;
  const raw = window.localStorage.getItem(_RAIL_WIDTH_KEY);
  const n = raw ? Number(raw) : NaN;
  return Number.isFinite(n) && n >= _RAIL_MIN_W ? n : _RAIL_DEFAULT_W;
}

/**
 * Work's multi-agent chat.
 *
 * Ryan, live 2026-07-27: "the multichat pop out is still exposed in allot of
 * places" -- then, on a first attempt that deleted it outright: "i want it in
 * all chat box areas, or wherever there is one."
 *
 * The capability was never the problem; the delivery was. This used
 * createPortal(document.body) with `fixed` + z-[999]/z-[998], so it escaped its
 * own panel and floated above every other screen -- the addon dock included --
 * and needed a six-condition `suppressQuickChat` prop plus a 400ms
 * getBoundingClientRect poll just to chase its own container around the
 * viewport.
 *
 * Now it renders INSIDE this component's relative container: absolute instead
 * of fixed, local stacking instead of z-999. It cannot overlay anything outside
 * Work, so the suppression prop and the position polling are both gone with it.
 * Chat stays where a chat box belongs.
 */
export function ConceptLab(props: ConceptLabProps) {
  const [chatRailOpen, setChatRailOpen] = useState(false);
  const [railWidth, setRailWidth] = useState(_RAIL_DEFAULT_W);
  useEffect(() => setRailWidth(_loadRailWidth()), []);

  const startRailResize = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = railWidth;
      // The panel's left edge is pinned to the rail button; the handle is on
      // its right edge, so dragging right grows it. Bounded by the container
      // now rather than the viewport, since it no longer escapes the panel.
      const maxWidth = Math.max(_RAIL_MIN_W, window.innerWidth - 120);
      const onMove = (ev: PointerEvent) => {
        const dx = ev.clientX - startX;
        setRailWidth(Math.min(maxWidth, Math.max(_RAIL_MIN_W, startWidth + dx)));
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        setRailWidth((w) => {
          window.localStorage.setItem(_RAIL_WIDTH_KEY, String(w));
          return w;
        });
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    },
    [railWidth]
  );

  return (
    <div className="relative h-full">
      <ConceptLabInner {...props} />

      <button
        type="button"
        onClick={() => setChatRailOpen((v) => !v)}
        title={chatRailOpen ? "Close chat" : "Open multi-agent chat"}
        aria-label={chatRailOpen ? "Close multi-agent chat" : "Open multi-agent chat"}
        data-testid="work-chat-toggle"
        className={`absolute left-0 top-1/2 z-20 flex w-6 -translate-y-1/2 flex-col items-center justify-center gap-1 rounded-r-md border border-l-0 border-white/8 bg-[var(--dtx-code-bg)] py-3 text-gray-600 shadow-lg transition-colors hover:text-fuchsia-300 ${
          chatRailOpen ? "border-fuchsia-400/30 text-fuchsia-300" : ""
        }`}
      >
        {chatRailOpen ? <ChevronLeft size={12} /> : <ChevronRight size={12} />}
        <MessageSquare size={12} />
      </button>

      {chatRailOpen && (
        <div
          className="absolute left-6 top-0 z-10 h-full border-l border-white/8 bg-[var(--dtx-code-bg)] shadow-2xl"
          style={{ width: railWidth }}
        >
          <div
            onPointerDown={startRailResize}
            title="Drag to resize"
            className="absolute -right-1.5 top-0 z-10 h-full w-3 cursor-ew-resize"
          />
          <AgentChatPanel workspacePath={props.projectPath ?? ""} />
        </div>
      )}
    </div>
  );
}

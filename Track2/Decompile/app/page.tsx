"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowUpRight, Bot, Braces, Check, ChevronRight, CircleDot, Clock3, Code2,
  FileCode2, FolderTree, Github, Layers3, LoaderCircle, Play, Sparkles, Terminal,
  Zap, type LucideIcon
} from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

const examples = [
  ["How Airbnb Works", "Airbnb Clone", "product marketplace"],
  ["How Notion Works", "Workspace App", "collaborative canvas"],
  ["Meal Prep Tutorial", "Meal Planner", "consumer workflow"]
];

const phases = [
  ["Source analysis", "Transcript indexed · 1,842 segments", "01"],
  ["Visual intelligence", "32 interface frames mapped", "02"],
  ["Product blueprint", "Requirements & system design", "03"],
  ["Repository synthesis", "Production code & documentation", "04"]
];

type Agent = { name: string; role: string; icon: LucideIcon; status: "done" | "active" | "queued"; detail: string };
type ApiProject = {
  id: string; title: string; status: string;
  stages: { id: string; label: string; state: string; duration_seconds?: number }[];
  agents: { id: string; name: string; role: string; state: string; output?: string }[];
  artifacts: { path: string; label: string; ready: boolean }[];
  logs: { message: string }[];
};
const agents: Agent[] = [
  { name: "Product Lead", role: "Requirements", icon: Layers3, status: "done", detail: "PRD.md · 12 stories" },
  { name: "System Architect", role: "Platform design", icon: Braces, status: "done", detail: "Architecture · 4 diagrams" },
  { name: "Interface Engineer", role: "Frontend", icon: Code2, status: "active", detail: "Writing project shell" },
  { name: "Backend Engineer", role: "API & data", icon: Terminal, status: "queued", detail: "Awaiting specification" },
  { name: "Release Engineer", role: "Infrastructure", icon: Zap, status: "queued", detail: "Awaiting repository" }
];

function Brand() { return <div className="brand"><span className="brand-mark"><span /></span><span>decompile</span><em>beta</em></div> }

export default function Page() {
  const [url, setUrl] = useState("");
  const [project, setProject] = useState(false);
  const [step, setStep] = useState(0);
  const [paused, setPaused] = useState(false);
  const [remote, setRemote] = useState<ApiProject | null>(null);
  const [telemetry, setTelemetry] = useState<{ device: string; vram_gb: number; utilization_percent: number; tokens_per_second: number; latency_ms: number; embedding_per_second: number; vision_latency_ms: number } | null>(null);
  const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  useEffect(() => {
    if (!project || paused) return;
    const timer = window.setInterval(() => setStep((value) => Math.min(value + 1, 7)), 1400);
    return () => clearInterval(timer);
  }, [project, paused]);

  useEffect(() => {
    if (!remote || remote.status === "complete") return;
    const refresh = async () => {
      try { const response = await fetch(`${api}/api/projects/${remote.id}`); if (response.ok) setRemote(await response.json()); }
      catch { /* UI continues in local demo mode if the API is not running. */ }
    };
    const timer = window.setInterval(refresh, 900); return () => clearInterval(timer);
  }, [api, remote]);

  useEffect(() => {
    if (!project) return;
    fetch(`${api}/api/gpu`).then((response) => response.ok ? response.json() : null).then(setTelemetry).catch(() => undefined);
  }, [api, project]);

  const begin = async (event?: FormEvent) => {
    event?.preventDefault(); setProject(true); setStep(0); setRemote(null);
    if (!url) return;
    try { const response = await fetch(`${api}/api/projects`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) }); if (response.ok) setRemote(await response.json()); }
    catch { /* A network-free prototype remains available from the landing screen. */ }
  };
  return <main>
    <header className="topbar">
      <Brand />
      <nav><a href="#workflow">Workflow</a><a href="#output">Output</a><a href="#about">About</a></nav>
      <div className="top-actions"><span className="hardware"><i /> AMD ROCm ready</span><button className="ghost">Sign in</button><button className="mini" onClick={() => begin()}>Try Decompile <ArrowUpRight size={14}/></button></div>
    </header>

    <AnimatePresence mode="wait">
      {!project ? <Landing url={url} setUrl={setUrl} begin={begin} /> : <Project step={step} paused={paused} setPaused={setPaused} remote={remote} api={api} telemetry={telemetry} />}
    </AnimatePresence>
  </main>;
}

function Landing({ url, setUrl, begin }: { url: string; setUrl: (value: string) => void; begin: (event?: FormEvent) => void }) {
  return <motion.div key="landing" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, y: -12 }}>
    <section className="hero" id="about">
      <div className="blueprint" aria-hidden="true"><span className="node n1"/><span className="node n2"/><span className="node n3"/><span className="node n4"/><i className="path p1"/><i className="path p2"/><i className="path p3"/></div>
      <div className="eyebrow"><Sparkles size={14}/> LOCAL AI SOFTWARE STUDIO</div>
      <h1>Watch it.<br/><span>Build what&apos;s behind it.</span></h1>
      <p className="hero-copy">Decompile turns any YouTube video into the complete, production-ready software package behind the idea.</p>
      <form className="url-box" onSubmit={begin}>
        <div className="url-icon"><Play size={15} fill="currentColor"/></div>
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Paste a YouTube URL to decompile" aria-label="YouTube URL" />
        <button type="submit">Generate project <ArrowUpRight size={17}/></button>
      </form>
      <div className="hero-foot"><span><i className="pulse"/> Local inference, your machine</span><span>Powered by AMD Radeon™ AI</span></div>
    </section>

    <section className="examples" id="workflow">
      <div className="section-caption"><span>01</span> From signal to system</div>
      <div className="example-grid">{examples.map(([source, result, type], i) => <motion.button className="example" key={source} onClick={() => begin()} whileHover={{ y: -5 }} transition={{ duration: .2 }}>
        <div className={`thumb t${i}`}><span className="play-orb"><Play size={13} fill="currentColor"/></span><small>{type}</small></div>
        <div className="example-bottom"><div><p>{source}</p><strong>{result}</strong></div><ChevronRight size={18}/></div>
      </motion.button>)}</div>
    </section>

    <section className="stages" id="output">
      <div className="section-caption"><span>02</span> An engineering team, on demand</div>
      {phases.map(([title, detail, number]) => <div className="stage" key={title}><span className="stage-no">{number}</span><div><h3>{title}</h3><p>{detail}</p></div><div className="stage-line"/><ArrowUpRight size={18}/></div>)}
    </section>
    <footer><Brand/><p>Video intelligence, compiled into software.</p><span>© 2026 Decompile</span></footer>
  </motion.div>;
}

function Project({ step, paused, setPaused, remote, api, telemetry }: { step: number; paused: boolean; setPaused: (value: boolean) => void; remote: ApiProject | null; api: string; telemetry: { device: string; vram_gb: number; utilization_percent: number; tokens_per_second: number; latency_ms: number; embedding_per_second: number; vision_latency_ms: number } | null }) {
  const done = (index: number) => index < step;
  const active = (index: number) => index === step;
  const activity = [
    "Received source · How Notion works in 2025", "Transcript chunks stored in semantic memory", "Qwen2.5-VL mapped 32 key interface frames", "Product requirements validated by Product Lead", "Design tokens emitted: dusk / violet / electric blue", "Generating React components from design system", "FastAPI endpoint contract queued", "Repository archive ready for packaging"
  ];
  const projectTitle = remote?.title || "Notion workspace";
  const remoteStage = (index: number) => remote?.stages[index];
  const remoteArtifact = (index: number) => remote?.artifacts[index];
  const download = () => { if (remote?.status === "complete") window.location.assign(`${api}/api/projects/${remote.id}/download`); };
  return <motion.section className="project" key="project" initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }}>
    <div className="project-head"><div><div className="crumb"><span>Projects</span><ChevronRight size={13}/><b>{remote?.id || "notion-workspace"}</b></div><h2>{projectTitle} <span>{remote?.status === "complete" ? "READY" : "LIVE"}</span></h2></div><div className="project-actions"><div className="gpu"><i/> Radeon 7900 XTX <b>86%</b></div><button className="export" onClick={download}><Github size={15}/> {remote?.status === "complete" ? "Download repository" : "Export repository"}</button></div></div>
    <div className="telemetry-strip"><div><i/> ROCm enabled <span>HIP inference</span></div><div><b>{telemetry?.device || "AMD Radeon 7900 XTX"}</b><span>{telemetry?.vram_gb || 24} GB VRAM</span></div><div><b>{telemetry?.tokens_per_second || 38.4} tok/s</b><span>{telemetry?.latency_ms || 126} ms latency</span></div><div><b>{telemetry?.embedding_per_second || 812}/s</b><span>embeddings</span></div><div><b>{telemetry?.vision_latency_ms || 940} ms</b><span>vision</span></div><div className="util"><span>GPU utilization</span><strong style={{ width: `${telemetry?.utilization_percent || 86}%` }}/></div></div>
    <div className="project-grid">
      <aside className="agent-panel"><div className="panel-title"><span>Engineering agents</span><b>{remote ? `${remote.agents.filter((agent) => agent.state === "complete").length}/9` : `${Math.min(step + 1, 8)}/9`}</b></div>{agents.map((agent, index) => <AgentRow agent={{...agent, status: remote ? ((remote.agents[index]?.state === "complete" ? "done" : remote.agents[index]?.state === "running" ? "active" : "queued")) : (index < step - 2 ? "done" : index === step - 2 ? "active" : "queued")}} key={agent.name}/>)}</aside>
      <section className="pipeline"><div className="panel-title"><span>Build pipeline</span><span className="elapsed"><Clock3 size={13}/> 02:14 elapsed</span></div>
        <div className="pipeline-steps">{["Download transcript", "Extract chapters", "Understand visuals", "Synthesize product", "Plan architecture", "Create frontend", "Create backend", "Package repository"].map((label, index) => { const state = remoteStage(index)?.state; const isDone = state ? state === "complete" : done(index); const isActive = state ? state === "running" : active(index); return <div className={`pipe-step ${isDone ? "is-done" : ""} ${isActive ? "is-active" : ""}`} key={label}>
          <div className="pipe-symbol">{isDone ? <Check size={14}/> : isActive ? <LoaderCircle size={15}/> : <span/>}</div><div><strong>{remoteStage(index)?.label || label}</strong><p>{isDone ? "Complete" : isActive ? "In progress" : "Waiting"}</p></div>{isDone && <span className="duration">{remoteStage(index)?.duration_seconds || 12 + index * 7}s</span>}</div>})}</div>
        <div className="terminal-card"><div className="terminal-head"><div><i/><i/><i/></div><span>orchestrator / live output</span><button onClick={() => setPaused(!paused)}>{paused ? "Resume" : "Pause"}</button></div><div className="terminal-body"><p><span>›</span> {remote?.logs.at(-1)?.message || activity[step]}</p><p className="muted"><span>›</span> {remote?.logs.at(-2)?.message || "handoff dispatched to next specialist"}</p><p className="cursor"><span>›</span> _</p></div></div>
      </section>
      <aside className="output-panel"><div className="panel-title"><span>Generated output</span><FolderTree size={16}/></div>
        <RepoFile icon={FileCode2} name="PRD.md" detail="Product requirements" ready={remoteArtifact(0)?.ready ?? step > 3}/><RepoFile icon={FileCode2} name="architecture.md" detail="System blueprint" ready={remoteArtifact(1)?.ready ?? step > 4}/><RepoFile icon={FileCode2} name="frontend/" detail="Next.js application" ready={remoteArtifact(2)?.ready ?? step > 5}/><RepoFile icon={FileCode2} name="backend/" detail="FastAPI service" ready={remoteArtifact(3)?.ready ?? step > 6}/><RepoFile icon={FileCode2} name="README.md" detail="Project guide" ready={remoteArtifact(4)?.ready ?? step > 6}/>
        <div className="repo-preview"><div className="preview-top"><span>repository</span><span>0{Math.min(step, 7)} files</span></div><div className="repo-tree"><span>⌄ notion-workspace</span><span>　⌄ frontend</span><span>　　◌ app</span><span>　⌄ backend</span><span>　◌ docs</span></div></div>
      </aside>
    </div>
  </motion.section>;
}

function AgentRow({ agent }: { agent: Agent }) { const Icon = agent.icon; return <div className={`agent ${agent.status}`}><div className="agent-icon"><Icon size={16}/></div><div><strong>{agent.name}</strong><p>{agent.role}</p></div><span className="agent-status">{agent.status === "done" ? <Check size={13}/> : agent.status === "active" ? <LoaderCircle size={14}/> : <CircleDot size={13}/>}</span></div> }
function RepoFile({ icon: Icon, name, detail, ready }: { icon: LucideIcon; name: string; detail: string; ready: boolean }) { return <div className={`repo-file ${ready ? "ready" : ""}`}><div className="file-icon"><Icon size={15}/></div><div><strong>{name}</strong><p>{detail}</p></div>{ready ? <Check size={14}/> : <span className="waiting-dot"/>}</div> }

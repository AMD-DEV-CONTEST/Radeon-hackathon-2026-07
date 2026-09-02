// 紧凑型进度条：阶段节点 + 进度条 + 当前阶段提示
// 用于 ChatConsole / DemoCanvas 等对话面板。

import { useEffect, useState } from "react";
import { Loader2, Check, ChevronDown, Brain, Shield, Map, Play } from "lucide-react";

export type StageName = "start" | "intent" | "guard" | "plan" | "act" | "gepa" | "reasoning" | "answer" | "done";

const STAGE_ORDER: StageName[] = ["start", "intent", "guard", "plan", "act", "gepa", "reasoning", "answer"];

const STAGE_LABEL: Record<StageName, string> = {
  start: "启动",
  intent: "意图",
  guard: "守卫",
  plan: "规划",
  act: "执行",
  gepa: "进化",
  reasoning: "推理",
  answer: "回复",
  done: "完成",
};

export interface ProgressInfo {
  intent?: { type: string; confidence: number };
  guard?: { level: string; reason: string };
  plan?: { steps: { step_id: number; agent: string; task: string; status: string }[] };
  progressStage?: string; // 当前 progress 阶段名 (plan/act/meta/gepa/推理中)
  progressText?: string;
  thoughtCount: number; // 思考链片段数
  tokenCount: number; // 已生成 token 数
  started: boolean; // 是否已开始
}

interface ProgressIndicatorProps {
  progress: ProgressInfo;
  compact?: boolean; // compact 模式用于折叠显示
}

export function ProgressIndicator({ progress, compact }: ProgressIndicatorProps) {
  const [expanded, setExpanded] = useState(!compact);

  // 计算进度（按阶段计数）
  const completedStages = new Set<StageName>();
  if (progress.started) completedStages.add("start");
  if (progress.intent) completedStages.add("intent");
  if (progress.guard) completedStages.add("guard");
  if (progress.plan) completedStages.add("plan");
  if (progress.tokenCount > 0) completedStages.add("reasoning");
  const isStreaming = progress.tokenCount > 0 && !progress.progressStage;

  // 当前活跃阶段
  let currentStage: StageName = "start";
  if (progress.intent) currentStage = "guard";
  if (progress.guard) currentStage = "plan";
  if (progress.plan) currentStage = "act";
  if (progress.progressStage === "gepa" || progress.progressStage === "进化") currentStage = "gepa";
  if (progress.progressStage === "推理中" || progress.tokenCount > 0) currentStage = "reasoning";

  const pct = (completedStages.size / 6) * 100;

  // 没有进度时不显示
  if (!progress.started) return null;

  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 overflow-hidden text-[11px]">
      {/* 进度条 */}
      <div className="h-1 bg-zinc-200 dark:bg-zinc-800 overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-blue-400 to-purple-500 transition-all duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* 阶段条 */}
      <div className="px-2.5 py-1.5 flex items-center gap-1.5 flex-wrap">
        {STAGE_ORDER.map((s) => {
          const done = completedStages.has(s);
          const active = s === currentStage && !done;
          const isAnswer = s === "answer" && progress.tokenCount > 0;
          return (
            <div key={s} className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded-full ${
              done || isAnswer ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400"
              : active ? "bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400"
              : "bg-zinc-100 dark:bg-zinc-800 text-zinc-400"
            }`}>
              {done || isAnswer ? <Check size={9} /> :
                active ? <Loader2 size={9} className="animate-spin" /> :
                <span className="w-1 h-1 rounded-full bg-current" />}
              <span>{STAGE_LABEL[s]}</span>
            </div>
          );
        })}
        {isStreaming && <Loader2 size={10} className="ml-1 animate-spin text-blue-500" />}
      </div>

      {/* 详情展开 */}
      {expanded && (
        <div className="px-2.5 pb-2 space-y-1">
          {progress.intent && (
            <div className="flex items-start gap-1.5 text-zinc-600 dark:text-zinc-400">
              <Brain size={10} className="mt-0.5 shrink-0 text-purple-500" />
              <span><b className="text-zinc-700 dark:text-zinc-300">{progress.intent.type}</b>
                <span className="ml-1">置信度 {(progress.intent.confidence * 100).toFixed(0)}%</span>
              </span>
            </div>
          )}
          {progress.guard && (
            <div className="flex items-start gap-1.5 text-zinc-600 dark:text-zinc-400">
              <Shield size={10} className="mt-0.5 shrink-0 text-amber-500" />
              <span><b className={progress.guard.level === "P0" ? "text-red-500" : "text-zinc-700 dark:text-zinc-300"}>
                {progress.guard.level}</b>
                <span className="ml-1">{progress.guard.reason}</span>
              </span>
            </div>
          )}
          {progress.plan && (
            <div className="flex items-start gap-1.5 text-zinc-600 dark:text-zinc-400">
              <Map size={10} className="mt-0.5 shrink-0 text-blue-500" />
              <span><b className="text-zinc-700 dark:text-zinc-300">{progress.plan.steps.length} 步计划：</b>
                {progress.plan.steps.map((s) => s.agent).join(" → ")}
              </span>
            </div>
          )}
          {progress.progressText && (
            <div className="flex items-start gap-1.5 text-zinc-600 dark:text-zinc-400">
              {progress.progressStage === "推理中" ? <Loader2 size={10} className="mt-0.5 shrink-0 animate-spin text-blue-500" /> : <Play size={10} className="mt-0.5 shrink-0 text-emerald-500" />}
              <span>{progress.progressText}</span>
            </div>
          )}
          {(progress.thoughtCount > 0 || progress.tokenCount > 0) && (
            <div className="flex items-center gap-2 text-zinc-400 pt-0.5">
              {progress.thoughtCount > 0 && <span>思考 {progress.thoughtCount} 段</span>}
              {progress.tokenCount > 0 && <span>· 已生成 {progress.tokenCount} 字</span>}
            </div>
          )}
        </div>
      )}

      {/* 折叠按钮 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-2 py-0.5 text-[10px] text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-900 flex items-center justify-center gap-0.5"
      >
        <ChevronDown size={10} className={`transition-transform ${expanded ? "rotate-180" : ""}`} />
        {expanded ? "收起" : "展开"}
      </button>
    </div>
  );
}

// 工具函数：从 sendChat 的 onEvent 流构建 ProgressInfo
export function buildProgressInfo(events: Array<{ type: string; [k: string]: any }>): ProgressInfo {
  const info: ProgressInfo = {
    thoughtCount: 0,
    tokenCount: 0,
    started: false,
  };
  for (const e of events) {
    switch (e.type) {
      case "start": info.started = true; break;
      case "intent": info.intent = { type: e.intent || "?", confidence: e.confidence || 0 }; break;
      case "guard": info.guard = { level: e.level || "?", reason: e.reason || "" }; break;
      case "plan": info.plan = { steps: e.steps || [] }; break;
      case "progress": info.progressStage = e.stage; info.progressText = e.text; break;
      case "thought": info.thoughtCount += 1; break;
      case "token": info.tokenCount += (e.text || "").length; break;
      case "answer": info.tokenCount += (e.text || "").length; break;
    }
  }
  return info;
}
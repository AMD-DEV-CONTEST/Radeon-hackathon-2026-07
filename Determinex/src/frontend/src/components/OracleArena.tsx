"use client";
import React, { useEffect, useState, useRef } from "react";
import { MessageBubble, TypingIndicator, PathInfo } from "./ConceptLab";
import { PathWireframe } from "./PathWireframe";
import { Bot, User, Zap } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export interface OracleState {
  step: string;
  messages: Array<{ role: "user" | "oracle"; text: string }>;
  oracleThinking: boolean;
  oracleTyping: string | null;
  paths: PathInfo[];
  guidedMode: boolean;
  guidedType: string;
  guidedQuestions: string[];
  currentQuestionIdx: number;
  guidedAnswers: string[];
}

export function OracleArena() {
  const [state, setState] = useState<OracleState | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleSync = (e: Event) => {
      setState((e as CustomEvent).detail);
    };
    window.addEventListener("oracle-sync", handleSync);
    return () => window.removeEventListener("oracle-sync", handleSync);
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state?.messages, state?.oracleTyping]);

  if (!state) return null;

  return (
    <div className="flex h-full w-full bg-[var(--dtx-code-bg)] text-gray-300">
      {/* Left side: Conversation */}
      <div className="flex-1 max-w-3xl border-r border-[var(--dtx-code-border)] flex flex-col h-full bg-[var(--dtx-code-bg-deep)]">
        <div className="p-6 border-b border-[var(--dtx-code-border)] flex items-center justify-between">
          <div>
            <h2 className="text-xl font-black text-cyan-400 flex items-center gap-2">
              <Zap size={20} /> Oracle Discovery
            </h2>
            <p className="text-xs text-gray-500 mt-1">
              {state.guidedMode ? `Guided Mode: ${state.guidedType}` : "Freeform exploration"}
            </p>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-8 flex flex-col gap-6">
          <AnimatePresence>
            {state.messages.map((msg, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 10, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ duration: 0.3, ease: "easeOut" }}
                className={`flex gap-4 ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}
              >
                <div
                  className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${msg.role === "oracle" ? "bg-cyan-900/30 text-cyan-400 border border-cyan-500/30" : "bg-purple-900/30 text-purple-400 border border-purple-500/30"}`}
                >
                  {msg.role === "oracle" ? <Bot size={16} /> : <User size={16} />}
                </div>
                <div
                  className={`max-w-[80%] rounded-2xl px-5 py-3.5 text-body leading-relaxed shadow-lg ${msg.role === "oracle" ? "bg-[var(--dtx-code-panel)] border border-[var(--dtx-code-border)]" : "bg-purple-900/10 border border-purple-500/20 text-purple-100"}`}
                >
                  {msg.text}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>

          {state.oracleTyping !== null && (
            <div className="flex gap-4 flex-row">
              <div className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-cyan-900/30 text-cyan-400 border border-cyan-500/30">
                <Bot size={16} />
              </div>
              <div className="max-w-[80%] rounded-2xl px-5 py-3.5 text-body leading-relaxed bg-[var(--dtx-code-panel)] border border-[var(--dtx-code-border)]">
                {state.oracleTyping || "▌"}
              </div>
            </div>
          )}

          {state.oracleThinking && state.oracleTyping === null && (
            <div className="flex gap-4 flex-row">
              <div className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-cyan-900/30 text-cyan-400 border border-cyan-500/30">
                <Bot size={16} />
              </div>
              <div className="max-w-[80%] rounded-2xl px-5 py-3.5 flex items-center bg-[var(--dtx-code-panel)] border border-[var(--dtx-code-border)]">
                <TypingIndicator />
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>
      </div>

      {/* Right side: Visuals / Wireframes */}
      <div className="flex-1 flex items-center justify-center bg-[#05090f] relative overflow-hidden">
        {/* Ambient background glow */}
        <div className="absolute inset-0 flex items-center justify-center opacity-20 pointer-events-none">
          <div className="w-[500px] h-[500px] bg-cyan-500/20 blur-[100px] rounded-full" />
        </div>

        {state.paths.length > 0 ? (
          <div className="z-10 w-[80%] max-w-lg aspect-square">
            {/* Show the wireframe of the best path (first path) */}
            <div className="bg-[var(--dtx-code-bg)] border border-[var(--dtx-code-border)] rounded-2xl p-8 h-full shadow-2xl flex flex-col items-center justify-center relative overflow-hidden transition-all duration-1000 transform translate-y-0 opacity-100">
              <div className="absolute top-4 left-4 text-meta uppercase font-bold tracking-widest text-gray-500">
                Current Blueprint
              </div>
              <div className="absolute top-4 right-4 text-label text-cyan-400 font-mono bg-cyan-950/30 px-2 py-0.5 rounded border border-cyan-500/20">
                {state.paths[0].name}
              </div>

              <div className="flex-1 w-full flex items-center justify-center">
                <PathWireframe path={state.paths[0]} />
              </div>
            </div>
          </div>
        ) : (
          <div className="z-10 text-center opacity-30">
            <Zap size={64} className="mx-auto mb-4" />
            <p className="font-mono text-sm tracking-widest uppercase">Waiting for paths</p>
          </div>
        )}
      </div>
    </div>
  );
}

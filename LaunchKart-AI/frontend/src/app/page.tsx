"use client";

import { motion } from "framer-motion";
import { Rocket, Cpu, Zap, ArrowRight, Activity, BrainCircuit, BarChart3, Sun, Moon, Laptop, ShieldCheck, Layers, GitCompare } from "lucide-react";
import Link from "next/link";
import { useThemeStore } from "@/stores/themeStore";
import { useEffect, useState } from "react";

export default function Home() {
  const { theme, setTheme, initTheme } = useThemeStore();
  const [showThemeMenu, setShowThemeMenu] = useState(false);

  useEffect(() => {
    initTheme();
  }, [initTheme]);

  const container = {
    hidden: { opacity: 0 },
    show: {
      opacity: 1,
      transition: {
        staggerChildren: 0.1,
        delayChildren: 0.2,
      },
    },
  };

  const item = {
    hidden: { opacity: 0, y: 20 },
    show: { opacity: 1, y: 0, transition: { type: "spring" as const, stiffness: 300, damping: 24 } },
  };

  return (
    <main className="relative min-h-screen flex flex-col items-center overflow-x-hidden bg-[var(--color-background)] text-[var(--color-foreground)] selection:bg-[var(--color-brand-primary)] selection:text-white transition-colors duration-200">
      {/* Dynamic Ambient Background Elements */}
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-gradient-to-r from-[var(--color-brand-primary)]/15 to-purple-600/10 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-gradient-to-l from-blue-600/10 to-[var(--color-brand-primary)]/15 blur-[120px] pointer-events-none" />
      <div className="absolute top-[20%] right-[20%] w-[20%] h-[20%] rounded-full bg-gradient-to-b from-[var(--color-brand-primary)]/10 to-transparent blur-[80px] pointer-events-none" />

      {/* Grid Pattern overlay */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,var(--color-border)_1px,transparent_1px),linear-gradient(to_bottom,var(--color-border)_1px,transparent_1px)] bg-[size:32px_32px] opacity-40 pointer-events-none" />

      {/* Top Landing Nav Bar */}
      <header className="relative z-20 w-full max-w-6xl mx-auto px-6 h-20 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 rounded-xl bg-[var(--color-brand-primary)] flex items-center justify-center text-white font-black text-lg shadow-md">
            LK
          </div>
          <span className="font-extrabold text-xl tracking-tight text-[var(--color-foreground)]">
            LaunchKart <span className="text-red-500 font-black">AI</span>
          </span>
          <span className="ml-2.5 text-[10px] uppercase px-2.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-500 border border-emerald-500/30 font-bold hidden sm:inline-block shadow-sm">
            PRO v2.5
          </span>
        </div>

        <div className="flex items-center gap-4">
          {/* Theme Switcher Toggle */}
          <div className="relative">
            <button
              onClick={() => setShowThemeMenu(!showThemeMenu)}
              className="flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white/5 border border-white/10 text-xs font-semibold text-[var(--color-foreground)] hover:border-red-500/50 shadow-sm transition-all backdrop-blur-md"
            >
              {theme === "light" ? (
                <>
                  <Sun className="w-4 h-4 text-amber-500" /> <span>Light Mode</span>
                </>
              ) : theme === "dark" ? (
                <>
                  <Moon className="w-4 h-4 text-blue-400" /> <span>Dark Mode</span>
                </>
              ) : (
                <>
                  <Laptop className="w-4 h-4 text-gray-400" /> <span>System Default</span>
                </>
              )}
            </button>

            {showThemeMenu && (
              <div className="absolute right-0 mt-2 w-44 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl shadow-2xl p-2 z-50 text-left space-y-1">
                <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-muted)] px-2 py-1">
                  Theme Preference
                </div>
                <button
                  onClick={() => { setTheme("light"); setShowThemeMenu(false); }}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                    theme === "light"
                      ? "bg-[var(--color-brand-primary)]/15 text-[var(--color-brand-primary)] font-bold"
                      : "text-[var(--color-foreground)] hover:bg-[var(--color-surface-hover)]"
                  }`}
                >
                  <Sun className="w-4 h-4 text-amber-500" /> Light Mode
                </button>
                <button
                  onClick={() => { setTheme("dark"); setShowThemeMenu(false); }}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                    theme === "dark"
                      ? "bg-[var(--color-brand-primary)]/15 text-[var(--color-brand-primary)] font-bold"
                      : "text-[var(--color-foreground)] hover:bg-[var(--color-surface-hover)]"
                  }`}
                >
                  <Moon className="w-4 h-4 text-blue-400" /> Dark Mode
                </button>
                <button
                  onClick={() => { setTheme("system"); setShowThemeMenu(false); }}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                    theme === "system"
                      ? "bg-[var(--color-brand-primary)]/15 text-[var(--color-brand-primary)] font-bold"
                      : "text-[var(--color-foreground)] hover:bg-[var(--color-surface-hover)]"
                  }`}
                >
                  <Laptop className="w-4 h-4 text-gray-400" /> System Default
                </button>
              </div>
            )}
          </div>

          <Link href="/dashboard">
            <button className="text-xs font-bold uppercase tracking-wider px-4 py-2 rounded-lg bg-[var(--color-brand-primary)] text-white hover:bg-red-700 transition-colors shadow-md">
              Go to Suite
            </button>
          </Link>
        </div>
      </header>

      <div className="relative z-10 w-full max-w-6xl px-6 pt-20 pb-24 mx-auto flex flex-col items-center text-center">
        {/* Hardware & Security Badge */}
        <motion.div
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="flex items-center gap-3 px-5 py-2.5 rounded-full bg-gradient-to-r from-red-500/15 via-neutral-900/80 to-orange-500/15 border border-red-500/30 mb-8 shadow-[0_0_25px_rgba(237,28,36,0.2)] backdrop-blur-xl"
        >
          <span className="flex h-2.5 w-2.5 relative">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-red-500" />
          </span>
          <Cpu className="w-4 h-4 text-red-500" />
          <span className="text-xs md:text-sm font-bold tracking-wide text-white">
            AMD Radeon ROCm 6.1 Acceleration • 15 Autonomous Agents
          </span>
        </motion.div>

        {/* Hero Title */}
        <motion.h1
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.2, ease: "easeOut" }}
          className="text-4xl sm:text-6xl md:text-7xl font-black tracking-tight mb-6 text-[var(--color-foreground)] leading-tight"
        >
          Welcome to <br className="hidden md:block" />
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-[var(--color-brand-primary)] via-red-500 to-amber-500 drop-shadow-sm">
            LaunchKart PRO
          </span>
        </motion.h1>

        {/* Subtitle */}
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.3, ease: "easeOut" }}
          className="text-base md:text-xl text-[var(--color-muted)] max-w-3xl mb-12 font-normal leading-relaxed"
        >
          The enterprise multi-channel e-commerce syndication and automation suite. Orchestrate product intelligence, dynamic pricing, and marketplace distribution in seconds with AMD Radeon hardware acceleration.
        </motion.p>

        {/* Call to Actions */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.4, ease: "easeOut" }}
          className="flex flex-col sm:flex-row gap-4 mb-24 w-full sm:w-auto"
        >
          <Link href="/dashboard">
            <button className="w-full sm:w-auto group relative flex items-center justify-center gap-3 px-8 py-4 bg-gradient-to-r from-[var(--color-brand-primary)] to-red-700 hover:from-red-600 hover:to-[var(--color-brand-primary)] text-white rounded-xl font-bold text-base transition-all duration-300 shadow-[0_0_25px_rgba(237,28,36,0.3)] hover:shadow-[0_0_35px_rgba(237,28,36,0.5)] transform hover:-translate-y-0.5">
              <Rocket className="w-5 h-5 fill-current" />
              <span>Launch Orchestration Suite</span>
              <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
            </button>
          </Link>
          <Link href="/marketplace">
            <button className="w-full sm:w-auto flex items-center justify-center gap-3 px-8 py-4 bg-[var(--color-surface)] hover:bg-[var(--color-surface-hover)] text-[var(--color-foreground)] border border-[var(--color-border)] rounded-xl font-bold text-base transition-all duration-300 shadow-md hover:-translate-y-0.5">
              <GitCompare className="w-5 h-5 text-[var(--color-brand-primary)]" />
              <span>Multi-Channel Catalog Hub</span>
            </button>
          </Link>
        </motion.div>

        {/* Features Grid */}
        <motion.div
          variants={container}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 md:grid-cols-3 gap-6 w-full text-left"
        >
          {[
            {
              icon: Layers,
              title: "15 Autonomous AI Agents",
              desc: "An automated orchestration pipeline handling everything from keyword generation to dynamic pricing and syndication.",
              badge: "AI Pipeline",
            },
            {
              icon: Zap,
              title: "AMD Radeon ROCm Acceleration",
              desc: "High-throughput local compute acceleration powered by ROCm 6.1 and AMD Radeon hardware infrastructure.",
              badge: "Hardware Accelerated",
            },
            {
              icon: ShieldCheck,
              title: "Compliance & Policy Guard",
              desc: "Real-time validation engine enforcing platform guidelines, character limits, and enterprise brand storytelling rules.",
              badge: "Strict Guardrails",
            },
          ].map((feature, i) => (
            <motion.div
              key={i}
              variants={item}
              className="p-7 rounded-2xl border border-white/10 bg-gradient-to-b from-neutral-900/80 to-neutral-950/90 hover:border-white/20 transition-all duration-300 group shadow-xl hover:shadow-2xl flex flex-col justify-between backdrop-blur-xl"
            >
              <div>
                <div className="flex items-center justify-between mb-5">
                  <div className="w-12 h-12 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center group-hover:scale-110 transition-transform shadow-inner">
                    <feature.icon className="w-6 h-6 text-red-500" />
                  </div>
                  <span className="text-[10px] font-bold uppercase tracking-wider px-3 py-1 rounded-full bg-white/5 text-neutral-300 border border-white/10 shadow-sm">
                    {feature.badge}
                  </span>
                </div>
                <h3 className="text-xl font-bold mb-2 text-white">{feature.title}</h3>
                <p className="text-neutral-400 leading-relaxed text-sm font-normal">{feature.desc}</p>
              </div>

              <div className="mt-6 pt-4 border-t border-white/10 flex items-center justify-between text-xs font-semibold text-neutral-400">
                <span>System Status:</span>
                <span className="text-emerald-400 font-bold uppercase flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span> Online
                </span>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </main>
  );
}

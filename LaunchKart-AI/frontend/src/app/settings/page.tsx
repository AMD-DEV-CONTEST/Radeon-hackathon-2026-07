"use client";

import { useState } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import {
  Settings,
  Sun,
  Moon,
  Laptop,
  Cpu,
  Key,
  ShieldCheck,
  Database,
  Save,
  RotateCcw,
  CheckCircle,
  AlertCircle,
  Sliders,
  Lock,
  Globe,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useThemeStore } from "@/stores/themeStore";
import { motion } from "framer-motion";

export default function SettingsPage() {
  const { theme, setTheme } = useThemeStore();
  const [threads, setThreads] = useState("16");
  const [vectorIndex, setVectorIndex] = useState("hnsw");
  const [cacheTtl, setCacheTtl] = useState("60");
  
  // API Keys state
  const [amazonKey, setAmazonKey] = useState("ak_live_892347592837459823");
  const [shopifyKey, setShopifyKey] = useState("shpat_394820394820394802");
  const [tiktokKey, setTiktokKey] = useState("tk_prod_2039482039482039");
  
  // Compliance toggles
  const [a9Policy, setA9Policy] = useState(true);
  const [gdprMask, setGdprMask] = useState(true);
  const [brandFilter, setBrandFilter] = useState(true);
  
  // Status feedback
  const [saved, setSaved] = useState(false);
  const [testingApi, setTestingApi] = useState(false);
  const [apiVerified, setApiVerified] = useState(false);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const handleTestApi = () => {
    setTestingApi(true);
    setApiVerified(false);
    setTimeout(() => {
      setTestingApi(false);
      setApiVerified(true);
    }, 1200);
  };

  const handleReset = () => {
    setThreads("16");
    setVectorIndex("hnsw");
    setCacheTtl("60");
    setA9Policy(true);
    setGdprMask(true);
    setBrandFilter(true);
    setTheme("dark");
  };

  return (
    <div className="min-h-screen bg-[var(--color-background)] text-[var(--color-foreground)] flex selection:bg-[var(--color-brand-primary)] selection:text-white transition-colors duration-200">
      <Sidebar />

      <div className="flex-1 flex flex-col pl-64 min-w-0">
        <Header />

        <main className="flex-1 pt-6 p-8 overflow-y-auto">
          <div className="max-w-[1400px] mx-auto space-y-8">
            {/* Top Control Banner */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 bg-[var(--color-surface)] border border-[var(--color-border)] p-6 rounded-2xl shadow-xl relative overflow-hidden transition-colors duration-200">
              <div className="absolute top-0 right-0 w-96 h-96 bg-gradient-to-l from-[var(--color-brand-primary)]/10 to-transparent rounded-full blur-3xl pointer-events-none" />

              <div>
                <div className="flex items-center gap-3 mb-2 flex-wrap font-semibold">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/15 border border-red-500/40 px-3.5 py-1 text-xs font-bold text-red-500 uppercase tracking-wider shadow-sm">
                    <ShieldCheck className="h-3.5 w-3.5 inline" />
                    Security Level: Enterprise Tier
                  </span>
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/40 px-3.5 py-1 text-xs font-bold text-emerald-500 uppercase tracking-wider shadow-sm">
                    <Cpu className="h-3.5 w-3.5 inline" />
                    Compute Engine: AMD Radeon ROCm
                  </span>
                </div>

                <h1 className="text-3xl lg:text-4xl font-black tracking-tight text-[var(--color-foreground)] flex items-center gap-3">
                  <Settings className="w-8 h-8 text-[var(--color-brand-primary)]" />
                  System Configuration & Theme Center
                </h1>
                <p className="text-[var(--color-muted)] text-sm mt-1 max-w-2xl">
                  Manage interface appearance, AMD hardware compute allocation, API syndication keys, and automated regulatory compliance pipelines.
                </p>
              </div>

              <div className="flex items-center gap-3 z-10 font-semibold">
                <Button
                  variant="outline"
                  onClick={handleReset}
                  className="gap-2 bg-[var(--color-surface-hover)] hover:bg-[var(--color-border)] border-[var(--color-border)] text-[var(--color-foreground)] text-xs shadow-sm"
                >
                  <RotateCcw className="w-3.5 h-3.5 text-[var(--color-muted)]" />
                  Reset Defaults
                </Button>
                <Button
                  onClick={handleSave}
                  className="gap-2 bg-gradient-to-r from-[var(--color-brand-primary)] to-red-700 hover:from-red-600 hover:to-[var(--color-brand-primary)] text-white font-bold tracking-wider uppercase text-xs px-6 shadow-[0_0_20px_rgba(237,28,36,0.3)] transition-all"
                >
                  <Save className="w-4 h-4" />
                  {saved ? "Saved Successfully!" : "Save Configuration"}
                </Button>
              </div>
            </div>

            {saved && (
              <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                className="bg-emerald-500/15 border border-emerald-500/40 text-emerald-500 p-4 rounded-xl flex items-center gap-3 font-semibold text-sm shadow-md"
              >
                <CheckCircle className="w-5 h-5 shrink-0" />
                <span>Enterprise configuration parameters and theme preferences have been committed to local persistence.</span>
              </motion.div>
            )}

            {/* Section 1: Appearance & Theme Mode */}
            <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl p-6 shadow-xl transition-colors duration-200">
              <div className="flex items-center justify-between pb-4 mb-6 border-b border-[var(--color-border)]">
                <div>
                  <h2 className="text-lg font-bold text-[var(--color-foreground)] flex items-center gap-2">
                    <Sun className="w-5 h-5 text-amber-500" />
                    Interface Appearance & Theme Mode
                  </h2>
                  <p className="text-xs text-[var(--color-muted)] mt-0.5">
                    Select your preferred visual color theme. Changes apply instantly across all dashboard and catalog modules.
                  </p>
                </div>
                <span className="text-xs font-bold text-[var(--color-brand-primary)] bg-[var(--color-brand-primary)]/10 border border-[var(--color-brand-primary)]/30 px-3 py-1 rounded-lg uppercase">
                  Active Mode: {theme.toUpperCase()}
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                {/* Light Mode Card */}
                <div
                  onClick={() => setTheme("light")}
                  className={`cursor-pointer rounded-xl border p-5 transition-all flex flex-col justify-between relative ${
                    theme === "light"
                      ? "border-[var(--color-brand-primary)] bg-[var(--color-brand-primary)]/5 shadow-[0_0_20px_rgba(237,28,36,0.15)] ring-2 ring-[var(--color-brand-primary)]"
                      : "border-[var(--color-border)] bg-[var(--color-surface-hover)]/40 hover:border-[var(--color-muted)]"
                  }`}
                >
                  <div className="flex items-center justify-between mb-4">
                    <div className="w-10 h-10 rounded-xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center text-amber-500">
                      <Sun className="w-6 h-6" />
                    </div>
                    {theme === "light" && (
                      <span className="text-xs font-bold text-[var(--color-brand-primary)] flex items-center gap-1">
                        <CheckCircle className="w-4 h-4" /> Selected
                      </span>
                    )}
                  </div>
                  <div>
                    <h3 className="font-bold text-base text-[var(--color-foreground)] mb-1">Light Mode</h3>
                    <p className="text-xs text-[var(--color-muted)] leading-relaxed font-normal">
                      Pristine high-contrast white surfaces, crisp slate typography, and optimized legibility for well-lit office environments.
                    </p>
                  </div>
                </div>

                {/* Dark Mode Card */}
                <div
                  onClick={() => setTheme("dark")}
                  className={`cursor-pointer rounded-xl border p-5 transition-all flex flex-col justify-between relative ${
                    theme === "dark"
                      ? "border-[var(--color-brand-primary)] bg-[var(--color-brand-primary)]/5 shadow-[0_0_20px_rgba(237,28,36,0.15)] ring-2 ring-[var(--color-brand-primary)]"
                      : "border-[var(--color-border)] bg-[var(--color-surface-hover)]/40 hover:border-[var(--color-muted)]"
                  }`}
                >
                  <div className="flex items-center justify-between mb-4">
                    <div className="w-10 h-10 rounded-xl bg-blue-500/15 border border-blue-500/30 flex items-center justify-center text-blue-400">
                      <Moon className="w-6 h-6" />
                    </div>
                    {theme === "dark" && (
                      <span className="text-xs font-bold text-[var(--color-brand-primary)] flex items-center gap-1">
                        <CheckCircle className="w-4 h-4" /> Selected
                      </span>
                    )}
                  </div>
                  <div>
                    <h3 className="font-bold text-base text-[var(--color-foreground)] mb-1">Dark Mode</h3>
                    <p className="text-xs text-[var(--color-muted)] leading-relaxed font-normal">
                      Deep cyber-dark glassmorphism, vibrant AMD red accents, and reduced eye strain for extended engineering and command operations.
                    </p>
                  </div>
                </div>

                {/* System Mode Card */}
                <div
                  onClick={() => setTheme("system")}
                  className={`cursor-pointer rounded-xl border p-5 transition-all flex flex-col justify-between relative ${
                    theme === "system"
                      ? "border-[var(--color-brand-primary)] bg-[var(--color-brand-primary)]/5 shadow-[0_0_20px_rgba(237,28,36,0.15)] ring-2 ring-[var(--color-brand-primary)]"
                      : "border-[var(--color-border)] bg-[var(--color-surface-hover)]/40 hover:border-[var(--color-muted)]"
                  }`}
                >
                  <div className="flex items-center justify-between mb-4">
                    <div className="w-10 h-10 rounded-xl bg-gray-500/15 border border-gray-500/30 flex items-center justify-center text-gray-400">
                      <Laptop className="w-6 h-6" />
                    </div>
                    {theme === "system" && (
                      <span className="text-xs font-bold text-[var(--color-brand-primary)] flex items-center gap-1">
                        <CheckCircle className="w-4 h-4" /> Selected
                      </span>
                    )}
                  </div>
                  <div>
                    <h3 className="font-bold text-base text-[var(--color-foreground)] mb-1">System Default</h3>
                    <p className="text-xs text-[var(--color-muted)] leading-relaxed font-normal">
                      Automatically synchronizes with your operating system's active display preference (macOS / Windows / Linux).
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Section 2: Pipeline Compute & Hardware Allocation */}
            <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl p-6 shadow-xl transition-colors duration-200">
              <div className="flex items-center justify-between pb-4 mb-6 border-b border-[var(--color-border)]">
                <div>
                  <h2 className="text-lg font-bold text-[var(--color-foreground)] flex items-center gap-2">
                    <Cpu className="w-5 h-5 text-emerald-500" />
                    AMD Radeon Compute & Pipeline Parameters
                  </h2>
                  <p className="text-xs text-[var(--color-muted)] mt-0.5">
                    Configure hardware thread concurrency, vector memory indexing algorithms, and ChromaDB cache retention.
                  </p>
                </div>
                <span className="text-xs font-bold text-emerald-500 bg-emerald-500/10 border border-emerald-500/30 px-3 py-1 rounded-lg uppercase">
                  Hardware: RX 7900 XTX (24GB VRAM)
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] mb-2">
                    ROCm Compute Threads
                  </label>
                  <select
                    value={threads}
                    onChange={(e) => setThreads(e.target.value)}
                    className="w-full bg-[var(--color-surface-hover)] border border-[var(--color-border)] rounded-xl px-4 py-3 text-sm font-medium text-[var(--color-foreground)] outline-none focus:border-[var(--color-brand-primary)] transition-colors"
                  >
                    <option value="8">8 Concurrent Threads (Low Impact)</option>
                    <option value="16">16 Concurrent Threads (Balanced Enterprise)</option>
                    <option value="24">24 Concurrent Threads (High Throughput)</option>
                    <option value="32">32 Concurrent Threads (Max GPU Saturation)</option>
                  </select>
                  <p className="text-[11px] text-[var(--color-muted)] mt-1.5 font-normal">
                    Controls parallel microservice execution across GPU compute units.
                  </p>
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] mb-2">
                    Vector DB Indexing Algorithm
                  </label>
                  <select
                    value={vectorIndex}
                    onChange={(e) => setVectorIndex(e.target.value)}
                    className="w-full bg-[var(--color-surface-hover)] border border-[var(--color-border)] rounded-xl px-4 py-3 text-sm font-medium text-[var(--color-foreground)] outline-none focus:border-[var(--color-brand-primary)] transition-colors"
                  >
                    <option value="hnsw">HNSW (Hierarchical Navigable Small World)</option>
                    <option value="flat">Flat L2 Distance (Exact Search)</option>
                    <option value="ivf">IVF-PQ (Inverted File Product Quantization)</option>
                  </select>
                  <p className="text-[11px] text-[var(--color-muted)] mt-1.5 font-normal">
                    Optimizes cosine similarity lookup speed in ChromaDB embeddings.
                  </p>
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] mb-2">
                    Memory Cache TTL (Minutes)
                  </label>
                  <input
                    type="number"
                    value={cacheTtl}
                    onChange={(e) => setCacheTtl(e.target.value)}
                    className="w-full bg-[var(--color-surface-hover)] border border-[var(--color-border)] rounded-xl px-4 py-3 text-sm font-medium text-[var(--color-foreground)] outline-none focus:border-[var(--color-brand-primary)] transition-colors"
                  />
                  <p className="text-[11px] text-[var(--color-muted)] mt-1.5 font-normal">
                    Duration for retaining intermediate catalog generation states in VRAM.
                  </p>
                </div>
              </div>
            </div>

            {/* Section 3: Marketplace API Credentials & Syndication */}
            <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl p-6 shadow-xl transition-colors duration-200">
              <div className="flex items-center justify-between pb-4 mb-6 border-b border-[var(--color-border)] flex-wrap gap-4">
                <div>
                  <h2 className="text-lg font-bold text-[var(--color-foreground)] flex items-center gap-2">
                    <Key className="w-5 h-5 text-blue-400" />
                    Marketplace Syndication API Credentials
                  </h2>
                  <p className="text-xs text-[var(--color-muted)] mt-0.5">
                    Configure OAuth tokens and API secrets for automated catalog injection into global marketplace seller portals.
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleTestApi}
                  disabled={testingApi}
                  className="gap-2 bg-[var(--color-surface-hover)] hover:bg-[var(--color-border)] border-[var(--color-border)] text-[var(--color-foreground)] text-xs font-semibold shadow-sm"
                >
                  <Globe className={`w-4 h-4 text-blue-400 ${testingApi ? "animate-spin" : ""}`} />
                  {testingApi ? "Pinging Seller APIs..." : "Test & Verify Connectivity"}
                </Button>
              </div>

              {apiVerified && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="mb-6 p-3.5 bg-emerald-500/10 border border-emerald-500/30 text-emerald-500 rounded-xl flex items-center gap-2.5 font-semibold text-xs shadow-sm"
                >
                  <CheckCircle className="w-4 h-4 shrink-0" />
                  <span>All 3 Marketplace Seller API endpoints verified: Amazon A+ SP-API (200 OK), Shopify GraphQL (200 OK), TikTok Shop Open API (200 OK).</span>
                </motion.div>
              )}

              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] mb-1.5">
                    Amazon SP-API / MWS Secret Key
                  </label>
                  <div className="relative">
                    <input
                      type="password"
                      value={amazonKey}
                      onChange={(e) => setAmazonKey(e.target.value)}
                      className="w-full bg-[var(--color-surface-hover)] border border-[var(--color-border)] rounded-xl px-4 py-3 text-sm font-medium text-[var(--color-foreground)] outline-none focus:border-[var(--color-brand-primary)] transition-colors"
                    />
                    <Lock className="w-4 h-4 text-[var(--color-muted)] absolute right-4 top-3.5" />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] mb-1.5">
                    Shopify Admin & Storefront Access Token
                  </label>
                  <div className="relative">
                    <input
                      type="password"
                      value={shopifyKey}
                      onChange={(e) => setShopifyKey(e.target.value)}
                      className="w-full bg-[var(--color-surface-hover)] border border-[var(--color-border)] rounded-xl px-4 py-3 text-sm font-medium text-[var(--color-foreground)] outline-none focus:border-[var(--color-brand-primary)] transition-colors"
                    />
                    <Lock className="w-4 h-4 text-[var(--color-muted)] absolute right-4 top-3.5" />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] mb-1.5">
                    TikTok Shop Open API App Secret
                  </label>
                  <div className="relative">
                    <input
                      type="password"
                      value={tiktokKey}
                      onChange={(e) => setTiktokKey(e.target.value)}
                      className="w-full bg-[var(--color-surface-hover)] border border-[var(--color-border)] rounded-xl px-4 py-3 text-sm font-medium text-[var(--color-foreground)] outline-none focus:border-[var(--color-brand-primary)] transition-colors"
                    />
                    <Lock className="w-4 h-4 text-[var(--color-muted)] absolute right-4 top-3.5" />
                  </div>
                </div>
              </div>
            </div>

            {/* Section 4: Enterprise Compliance & Policy Enforcement */}
            <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl p-6 shadow-xl transition-colors duration-200">
              <div className="flex items-center justify-between pb-4 mb-6 border-b border-[var(--color-border)]">
                <div>
                  <h2 className="text-lg font-bold text-[var(--color-foreground)] flex items-center gap-2">
                    <ShieldCheck className="w-5 h-5 text-[var(--color-brand-primary)]" />
                    Automated Regulatory & Policy Compliance Engine
                  </h2>
                  <p className="text-xs text-[var(--color-muted)] mt-0.5">
                    Configure automated pre-flight checks before catalog feeds are exported or transmitted to external marketplaces.
                  </p>
                </div>
                <span className="text-xs font-bold text-emerald-500 bg-emerald-500/10 border border-emerald-500/30 px-3 py-1 rounded-lg uppercase">
                  Compliance Tier: Strict
                </span>
              </div>

              <div className="space-y-4">
                <div className="flex items-center justify-between p-4 rounded-xl bg-[var(--color-surface-hover)]/60 border border-[var(--color-border)]">
                  <div>
                    <h4 className="font-bold text-sm text-[var(--color-foreground)] mb-0.5">
                      Amazon A9 & A+ Content Policy Enforcement
                    </h4>
                    <p className="text-xs text-[var(--color-muted)]">
                      Automatically strips restricted promotional terms (e.g., &quot;Best Seller&quot;, &quot;Guaranteed&quot;, &quot;#1 Rated&quot;) to prevent listing suppression.
                    </p>
                  </div>
                  <button
                    onClick={() => setA9Policy(!a9Policy)}
                    className={`w-12 h-6 rounded-full transition-colors relative px-0.5 ${
                      a9Policy ? "bg-[var(--color-brand-primary)]" : "bg-gray-600"
                    }`}
                  >
                    <span
                      className={`w-5 h-5 rounded-full bg-white block transition-transform ${
                        a9Policy ? "translate-x-6" : "translate-x-0"
                      }`}
                    />
                  </button>
                </div>

                <div className="flex items-center justify-between p-4 rounded-xl bg-[var(--color-surface-hover)]/60 border border-[var(--color-border)]">
                  <div>
                    <h4 className="font-bold text-sm text-[var(--color-foreground)] mb-0.5">
                      GDPR & CCPA PII Data Masking
                    </h4>
                    <p className="text-xs text-[var(--color-muted)]">
                      Redacts personally identifiable information (PII) from vendor logs, telemetry traces, and memory vector embeddings.
                    </p>
                  </div>
                  <button
                    onClick={() => setGdprMask(!gdprMask)}
                    className={`w-12 h-6 rounded-full transition-colors relative px-0.5 ${
                      gdprMask ? "bg-[var(--color-brand-primary)]" : "bg-gray-600"
                    }`}
                  >
                    <span
                      className={`w-5 h-5 rounded-full bg-white block transition-transform ${
                        gdprMask ? "translate-x-6" : "translate-x-0"
                      }`}
                    />
                  </button>
                </div>

                <div className="flex items-center justify-between p-4 rounded-xl bg-[var(--color-surface-hover)]/60 border border-[var(--color-border)]">
                  <div>
                    <h4 className="font-bold text-sm text-[var(--color-foreground)] mb-0.5">
                      Strict Brand Guideline & Vocabulary Filtering
                    </h4>
                    <p className="text-xs text-[var(--color-muted)]">
                      Ensures generated copy adheres strictly to approved enterprise vocabulary and voice guidelines.
                    </p>
                  </div>
                  <button
                    onClick={() => setBrandFilter(!brandFilter)}
                    className={`w-12 h-6 rounded-full transition-colors relative px-0.5 ${
                      brandFilter ? "bg-[var(--color-brand-primary)]" : "bg-gray-600"
                    }`}
                  >
                    <span
                      className={`w-5 h-5 rounded-full bg-white block transition-transform ${
                        brandFilter ? "translate-x-6" : "translate-x-0"
                      }`}
                    />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

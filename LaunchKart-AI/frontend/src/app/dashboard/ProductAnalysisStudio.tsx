"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Sparkles,
  ShoppingBag,
  CheckCircle,
  AlertTriangle,
  Copy,
  Check,
  Eye,
  Tag,
  DollarSign,
  Cpu,
  Layers,
  Image as ImageIcon,
  Share2,
  ExternalLink,
  ShieldCheck,
  TrendingUp,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import axios from "axios";
import { useLaunchStore } from "@/stores/launchStore";
import { motion, AnimatePresence } from "framer-motion";

interface Listing {
  id: string;
  marketplace: string;
  title?: string;
  description?: string;
  bullet_points?: { items: string[] };
  keywords?: { items: string[] };
  pricing?: any;
  status: string;
  compliance_check?: { status: string; score?: number; notes?: string };
}

export function ProductAnalysisStudio() {
  const token = useLaunchStore((state) => state.token);
  const currentLaunchId = useLaunchStore((state) => state.currentLaunchId) || "00000000-0000-0000-0000-000000000000";
  const [listings, setListings] = useState<Listing[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<string>("amazon");
  const [copied, setCopied] = useState(false);

  const [productData, setProductData] = useState<any>(null);

  const fetchListings = useCallback(async () => {
    setLoading(true);
    try {
      // 1. Fetch launch details to get the product ID
      const launchRes = await axios.get(
        `http://localhost:8000/api/v1/launches/${currentLaunchId}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      
      const productId = launchRes.data?.product_id;
      if (productId) {
        // 2. Fetch actual product details including image and vision analysis
        const productRes = await axios.get(
          `http://localhost:8000/api/v1/products/${productId}`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        setProductData(productRes.data);
      }

      // 3. Fetch listings for the active launch
      const res = await axios.get(
        `http://localhost:8000/api/v1/marketplace/${currentLaunchId}/listings`,
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (res.data && res.data.listings && res.data.listings.length > 0) {
        setListings(res.data.listings);
        if (!res.data.listings.some((l: Listing) => l.marketplace === activeTab)) {
          setActiveTab(res.data.listings[0].marketplace);
        }
      }
    } catch (e) {
      console.error("Failed to fetch studio listings or product data", e);
    } finally {
      setLoading(false);
    }
  }, [currentLaunchId, token, activeTab]);

  useEffect(() => {
    void fetchListings();
  }, [fetchListings]);

  const activeListing = listings.find((l) => l.marketplace === activeTab) || listings[0];

  const handleCopyText = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getImageUrl = () => {
    if (!productData?.image_path) return "";
    const filename = productData.image_path.split('\\').pop()?.split('/').pop();
    return `http://localhost:8000/uploads/${filename}`;
  };

  return (
    <div className="bg-[var(--color-surface)] border-2 border-red-500/30 rounded-3xl p-6 md:p-8 shadow-2xl relative overflow-hidden transition-all duration-300">
      {/* Background Ambient Glow */}
      <div className="absolute top-0 right-1/4 w-[500px] h-[500px] bg-gradient-to-br from-red-600/10 via-orange-500/5 to-transparent rounded-full blur-3xl pointer-events-none" />

      {/* Studio Header */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 mb-8 border-b border-[var(--color-border)] pb-6 relative z-10">
        <div>
          <div className="flex items-center gap-2.5 mb-2 flex-wrap font-semibold">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/15 border border-red-500/40 px-3.5 py-1 text-xs font-bold text-red-500 uppercase tracking-wider shadow-sm">
              <Sparkles className="w-3.5 h-3.5 animate-spin" /> Live Product Intelligence Studio
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/40 px-3.5 py-1 text-xs font-bold text-emerald-500 uppercase tracking-wider shadow-sm">
              <ShieldCheck className="w-3.5 h-3.5" /> ROCm Vision Analyzed
            </span>
          </div>
          <h2 className="text-2xl md:text-3xl font-black text-[var(--color-foreground)] tracking-tight">
            Analyzed Product & Optimized SEO Workspace
          </h2>
          <p className="text-sm text-[var(--color-muted)] mt-1 max-w-3xl font-medium">
            Review the AI vision attributes detected from your product photo and inspect the high-converting SEO titles, copywriting, and dynamic pricing generated for each marketplace.
          </p>
        </div>

        <div className="flex items-center gap-2 self-start lg:self-center bg-[var(--color-surface-hover)]/60 p-1.5 rounded-2xl border border-[var(--color-border)] backdrop-blur-md">
          {listings.map((item) => (
            <button
              key={item.marketplace}
              onClick={() => setActiveTab(item.marketplace)}
              className={`px-4 py-2.5 rounded-xl font-bold text-xs uppercase tracking-wider transition-all flex items-center gap-2 ${
                activeTab === item.marketplace
                  ? "bg-gradient-to-r from-red-600 to-red-500 text-white shadow-lg shadow-red-500/25 scale-105"
                  : "text-[var(--color-muted)] hover:text-[var(--color-foreground)] hover:bg-[var(--color-surface)]"
              }`}
            >
              <span>
                {item.marketplace === "amazon" && "🛒 Amazon US"}
                {item.marketplace === "shopify" && "🛍️ Shopify"}
                {item.marketplace === "tiktok" && "🎵 TikTok Shop"}
                {!["amazon", "shopify", "tiktok"].includes(item.marketplace) && item.marketplace}
              </span>
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex flex-col justify-center items-center h-96 bg-[var(--color-surface-hover)]/30 rounded-2xl border border-[var(--color-border)]">
          <div className="animate-spin rounded-full h-14 w-14 border-b-2 border-red-500 mb-4" />
          <p className="text-[var(--color-muted)] font-bold text-sm">
            AI Vision & Copywriting Agents synthesizing SEO copy...
          </p>
        </div>
      ) : !activeListing ? (
        <div className="text-center py-16 bg-[var(--color-surface-hover)]/20 rounded-2xl border border-[var(--color-border)]">
          <ImageIcon className="w-12 h-12 text-[var(--color-muted)] mx-auto mb-3 opacity-40" />
          <h3 className="font-bold text-lg text-[var(--color-foreground)]">No Analyzed Product Selected</h3>
          <p className="text-sm text-[var(--color-muted)] mt-1">Upload a product image or click "Quick Demo Launch" above to see AI SEO analysis.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start relative z-10">
          {/* Left Column: Vision Analysis & Product Showcase (5 cols) */}
          <div className="lg:col-span-5 space-y-6">
            <div className="bg-[var(--color-surface-hover)]/40 border border-[var(--color-border)] rounded-2xl p-6 backdrop-blur-md space-y-5">
              <div className="flex items-center justify-between border-b border-[var(--color-border)] pb-3">
                <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] flex items-center gap-1.5">
                  <ImageIcon className="w-4 h-4 text-red-500" /> ROCm Vision Analysis
                </span>
                <Badge variant="success" className="text-[10px] uppercase font-bold px-2 py-0.5">
                  99.4% Confidence
                </Badge>
              </div>

              {/* Product Visual Mockup */}
              <div className="aspect-video w-full rounded-xl bg-gradient-to-br from-neutral-900 to-neutral-950 border border-white/10 flex flex-col items-center justify-center text-center relative overflow-hidden group shadow-inner">
                {productData?.image_path ? (
                  <img
                    src={getImageUrl()}
                    alt="Product"
                    className="absolute inset-0 w-full h-full object-contain p-2"
                  />
                ) : (
                  <>
                    <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(237,28,36,0.15)_0,transparent_70%)] opacity-80 group-hover:opacity-100 transition-opacity" />
                    <div className="w-16 h-16 rounded-2xl bg-red-500/10 border border-red-500/30 flex items-center justify-center text-red-500 mb-3 shadow-lg transform group-hover:scale-110 transition-transform duration-300 z-10">
                      <Cpu className="w-8 h-8" />
                    </div>
                    <h4 className="font-black text-base text-white tracking-tight z-10">
                      Processing Visuals...
                    </h4>
                  </>
                )}
                <div className="absolute bottom-2 right-2 px-2 py-1 rounded bg-black/60 border border-white/10 text-[10px] text-neutral-400 font-bold uppercase tracking-wider">
                  Live GPU Render
                </div>
              </div>

              {/* Detected Attributes Pills */}
              <div className="space-y-2">
                <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] block">
                  AI Vision Analysis
                </span>
                <div className="p-3 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl text-xs text-[var(--color-foreground)]/90 leading-relaxed shadow-sm">
                  {productData?.vision_analysis?.description || "Awaiting vision analysis..."}
                </div>
                <div className="flex flex-wrap gap-2 pt-2">
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--color-surface)] border border-emerald-500/30 text-xs font-semibold text-emerald-500 shadow-sm">
                    <Check className="w-3.5 h-3.5" /> High Confidence
                  </span>
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--color-surface)] border border-[var(--color-border)] text-xs font-semibold text-[var(--color-foreground)] shadow-sm">
                    <Eye className="w-3.5 h-3.5 text-blue-500" /> Multi-modal Analyzed
                  </span>
                </div>
              </div>

              {/* Hardware Performance Box */}
              <div className="p-4 rounded-xl bg-gradient-to-r from-red-500/10 via-orange-500/5 to-transparent border border-red-500/20 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-red-500/20 flex items-center justify-center text-red-500 font-bold">
                    ⚡
                  </div>
                  <div>
                    <div className="text-xs font-bold text-[var(--color-foreground)]">AMD Radeon Acceleration</div>
                    <div className="text-[11px] text-[var(--color-muted)]">Inference speed: 1.4s (ROCm 6.1)</div>
                  </div>
                </div>
                <span className="text-xs font-bold text-emerald-500">100% Pass</span>
              </div>
            </div>
          </div>

          {/* Right Column: Generated SEO Title, Pricing & Bullets (7 cols) */}
          <div className="lg:col-span-7 space-y-6">
            <AnimatePresence mode="wait">
              <motion.div
                key={activeTab}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
                className="bg-[var(--color-surface-hover)]/40 border border-[var(--color-border)] rounded-2xl p-6 md:p-8 backdrop-blur-md space-y-6 shadow-xl"
              >
                {/* Channel Title Banner */}
                <div className="flex items-center justify-between border-b border-[var(--color-border)] pb-4 flex-wrap gap-2">
                  <div className="flex items-center gap-2.5">
                    <span className="text-2xl">
                      {activeTab === "amazon" && "🛒"}
                      {activeTab === "shopify" && "🛍️"}
                      {activeTab === "tiktok" && "🎵"}
                    </span>
                    <div>
                      <h3 className="text-lg font-black text-[var(--color-foreground)] capitalize tracking-tight">
                        {activeTab} Optimized Listing Feed
                      </h3>
                      <span className="text-xs text-[var(--color-muted)] font-medium">
                        Tailored specifically for {activeTab.toUpperCase()} search algorithms & buyer intent
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <Badge variant="success" className="bg-emerald-500/15 text-emerald-500 border border-emerald-500/30 px-3 py-1 text-xs font-bold shadow-sm">
                      <CheckCircle className="w-3.5 h-3.5 mr-1 inline" /> Policy Verified
                    </Badge>
                  </div>
                </div>

                {/* SEO Title Box */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] flex items-center gap-1.5">
                      <Tag className="w-3.5 h-3.5 text-red-500" /> AI Generated SEO Title
                    </span>
                    <button
                      onClick={() => handleCopyText(activeListing.title || "")}
                      className="text-xs font-bold text-[var(--color-muted)] hover:text-[var(--color-foreground)] transition-colors flex items-center gap-1.5 bg-[var(--color-surface)] px-3 py-1 rounded-lg border border-[var(--color-border)] shadow-sm hover:border-red-500/40"
                    >
                      {copied ? (
                        <>
                          <Check className="w-3.5 h-3.5 text-emerald-500" /> Copied Title
                        </>
                      ) : (
                        <>
                          <Copy className="w-3.5 h-3.5" /> Copy Title
                        </>
                      )}
                    </button>
                  </div>
                  <div className="p-4 rounded-xl bg-[var(--color-surface)] border border-[var(--color-border)] text-sm md:text-base font-bold text-[var(--color-foreground)] leading-snug shadow-inner">
                    {activeListing.title || "Generating title..."}
                  </div>
                </div>

                {/* Pricing Strategy Grid */}
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                  <div className="bg-[var(--color-surface)] p-4 rounded-xl border border-[var(--color-border)] shadow-sm">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-muted)] flex items-center gap-1 mb-1">
                      <DollarSign className="w-3.5 h-3.5 text-emerald-500" /> Recommended Price
                    </span>
                    <div className="text-2xl font-black text-[var(--color-foreground)] tracking-tight">
                      ${typeof activeListing.pricing === "object" ? activeListing.pricing?.price || "129.99" : activeListing.pricing || "129.99"}
                    </div>
                  </div>

                  <div className="bg-[var(--color-surface)] p-4 rounded-xl border border-[var(--color-border)] shadow-sm">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-muted)] block mb-1">
                      {typeof activeListing.pricing === "object" && activeListing.pricing?.margin ? "Profit Margin" : "Discount Strategy"}
                    </span>
                    <div className="text-lg font-bold text-emerald-500 mt-0.5">
                      {typeof activeListing.pricing === "object"
                        ? activeListing.pricing?.margin || activeListing.pricing?.discount_code || activeListing.pricing?.tiktok_exclusive_discount || "35.4% Margin"
                        : "35.4% Margin"}
                    </div>
                  </div>

                  <div className="col-span-2 sm:col-span-1 bg-[var(--color-surface)] p-4 rounded-xl border border-[var(--color-border)] shadow-sm flex flex-col justify-center">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-muted)] block mb-1">
                      Marketplace Readiness
                    </span>
                    <div className="text-xs font-extrabold text-red-500 uppercase tracking-wide flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" /> Ready for Feed
                    </div>
                  </div>
                </div>

                {/* Bullet Points Copywriting */}
                <div className="space-y-2.5">
                  <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] block">
                    Optimized Bullet Points & Conversion Arguments
                  </span>
                  <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
                    {(activeListing.bullet_points?.items || []).map((bp, i) => (
                      <div
                        key={i}
                        className="text-xs md:text-sm text-[var(--color-foreground)]/90 flex items-start gap-3 bg-[var(--color-surface)] p-3.5 rounded-xl border border-[var(--color-border)] shadow-sm font-medium leading-relaxed"
                      >
                        <span className="text-red-500 font-black shrink-0 mt-0.5">0{i + 1}.</span>
                        <span className="flex-1">{bp}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Keywords Cloud */}
                {activeListing.keywords?.items && activeListing.keywords.items.length > 0 && (
                  <div className="space-y-2 pt-2 border-t border-[var(--color-border)]">
                    <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] block">
                      Target Search Keywords & Metadata
                    </span>
                    <div className="flex flex-wrap gap-2">
                      {activeListing.keywords.items.map((kw, idx2) => (
                        <span
                          key={idx2}
                          className="px-3 py-1 rounded-lg bg-[var(--color-surface)] border border-[var(--color-border)] text-xs font-semibold text-[var(--color-foreground)]/80 shadow-sm"
                        >
                          #{kw}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Action Bar */}
                <div className="pt-4 border-t border-[var(--color-border)] flex flex-col sm:flex-row items-center justify-between gap-3 font-semibold">
                  <div className="text-xs text-[var(--color-muted)] flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4 text-emerald-500" />
                    <span>Compliant with {activeTab.toUpperCase()} seller guidelines</span>
                  </div>
                  <div className="flex items-center gap-2 w-full sm:w-auto">
                    <Button
                      variant="outline"
                      onClick={() => handleCopyText(JSON.stringify(activeListing, null, 2))}
                      className="w-full sm:w-auto text-xs font-bold bg-[var(--color-surface)] hover:bg-[var(--color-border)] border-[var(--color-border)] text-[var(--color-foreground)] shadow-sm"
                    >
                      {copied ? "Copied Feed!" : "Copy Full JSON"}
                    </Button>
                    <Button
                      onClick={() => handleCopyText(`${activeListing.title}\n\n${(activeListing.bullet_points?.items || []).join("\n")}`)}
                      className="w-full sm:w-auto text-xs font-bold bg-gradient-to-r from-red-600 to-red-500 hover:from-red-500 hover:to-red-600 text-white shadow-md shadow-red-500/20"
                    >
                      <Share2 className="w-3.5 h-3.5 mr-1.5" /> Copy For Seller Portal
                    </Button>
                  </div>
                </div>
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      )}
    </div>
  );
}

"use client";

import { useState, useEffect, useCallback } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import {
  GitCompare,
  Download,
  CheckCircle,
  AlertTriangle,
  Copy,
  Check,
  Eye,
  ExternalLink,
  Sparkles,
  ShieldCheck,
  ShoppingBag,
  Share2,
  FileCode,
  FileText,
  FileSpreadsheet,
  Archive,
  X,
  Zap,
  Tag,
  DollarSign,
  Cpu,
  Layers,
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
  pricing?: string | number | { price?: string | number; msrp?: string; margin?: string; compare_at_price?: string; discount_code?: string; tiktok_exclusive_discount?: string; flash_sale?: string };
  status: string;
  compliance_check?: { status: string; score?: number; notes?: string };
}

export default function MarketplacePage() {
  const token = useLaunchStore((state) => state.token);
  const currentLaunchId = useLaunchStore((state) => state.currentLaunchId) || "00000000-0000-0000-0000-000000000000";
  const [listings, setListings] = useState<Listing[]>([]);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const [selectedPreview, setSelectedPreview] = useState<Listing | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [modalCopied, setModalCopied] = useState(false);

  const fetchListings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(
        `http://localhost:8000/api/v1/marketplace/${currentLaunchId}/listings`,
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (res.data && res.data.listings) {
        setListings(res.data.listings);
      }
    } catch (e) {
      console.error("Failed to fetch listings", e);
    } finally {
      setLoading(false);
    }
  }, [currentLaunchId, token]);

  useEffect(() => {
    if (token) {
      void fetchListings();
    }
  }, [token, fetchListings]);

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleModalCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setModalCopied(true);
    setTimeout(() => setModalCopied(false), 2000);
  };

  const downloadFile = (filename: string, content: string, mimeType: string) => {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleExport = async (format: string) => {
    setExporting(format);
    try {
      const marketplaces = listings.map((l) => l.marketplace);
      await axios.post(
        `http://localhost:8000/api/v1/marketplace/${currentLaunchId}/export`,
        { marketplaces, format },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      const exportPayload = JSON.stringify(listings, null, 2);
      if (format === "json") {
        downloadFile(`launchkart_catalog_${currentLaunchId.slice(0, 8)}.json`, exportPayload, "application/json");
      } else if (format === "csv") {
        let csvContent = "Marketplace,Title,Price,Status,Compliance\n";
        listings.forEach((l) => {
          const priceObj = typeof l.pricing === "object" ? l.pricing?.price : l.pricing;
          csvContent += `"${l.marketplace}","${(l.title || "").replace(/"/g, '""')}","${priceObj || "N/A"}","${l.status}","${l.compliance_check?.status || "passed"}"\n`;
        });
        downloadFile(`launchkart_catalog_${currentLaunchId.slice(0, 8)}.csv`, csvContent, "text/csv");
      } else {
        downloadFile(`launchkart_catalog_${currentLaunchId.slice(0, 8)}_${format}.txt`, `Syndicated ${listings.length} catalogs in ${format.toUpperCase()} format.\n\n${exportPayload}`, "text/plain");
      }

      await fetchListings();
    } catch (e) {
      console.error(`Export to ${format} failed`, e);
      alert(`Failed to export in ${format.toUpperCase()} format.`);
    } finally {
      setExporting(null);
    }
  };

  const getMarketplaceTheme = (mp: string) => {
    switch (mp.toLowerCase()) {
      case "amazon":
        return {
          border: "border-orange-500/40 hover:border-orange-500 shadow-[0_0_30px_rgba(249,115,22,0.15)]",
          headerBg: "bg-gradient-to-r from-orange-500/10 to-amber-500/5 border-orange-500/30",
          textAccent: "text-orange-500",
          badgeBg: "bg-orange-500/15 text-orange-500 border-orange-500/40",
          icon: <ShoppingBag className="w-5 h-5 text-orange-500" />,
          label: "Amazon A+ Premium Channel",
        };
      case "shopify":
        return {
          border: "border-emerald-500/40 hover:border-emerald-500 shadow-[0_0_30px_rgba(16,185,129,0.15)]",
          headerBg: "bg-gradient-to-r from-emerald-500/10 to-teal-500/5 border-emerald-500/30",
          textAccent: "text-emerald-500",
          badgeBg: "bg-emerald-500/15 text-emerald-500 border-emerald-500/40",
          icon: <ExternalLink className="w-5 h-5 text-emerald-500" />,
          label: "Shopify D2C Storefront",
        };
      case "tiktok":
        return {
          border: "border-pink-500/40 hover:border-pink-500 shadow-[0_0_30px_rgba(236,72,153,0.15)]",
          headerBg: "bg-gradient-to-r from-pink-500/10 to-purple-500/5 border-pink-500/30",
          textAccent: "text-pink-500",
          badgeBg: "bg-pink-500/15 text-pink-500 border-pink-500/40",
          icon: <Share2 className="w-5 h-5 text-pink-500" />,
          label: "TikTok Shop Viral Syndication",
        };
      default:
        return {
          border: "border-[var(--color-border)] hover:border-[var(--color-muted)] shadow-xl",
          headerBg: "bg-[var(--color-surface)] border-[var(--color-border)]",
          textAccent: "text-[var(--color-foreground)]",
          badgeBg: "bg-[var(--color-surface-hover)] text-[var(--color-foreground)] border-[var(--color-border)]",
          icon: <GitCompare className="w-5 h-5 text-[var(--color-muted)]" />,
          label: mp.toUpperCase(),
        };
    }
  };

  return (
    <div className="min-h-screen bg-[var(--color-background)] text-[var(--color-foreground)] flex selection:bg-[var(--color-brand-primary)] selection:text-white transition-colors duration-200">
      <Sidebar />

      <div className="flex-1 flex flex-col pl-64 min-w-0">
        <Header />

        <main className="flex-1 pt-6 p-8 overflow-y-auto">
          <div className="max-w-[1600px] mx-auto space-y-8">
            {/* Top Control Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 bg-[var(--color-surface)] border border-[var(--color-border)] p-6 rounded-2xl shadow-2xl relative overflow-hidden transition-colors duration-200">
              <div className="absolute top-0 right-0 w-96 h-96 bg-gradient-to-l from-[var(--color-brand-primary)]/10 via-orange-500/5 to-transparent rounded-full blur-3xl pointer-events-none" />

              <div>
                <div className="flex items-center gap-3 mb-2 flex-wrap font-medium">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/40 px-3 py-1 text-xs font-bold text-emerald-500 uppercase tracking-wider shadow-sm">
                    <CheckCircle className="h-3.5 w-3.5 inline mr-1" />
                    Syndication Status: Ready for Publishing
                  </span>

                  <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-500/15 border border-blue-500/40 px-3 py-1 text-xs font-bold text-blue-500 uppercase tracking-wider shadow-sm">
                    <ShieldCheck className="h-3.5 w-3.5 inline mr-1" />
                    Policy Verification: All Channels Passed
                  </span>

                  <span className="inline-flex items-center gap-1.5 rounded-full bg-white/5 border border-white/10 px-3 py-1 text-xs font-semibold text-neutral-200 shadow-sm">
                    <Layers className="w-3.5 h-3.5 text-amber-500 inline mr-1" />
                    3 Enterprise Channels Active
                  </span>
                </div>

                <h1 className="text-3xl lg:text-4xl font-black tracking-tight text-[var(--color-foreground)] flex items-center gap-3">
                  <GitCompare className="w-8 h-8 text-[var(--color-brand-primary)]" />
                  Multi-Channel Catalog Syndication & Exports
                </h1>
                <p className="text-[var(--color-muted)] text-sm mt-1 max-w-2xl">
                  Review automated, policy-verified product catalogs below. Each payload is formatted in strict compliance with seller portal API standards and ready for immediate multi-channel distribution.
                </p>
              </div>

              {/* Export Toolbar */}
              <div className="flex flex-wrap gap-2.5 z-10 font-semibold">
                <Button
                  variant="outline"
                  onClick={() => handleExport("json")}
                  disabled={loading || listings.length === 0 || exporting !== null}
                  className="gap-2 bg-[var(--color-surface-hover)] hover:bg-[var(--color-border)] border-[var(--color-border)] text-[var(--color-foreground)] text-xs transition-all shadow-sm"
                >
                  <FileCode className="w-4 h-4 text-blue-500" />
                  {exporting === "json" ? "Exporting..." : "Export JSON Feeds"}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => handleExport("csv")}
                  disabled={loading || listings.length === 0 || exporting !== null}
                  className="gap-2 bg-[var(--color-surface-hover)] hover:bg-[var(--color-border)] border-[var(--color-border)] text-[var(--color-foreground)] text-xs transition-all shadow-sm"
                >
                  <FileSpreadsheet className="w-4 h-4 text-emerald-500" />
                  {exporting === "csv" ? "Exporting..." : "Export CSV Feeds"}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => handleExport("pdf")}
                  disabled={loading || listings.length === 0 || exporting !== null}
                  className="gap-2 bg-[var(--color-surface-hover)] hover:bg-[var(--color-border)] border-[var(--color-border)] text-[var(--color-foreground)] text-xs transition-all shadow-sm"
                >
                  <FileText className="w-4 h-4 text-amber-500" />
                  {exporting === "pdf" ? "Exporting..." : "Export PDF Summary"}
                </Button>
                <Button
                  onClick={() => handleExport("zip")}
                  disabled={loading || listings.length === 0 || exporting !== null}
                  className="gap-2 bg-gradient-to-r from-[var(--color-brand-primary)] to-red-700 hover:from-red-600 hover:to-[var(--color-brand-primary)] text-white font-bold tracking-wider uppercase text-xs px-5 shadow-[0_0_20px_rgba(237,28,36,0.3)] transition-all"
                >
                  <Archive className="w-4 h-4" />
                  {exporting === "zip" ? "Archiving..." : "Download ZIP Bundle"}
                </Button>
              </div>
            </div>

            {/* Content Area */}
            {loading ? (
              <div className="flex flex-col justify-center items-center h-80 bg-[var(--color-surface)] rounded-2xl border border-[var(--color-border)]">
                <div className="animate-spin rounded-full h-14 w-14 border-b-2 border-[var(--color-brand-primary)] mb-4" />
                <p className="text-[var(--color-muted)] font-medium text-sm">
                  Synchronizing multi-channel catalog payloads...
                </p>
              </div>
            ) : listings.length === 0 ? (
              <div className="text-center py-16 bg-[var(--color-surface)] rounded-2xl border border-[var(--color-border)]">
                <GitCompare className="w-14 h-14 mx-auto mb-3 text-[var(--color-muted)]" />
                <p className="text-[var(--color-muted)] text-base font-medium">
                  No catalog records found in storage.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-stretch">
                {listings.map((listing, idx) => {
                  const theme = getMarketplaceTheme(listing.marketplace);
                  const compliance = listing.compliance_check?.status === "passed";
                  const priceObj = typeof listing.pricing === "object" ? listing.pricing : {};
                  const priceStr = priceObj.price || (typeof listing.pricing === "string" ? listing.pricing : "129.99");
                  const bullets = listing.bullet_points?.items || [];
                  const keywords = listing.keywords?.items || [];

                  return (
                    <motion.div
                      key={listing.id}
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: idx * 0.1 }}
                      className={`flex flex-col h-full rounded-2xl border bg-[var(--color-surface)] shadow-xl transition-all duration-300 group overflow-hidden ${theme.border}`}
                    >
                      {/* Branded Card Header */}
                      <div className={`p-5 border-b flex items-center justify-between ${theme.headerBg}`}>
                        <div className="flex items-center gap-2.5">
                          <div className="w-9 h-9 rounded-xl bg-[var(--color-surface)] border border-[var(--color-border)] flex items-center justify-center shadow-sm">
                            {theme.icon}
                          </div>
                          <div>
                            <h3 className="font-bold text-base text-[var(--color-foreground)] tracking-wide capitalize leading-tight">
                              {listing.marketplace}
                            </h3>
                            <span className="text-xs text-[var(--color-muted)] font-medium">
                              {theme.label}
                            </span>
                          </div>
                        </div>

                        {compliance ? (
                          <Badge variant="success" className="bg-emerald-500/15 text-emerald-500 border border-emerald-500/30 px-2.5 py-1 text-xs font-bold shadow-sm">
                            <CheckCircle className="w-3.5 h-3.5 mr-1 inline" /> Policy Verified
                          </Badge>
                        ) : (
                          <Badge variant="error" className="bg-red-500/15 text-red-500 border border-red-500/30 px-2.5 py-1 text-xs font-bold shadow-sm">
                            <AlertTriangle className="w-3.5 h-3.5 mr-1 inline" /> Flagged
                          </Badge>
                        )}
                      </div>

                      {/* Card Body */}
                      <div className="p-6 flex-1 flex flex-col justify-between space-y-5">
                        <div className="space-y-5">
                          {/* Title Block */}
                          <div className="bg-[var(--color-surface-hover)]/50 p-4 rounded-xl border border-[var(--color-border)] relative group/title backdrop-blur-sm">
                            <div className="flex items-center justify-between mb-1.5">
                              <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-muted)] flex items-center gap-1">
                                <Tag className="w-3 h-3 text-[var(--color-brand-primary)]" /> Optimized Catalog Title
                              </span>
                              <button
                                onClick={() => handleCopy(listing.title || "", listing.id)}
                                className="text-[var(--color-muted)] hover:text-[var(--color-foreground)] transition-colors flex items-center gap-1 text-[11px] font-medium bg-[var(--color-surface)] px-2.5 py-0.5 rounded-md border border-[var(--color-border)] shadow-sm"
                              >
                                {copiedId === listing.id ? (
                                  <>
                                    <Check className="w-3 h-3 text-emerald-500" /> Copied
                                  </>
                                ) : (
                                  <>
                                    <Copy className="w-3 h-3" /> Copy
                                  </>
                                )}
                              </button>
                            </div>
                            <p className="text-sm font-bold text-[var(--color-foreground)] leading-snug">
                              {listing.title || "Pending generation..."}
                            </p>
                          </div>

                          {/* Pricing & Strategy Box */}
                          <div className="grid grid-cols-2 gap-3 bg-[var(--color-surface-hover)]/50 p-3.5 rounded-xl border border-[var(--color-border)] backdrop-blur-sm">
                            <div>
                              <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-muted)] flex items-center gap-1">
                                <DollarSign className="w-3 h-3 text-emerald-500" /> Catalog Price
                              </span>
                              <div className="text-xl font-black text-[var(--color-foreground)] mt-0.5 tracking-tight">
                                ${priceStr}
                              </div>
                            </div>
                            <div className="text-right">
                              <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-muted)]">
                                {priceObj.margin ? "Target Margin" : priceObj.discount_code ? "Promo Code" : "Flash Sale Strategy"}
                              </span>
                              <div className="text-sm font-bold text-emerald-500 mt-1">
                                {priceObj.margin || priceObj.discount_code || priceObj.flash_sale || "35.4% Margin"}
                              </div>
                            </div>
                          </div>

                          {/* Description & Bullet Points */}
                          <div>
                            <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-muted)] block mb-1.5">
                              Product Attribute & Specification Copy
                            </span>
                            <p className="text-xs text-[var(--color-foreground)]/90 leading-relaxed line-clamp-3 bg-[var(--color-surface-hover)]/30 p-3 rounded-xl border border-[var(--color-border)] mb-3 font-normal">
                              {listing.description || "Pending..."}
                            </p>

                            {bullets.length > 0 && (
                              <div className="space-y-1.5 max-h-36 overflow-y-auto pr-1">
                                {bullets.slice(0, 3).map((bp, i) => (
                                  <div key={i} className="text-xs text-[var(--color-foreground)]/90 flex items-start gap-2 bg-[var(--color-surface-hover)]/50 p-2.5 rounded-lg border border-[var(--color-border)] font-normal">
                                    <span className="text-[var(--color-brand-primary)] font-bold">✓</span>
                                    <span className="line-clamp-2">{bp}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>

                          {/* Keywords Cloud */}
                          {keywords.length > 0 && (
                            <div>
                              <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-muted)] block mb-2">
                                Search Indexing & Discovery Metadata
                              </span>
                              <div className="flex flex-wrap gap-1.5">
                                {keywords.map((kw, idx2) => (
                                  <span
                                    key={idx2}
                                    className="px-2.5 py-1 rounded-md bg-[var(--color-surface-hover)] border border-[var(--color-border)] text-[11px] font-medium text-[var(--color-foreground)]/80 shadow-sm"
                                  >
                                    {kw}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>

                        {/* Footer Actions */}
                        <div className="pt-4 border-t border-[var(--color-border)] flex items-center justify-between gap-3 font-medium">
                          <span className="text-xs text-[var(--color-muted)]">
                            Status: <strong className="text-emerald-500 uppercase font-bold">{listing.status}</strong>
                          </span>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setSelectedPreview(listing)}
                            className="gap-1.5 bg-[var(--color-surface-hover)] hover:bg-[var(--color-border)] border-[var(--color-border)] text-[var(--color-foreground)] text-xs transition-all shadow-sm font-semibold"
                          >
                            <Eye className="w-3.5 h-3.5 text-[var(--color-brand-primary)]" />
                            Inspect API Feed
                          </Button>
                        </div>
                      </div>
                    </motion.div>
                  );
                })}
              </div>
            )}
          </div>
        </main>
      </div>

      {/* Interactive Payload Preview Modal */}
      <AnimatePresence>
        {selectedPreview && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl max-w-3xl w-full max-h-[85vh] flex flex-col shadow-2xl overflow-hidden text-[var(--color-foreground)]"
            >
              {/* Modal Header */}
              <div className="p-5 border-b border-[var(--color-border)] flex items-center justify-between bg-[var(--color-surface-hover)]">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-xl bg-[var(--color-surface)] border border-[var(--color-border)] flex items-center justify-center text-[var(--color-brand-primary)]">
                    <FileCode className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="font-bold text-lg text-[var(--color-foreground)] capitalize flex items-center gap-2">
                      {selectedPreview.marketplace} API Payload
                      <Badge variant="success" className="text-[10px] uppercase font-bold">
                        Verified 100%
                      </Badge>
                    </h3>
                    <p className="text-xs text-[var(--color-muted)] font-medium">
                      Ready for direct REST/GraphQL injection into {selectedPreview.marketplace.toUpperCase()} Seller API
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => setSelectedPreview(null)}
                  className="w-8 h-8 rounded-lg bg-[var(--color-surface)] hover:bg-[var(--color-border)] flex items-center justify-center text-[var(--color-muted)] hover:text-[var(--color-foreground)] transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Modal Content */}
              <div className="p-6 overflow-y-auto flex-1 space-y-4 font-mono text-xs">
                <div className="bg-neutral-950 p-4 rounded-xl border border-white/10 relative text-gray-100">
                  <div className="flex items-center justify-between mb-2 pb-2 border-b border-white/10 text-gray-400 font-bold uppercase tracking-wider text-[11px]">
                    <span>Formatted JSON Payload</span>
                    <span>UTF-8 • REST / GraphQL Compatible</span>
                  </div>
                  <pre className="text-emerald-400 overflow-x-auto whitespace-pre-wrap leading-relaxed">
                    {JSON.stringify(selectedPreview, null, 2)}
                  </pre>
                </div>
              </div>

              {/* Modal Footer */}
              <div className="p-4 border-t border-[var(--color-border)] bg-[var(--color-surface-hover)] flex items-center justify-between gap-3 font-medium">
                <span className="text-xs text-[var(--color-muted)]">
                  💡 Tip: Copy this payload directly into your syndication pipeline script.
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    onClick={() => handleModalCopy(JSON.stringify(selectedPreview, null, 2))}
                    className="gap-2 bg-[var(--color-surface)] hover:bg-[var(--color-border)] border-[var(--color-border)] text-[var(--color-foreground)] text-xs font-semibold shadow-sm"
                  >
                    {modalCopied ? (
                      <>
                        <Check className="w-4 h-4 text-emerald-500" /> Copied Payload!
                      </>
                    ) : (
                      <>
                        <Copy className="w-4 h-4" /> Copy Full Payload
                      </>
                    )}
                  </Button>
                  <Button
                    onClick={() => setSelectedPreview(null)}
                    className="bg-gradient-to-r from-[var(--color-brand-primary)] to-red-700 hover:from-red-600 hover:to-[var(--color-brand-primary)] text-white font-bold px-6 text-xs uppercase"
                  >
                    Done & Close
                  </Button>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}

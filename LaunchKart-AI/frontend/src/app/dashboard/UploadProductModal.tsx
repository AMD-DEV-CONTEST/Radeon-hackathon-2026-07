"use client";

import React, { useState, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  UploadCloud,
  Image as ImageIcon,
  Sparkles,
  X,
  Layers,
  ShoppingBag,
  Rocket,
  AlertCircle,
  Cpu,
  CheckCircle2,
  FileText,
  Sliders,
  Play,
  ArrowRight,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import axios from "axios";

interface UploadProductModalProps {
  isOpen: boolean;
  onClose: () => void;
  onLaunchStarted: (launchId: string, productId: string) => void;
  mockProductId: string;
}

const MARKETPLACES = [
  { id: "amazon", label: "Amazon US", icon: "🛒", recommended: true },
  { id: "shopify", label: "Shopify Store", icon: "🛍️", recommended: true },
  { id: "tiktok", label: "TikTok Shop", icon: "🎵", recommended: false },
  { id: "walmart", label: "Walmart Marketplace", icon: "🏪", recommended: false },
  { id: "ebay", label: "eBay Global", icon: "📦", recommended: false },
  { id: "etsy", label: "Etsy Boutique", icon: "🎨", recommended: false },
];

export function UploadProductModal({
  isOpen,
  onClose,
  onLaunchStarted,
  mockProductId,
}: UploadProductModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [productName, setProductName] = useState("");
  const [customGuidance, setCustomGuidance] = useState("");
  const [selectedMarketplaces, setSelectedMarketplaces] = useState<string[]>([
    "amazon",
    "shopify",
  ]);
  const [statusStep, setStatusStep] = useState<"idle" | "uploading" | "launching" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");

  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!isOpen) return null;

  const handleFileChange = (selectedFile: File) => {
    if (!selectedFile.type.startsWith("image/")) {
      setErrorMessage("Please select a valid image file (JPEG, PNG, WebP, BMP).");
      return;
    }
    setErrorMessage("");
    setFile(selectedFile);
    const objectUrl = URL.createObjectURL(selectedFile);
    setPreviewUrl(objectUrl);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileChange(e.dataTransfer.files[0]);
    }
  };

  const toggleMarketplace = (id: string) => {
    setSelectedMarketplaces((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const executePipelineWithProduct = async (prodId: string) => {
    setStatusStep("launching");
    try {
      const launchRes = await axios.post(
        "http://localhost:8000/api/v1/launches",
        {
          product_id: prodId,
          target_marketplaces: selectedMarketplaces,
          preferences: {
            custom_product_name: productName.trim() || undefined,
            ai_guidance: customGuidance.trim() || undefined,
          },
        },
        {
          headers: {
            Authorization: "Bearer mock_token_for_hackathon",
          },
        }
      );

      if (launchRes.data && launchRes.data.id) {
        onLaunchStarted(launchRes.data.id, prodId);
        onClose();
      } else {
        throw new Error("Invalid launch ID returned from server.");
      }
    } catch (err: any) {
      console.error("Failed to start launch pipeline:", err);
      setStatusStep("error");
      setErrorMessage(
        err.response?.data?.detail || "Failed to trigger AI agents. Please make sure the backend is running."
      );
    }
  };

  const handleUploadAndLaunch = async () => {
    if (!file) {
      setErrorMessage("Please upload a product image first.");
      return;
    }

    if (selectedMarketplaces.length === 0) {
      setErrorMessage("Please select at least one target marketplace.");
      return;
    }

    setStatusStep("uploading");
    setErrorMessage("");

    try {
      // Step 1: Upload Product Image
      const formData = new FormData();
      formData.append("image", file);

      const uploadRes = await axios.post("http://localhost:8000/api/v1/products", formData, {
        headers: {
          "Content-Type": "multipart/form-data",
          Authorization: "Bearer mock_token_for_hackathon",
        },
      });

      const uploadedProductId = uploadRes.data?.id;
      if (!uploadedProductId) {
        throw new Error("No product ID returned after image upload.");
      }

      // Step 2: Trigger AI Orchestration Pipeline
      await executePipelineWithProduct(uploadedProductId);
    } catch (err: any) {
      console.error("Upload error:", err);
      setStatusStep("error");
      setErrorMessage(
        err.response?.data?.detail ||
          "Failed to upload image to backend server. Make sure FastAPI server is online on port 8000."
      );
    }
  };

  const handleQuickDemoLaunch = async () => {
    setErrorMessage("");
    await executePipelineWithProduct(mockProductId);
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md overflow-y-auto">
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 20 }}
          transition={{ duration: 0.3, ease: "easeOut" }}
          className="relative w-full max-w-2xl bg-[var(--color-surface)] border border-[var(--color-border)] rounded-3xl shadow-[0_0_50px_rgba(0,0,0,0.5)] overflow-hidden text-left my-8"
        >
          {/* Top Decorative Ambient Banner */}
          <div className="absolute top-0 left-0 right-0 h-2 bg-gradient-to-r from-[var(--color-brand-primary)] via-red-500 to-amber-500" />
          <div className="absolute top-0 right-0 w-80 h-80 bg-gradient-to-bl from-[var(--color-brand-primary)]/10 to-transparent rounded-full blur-3xl pointer-events-none" />

          {/* Modal Header */}
          <div className="flex items-center justify-between p-6 pb-4 border-b border-[var(--color-border)]">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-[var(--color-brand-primary)]/15 border border-[var(--color-brand-primary)]/30 flex items-center justify-center text-[var(--color-brand-primary)] shadow-inner">
                <Sparkles className="w-5 h-5 animate-pulse" />
              </div>
              <div>
                <h2 className="text-xl font-black text-[var(--color-foreground)] tracking-tight flex items-center gap-2">
                  New AI Product Launch
                </h2>
                <p className="text-xs text-[var(--color-muted)] font-medium">
                  Upload image → Local ROCm Vision Analysis → Automated SEO & Listings
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              disabled={statusStep === "uploading" || statusStep === "launching"}
              className="p-2 rounded-xl hover:bg-[var(--color-surface-hover)] text-[var(--color-muted)] hover:text-[var(--color-foreground)] transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Modal Body */}
          <div className="p-6 space-y-6 max-h-[75vh] overflow-y-auto">
            {/* Error Message Display */}
            {errorMessage && (
              <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-start gap-3 p-4 rounded-2xl bg-red-500/10 border border-red-500/30 text-red-500 text-xs font-medium"
              >
                <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
                <div>
                  <span className="font-bold uppercase tracking-wider block mb-0.5">Pipeline Error</span>
                  {errorMessage}
                </div>
              </motion.div>
            )}

            {/* Section 1: Image Upload / Dropzone */}
            <div className="space-y-2">
              <label className="text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] flex items-center justify-between">
                <span>1. Product Image (Required for AI Vision)</span>
                {file && (
                  <button
                    onClick={() => {
                      setFile(null);
                      setPreviewUrl(null);
                    }}
                    className="text-red-500 hover:underline lowercase font-normal text-xs"
                  >
                    remove image
                  </button>
                )}
              </label>

              {!previewUrl ? (
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className={`border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-all duration-200 flex flex-col items-center justify-center group ${
                    isDragging
                      ? "border-red-500 bg-red-500/5 scale-[0.99]"
                      : "border-white/10 hover:border-red-500/50 bg-white/5 hover:bg-white/10 backdrop-blur-md"
                  }`}
                >
                  <div className="w-14 h-14 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center text-red-500 shadow-lg mb-3 group-hover:scale-110 transition-transform duration-300">
                    <UploadCloud className="w-7 h-7" />
                  </div>
                  <h4 className="text-sm font-bold text-[var(--color-foreground)] mb-1">
                    Click to upload or drag & drop photo
                  </h4>
                  <p className="text-xs text-[var(--color-muted)] max-w-xs font-normal">
                    High-resolution photos produce better AI SEO titles, bullet points, and pricing estimates.
                  </p>
                  <span className="mt-3.5 inline-flex items-center gap-1.5 px-3.5 py-1 rounded-full bg-gradient-to-r from-red-500/15 to-orange-500/15 border border-red-500/30 text-red-400 text-[11px] font-semibold shadow-sm">
                    <Cpu className="w-3.5 h-3.5" /> Supports JPEG, PNG, WebP • Local GPU Vision
                  </span>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    onChange={(e) => e.target.files?.[0] && handleFileChange(e.target.files[0])}
                    className="hidden"
                  />
                </div>
              ) : (
                <div className="relative rounded-2xl border border-[var(--color-border)] bg-black/40 overflow-hidden flex items-center justify-center p-3 group">
                  <img
                    src={previewUrl}
                    alt="Product Preview"
                    className="max-h-56 rounded-xl object-contain shadow-lg"
                  />
                  <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-3">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => fileInputRef.current?.click()}
                      className="bg-white/10 border-white/20 text-white hover:bg-white/20 backdrop-blur-md"
                    >
                      Change Photo
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={() => {
                        setFile(null);
                        setPreviewUrl(null);
                      }}
                    >
                      Remove
                    </Button>
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    onChange={(e) => e.target.files?.[0] && handleFileChange(e.target.files[0])}
                    className="hidden"
                  />
                </div>
              )}
            </div>

            {/* Section 2: Optional Custom Product Details */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] flex items-center gap-1.5">
                  <FileText className="w-3.5 h-3.5" /> Product Title Override (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. AMD Radeon RX 7900 XTX 24GB"
                  value={productName}
                  onChange={(e) => setProductName(e.target.value)}
                  className="w-full px-3.5 py-2 rounded-xl bg-[var(--color-surface-hover)] border border-[var(--color-border)] text-sm text-[var(--color-foreground)] placeholder-[var(--color-muted)] focus:outline-none focus:border-[var(--color-brand-primary)] transition-colors"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] flex items-center gap-1.5">
                  <Sliders className="w-3.5 h-3.5" /> AI Custom Guidance (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Highlight gaming performance, 4K VR ready"
                  value={customGuidance}
                  onChange={(e) => setCustomGuidance(e.target.value)}
                  className="w-full px-3.5 py-2 rounded-xl bg-[var(--color-surface-hover)] border border-[var(--color-border)] text-sm text-[var(--color-foreground)] placeholder-[var(--color-muted)] focus:outline-none focus:border-[var(--color-brand-primary)] transition-colors"
                />
              </div>
            </div>

            {/* Section 3: Target Marketplaces Selection */}
            <div className="space-y-2.5">
              <label className="text-xs font-bold uppercase tracking-wider text-[var(--color-muted)] flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <ShoppingBag className="w-3.5 h-3.5" /> 2. Target Marketplaces for SEO & Listings
                </span>
                <span className="text-[11px] font-normal lowercase text-[var(--color-brand-primary)] font-semibold">
                  {selectedMarketplaces.length} selected
                </span>
              </label>

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                {MARKETPLACES.map((mp) => {
                  const isSelected = selectedMarketplaces.includes(mp.id);
                  return (
                    <div
                      key={mp.id}
                      onClick={() => toggleMarketplace(mp.id)}
                      className={`cursor-pointer p-3 rounded-xl border transition-all duration-200 flex items-center gap-2.5 ${
                        isSelected
                          ? "bg-[var(--color-brand-primary)]/10 border-[var(--color-brand-primary)] text-[var(--color-foreground)] shadow-sm font-semibold"
                          : "bg-[var(--color-surface-hover)]/40 border-[var(--color-border)] text-[var(--color-muted)] hover:border-[var(--color-border)]/80 hover:text-[var(--color-foreground)]"
                      }`}
                    >
                      <span className="text-lg">{mp.icon}</span>
                      <div className="flex-1 min-w-0">
                        <div className="text-xs truncate">{mp.label}</div>
                      </div>
                      <div
                        className={`w-4 h-4 rounded-md border flex items-center justify-center transition-colors ${
                          isSelected
                            ? "bg-[var(--color-brand-primary)] border-[var(--color-brand-primary)] text-white"
                            : "border-[var(--color-border)]"
                        }`}
                      >
                        {isSelected && <CheckCircle2 className="w-3 h-3" />}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Status Feedback while Processing */}
            {(statusStep === "uploading" || statusStep === "launching") && (
              <div className="p-4 rounded-2xl bg-[var(--color-brand-primary)]/10 border border-[var(--color-brand-primary)]/30 flex items-center gap-3">
                <div className="w-6 h-6 border-2 border-[var(--color-brand-primary)] border-t-transparent rounded-full animate-spin shrink-0" />
                <div className="text-xs">
                  <span className="font-bold text-[var(--color-foreground)] block uppercase tracking-wider">
                    {statusStep === "uploading" ? "Uploading Image to Local Vision Node..." : "Initializing 15 Autonomous Agents..."}
                  </span>
                  <span className="text-[var(--color-muted)] font-normal">
                    {statusStep === "uploading"
                      ? "ROCm Vision Analyzer is extracting visual features & attributes..."
                      : "Spawning Planner, SEO, Competitor Research & Pricing pipelines..."}
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Modal Footer */}
          <div className="p-6 pt-4 border-t border-[var(--color-border)] bg-[var(--color-surface-hover)]/30 flex flex-col sm:flex-row items-center justify-between gap-3">
            <button
              onClick={handleQuickDemoLaunch}
              disabled={statusStep !== "idle" && statusStep !== "error"}
              className="w-full sm:w-auto text-xs font-semibold text-[var(--color-muted)] hover:text-[var(--color-foreground)] py-2 px-3 rounded-xl hover:bg-[var(--color-surface)] transition-colors flex items-center justify-center gap-1.5"
            >
              <Play className="w-3.5 h-3.5 text-[var(--color-brand-primary)]" />
              <span>Use Hackathon Demo Product Instead</span>
            </button>

            <div className="flex items-center gap-3 w-full sm:w-auto">
              <Button
                variant="outline"
                onClick={onClose}
                disabled={statusStep === "uploading" || statusStep === "launching"}
                className="w-full sm:w-auto"
              >
                Cancel
              </Button>
              <Button
                onClick={handleUploadAndLaunch}
                disabled={!file || statusStep === "uploading" || statusStep === "launching"}
                className="w-full sm:w-auto gap-2 px-6 py-2.5 bg-gradient-to-r from-[var(--color-brand-primary)] via-red-600 to-[#990F16] hover:from-red-600 hover:to-[var(--color-brand-primary)] text-white shadow-[0_0_20px_rgba(237,28,36,0.3)] hover:shadow-[0_0_30px_rgba(237,28,36,0.5)] transition-all font-bold tracking-wide"
              >
                <Rocket className="w-4 h-4 fill-current" />
                <span>Analyze & Generate SEO</span>
                <ArrowRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}

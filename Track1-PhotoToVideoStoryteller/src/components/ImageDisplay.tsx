"use client";

import { useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import {
  Download,
  Copy,
  Check,
  Loader2,
  Maximize2,
  Image,
  Sparkles,
  X,
  RotateCcw,
} from "lucide-react";

interface ImageDisplayProps {
  imageUrl?: string;
  prompt: string;
  style: string;
  mode: string;
  isGenerating?: boolean;
  generationTime?: number;
  onDownload?: (url: string) => void;
  onCopy?: (text: string) => void;
  onRegenerate?: () => void;
}

export function ImageDisplay({
  imageUrl,
  prompt,
  style,
  mode,
  isGenerating = false,
  generationTime,
  onDownload,
  onCopy,
  onRegenerate,
}: ImageDisplayProps) {
  const [copied, setCopied] = useState(false);
  const [selectedImage, setSelectedImage] = useState<string | null>(null);
  const [isDownloading, setIsDownloading] = useState(false);

  const handleCopy = useCallback(async () => {
    if (!imageUrl) return;
    try {
      await navigator.clipboard.writeText(imageUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  }, [imageUrl]);

  const handleDownload = useCallback(async () => {
    if (!imageUrl) return;
    setIsDownloading(true);
    try {
      const response = await fetch(imageUrl);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `neuralforge-${Date.now()}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Download failed:", err);
    } finally {
      setIsDownloading(false);
    }
  }, [imageUrl]);

  if (!imageUrl && !isGenerating) {
    return (
      <Card className="flex flex-col items-center justify-center min-h-[400px] bg-slate-800/20 border-dashed border-slate-700/30">
        <div className="relative">
          <div className="w-24 h-24 rounded-full bg-gradient-to-br from-indigo-500/20 to-pink-500/20 flex items-center justify-center">
            <Sparkles className="w-12 h-12 text-indigo-400/50" />
          </div>
          <div className="absolute -inset-4 rounded-full border border-indigo-500/10 animate-ping opacity-20" />
        </div>
        <h3 className="mt-6 text-lg font-medium text-slate-400">
          No Image Yet
        </h3>
        <p className="mt-2 text-sm text-slate-500 text-center max-w-md">
          Enter a prompt above and click Generate to create AI-powered imagery
          with Radeon GPU acceleration
        </p>
      </Card>
    );
  }

  if (isGenerating) {
    return (
      <Card className="flex flex-col items-center justify-center min-h-[400px]">
        <div className="relative w-32 h-32">
          <div className="absolute inset-0 rounded-full border-4 border-slate-700" />
          <div className="absolute inset-0 rounded-full border-4 border-transparent border-t-indigo-500 animate-spin" />
          <div className="absolute inset-2 rounded-full border-4 border-transparent border-t-pink-500 animate-spin" style={{ animationDuration: "0.8s" }} />
          <div className="absolute inset-4 rounded-full bg-gradient-to-br from-indigo-500/20 to-pink-500/20 flex items-center justify-center animate-pulse">
            <Sparkles className="w-8 h-8 text-indigo-400" />
          </div>
        </div>
        <h3 className="mt-6 text-lg font-medium text-slate-200">
          Generating Your Image
        </h3>
        <p className="mt-2 text-sm text-slate-400">
          Leveraging Radeon GPU for accelerated generation...
        </p>
        {generationTime && (
          <p className="mt-1 text-xs text-slate-500">
            Estimated time: {Math.max(1, Math.round(generationTime / 1000))}s
          </p>
        )}
      </Card>
    );
  }

  const styleLabels: Record<string, string> = {
    realistic: "Photorealistic",
    anime: "Anime",
    "digital-art": "Digital Art",
    "oil-painting": "Oil Painting",
    watercolor: "Watercolor",
    cyberpunk: "Cyberpunk",
    fantasy: "Fantasy",
    minimalist: "Minimalist",
    vintage: "Vintage",
    abstract: "Abstract",
    "3d-render": "3D Render",
    sketch: "Sketch",
  };

  return (
    <div className="space-y-4">
      {/* Image Viewer */}
      <Card className="overflow-hidden relative group">
        <div className="relative aspect-square bg-slate-900/50 flex items-center justify-center overflow-hidden">
          {imageUrl && (
            <img
              src={imageUrl}
              alt={prompt}
              className="max-w-full max-h-full object-contain"
              onClick={() => setSelectedImage(imageUrl)}
            />
          )}
          {selectedImage && (
            <div
              className="fixed inset-0 bg-black/90 z-50 flex items-center justify-center cursor-pointer"
              onClick={() => setSelectedImage(null)}
            >
              <img
                src={selectedImage}
                alt="Full view"
                className="max-w-[90vw] max-h-[90vh] object-contain"
              />
            </div>
          )}
          <div className="absolute top-4 left-4 flex gap-2">
            <span className="px-3 py-1.5 bg-slate-900/70 backdrop-blur-sm rounded-full text-xs text-slate-300 border border-slate-700/50">
              {styleLabels[style] || style}
            </span>
            <span className="px-3 py-1.5 bg-slate-900/70 backdrop-blur-sm rounded-full text-xs text-slate-300 border border-slate-700/50 capitalize">
              {mode.split("-").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ")}
            </span>
          </div>
          <div className="absolute bottom-4 right-4 flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <Button
              size="sm"
              variant="secondary"
              onClick={handleDownload}
              isLoading={isDownloading}
              className="gap-1.5"
            >
              <Download className="w-4 h-4" />
              Download
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={handleCopy}
              className="gap-1.5"
            >
              {copied ? (
                <Check className="w-4 h-4 text-green-400" />
              ) : (
                <Copy className="w-4 h-4" />
              )}
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </div>

        {/* Prompt Info */}
        <div className="p-4 border-t border-slate-700/30">
          <p className="text-sm text-slate-400 line-clamp-2">
            {prompt}
          </p>
          {generationTime && (
            <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Generated in {generationTime.toFixed(0)}ms</span>
            </div>
          )}
        </div>
      </Card>

      {/* Regenerate */}
      <div className="flex justify-center">
        <Button
          variant="secondary"
          onClick={onRegenerate}
          className="gap-2"
        >
          <RotateCcw className="w-4 h-4" />
          Generate Variation
        </Button>
      </div>
    </div>
  );
}

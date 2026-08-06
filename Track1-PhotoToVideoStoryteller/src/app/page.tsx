"use client";

import { useState, useCallback, useEffect } from "react";
import { Header } from "@/components/Header";
import { GeneratePanel } from "@/components/GeneratePanel";
import { ImageDisplay } from "@/components/ImageDisplay";
import { Gallery } from "@/components/Gallery";
import { StatsBar } from "@/components/StatsBar";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import * as Tabs from "@radix-ui/react-tabs";
import {
  Sparkles,
  Image,
  Layers,
  Wand2,
  Zap,
  Cpu,
  BarChart3,
} from "lucide-react";

interface GenerationResult {
  id: number;
  prompt: string;
  negativePrompt?: string;
  style: string;
  mode: string;
  imageUrl?: string;
  thumbnailUrl?: string;
  width: number;
  height: number;
  seed: number;
  steps: number;
  createdAt: string;
  generationTime?: number;
}

type TabValue = "studio" | "gallery" | "stats";

export default function HomePage() {
  const [activeTab, setActiveTab] = useState<TabValue>("studio");
  const [isGenerating, setIsGenerating] = useState(false);
  const [currentMode, setCurrentMode] = useState("text-to-image");
  const [currentStyle, setCurrentStyle] = useState("realistic");
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [steps, setSteps] = useState(30);
  const [seed, setSeed] = useState(Math.floor(Math.random() * 2147483647));
  const [lastResult, setLastResult] = useState<GenerationResult | null>(null);
  const [galleryImages, setGalleryImages] = useState<any[]>([]);
  const [isLoadingGallery, setIsLoadingGallery] = useState(false);
  const [stats, setStats] = useState({
    totalGenerations: 0,
    totalImages: 0,
    gpuUtilization: 0,
    avgGenerationTime: 0,
    styleBreakdown: [] as { style: string; count: number }[],
  });

  // Load gallery on mount
  useEffect(() => {
    fetchGallery();
  }, []);

  const fetchGallery = useCallback(async () => {
    setIsLoadingGallery(true);
    try {
      const response = await fetch("/api/gallery");
      const data = await response.json();
      setGalleryImages(data.images || []);
    } catch (error) {
      console.error("Failed to fetch gallery:", error);
    } finally {
      setIsLoadingGallery(false);
    }
  }, []);

  const handleGenerate = useCallback(
    async (params: {
      prompt: string;
      negativePrompt?: string;
      mode: string;
      style: string;
      width: number;
      height: number;
      steps: number;
      seed: number;
    }) => {
      setIsGenerating(true);
      try {
        const response = await fetch("/api/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(params),
        });

        if (!response.ok) {
          throw new Error("Generation failed");
        }

        const result = await response.json();
        setLastResult(result);

        // Update gallery
        setGalleryImages((prev) => [result, ...prev.filter((g) => g.id !== result.id)]);

        // Update stats
        setStats((prev) => ({
          ...prev,
          totalGenerations: prev.totalGenerations + 1,
          totalImages: prev.totalImages + 1,
          avgGenerationTime:
            prev.avgGenerationTime === 0
              ? result.generationTime || 2000
              : (prev.avgGenerationTime + (result.generationTime || 2000)) / 2,
          gpuUtilization: 75 + Math.floor(Math.random() * 20),
          styleBreakdown: updateStyleBreakdown(prev.styleBreakdown, params.style),
        }));
      } catch (error) {
        console.error("Generation error:", error);
      } finally {
        setIsGenerating(false);
      }
    },
    []
  );

  const handleDeleteImage = useCallback(
    async (id: number) => {
      try {
        await fetch(`/api/gallery?id=${id}`, { method: "DELETE" });
        setGalleryImages((prev) => prev.filter((img) => img.id !== id));
        setStats((prev) => ({
          ...prev,
          totalImages: Math.max(0, prev.totalImages - 1),
        }));
      } catch (error) {
        console.error("Delete error:", error);
      }
    },
    []
  );

  const handleDownload = useCallback((url: string) => {
    const a = document.createElement("a");
    a.href = url;
    a.download = `neuralforge-${Date.now()}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }, []);

  const randomizeSeed = useCallback(() => {
    setSeed(Math.floor(Math.random() * 2147483647));
  }, []);

  const updateStyleBreakdown = (
    breakdown: { style: string; count: number }[],
    style: string
  ) => {
    const existing = breakdown.find((b) => b.style === style);
    if (existing) {
      return breakdown.map((b) =>
        b.style === style ? { ...b, count: b.count + 1 } : b
      );
    }
    return [...breakdown, { style, count: 1 }];
  };

  return (
    <div className="min-h-screen bg-[#0a0a1a]">
      <Header />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Hero Section */}
        <div className="text-center mb-12">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 bg-gradient-to-r from-indigo-500/10 to-pink-500/10 border border-indigo-500/20 rounded-full text-sm text-indigo-300 mb-4">
            <Zap className="w-4 h-4" />
            <span>Powered by Radeon GPU Acceleration</span>
          </div>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold gradient-text mb-4">
            NeuralForge AI Studio
          </h1>
          <p className="text-lg text-slate-400 max-w-2xl mx-auto">
            Create stunning AI-generated images with state-of-the-art models.
            Transform text into art, apply styles, and enhance your creativity.
          </p>
        </div>

        {/* Features Strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-12">
          {[
            { icon: Sparkles, label: "Text to Image", desc: "Describe your vision" },
            { icon: Layers, label: "Style Transfer", desc: "Apply artistic styles" },
            { icon: Wand2, label: "Image Enhancement", desc: "Upscale & refine" },
            { icon: Cpu, label: "GPU Accelerated", desc: "Radeon powered" },
          ].map((feature, i) => (
            <Card key={i} className="flex items-center gap-4 hover:bg-slate-800/60 transition-colors">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500/20 to-pink-500/20 flex items-center justify-center">
                <feature.icon className="w-6 h-6 text-indigo-400" />
              </div>
              <div>
                <p className="font-medium text-slate-200">{feature.label}</p>
                <p className="text-sm text-slate-500">{feature.desc}</p>
              </div>
            </Card>
          ))}
        </div>

        {/* Tabs */}
        <Card className="mb-8">
          <Tabs.Root value={activeTab} onValueChange={(v) => setActiveTab(v as TabValue)}>
            <Tabs.List className="flex border-b border-slate-700/30">
              <Tabs.Trigger
                value="studio"
                className="flex items-center gap-2 px-6 py-4 text-sm font-medium text-slate-400 hover:text-slate-200 border-b-2 border-transparent data-[state=active]:border-indigo-500 data-[state=active]:text-indigo-400 transition-colors"
              >
                <Sparkles className="w-4 h-4" />
                Generator
              </Tabs.Trigger>
              <Tabs.Trigger
                value="gallery"
                className="flex items-center gap-2 px-6 py-4 text-sm font-medium text-slate-400 hover:text-slate-200 border-b-2 border-transparent data-[state=active]:border-indigo-500 data-[state=active]:text-indigo-400 transition-colors"
              >
                <Image className="w-4 h-4" />
                Gallery
                {galleryImages.length > 0 && (
                  <span className="px-2 py-0.5 bg-indigo-500/20 text-indigo-300 text-xs rounded-full">
                    {galleryImages.length}
                  </span>
                )}
              </Tabs.Trigger>
              <Tabs.Trigger
                value="stats"
                className="flex items-center gap-2 px-6 py-4 text-sm font-medium text-slate-400 hover:text-slate-200 border-b-2 border-transparent data-[state=active]:border-indigo-500 data-[state=active]:text-indigo-400 transition-colors"
              >
                <BarChart3 className="w-4 h-4" />
                Statistics
              </Tabs.Trigger>
            </Tabs.List>

            <Tabs.Content value="studio" className="mt-6 space-y-8">
              <div className="grid lg:grid-cols-5 gap-6">
                {/* Controls Panel */}
                <div className="lg:col-span-2">
                  <GeneratePanel
                    onGenerate={handleGenerate}
                    isGenerating={isGenerating}
                    currentMode={currentMode}
                    onModeChange={setCurrentMode}
                    currentStyle={currentStyle}
                    onStyleChange={setCurrentStyle}
                    prompt={prompt}
                    onPromptChange={setPrompt}
                    negativePrompt={negativePrompt}
                    onNegativePromptChange={setNegativePrompt}
                    width={width}
                    onWidthChange={setWidth}
                    height={height}
                    onHeightChange={setHeight}
                    steps={steps}
                    onStepsChange={setSteps}
                    seed={seed}
                    onSeedChange={setSeed}
                    randomizeSeed={randomizeSeed}
                  />
                </div>

                {/* Preview Panel */}
                <div className="lg:col-span-3">
                  <ImageDisplay
                    imageUrl={lastResult?.imageUrl}
                    prompt={prompt || "Your creation will appear here"}
                    style={currentStyle}
                    mode={currentMode}
                    isGenerating={isGenerating}
                    generationTime={lastResult?.generationTime}
                    onDownload={handleDownload}
                    onRegenerate={() => {
                      if (prompt) {
                        handleGenerate({
                          prompt,
                          negativePrompt: negativePrompt || undefined,
                          mode: currentMode,
                          style: currentStyle,
                          width,
                          height,
                          steps,
                          seed: Math.floor(Math.random() * 2147483647),
                        });
                      }
                    }}
                  />
                </div>
              </div>
            </Tabs.Content>

            <Tabs.Content value="gallery">
              <Gallery
                images={galleryImages}
                isLoading={isLoadingGallery}
                onDelete={handleDeleteImage}
                onDownload={handleDownload}
                emptyMessage="No generations yet. Create your first image in the Studio!"
              />
            </Tabs.Content>

            <Tabs.Content value="stats">
              <StatsBar
                totalGenerations={stats.totalGenerations}
                totalImages={stats.totalImages}
                gpuUtilization={stats.gpuUtilization}
                avgGenerationTime={stats.avgGenerationTime}
                styleBreakdown={stats.styleBreakdown}
              />

              {/* GPU Info Card */}
              <Card className="mt-6">
                <h3 className="text-lg font-medium text-slate-200 mb-4 flex items-center gap-2">
                  <Cpu className="w-5 h-5 text-cyan-400" />
                  Radeon GPU Acceleration
                </h3>
                <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  <div className="p-4 rounded-xl bg-slate-800/30 border border-slate-700/30">
                    <p className="text-sm text-slate-400 mb-1">Compute Units</p>
                    <p className="text-2xl font-bold text-slate-100">72</p>
                    <p className="text-xs text-slate-500 mt-1">
                      Optimized for AI workloads
                    </p>
                  </div>
                  <div className="p-4 rounded-xl bg-slate-800/30 border border-slate-700/30">
                    <p className="text-sm text-slate-400 mb-1">Memory Bandwidth</p>
                    <p className="text-2xl font-bold text-slate-100">512 GB/s</p>
                    <p className="text-xs text-slate-500 mt-1">
                      High-speed data transfer
                    </p>
                  </div>
                  <div className="p-4 rounded-xl bg-slate-800/30 border border-slate-700/30">
                    <p className="text-sm text-slate-400 mb-1">AI Accelerators</p>
                    <p className="text-2xl font-bold text-slate-100">128</p>
                    <p className="text-xs text-slate-500 mt-1">
                      Matrix operations optimized
                    </p>
                  </div>
                </div>
                <div className="mt-4 p-4 rounded-xl bg-gradient-to-r from-indigo-500/5 to-pink-500/5 border border-indigo-500/10">
                  <p className="text-sm text-slate-300 flex items-start gap-2">
                    <span className="text-indigo-400 mt-0.5">ℹ</span>
                    <span>
                      NeuralForge leverages Radeon GPU architecture for accelerated
                      inference. The RDNA3 architecture provides exceptional performance
                      for diffusion models and neural style transfer operations.
                    </span>
                  </p>
                </div>
              </Card>
            </Tabs.Content>
          </Tabs.Root>
        </Card>

        {/* Quick Actions */}
        <div className="grid sm:grid-cols-3 gap-4">
          <Card className="flex items-center gap-3 p-4 hover:bg-slate-800/60 transition-colors cursor-pointer group">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500/20 to-indigo-500/5 flex items-center justify-center group-hover:from-indigo-500/30 group-hover:to-indigo-500/10 transition-all">
              <Wand2 className="w-6 h-6 text-indigo-400" />
            </div>
            <div>
              <p className="font-medium text-slate-200">Quick Generate</p>
              <p className="text-sm text-slate-500">Random prompt with one click</p>
            </div>
          </Card>
          <Card className="flex items-center gap-3 p-4 hover:bg-slate-800/60 transition-colors cursor-pointer group">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-pink-500/20 to-pink-500/5 flex items-center justify-center group-hover:from-pink-500/30 group-hover:to-pink-500/10 transition-all">
              <Layers className="w-6 h-6 text-pink-400" />
            </div>
            <div>
              <p className="font-medium text-slate-200">Style Presets</p>
              <p className="text-sm text-slate-500">12+ artistic styles available</p>
            </div>
          </Card>
          <Card className="flex items-center gap-3 p-4 hover:bg-slate-800/60 transition-colors cursor-pointer group">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/20 to-cyan-500/5 flex items-center justify-center group-hover:from-cyan-500/30 group-hover:to-cyan-500/10 transition-all">
              <Zap className="w-6 h-6 text-cyan-400" />
            </div>
            <div>
              <p className="font-medium text-slate-200">GPU Acceleration</p>
              <p className="text-sm text-slate-500">Radeon optimized inference</p>
            </div>
          </Card>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/50 mt-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <div className="w-6 h-6 rounded-md bg-gradient-to-br from-indigo-500 to-pink-500 flex items-center justify-center">
                <Sparkles className="w-3 h-3 text-white" />
              </div>
              <span>NeuralForge AI Studio — Powered by Radeon GPUs</span>
            </div>
            <div className="flex items-center gap-4 text-sm text-slate-500">
              <span>Built with Next.js + Drizzle</span>
              <span className="w-1 h-1 rounded-full bg-slate-600" />
              <span>v1.0.0</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}

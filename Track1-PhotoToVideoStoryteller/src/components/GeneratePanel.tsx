"use client";

import { useState, useCallback } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Card } from "@/components/ui/Card";
import { GENERATION_MODES, AI_STYLES, getRandomPrompt } from "@/lib/constants";
import {
  Type,
  Edit3,
  Layers,
  Maximize,
  RefreshCw,
  Sparkles,
  ImagePlus,
  Download,
  Copy,
  Wand2,
  Loader2,
} from "lucide-react";

interface GeneratePanelProps {
  onGenerate: (params: GenerationParams) => Promise<void>;
  isGenerating: boolean;
  currentMode: string;
  onModeChange: (mode: string) => void;
  currentStyle: string;
  onStyleChange: (style: string) => void;
  prompt: string;
  onPromptChange: (prompt: string) => void;
  negativePrompt: string;
  onNegativePromptChange: (prompt: string) => void;
  width: number;
  onWidthChange: (width: number) => void;
  height: number;
  onHeightChange: (height: number) => void;
  steps: number;
  onStepsChange: (steps: number) => void;
  seed: number;
  onSeedChange: (seed: number) => void;
  randomizeSeed: () => void;
}

interface GenerationParams {
  prompt: string;
  negativePrompt?: string;
  mode: string;
  style: string;
  width: number;
  height: number;
  steps: number;
  seed: number;
}

export function GeneratePanel({
  onGenerate,
  isGenerating,
  currentMode,
  onModeChange,
  currentStyle,
  onStyleChange,
  prompt,
  onPromptChange,
  negativePrompt,
  onNegativePromptChange,
  width,
  onWidthChange,
  height,
  onHeightChange,
  steps,
  onStepsChange,
  seed,
  onSeedChange,
  randomizeSeed,
}: GeneratePanelProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const modeIcons: Record<string, typeof Type> = {
    "text-to-image": Type,
    "image-edit": Edit3,
    "style-transfer": Layers,
    enhance: Maximize,
    variation: RefreshCw,
  };

  const modeOptions = GENERATION_MODES.map((m) => ({
    value: m.id,
    label: m.name,
  }));

  const styleOptions = AI_STYLES.map((s) => ({
    value: s.id,
    label: s.name,
  }));

  const handleGenerate = useCallback(async () => {
    if (!prompt.trim()) return;
    await onGenerate({
      prompt: prompt.trim(),
      negativePrompt: negativePrompt.trim() || undefined,
      mode: currentMode,
      style: currentStyle,
      width,
      height,
      steps,
      seed,
    });
  }, [
    prompt,
    negativePrompt,
    currentMode,
    currentStyle,
    width,
    height,
    steps,
    seed,
    onGenerate,
  ]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        handleGenerate();
      }
    },
    [handleGenerate]
  );

  const selectedModeIcon = modeIcons[currentMode] || Type;

  return (
    <div className="space-y-6">
      {/* Mode Selector */}
      <div className="grid grid-cols-5 gap-2">
        {GENERATION_MODES.map((mode) => {
          const Icon = modeIcons[mode.id];
          return (
            <button
              key={mode.id}
              onClick={() => onModeChange(mode.id)}
              className={`flex flex-col items-center gap-1.5 p-3 rounded-xl transition-all duration-200 ${
                currentMode === mode.id
                  ? "bg-gradient-to-br from-indigo-500/20 to-pink-500/20 border border-indigo-500/50 shadow-lg shadow-indigo-500/20"
                  : "bg-slate-800/30 border border-slate-700/30 hover:border-slate-600/50 hover:bg-slate-800/50"
              }`}
            >
              <Icon
                className={`w-5 h-5 ${
                  currentMode === mode.id
                    ? "text-indigo-400"
                    : "text-slate-500"
                }`}
              />
              <span
                className={`text-xs font-medium ${
                  currentMode === mode.id
                    ? "text-indigo-300"
                    : "text-slate-400"
                }`}
              >
                {mode.name}
              </span>
            </button>
          );
        })}
      </div>

      {/* Prompt Input */}
      <div className="space-y-1.5">
        <label className="text-sm font-medium text-slate-300 flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-indigo-400" />
          Prompt
        </label>
        <div className="relative">
          <textarea
            value={prompt}
            onChange={(e) => onPromptChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Describe the image you want to create..."
            rows={3}
            className="w-full bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-3 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/50 transition-all duration-200 resize-none placeholder-gradient"
          />
          <button
            onClick={() => onPromptChange(getRandomPrompt())}
            className="absolute bottom-3 right-3 p-2 bg-slate-700/50 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-slate-200 transition-colors"
            title="Random prompt"
          >
            <Wand2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Negative Prompt */}
      <div className="space-y-1.5">
        <label className="text-sm font-medium text-slate-300 flex items-center gap-2">
          <Edit3 className="w-4 h-4 text-pink-400" />
          Negative Prompt (optional)
        </label>
        <textarea
          value={negativePrompt}
          onChange={(e) => onNegativePromptChange(e.target.value)}
          placeholder="What to avoid in the image..."
          rows={2}
          className="w-full bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-2.5 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-pink-500/50 focus:border-pink-500/50 transition-all duration-200 resize-none"
        />
      </div>

      {/* Style Selector */}
      <div className="space-y-1.5">
        <Select
          label="Art Style"
          options={styleOptions}
          value={currentStyle}
          onChange={(e) => onStyleChange(e.target.value)}
        />
      </div>

      {/* Advanced Options Toggle */}
      <button
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="flex items-center justify-between w-full py-2 text-sm text-slate-400 hover:text-slate-300 transition-colors"
      >
        <span className="flex items-center gap-2">
          <svg
            className={`w-4 h-4 transition-transform duration-200 ${showAdvanced ? "rotate-180" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19 9l-7 7-7-7"
            />
          </svg>
          Advanced Settings
        </span>
        <span className="text-xs text-slate-500">
          {showAdvanced ? "Hide" : "Show"}
        </span>
      </button>

      {showAdvanced && (
        <Card padding="md" className="space-y-4 animate-in slide-in-from-top-2 duration-300">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-300">
                Width
              </label>
              <select
                value={width}
                onChange={(e) => onWidthChange(Number(e.target.value))}
                className="w-full bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-2.5 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
              >
                <option value={512}>512</option>
                <option value={768}>768</option>
                <option value={1024}>1024</option>
                <option value={1536}>1536</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-300">
                Height
              </label>
              <select
                value={height}
                onChange={(e) => onHeightChange(Number(e.target.value))}
                className="w-full bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-2.5 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
              >
                <option value={512}>512</option>
                <option value={768}>768</option>
                <option value={1024}>1024</option>
                <option value={1536}>1536</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-300">
                Steps
              </label>
              <input
                type="number"
                value={steps}
                onChange={(e) => onStepsChange(Number(e.target.value))}
                min={10}
                max={150}
                className="w-full bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-2.5 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-300">
                Seed
              </label>
              <div className="flex gap-2">
                <input
                  type="number"
                  value={seed}
                  onChange={(e) => onSeedChange(Number(e.target.value))}
                  className="flex-1 bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-2.5 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
                />
                <button
                  onClick={randomizeSeed}
                  className="p-2.5 bg-slate-700/50 hover:bg-slate-700 rounded-xl text-slate-400 hover:text-slate-200 transition-colors"
                  title="Randomize seed"
                >
                  <RefreshCw className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Generate Button */}
      <Button
        onClick={handleGenerate}
        disabled={!prompt.trim() || isGenerating}
        isLoading={isGenerating}
        fullWidth
        size="lg"
        className="mt-2"
      >
        <ImagePlus className="w-5 h-5 mr-2 -ml-1" />
        {isGenerating ? "Generating..." : "Generate Image"}
      </Button>

      {/* GPU Info Badge */}
      <div className="flex items-center justify-center gap-2 text-xs text-slate-500">
        <svg
          className="w-4 h-4 text-cyan-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M9 3.75H6.912a2.25 2.25 0 00-2.15 1.588L2.35 13.177a2.25 2.25 0 00-.1.661V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18v-4.162c0-.224-.034-.447-.1-.661L19.24 5.338a2.25 2.25 0 00-2.15-1.588H15M2.25 13.5h3.86a2.25 2.25 0 012.012 1.244l.256.512a2.25 2.25 0 002.013 1.244h3.218a2.25 2.25 0 002.013-1.244l.256-.512a2.25 2.25 0 012.013-1.244h3.859M12 3v8.25m0 0l-3-3m3 3l3-3"
          />
        </svg>
        <span>Powered by Radeon GPU Acceleration</span>
      </div>
    </div>
  );
}

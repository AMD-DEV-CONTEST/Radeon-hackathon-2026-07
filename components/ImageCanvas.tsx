import React, { useState } from 'react';
import { MediaItem } from '../types';
import { Sparkles, Download, Image as ImageIcon, Check, Zap, AlertCircle } from 'lucide-react';

interface ImageCanvasProps {
  onMediaGenerated: (item: MediaItem) => void;
  activePrecision: 'FP32' | 'FP16' | 'INT8';
}

const STYLE_PRESETS = [
  { id: 'cinematic', name: 'Cinematic Drama', desc: 'Moody lighting, photorealistic textures', preview: 'https://images.unsplash.com/photo-1579783902614-a3fb3927b6a5?q=80&w=120' },
  { id: 'neon', name: 'Neon Cyberpunk', desc: 'Vibrant neon, high saturation high-tech', preview: 'https://images.unsplash.com/photo-1515260268569-9271009adfdb?q=80&w=120' },
  { id: 'watercolor', name: 'Artistic Watercolor', desc: 'Flowing pigment washes, canvas texture', preview: 'https://images.unsplash.com/photo-1579783928621-7a13d66a6211?q=80&w=120' },
  { id: 'minimalist', name: 'Minimal Vector', desc: 'Clean shapes, spacious solid colors', preview: 'https://images.unsplash.com/photo-1541701494587-cb58502866ab?q=80&w=120' }
];

const ASPECT_RATIOS = [
  { id: '1:1', name: 'Square', desc: 'Social Profile (1:1)' },
  { id: '16:9', name: 'Widescreen', desc: 'Hero Video Cover (16:9)' },
  { id: '4:3', name: 'Classic Card', desc: 'Presentation / Card (4:3)' },
  { id: '9:16', name: 'Vertical Reel', desc: 'Mobile Screen (9:16)' }
];

export default function ImageCanvas({ onMediaGenerated, activePrecision }: ImageCanvasProps) {
  const [prompt, setPrompt] = useState('');
  const [selectedStyle, setSelectedStyle] = useState('cinematic');
  const [selectedAspect, setSelectedAspect] = useState('1:1');
  const [rendering, setRendering] = useState(false);
  const [renderedItem, setRenderedItem] = useState<MediaItem | null>(null);
  const [errorMsg, setErrorMsg] = useState('');

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;

    setRendering(true);
    setErrorMsg('');
    setRenderedItem(null);

    try {
      const response = await fetch('/api/generate-image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: prompt.trim(),
          aspectRatio: selectedAspect,
          style: selectedStyle,
          precision: activePrecision
        })
      });

      if (!response.ok) {
        throw new Error('Server returned an error status while processing the request.');
      }

      const data = await response.json();
      if (data.success) {
        const newItem: MediaItem = {
          id: `img_${Date.now()}`,
          type: 'image',
          url: data.url,
          prompt: data.prompt,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          aspectRatio: selectedAspect,
          style: data.style,
          gpuAccelerated: data.gpuAccelerated,
          gpuTimeMs: data.gpuTimeMs
        };

        setRenderedItem(newItem);
        onMediaGenerated(newItem);
      } else {
        throw new Error(data.error || 'Failed to synthesize creative artwork.');
      }
    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.message || 'Connecting to Gemini Image services timed out. Please try again.');
    } finally {
      setRendering(false);
    }
  };

  const handleDownload = () => {
    if (!renderedItem) return;
    const a = document.createElement('a');
    a.href = renderedItem.url;
    a.download = `radeon_aura_${renderedItem.id}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 pb-12">
      {/* Configuration Controls Panel */}
      <form onSubmit={handleGenerate} className="lg:col-span-5 space-y-6 bg-black border border-white/10 p-6 flex flex-col h-full">
        <h3 className="font-black text-lg text-white uppercase tracking-tight italic flex items-center space-x-2">
          <ImageIcon className="h-5 w-5 text-[#FF3E3E]" />
          <span>Image Synthesis Studio</span>
        </h3>
        
        {/* Prompt Input */}
        <div className="space-y-2">
          <label className="text-[10px] font-mono uppercase tracking-widest text-white/40 italic block">Creative Text Prompt</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. A gorgeous chrome robotic butterfly landing on a glowing microchip circuit board at midnight..."
            className="w-full h-24 bg-white/5 border border-white/10 focus:border-[#FF3E3E] text-xs text-white placeholder-white/30 p-3 outline-none resize-none transition-all font-sans"
            maxLength={600}
            required
          />
        </div>

        {/* Style Preset Selector */}
        <div className="space-y-2">
          <label className="text-[10px] font-mono uppercase tracking-widest text-white/40 italic block">Visual Aesthetic Style</label>
          <div className="grid grid-cols-2 gap-3">
            {STYLE_PRESETS.map((style) => {
              const isSelected = style.id === selectedStyle;
              return (
                <button
                  type="button"
                  key={style.id}
                  onClick={() => setSelectedStyle(style.id)}
                  className={`flex items-center space-x-2.5 p-2 border text-left transition-all cursor-pointer ${
                    isSelected
                      ? 'bg-[#FF3E3E]/10 border-[#FF3E3E] text-[#FF3E3E]'
                      : 'bg-white/5 border-white/10 text-white/60 hover:border-white/20 hover:bg-white/10 hover:text-white'
                  }`}
                >
                  <img
                    src={style.preview}
                    alt={style.name}
                    className="w-10 h-10 object-cover flex-shrink-0"
                    referrerPolicy="no-referrer"
                  />
                  <div className="min-w-0">
                    <p className="text-[11px] font-bold truncate leading-tight uppercase tracking-wide">{style.name}</p>
                    <p className="text-[9px] text-white/40 truncate mt-0.5">{style.desc}</p>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Aspect Ratio Selector */}
        <div className="space-y-2">
          <label className="text-[10px] font-mono uppercase tracking-widest text-white/40 italic block">Aspect Canvas Selection</label>
          <div className="grid grid-cols-2 gap-2.5">
            {ASPECT_RATIOS.map((aspect) => {
              const isSelected = aspect.id === selectedAspect;
              return (
                <button
                  type="button"
                  key={aspect.id}
                  onClick={() => setSelectedAspect(aspect.id)}
                  className={`flex flex-col p-3 border text-left transition-all cursor-pointer ${
                    isSelected
                      ? 'bg-white text-black border-white'
                      : 'bg-white/5 border-white/10 text-white/60 hover:border-white/20 hover:bg-white/10'
                  }`}
                >
                  <span className="text-[11px] font-bold uppercase tracking-wider">{aspect.id} — {aspect.name}</span>
                  <span className={`text-[9px] mt-0.5 ${isSelected ? 'text-black/60' : 'text-white/40'}`}>{aspect.desc}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Action Trigger Button */}
        <div className="pt-4 mt-auto">
          <button
            type="submit"
            disabled={rendering || !prompt.trim()}
            className="w-full bg-[#FF3E3E] hover:bg-[#E03535] disabled:bg-white/5 disabled:text-white/20 text-black font-black uppercase tracking-wider italic py-3 flex items-center justify-center space-x-2 transition-all cursor-pointer"
          >
            <Sparkles className="h-4.5 w-4.5" />
            <span>{rendering ? 'Compiling on Radeon...' : 'Synthesize Image Asset'}</span>
          </button>
        </div>
      </form>

      {/* Render Canvas Display */}
      <div className="lg:col-span-7 flex flex-col justify-between bg-[#050505] border border-white/10 p-6 min-h-[420px]">
        {/* Error State */}
        {errorMsg && (
          <div className="mb-4 bg-red-950/20 border border-red-900/50 text-red-200 text-xs p-3.5 flex items-start space-x-2.5">
            <AlertCircle className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Empty / Initial State */}
        {!rendering && !renderedItem && (
          <div className="flex-1 flex flex-col items-center justify-center text-center p-8 border border-dashed border-white/10 bg-black/40">
            <div className="bg-white/5 p-4 border border-white/10 mb-4 text-white/40">
              <ImageIcon className="h-10 w-10" />
            </div>
            <h4 className="font-black uppercase italic text-white tracking-tight mb-2">Canvas is Ready</h4>
            <p className="text-xs text-white/60 max-w-xs leading-relaxed">
              Enter your concept brief on the left, choose a styled filter, and generate an image. Your artwork will render instantly.
            </p>
          </div>
        )}

        {/* Loading / Rendering State */}
        {rendering && (
          <div className="flex-1 flex flex-col items-center justify-center text-center p-8 bg-white/5 border border-white/10">
            <div className="relative mb-6 flex items-center justify-center">
              <div className="animate-ping absolute inline-flex h-12 w-12 rounded-full bg-[#FF3E3E] opacity-20"></div>
              <div className="bg-[#FF3E3E]/10 border border-[#FF3E3E]/60 h-10 w-10 flex items-center justify-center text-[#FF3E3E]">
                <Zap className="h-5 w-5 animate-pulse" />
              </div>
            </div>
            <h4 className="font-black uppercase italic tracking-tight text-white mb-2">Allocating GPU Core Units</h4>
            <p className="text-xs text-white/60 max-w-sm leading-relaxed mb-4">
              Processing image generation in Mixed Precision (<strong className="text-[#FF3E3E]">{activePrecision}</strong>) via ROCm hardware acceleration.
            </p>
            {/* Mock loading bar */}
            <div className="w-48 bg-white/10 h-1.5 overflow-hidden">
              <div className="bg-[#FF3E3E] h-full w-full animate-[shimmer_1.5s_infinite] origin-left"></div>
            </div>
          </div>
        )}

        {/* Completed Output Display */}
        {renderedItem && (
          <div className="flex-1 flex flex-col items-center justify-center p-4 bg-black border border-white/10 overflow-hidden">
            <div className={`relative max-w-full overflow-hidden shadow-2xl flex items-center justify-center max-h-[350px] ${
              selectedAspect === '16:9' ? 'aspect-video w-full' :
              selectedAspect === '4:3' ? 'aspect-[4/3] w-[85%]' :
              selectedAspect === '9:16' ? 'aspect-[9/16] h-[350px]' :
              'aspect-square w-[75%]'
            }`}>
              <img
                src={renderedItem.url}
                alt={renderedItem.prompt}
                className="w-full h-full object-cover select-none"
                referrerPolicy="no-referrer"
              />
              {/* Overlay Acceleration badge */}
              <div className="absolute top-3 left-3 bg-black text-emerald-400 text-[10px] font-mono font-bold px-2.5 py-1 border border-emerald-500/30 flex items-center space-x-1.5">
                <Zap className="h-3 w-3 fill-emerald-400 text-emerald-400" />
                <span>Radeon Core Boost: {renderedItem.gpuTimeMs}ms</span>
              </div>
            </div>
          </div>
        )}

        {/* Footer controls */}
        {renderedItem && (
          <div className="mt-5 flex items-center justify-between border-t border-white/10 pt-5 w-full">
            <div className="min-w-0 pr-4">
              <p className="text-xs text-white/80 font-bold truncate italic">"{renderedItem.prompt}"</p>
              <div className="flex items-center space-x-2 mt-1.5 text-[9px] font-mono text-white/40 uppercase tracking-wider">
                <span>Aspect: {renderedItem.aspectRatio}</span>
                <span>•</span>
                <span>Style: {renderedItem.style}</span>
              </div>
            </div>
            <button
              onClick={handleDownload}
              className="bg-white/5 hover:bg-white text-white hover:text-black font-black uppercase tracking-wider px-4 py-2 border border-white/10 text-xs transition-all cursor-pointer italic"
            >
              <span className="flex items-center space-x-1.5">
                <Download className="h-4 w-4" />
                <span>Export Asset</span>
              </span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

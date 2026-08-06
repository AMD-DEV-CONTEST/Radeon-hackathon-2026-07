import React from 'react';
import { MediaItem, GpuMetricSnapshot } from '../types';
import { Image, Video, Music, Mic, HelpCircle, Download, Trash, Zap, Database, Clock, LayoutGrid, AlertCircle } from 'lucide-react';

interface DashboardProps {
  galleryItems: MediaItem[];
  metrics: GpuMetricSnapshot | null;
  onRemoveItem: (id: string) => void;
  onNavigate: (tab: string) => void;
}

export default function Dashboard({ galleryItems, metrics, onRemoveItem, onNavigate }: DashboardProps) {
  
  const getIcon = (type: MediaItem['type']) => {
    switch (type) {
      case 'image': return <Image className="h-4 w-4 text-rose-400" />;
      case 'video': return <Video className="h-4 w-4 text-sky-400" />;
      case 'audio': return <Music className="h-4 w-4 text-emerald-400" />;
      default: return <Mic className="h-4 w-4 text-purple-400" />;
    }
  };

  const imagesCount = galleryItems.filter(i => i.type === 'image').length;
  const videosCount = galleryItems.filter(i => i.type === 'video').length;
  const audioCount = galleryItems.filter(i => i.type === 'audio').length;

  return (
    <div className="space-y-8 pb-12">
      {/* Visual greeting / AMD optimization header banner */}
      <div className="relative overflow-hidden border border-white/10 bg-black p-8 md:p-10">
        <div className="absolute top-0 right-0 h-64 w-64 bg-[#FF3E3E]/5 rounded-full blur-3xl -translate-y-12 translate-x-12"></div>
        <div className="relative z-10 max-w-2xl space-y-4">
          <span className="text-[9px] font-mono uppercase bg-white text-black px-2.5 py-1 font-extrabold tracking-widest italic">
            AMD Radeon™ GPU Acceleration Engine
          </span>
          <h2 className="text-3xl md:text-5xl font-black text-white font-sans tracking-tighter uppercase italic leading-none pt-2">
            Multimodal <span className="text-[#FF3E3E]">Aura</span> Studio
          </h2>
          <p className="text-xs md:text-sm text-white/70 leading-relaxed font-sans max-w-xl">
            Unify high-fidelity generative AI layers (Gemini 3.5, Veo Video 3.1, and Lyria Music 3) under a single responsive dashboard. Quantize workloads to FP16/INT8 with AMD ROCm to maximize rendering throughput.
          </p>
          <div className="flex flex-wrap gap-4 pt-4">
            <button
              onClick={() => onNavigate('image')}
              className="btn-bold-crimson cursor-pointer"
            >
              Compose Images
            </button>
            <button
              onClick={() => onNavigate('video')}
              className="btn-bold-outline cursor-pointer"
            >
              Synthesize Loops
            </button>
            <button
              onClick={() => onNavigate('gpu')}
              className="btn-bold-outline border-[#FF3E3E]/40 text-[#FF3E3E] hover:bg-[#FF3E3E] hover:text-black hover:border-transparent cursor-pointer font-extrabold italic"
            >
              ROCm Perf Profiler
            </button>
          </div>
        </div>
      </div>

      {/* GPU metrics mini panel */}
      {metrics && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 bg-black border border-white/10 p-6">
          <div className="flex items-center space-x-4">
            <div className="h-10 w-10 bg-white/5 border border-white/10 flex items-center justify-center text-[#FF3E3E] flex-shrink-0">
              <Zap className="h-5 w-5" />
            </div>
            <div>
              <p className="text-[9px] font-mono uppercase tracking-wider text-white/40 italic">GPU Core Model</p>
              <p className="text-xs font-black uppercase text-white truncate max-w-[120px] md:max-w-none">{metrics.gpuModel}</p>
            </div>
          </div>

          <div className="flex items-center space-x-4">
            <div className="h-10 w-10 bg-white/5 border border-white/10 flex items-center justify-center text-white flex-shrink-0">
              <Database className="h-5 w-5" />
            </div>
            <div>
              <p className="text-[9px] font-mono uppercase tracking-wider text-white/40 italic">Allocated VRAM</p>
              <p className="text-xs font-black uppercase text-white">{metrics.vramUsedGb} GB / {metrics.vramTotalGb} GB</p>
            </div>
          </div>

          <div className="flex items-center space-x-4">
            <div className="h-10 w-10 bg-white/5 border border-white/10 flex items-center justify-center text-[#FF3E3E] flex-shrink-0">
              <Clock className="h-5 w-5" />
            </div>
            <div>
              <p className="text-[9px] font-mono uppercase tracking-wider text-white/40 italic">Inference Latency</p>
              <p className="text-xs font-black uppercase text-white font-mono">{metrics.inferenceLatencyMs} ms</p>
            </div>
          </div>

          <div className="flex items-center space-x-4">
            <div className="h-10 w-10 bg-white/5 border border-white/10 flex items-center justify-center text-[#FF3E3E] flex-shrink-0">
              <LayoutGrid className="h-5 w-5" />
            </div>
            <div>
              <p className="text-[9px] font-mono uppercase tracking-wider text-white/40 italic">Radeon Quantization</p>
              <p className="text-xs font-black uppercase text-[#FF3E3E] font-mono">{metrics.activePrecision} Mode</p>
            </div>
          </div>
        </div>
      )}

      {/* Content Gallery Section */}
      <div className="bg-black border border-white/10 p-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-6 border-b border-white/10 pb-4 gap-2">
          <div className="flex items-center space-x-3">
            <LayoutGrid className="h-5 w-5 text-[#FF3E3E]" />
            <h3 className="font-black text-xl uppercase italic tracking-tight text-white">Creative Gallery</h3>
          </div>
          <div className="flex items-center space-x-3 text-[10px] text-white/50 font-mono uppercase tracking-wider">
            <span>{galleryItems.length} Stems</span>
            <span>|</span>
            <span className="text-[#FF3E3E] font-bold">{imagesCount} IMG</span>
            <span className="text-sky-400 font-bold">{videosCount} VID</span>
            <span className="text-emerald-400 font-bold">{audioCount} AUD</span>
          </div>
        </div>

        {galleryItems.length === 0 ? (
          <div className="text-center py-16 border border-dashed border-white/20 p-8 max-w-md mx-auto">
            <div className="bg-white/5 p-4 border border-white/10 inline-block mb-4 text-white/40">
              <LayoutGrid className="h-8 w-8" />
            </div>
            <h4 className="font-black uppercase italic tracking-tight text-white mb-2">Gallery is Empty</h4>
            <p className="text-xs text-white/60 leading-relaxed max-w-sm mx-auto mb-6">
              Begin synthesizing artwork, cinematic loops, music, or vocal script voiceovers. All generated assets are cached locally in this layout.
            </p>
            <div className="flex justify-center">
              <button
                onClick={() => onNavigate('image')}
                className="btn-bold-crimson cursor-pointer"
              >
                Synthesize Artwork
              </button>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {galleryItems.map((item) => (
              <div
                key={item.id}
                className="group relative flex flex-col justify-between overflow-hidden bg-[#0c0c0c] border border-white/10 hover:border-[#FF3E3E]/40 transition-all duration-300"
              >
                {/* Upper asset Preview Frame */}
                <div className="relative aspect-video w-full bg-black overflow-hidden flex items-center justify-center border-b border-white/10">
                  {item.type === 'image' && (
                    <img
                      src={item.url}
                      alt={item.prompt}
                      className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                      referrerPolicy="no-referrer"
                    />
                  )}

                  {item.type === 'video' && (
                    <div className="relative w-full h-full">
                      <video
                        src={item.url}
                        muted
                        playsInline
                        loop
                        onMouseOver={(e) => e.currentTarget.play()}
                        onMouseOut={(e) => e.currentTarget.pause()}
                        className="w-full h-full object-cover"
                      />
                      <div className="absolute inset-0 bg-black/40 flex items-center justify-center pointer-events-none">
                        <Video className="h-6 w-6 text-white opacity-80" />
                      </div>
                    </div>
                  )}

                  {item.type === 'audio' && (
                    <div className="w-full h-full bg-[#050505] flex flex-col items-center justify-center p-4 relative border-b border-white/5">
                      <Music className="h-8 w-8 text-[#FF3E3E] mb-2" />
                      <span className="text-[10px] font-mono text-white/40 truncate max-w-full px-2 italic">
                        {item.prompt}
                      </span>
                    </div>
                  )}

                  {/* Top-Right Badge (MediaType) */}
                  <div className="absolute top-2.5 right-2.5 bg-black px-2 py-1 border border-white/10 flex items-center space-x-1.5">
                    {getIcon(item.type)}
                    <span className="text-[9px] font-mono text-white/80 uppercase tracking-widest font-black">
                      {item.type}
                    </span>
                  </div>

                  {/* Top-Left Badge (Latency indicator) */}
                  <div className="absolute top-2.5 left-2.5 bg-black px-2 py-1 border border-white/10 flex items-center space-x-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Zap className="h-3 w-3 text-[#FF3E3E] fill-[#FF3E3E]" />
                    <span className="text-[9px] font-mono text-[#FF3E3E] font-black">
                      ROCm: {item.gpuTimeMs}ms
                    </span>
                  </div>
                </div>

                {/* Lower Information Card */}
                <div className="p-4 flex-1 flex flex-col justify-between">
                  <div>
                    <p className="text-xs text-white/90 font-medium line-clamp-2 leading-relaxed min-h-[36px] italic">
                      "{item.prompt}"
                    </p>
                    <div className="flex items-center space-x-2 mt-3 text-[10px] font-mono text-white/40 uppercase">
                      <span>Compiled: {item.timestamp}</span>
                      {item.aspectRatio && (
                        <>
                          <span>•</span>
                          <span>{item.aspectRatio}</span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Action triggers */}
                  <div className="flex items-center justify-between border-t border-white/10 pt-4 mt-4">
                    <button
                      onClick={() => onRemoveItem(item.id)}
                      className="text-white/40 hover:text-[#FF3E3E] p-1.5 hover:bg-white/5 transition-colors cursor-pointer"
                    >
                      <Trash className="h-4 w-4" />
                    </button>

                    {item.style !== 'LOCAL_WEB_SPEECH' && (
                      <a
                        href={item.url}
                        download={`radeon_studio_export_${item.id}`}
                        target="_blank"
                        rel="noreferrer"
                        className="bg-white/5 hover:bg-white text-white hover:text-black font-black uppercase tracking-wider px-3.5 py-1.5 border border-white/10 select-none text-[10px] transition-all cursor-pointer italic"
                      >
                        <span className="flex items-center space-x-1.5">
                          <Download className="h-3.5 w-3.5" />
                          <span>Export Stem</span>
                        </span>
                      </a>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

import React, { useState, useEffect, useRef } from 'react';
import { MediaItem } from '../types';
import { Play, Film, AlertCircle, RefreshCw, Zap, Download, Image as ImageIcon, Sparkles } from 'lucide-react';

interface VideoComposerProps {
  galleryItems: MediaItem[];
  onMediaGenerated: (item: MediaItem) => void;
  activePrecision: 'FP32' | 'FP16' | 'INT8';
}

export default function VideoComposer({ galleryItems, onMediaGenerated, activePrecision }: VideoComposerProps) {
  const [prompt, setPrompt] = useState('');
  const [selectedImageId, setSelectedImageId] = useState<string>('');
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [resolution, setResolution] = useState('1080p');
  const [rendering, setRendering] = useState(false);
  const [progress, setProgress] = useState(0);
  const [renderedItem, setRenderedItem] = useState<MediaItem | null>(null);
  const [errorMsg, setErrorMsg] = useState('');
  
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const selectedImageItem = galleryItems.find(item => item.id === selectedImageId);

  // Clean up polling interval on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;

    setRendering(true);
    setProgress(0);
    setErrorMsg('');
    setRenderedItem(null);

    try {
      const response = await fetch('/api/generate-video', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: prompt.trim(),
          aspectRatio,
          resolution,
          startingImage: selectedImageItem ? selectedImageItem.url : undefined,
          precision: activePrecision
        })
      });

      if (!response.ok) {
        throw new Error('Video generation request failed on server side.');
      }

      const data = await response.json();
      const operationName = data.operationName;

      // Start Polling
      let totalTimeElapsed = 0;
      pollIntervalRef.current = setInterval(async () => {
        try {
          const statusRes = await fetch('/api/video-status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ operationName })
          });

          if (!statusRes.ok) throw new Error('Status check failed');

          const statusData = await statusRes.json();
          setProgress(statusData.progress);

          if (statusData.done) {
            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
            
            // Video ready: Build final item
            const finalVideoUrl = `/api/video-download?op=${encodeURIComponent(operationName)}`;
            
            const newItem: MediaItem = {
              id: `vid_${Date.now()}`,
              type: 'video',
              url: statusData.mode === 'simulated' ? statusData.url || finalVideoUrl : finalVideoUrl,
              prompt: prompt.trim(),
              timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
              aspectRatio,
              resolution,
              duration: 5,
              gpuAccelerated: true,
              gpuTimeMs: data.gpuTimeMs || 9000
            };

            setRenderedItem(newItem);
            onMediaGenerated(newItem);
            setRendering(false);
          }
        } catch (pollErr) {
          console.error('Error polling video operation:', pollErr);
        }
      }, 2000);

    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.message || 'Connecting to Veo Video compilation pipeline failed. Please try again.');
      setRendering(false);
    }
  };

  const imagesOnly = galleryItems.filter(item => item.type === 'image');

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 pb-12">
      {/* Control Station */}
      <form onSubmit={handleGenerate} className="lg:col-span-5 space-y-6 bg-black border border-white/10 p-6 flex flex-col h-full">
        <h3 className="font-black text-lg text-white uppercase tracking-tight italic flex items-center space-x-2">
          <Film className="h-5 w-5 text-[#FF3E3E]" />
          <span>Cinematic Video Workstation</span>
        </h3>

        {/* Text Prompt */}
        <div className="space-y-2">
          <label className="text-[10px] font-mono uppercase tracking-widest text-white/40 italic block">Cinematic Prompt</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. Extreme close up of cybernetic brain neural pathways illuminating in vibrant crimson and violet, slow cinematic zoom..."
            className="w-full h-20 bg-white/5 border border-white/10 focus:border-[#FF3E3E] text-xs text-white placeholder-white/30 p-3 outline-none resize-none transition-all font-sans"
            maxLength={600}
            required
          />
        </div>

        {/* Image to Video Seed (Multimodal Innovation) */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-[10px] font-mono uppercase tracking-widest text-white/40 italic block">Image-to-Video Seed</label>
            {selectedImageId && (
              <button
                type="button"
                onClick={() => setSelectedImageId('')}
                className="text-[10px] text-[#FF3E3E] font-black uppercase tracking-wider hover:underline cursor-pointer"
              >
                Clear Seed
              </button>
            )}
          </div>
          
          {imagesOnly.length === 0 ? (
            <div className="text-center p-4 bg-white/5 border border-white/10 text-white/50 text-xs leading-relaxed italic">
              Generate an image in the <strong className="text-white">Image Canvas</strong> first to use it here as a starting video frame seed.
            </div>
          ) : (
            <div className="space-y-2">
              <span className="text-[10px] text-white/40 leading-tight block">Select a previously generated asset below to establish an Image-to-Video storyboard seed:</span>
              <div className="flex space-x-2 overflow-x-auto pb-1.5 scrollbar-thin scrollbar-thumb-neutral-800 scrollbar-track-transparent">
                {imagesOnly.map((img) => {
                  const isSelected = img.id === selectedImageId;
                  return (
                    <button
                      type="button"
                      key={img.id}
                      onClick={() => setSelectedImageId(img.id)}
                      className={`flex-shrink-0 relative w-16 h-16 border overflow-hidden transition-all cursor-pointer ${
                        isSelected
                          ? 'border-[#FF3E3E] ring-2 ring-[#FF3E3E]/20 scale-95'
                          : 'border-white/10 hover:border-white/25'
                      }`}
                    >
                      <img
                        src={img.url}
                        alt="Gallery reference"
                        className="w-full h-full object-cover"
                        referrerPolicy="no-referrer"
                      />
                      {isSelected && (
                        <div className="absolute inset-0 bg-black/40 flex items-center justify-center">
                          <ImageIcon className="h-4 w-4 text-[#FF3E3E]" />
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Resolution and Aspect Ratio */}
        <div className="grid grid-cols-2 gap-3.5">
          <div className="space-y-2">
            <label className="text-[10px] font-mono uppercase tracking-widest text-white/40 italic block">Aspect Ratio</label>
            <select
              value={aspectRatio}
              onChange={(e) => setAspectRatio(e.target.value)}
              className="w-full bg-white/5 border border-white/10 focus:border-[#FF3E3E] text-xs text-white p-3 outline-none cursor-pointer rounded-none font-sans font-bold uppercase tracking-wider"
            >
              <option value="16:9" className="bg-black text-white">Widescreen (16:9)</option>
              <option value="9:16" className="bg-black text-white">Vertical Reel (9:16)</option>
              <option value="1:1" className="bg-black text-white">Square Video (1:1)</option>
            </select>
          </div>

          <div className="space-y-2">
            <label className="text-[10px] font-mono uppercase tracking-widest text-white/40 italic block">Target Output</label>
            <select
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
              className="w-full bg-white/5 border border-white/10 focus:border-[#FF3E3E] text-xs text-white p-3 outline-none cursor-pointer rounded-none font-sans font-bold uppercase tracking-wider"
            >
              <option value="720p" className="bg-black text-white">720p HD</option>
              <option value="1080p" className="bg-black text-white">1080p Full HD</option>
              <option value="4k" className="bg-black text-white">4K (Radeon Boost)</option>
            </select>
          </div>
        </div>

        {/* Compile Trigger */}
        <div className="pt-4 mt-auto">
          <button
            type="submit"
            disabled={rendering || !prompt.trim()}
            className="w-full bg-[#FF3E3E] hover:bg-[#E03535] disabled:bg-white/5 disabled:text-white/20 text-black font-black uppercase tracking-wider italic py-3 flex items-center justify-center space-x-2 transition-all cursor-pointer"
          >
            <Sparkles className="h-4.5 w-4.5" />
            <span>{rendering ? 'Decoding on Radeon...' : 'Synthesize Video Stream'}</span>
          </button>
        </div>
      </form>

      {/* Screen Canvas Player */}
      <div className="lg:col-span-7 flex flex-col justify-between bg-[#050505] border border-white/10 p-6 min-h-[420px]">
        {/* Error State */}
        {errorMsg && (
          <div className="mb-4 bg-red-950/20 border border-red-900/50 text-red-200 text-xs p-3.5 flex items-start space-x-2.5">
            <AlertCircle className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Initial Empty State */}
        {!rendering && !renderedItem && (
          <div className="flex-1 flex flex-col items-center justify-center text-center p-8 border border-dashed border-white/10 bg-black/40">
            <div className="bg-white/5 p-4 border border-white/10 mb-4 text-white/40">
              <Film className="h-10 w-10" />
            </div>
            <h4 className="font-black uppercase italic text-white tracking-tight mb-2">Cinematograph Player Ready</h4>
            <p className="text-xs text-white/60 max-w-sm leading-relaxed">
              Inject a visual prompt and frame starting seeds on the left. Press render to initialize the Google Veo synthesis pipelines.
            </p>
          </div>
        )}

        {/* Progressive Render / Loading State */}
        {rendering && (
          <div className="flex-1 flex flex-col items-center justify-center text-center p-8 bg-white/5 border border-white/10">
            <div className="relative mb-5 flex items-center justify-center">
              <div className="animate-spin absolute inline-flex h-16 w-16 rounded-full border-2 border-[#FF3E3E]/10 border-t-[#FF3E3E]"></div>
              <div className="bg-[#FF3E3E]/10 border border-[#FF3E3E]/60 h-10 w-10 flex items-center justify-center text-[#FF3E3E]">
                <RefreshCw className="h-4 w-4 animate-spin" />
              </div>
            </div>
            
            <h4 className="font-black uppercase italic tracking-tight text-white mb-2">Rendering Video Frames ({progress}%)</h4>
            <p className="text-xs text-white/60 max-w-sm leading-relaxed mb-4">
              Synthesizing temporal textures in mixed precision via ROCm acceleration onto VRAM cache pools.
            </p>

            <div className="w-56 bg-white/10 h-1.5 overflow-hidden">
              <div
                className="bg-[#FF3E3E] h-full transition-all duration-300"
                style={{ width: `${progress}%` }}
              ></div>
            </div>
            <span className="text-[10px] font-mono text-white/40 uppercase mt-3">Active precision compilation: {activePrecision}</span>
          </div>
        )}

        {/* Completed Video Player */}
        {renderedItem && (
          <div className="flex-1 flex flex-col items-center justify-center p-4 bg-black border border-white/10 overflow-hidden">
            <div className={`relative max-w-full overflow-hidden shadow-2xl flex items-center justify-center bg-black ${
              aspectRatio === '16:9' ? 'aspect-video w-full' :
              aspectRatio === '9:16' ? 'aspect-[9/16] h-[340px]' :
              'aspect-square w-[75%]'
            }`}>
              <video
                src={renderedItem.url}
                controls
                autoPlay
                loop
                playsInline
                className="w-full h-full object-cover select-none"
              />
              
              <div className="absolute top-3 left-3 bg-black text-emerald-400 text-[10px] font-mono font-bold px-2.5 py-1 border border-emerald-500/30 flex items-center space-x-1.5 z-10">
                <Zap className="h-3 w-3 fill-emerald-400 text-emerald-400" />
                <span>Radeon Veo Rendered ({renderedItem.gpuTimeMs}ms)</span>
              </div>
            </div>
          </div>
        )}

        {/* Player controls / export */}
        {renderedItem && (
          <div className="mt-5 flex items-center justify-between border-t border-white/10 pt-5 w-full">
            <div className="min-w-0 pr-4">
              <p className="text-xs text-white/80 font-bold truncate italic">"{renderedItem.prompt}"</p>
              <div className="flex items-center space-x-2 mt-1.5 text-[9px] font-mono text-white/40 uppercase tracking-wider">
                <span>Aspect: {renderedItem.aspectRatio}</span>
                <span>•</span>
                <span>Res: {renderedItem.resolution}</span>
                {selectedImageId && (
                  <>
                    <span>•</span>
                    <span className="text-[#FF3E3E] font-bold flex items-center space-x-0.5">
                      <ImageIcon className="h-2.5 w-2.5 mr-0.5" />
                      Image Seed Applied
                    </span>
                  </>
                )}
              </div>
            </div>
            <a
              href={renderedItem.url}
              download={`radeon_veo_render_${renderedItem.id}.mp4`}
              target="_blank"
              rel="noreferrer"
              className="bg-white/5 hover:bg-white text-white hover:text-black font-black uppercase tracking-wider px-4 py-2 border border-white/10 text-xs transition-all cursor-pointer italic"
            >
              <span className="flex items-center space-x-1.5">
                <Download className="h-4 w-4" />
                <span>Export Video</span>
              </span>
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

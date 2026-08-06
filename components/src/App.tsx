import React, { useState, useEffect } from 'react';
import { MediaItem, GpuMetricSnapshot } from './types';
import Dashboard from './components/Dashboard';
import ImageCanvas from './components/ImageCanvas';
import VideoComposer from './components/VideoComposer';
import AudioStudio from './components/AudioStudio';
import GpuProfiler, { GPU_PRESETS } from './components/GpuProfiler';
import DirectorChat from './components/DirectorChat';
import { motion, AnimatePresence } from 'motion/react';
import { LayoutGrid, Image, Film, Music, Cpu, Bot, ChevronRight, Zap, Menu, X, Monitor } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('dashboard');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [copilotOpen, setCopilotOpen] = useState(true);
  const [galleryItems, setGalleryItems] = useState<MediaItem[]>([
    {
      id: 'img_default_1',
      type: 'image',
      url: 'https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?q=80&w=600',
      prompt: 'AMD Radeon RX 7900 XTX core architecture, glowing crimson energy pathways, detailed circuit microprocessors, photorealistic 3D render',
      timestamp: '11:24 AM',
      aspectRatio: '16:9',
      style: 'Cinematic Drama',
      gpuAccelerated: true,
      gpuTimeMs: 2480
    },
    {
      id: 'mus_default_2',
      type: 'audio',
      url: 'https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3',
      prompt: 'Cinematic electronic synthwave arpeggio theme, high-velocity beats, neon red-glow undertones',
      timestamp: '11:35 AM',
      style: '[Verse 1]\nSynchronized in ROCm queues,\nRadeon colors, reds and blues...',
      gpuAccelerated: true,
      gpuTimeMs: 3120,
      duration: 30
    }
  ]);

  // GPU states
  const [activePresetId, setActivePresetId] = useState('rx-7900-xtx');
  const [activePrecision, setActivePrecision] = useState<'FP32' | 'FP16' | 'INT8'>('FP16');
  const [gpuMetrics, setGpuMetrics] = useState<GpuMetricSnapshot | null>(null);

  // States for prompt injections from director co-pilot
  const [injectedImagePrompt, setInjectedImagePrompt] = useState('');
  const [injectedVideoPrompt, setInjectedVideoPrompt] = useState('');
  const [injectedAudioPrompt, setInjectedAudioPrompt] = useState('');

  // Auto-fetch initial metrics
  useEffect(() => {
    const fetchInitialMetrics = async () => {
      try {
        const res = await fetch('/api/gpu-stats', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ presetId: activePresetId, precision: activePrecision })
        });
        if (res.ok) {
          const data = await res.json();
          setGpuMetrics(data);
        }
      } catch (err) {
        console.error('Failed to contact hardware telemetry API:', err);
      }
    };
    fetchInitialMetrics();
  }, [activePresetId, activePrecision]);

  const handleMediaGenerated = (newItem: MediaItem) => {
    setGalleryItems((prev) => [newItem, ...prev]);
  };

  const handleRemoveItem = (id: string) => {
    setGalleryItems((prev) => prev.filter((item) => item.id !== id));
  };

  // Callback from AI Director to instantly inject prompts and focus creative tab
  const handlePromptInject = (tab: 'image' | 'video' | 'audio', promptText: string) => {
    setActiveTab(tab);
    if (tab === 'image') {
      setInjectedImagePrompt(promptText);
    } else if (tab === 'video') {
      setInjectedVideoPrompt(promptText);
    } else {
      setInjectedAudioPrompt(promptText);
    }
  };

  return (
    <div className="min-h-screen bg-[#050505] text-[#F0F0F0] flex flex-col font-sans selection:bg-[#FF3E3E]/30 selection:text-white border-[12px] border-[#111]">
      
      {/* Upper Navigation Rail */}
      <header className="flex items-center justify-between px-6 py-5 border-b border-white/10 bg-[#050505] sticky top-0 z-40">
        <div className="flex items-center space-x-4">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 hover:bg-white/5 text-white/60 hover:text-white transition-colors md:hidden cursor-pointer"
          >
            <Menu className="h-5 w-5" />
          </button>
          
          <div className="flex items-baseline space-x-3">
            <h1 className="text-2xl md:text-3xl font-black tracking-tighter uppercase italic text-white flex items-center">
              Radeon<span className="text-[#FF3E3E] italic">.Aura</span>
            </h1>
            <span className="text-[9px] font-mono bg-white text-black px-1.5 py-0.5 font-bold">
              v1.2.0
            </span>
          </div>
        </div>

        {/* Global Connection Telemetry Bar */}
        <div className="flex items-center space-x-6">
          <div className="hidden sm:flex flex-col items-end">
            <span className="text-[9px] uppercase tracking-widest text-white/40 font-mono">ROCm Telemetry</span>
            <span className="text-xs font-bold text-[#FF3E3E] font-mono tracking-wide">AMD RADEON™ ACTIVE</span>
          </div>
          <button
            onClick={() => setCopilotOpen(!copilotOpen)}
            className={`px-4 py-2 border text-[11px] uppercase tracking-wider font-black italic transition-all duration-150 cursor-pointer ${
              copilotOpen
                ? 'bg-[#FF3E3E] border-transparent text-black'
                : 'bg-transparent border-white/20 hover:border-white text-white hover:bg-white/5'
            }`}
          >
            Director Co-Pilot
          </button>
        </div>
      </header>

      {/* Main Structural Layout Wrapper */}
      <div className="flex-1 flex relative">
        
        {/* Left Side Navigation Sidebar */}
        <aside
          className={`w-64 border-r border-white/10 bg-[#050505] flex flex-col justify-between absolute md:static inset-y-0 left-0 z-30 transform md:transform-none transition-transform duration-300 ${
            sidebarOpen ? 'translate-x-0' : '-translate-x-full'
          }`}
        >
          {/* Upper Nav nodes */}
          <div className="p-4 space-y-1.5">
            <span className="text-[9px] font-mono uppercase tracking-widest text-white/40 block pl-3 mb-3 italic">Workspace Navigation</span>
            
            <button
              onClick={() => { setActiveTab('dashboard'); if(window.innerWidth < 768) setSidebarOpen(false); }}
              className={`w-full flex items-center space-x-3 px-4 py-3 border text-[11px] font-black uppercase tracking-wider transition-all duration-150 cursor-pointer ${
                activeTab === 'dashboard'
                  ? 'bg-white text-black border-white'
                  : 'text-white/60 border-transparent hover:border-white/20 hover:text-white hover:bg-white/5'
              }`}
            >
              <LayoutGrid className="h-4 w-4" />
              <span>Studio Dashboard</span>
            </button>

            <button
              onClick={() => { setActiveTab('image'); if(window.innerWidth < 768) setSidebarOpen(false); }}
              className={`w-full flex items-center space-x-3 px-4 py-3 border text-[11px] font-black uppercase tracking-wider transition-all duration-150 cursor-pointer ${
                activeTab === 'image'
                  ? 'bg-white text-black border-white'
                  : 'text-white/60 border-transparent hover:border-white/20 hover:text-white hover:bg-white/5'
              }`}
            >
              <Image className="h-4 w-4" />
              <span>Image Synthesis</span>
            </button>

            <button
              onClick={() => { setActiveTab('video'); if(window.innerWidth < 768) setSidebarOpen(false); }}
              className={`w-full flex items-center space-x-3 px-4 py-3 border text-[11px] font-black uppercase tracking-wider transition-all duration-150 cursor-pointer ${
                activeTab === 'video'
                  ? 'bg-white text-black border-white'
                  : 'text-white/60 border-transparent hover:border-white/20 hover:text-white hover:bg-white/5'
              }`}
            >
              <Film className="h-4 w-4" />
              <span>Video Workstation</span>
            </button>

            <button
              onClick={() => { setActiveTab('audio'); if(window.innerWidth < 768) setSidebarOpen(false); }}
              className={`w-full flex items-center space-x-3 px-4 py-3 border text-[11px] font-black uppercase tracking-wider transition-all duration-150 cursor-pointer ${
                activeTab === 'audio'
                  ? 'bg-white text-black border-white'
                  : 'text-white/60 border-transparent hover:border-white/20 hover:text-white hover:bg-white/5'
              }`}
            >
              <Music className="h-4 w-4" />
              <span>Audio & Speech</span>
            </button>

            <button
              onClick={() => { setActiveTab('gpu'); if(window.innerWidth < 768) setSidebarOpen(false); }}
              className={`w-full flex items-center space-x-3 px-4 py-3 border text-[11px] font-black uppercase tracking-wider transition-all duration-150 cursor-pointer ${
                activeTab === 'gpu'
                  ? 'bg-white text-black border-white'
                  : 'text-white/60 border-transparent hover:border-white/20 hover:text-white hover:bg-white/5'
              }`}
            >
              <Cpu className="h-4 w-4" />
              <span>Radeon Boost Panel</span>
            </button>
          </div>

          {/* Lower Sidebar Hardware Monitor Node */}
          {gpuMetrics && (
            <div className="p-4 border-t border-white/10 bg-[#050505] space-y-4">
              <span className="text-[9px] font-mono uppercase tracking-widest text-white/40 block pl-1 italic">Hardware Engine</span>
              
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-white/60 font-sans font-bold uppercase tracking-wider">ROCm Memory</span>
                  <span className="font-mono text-white font-extrabold">{gpuMetrics.vramUsedGb} / {gpuMetrics.vramTotalGb} GB</span>
                </div>
                <div className="w-full bg-white/10 h-1.5 rounded-none overflow-hidden">
                  <div
                    className="bg-[#FF3E3E] h-full transition-all duration-500"
                    style={{ width: `${(gpuMetrics.vramUsedGb / gpuMetrics.vramTotalGb) * 100}%` }}
                  ></div>
                </div>
              </div>

              <div className="flex items-center justify-between text-[11px]">
                <span className="text-white/60 font-sans font-bold uppercase tracking-wider">Precision</span>
                <span className="font-mono bg-[#FF3E3E] text-black px-2 py-0.5 text-[10px] font-extrabold italic">
                  {activePrecision}
                </span>
              </div>
            </div>
          )}
        </aside>

        {/* Sidebar backdrop for mobile view */}
        {sidebarOpen && (
          <div
            onClick={() => setSidebarOpen(false)}
            className="fixed inset-0 bg-black/80 md:hidden z-20 cursor-pointer"
          ></div>
        )}

        {/* Center content window with layout animations */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8 scrollbar-thin scrollbar-thumb-neutral-850 scrollbar-track-transparent">
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, y: 15 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -15 }}
              transition={{ duration: 0.25, ease: 'easeOut' }}
              className="max-w-6xl mx-auto h-full"
            >
              {activeTab === 'dashboard' && (
                <Dashboard
                  galleryItems={galleryItems}
                  metrics={gpuMetrics}
                  onRemoveItem={handleRemoveItem}
                  onNavigate={setActiveTab}
                />
              )}

              {activeTab === 'image' && (
                <div key={`img_canvas_${injectedImagePrompt}`} className="h-full">
                  <ImageCanvas
                    onMediaGenerated={handleMediaGenerated}
                    activePrecision={activePrecision}
                  />
                </div>
              )}

              {activeTab === 'video' && (
                <div key={`vid_composer_${injectedVideoPrompt}`} className="h-full">
                  <VideoComposer
                    galleryItems={galleryItems}
                    onMediaGenerated={handleMediaGenerated}
                    activePrecision={activePrecision}
                  />
                </div>
              )}

              {activeTab === 'audio' && (
                <div key={`aud_studio_${injectedAudioPrompt}`} className="h-full">
                  <AudioStudio
                    galleryItems={galleryItems}
                    onMediaGenerated={handleMediaGenerated}
                    activePrecision={activePrecision}
                  />
                </div>
              )}

              {activeTab === 'gpu' && (
                <GpuProfiler
                  activePresetId={activePresetId}
                  setActivePresetId={setActivePresetId}
                  activePrecision={activePrecision}
                  setActivePrecision={setActivePrecision}
                  metrics={gpuMetrics}
                  setMetrics={setGpuMetrics}
                />
              )}
            </motion.div>
          </AnimatePresence>
        </main>

        {/* Right Collapsible AI Creative Director Chat Sidebar */}
        <AnimatePresence>
          {copilotOpen && (
            <motion.div
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 340, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: 'easeInOut' }}
              className="hidden lg:block border-l border-white/10 bg-[#050505] flex-shrink-0"
            >
              <div className="w-[340px] p-4 h-full flex flex-col">
                <DirectorChat
                  galleryItems={galleryItems}
                  onPromptInject={handlePromptInject}
                  activePrecision={activePrecision}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

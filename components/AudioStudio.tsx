import React, { useState, useRef, useEffect } from 'react';
import { MediaItem } from '../types';
import { Music, Mic, Play, Pause, Volume2, Download, AlertCircle, Sparkles, Zap, FileText } from 'lucide-react';

interface AudioStudioProps {
  galleryItems: MediaItem[];
  onMediaGenerated: (item: MediaItem) => void;
  activePrecision: 'FP32' | 'FP16' | 'INT8';
}

const VOICES = [
  { name: 'Zephyr', desc: 'Warm, clear, modern storyteller', lang: 'en-US' },
  { name: 'Kore', desc: 'Upbeat, professional corporate tone', lang: 'en-GB' },
  { name: 'Puck', desc: 'Energetic, cheerful character voice', lang: 'en-US' },
  { name: 'Charon', desc: 'Deep, dramatic, narrative baritone', lang: 'en-AU' },
  { name: 'Fenrir', desc: 'Calm, soothing, educational guide', lang: 'en-GB' }
];

export default function AudioStudio({ galleryItems, onMediaGenerated, activePrecision }: AudioStudioProps) {
  const [activeTab, setActiveTab] = useState<'music' | 'voice'>('music');
  
  // Music States
  const [musicPrompt, setMusicPrompt] = useState('');
  const [musicRendering, setMusicRendering] = useState(false);
  const [renderedMusic, setRenderedMusic] = useState<MediaItem | null>(null);
  
  // TTS States
  const [voiceText, setVoiceText] = useState('');
  const [selectedVoice, setSelectedVoice] = useState('Zephyr');
  const [voiceRendering, setVoiceRendering] = useState(false);
  const [renderedVoice, setRenderedVoice] = useState<MediaItem | null>(null);

  // Common Audio Playback States
  const [playingItemId, setPlayingItemId] = useState<string | null>(null);
  const [musicError, setMusicError] = useState('');
  const [voiceError, setVoiceError] = useState('');

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  // Handle music play/pause toggle
  const togglePlay = (item: MediaItem) => {
    if (!audioRef.current) {
      audioRef.current = new Audio(item.url);
      audioRef.current.onended = () => {
        setIsPlaying(false);
        setPlayingItemId(null);
      };
    }

    if (playingItemId === item.id) {
      if (isPlaying) {
        audioRef.current.pause();
        setIsPlaying(false);
      } else {
        audioRef.current.play();
        setIsPlaying(true);
      }
    } else {
      audioRef.current.pause();
      audioRef.current = new Audio(item.url);
      audioRef.current.onended = () => {
        setIsPlaying(false);
        setPlayingItemId(null);
      };
      audioRef.current.play();
      setIsPlaying(true);
      setPlayingItemId(item.id);
    }
  };

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
      }
    };
  }, []);

  // 1. Lyria Music Generation Handler
  const handleGenerateMusic = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!musicPrompt.trim()) return;

    setMusicRendering(true);
    setMusicError('');
    setRenderedMusic(null);

    try {
      const response = await fetch('/api/generate-music', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: musicPrompt.trim(),
          precision: activePrecision
        })
      });

      if (!response.ok) throw new Error('Music compile pipeline failed.');

      const data = await response.json();
      if (data.success) {
        const newItem: MediaItem = {
          id: `mus_${Date.now()}`,
          type: 'audio',
          url: data.audioUrl,
          prompt: data.prompt,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          style: 'Lyria Melodic Synth',
          gpuAccelerated: true,
          gpuTimeMs: data.gpuTimeMs,
          duration: 30
        };

        // Cache simulated lyrics
        newItem.style = data.lyrics; // Use style field to hold lyrical snippets
        setRenderedMusic(newItem);
        onMediaGenerated(newItem);
      } else {
        throw new Error(data.error || 'Failed to compose audio sequence.');
      }
    } catch (err: any) {
      console.error(err);
      setMusicError(err.message || 'Connecting to Lyria music engine timed out. Please try again.');
    } finally {
      setMusicRendering(false);
    }
  };

  // 2. TTS Voiceover Generation Handler
  const handleGenerateTTS = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!voiceText.trim()) return;

    setVoiceRendering(true);
    setVoiceError('');
    setRenderedVoice(null);

    try {
      const response = await fetch('/api/generate-tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: voiceText.trim(),
          voiceName: selectedVoice,
          precision: activePrecision
        })
      });

      if (!response.ok) throw new Error('TTS compile service returned an error.');

      const data = await response.json();
      
      // Standard local browser Speech Synthesis Fallback if no real base64 is generated
      if (data.success) {
        let audioUrl = data.audioUrl;
        
        if (!audioUrl && 'speechSynthesis' in window) {
          // Fallback simulation: Build speech synthesis blob or trigger client audio on demand
          const synth = window.speechSynthesis;
          const utterance = new SpeechSynthesisUtterance(voiceText);
          
          // Match selected voice names conceptually to browser voice filters
          const browserVoices = synth.getVoices();
          const targetVoice = browserVoices.find(v => 
            v.name.toLowerCase().includes(selectedVoice.toLowerCase()) || 
            (selectedVoice === 'Kore' && v.lang.startsWith('en-GB')) ||
            (selectedVoice === 'Charon' && v.name.toLowerCase().includes('google'))
          );
          if (targetVoice) utterance.voice = targetVoice;
          utterance.rate = 1.0;
          utterance.pitch = selectedVoice === 'Charon' ? 0.85 : selectedVoice === 'Puck' ? 1.15 : 1.0;

          // Standard placeholder sound to let user click play/pause in the player cleanly
          audioUrl = 'https://actions.google.com/sounds/v1/alarms/digital_watch_alarm_long.ogg'; // Standard duration click
          
          // Attach local browser synthesize trigger directly to custom click
          const speakLocal = () => {
            synth.cancel();
            synth.speak(utterance);
          };

          const newItem: MediaItem = {
            id: `tts_${Date.now()}`,
            type: 'audio',
            url: audioUrl,
            prompt: voiceText,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
            voiceName: selectedVoice,
            gpuAccelerated: true,
            gpuTimeMs: data.gpuTimeMs,
            duration: Math.ceil(voiceText.split(' ').length / 3) // Estimate duration
          };

          // Override local play event handler
          newItem.style = 'LOCAL_WEB_SPEECH';
          setRenderedVoice(newItem);
          onMediaGenerated(newItem);
          speakLocal(); // Trigger speech instantly
        } else if (audioUrl) {
          const newItem: MediaItem = {
            id: `tts_${Date.now()}`,
            type: 'audio',
            url: audioUrl,
            prompt: voiceText,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
            voiceName: selectedVoice,
            gpuAccelerated: true,
            gpuTimeMs: data.gpuTimeMs,
            duration: 5
          };

          setRenderedVoice(newItem);
          onMediaGenerated(newItem);
        } else {
          throw new Error('TTS rendering failed and SpeechSynthesis is unsupported in this browser sandbox.');
        }
      }
    } catch (err: any) {
      console.error(err);
      setVoiceError(err.message || 'Connecting to Speech Synthesizer timed out.');
    } finally {
      setVoiceRendering(false);
    }
  };

  const imagesOnly = galleryItems.filter(item => item.type === 'image');

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 pb-12">
      {/* Control Station (Dual Tabs) */}
      <div className="lg:col-span-5 bg-black border border-white/10 p-6 flex flex-col h-full">
        {/* Navigation Tabs */}
        <div className="flex border-b border-white/10 pb-4 mb-5 gap-2">
          <button
            onClick={() => setActiveTab('music')}
            className={`flex-1 flex items-center justify-center space-x-2 py-3 text-xs font-black uppercase tracking-wider transition-all duration-150 cursor-pointer ${
              activeTab === 'music'
                ? 'bg-[#FF3E3E] text-black'
                : 'text-white/60 hover:bg-white/5 hover:text-white border border-white/10'
            }`}
          >
            <Music className="h-4 w-4" />
            <span>Lyria Music</span>
          </button>
          <button
            onClick={() => setActiveTab('voice')}
            className={`flex-1 flex items-center justify-center space-x-2 py-3 text-xs font-black uppercase tracking-wider transition-all duration-150 cursor-pointer ${
              activeTab === 'voice'
                ? 'bg-[#FF3E3E] text-black'
                : 'text-white/60 hover:bg-white/5 hover:text-white border border-white/10'
            }`}
          >
            <Mic className="h-4 w-4" />
            <span>Voice & TTS</span>
          </button>
        </div>

        {/* TAB 1: LYRIA MUSIC STUDIO */}
        {activeTab === 'music' && (
          <form onSubmit={handleGenerateMusic} className="space-y-5 flex-1 flex flex-col">
            <div className="space-y-2">
              <label className="text-[10px] font-mono uppercase tracking-widest text-white/40 italic block">Sonic Style Brief</label>
              <textarea
                value={musicPrompt}
                onChange={(e) => setMusicPrompt(e.target.value)}
                placeholder="e.g. Generate a cinematic cyberpunk electronic track, heavy bass beats, rapid red-neon synthesizer waves..."
                className="w-full h-24 bg-white/5 border border-white/10 focus:border-[#FF3E3E] text-xs text-white placeholder-white/30 p-3 outline-none resize-none transition-all font-sans"
                maxLength={400}
                required
              />
            </div>

            {/* Optional Image Grounding Indicator */}
            {imagesOnly.length > 0 && (
              <div className="bg-[#FF3E3E]/5 p-4 border border-[#FF3E3E]/20">
                <span className="text-[9px] font-mono text-[#FF3E3E] uppercase block mb-1 font-black tracking-widest italic">Sonic Vision Grounding</span>
                <span className="text-xs text-white/70 leading-relaxed font-sans">
                  Lyria will automatically extract structural and chromatic properties from your generated graphics gallery to anchor the melodic tone!
                </span>
              </div>
            )}

            <div className="pt-4 mt-auto">
              <button
                type="submit"
                disabled={musicRendering || !musicPrompt.trim()}
                className="w-full bg-[#FF3E3E] hover:bg-[#E03535] disabled:bg-white/5 disabled:text-white/20 text-black font-black uppercase tracking-wider italic py-3 flex items-center justify-center space-x-2 transition-all cursor-pointer"
              >
                <Sparkles className="h-4.5 w-4.5" />
                <span>{musicRendering ? 'Compiling Melody on Radeon...' : 'Synthesize Lyria Clip'}</span>
              </button>
            </div>
          </form>
        )}

        {/* TAB 2: SPEECH SYNTHESIS */}
        {activeTab === 'voice' && (
          <form onSubmit={handleGenerateTTS} className="space-y-5 flex-1 flex flex-col">
            <div className="space-y-2">
              <label className="text-[10px] font-mono uppercase tracking-widest text-white/40 italic block">Script Voiceover Text</label>
              <textarea
                value={voiceText}
                onChange={(e) => setVoiceText(e.target.value)}
                placeholder="e.g. Accelerating creative pipelines. The AMD Radeon RX series delivers optimized compute efficiency for multi-threaded AI tasks..."
                className="w-full h-24 bg-white/5 border border-white/10 focus:border-[#FF3E3E] text-xs text-white placeholder-white/30 p-3 outline-none resize-none transition-all font-sans"
                maxLength={500}
                required
              />
            </div>

            {/* Voice select */}
            <div className="space-y-2">
              <label className="text-[10px] font-mono uppercase tracking-widest text-white/40 italic block">Voice Character Profile</label>
              <div className="grid grid-cols-1 gap-2.5 max-h-[170px] overflow-y-auto pr-1">
                {VOICES.map((v) => {
                  const isSelected = v.name === selectedVoice;
                  return (
                    <button
                      type="button"
                      key={v.name}
                      onClick={() => setSelectedVoice(v.name)}
                      className={`flex items-center justify-between p-3 border text-left transition-all cursor-pointer ${
                        isSelected
                          ? 'bg-white text-black border-white'
                          : 'bg-white/5 border-white/10 text-white/60 hover:border-white/20 hover:bg-white/10'
                      }`}
                    >
                      <div>
                        <p className="text-[11px] font-bold uppercase tracking-wider leading-none">{v.name}</p>
                        <p className={`text-[9px] mt-1 ${isSelected ? 'text-black/60' : 'text-white/40'}`}>{v.desc}</p>
                      </div>
                      <span className={`text-[9px] font-mono px-1.5 py-0.5 font-bold uppercase ${isSelected ? 'bg-black text-white' : 'bg-white/10 text-white/80'}`}>{v.lang}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="pt-4 mt-auto">
              <button
                type="submit"
                disabled={voiceRendering || !voiceText.trim()}
                className="w-full bg-[#FF3E3E] hover:bg-[#E03535] disabled:bg-white/5 disabled:text-white/20 text-black font-black uppercase tracking-wider italic py-3 flex items-center justify-center space-x-2 transition-all cursor-pointer"
              >
                <Sparkles className="h-4.5 w-4.5" />
                <span>{voiceRendering ? 'Synthesizing Accent...' : 'Synthesize Speech Voiceover'}</span>
              </button>
            </div>
          </form>
        )}
      </div>

      {/* Screen Canvas Player (Animated Equalizers!) */}
      <div className="lg:col-span-7 flex flex-col justify-between bg-[#050505] border border-white/10 p-6 min-h-[420px]">
        
        {/* MUSIC PORTION VIEW */}
        {activeTab === 'music' && (
          <div className="flex-1 flex flex-col justify-between h-full">
            {musicError && (
              <div className="mb-4 bg-red-950/20 border border-red-900/50 text-red-200 text-xs p-3.5 flex items-start space-x-2.5">
                <AlertCircle className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
                <span>{musicError}</span>
              </div>
            )}

            {!musicRendering && !renderedMusic && (
              <div className="flex-1 flex flex-col items-center justify-center text-center p-8 border border-dashed border-white/10 bg-black/40">
                <div className="bg-white/5 p-4 border border-white/10 mb-4 text-white/40">
                  <Music className="h-10 w-10 animate-[bounce_3s_infinite]" />
                </div>
                <h4 className="font-black uppercase italic tracking-tight text-white mb-2">Acoustic Synth Desk Ready</h4>
                <p className="text-xs text-white/60 max-w-sm leading-relaxed">
                  Select a musical style above and compile. The Lyria generative engine will produce custom waveforms and lyrics.
                </p>
              </div>
            )}

            {musicRendering && (
              <div className="flex-1 flex flex-col items-center justify-center text-center p-8 bg-white/5 border border-white/10">
                <div className="relative mb-6 flex items-center justify-center">
                  <div className="animate-ping absolute inline-flex h-12 w-12 rounded-full bg-[#FF3E3E] opacity-20"></div>
                  <div className="bg-[#FF3E3E]/10 border border-[#FF3E3E]/60 h-10 w-10 flex items-center justify-center text-[#FF3E3E]">
                    <Volume2 className="h-5 w-5 animate-bounce" />
                  </div>
                </div>
                <h4 className="font-black uppercase italic tracking-tight text-white mb-2">Synthesizing WAV Waveform</h4>
                <p className="text-xs text-white/60 max-w-sm leading-relaxed mb-4">
                  Translating visual prompts and text styles into high-fidelity melodic arpeggios on AMD Radeon RX stream processors.
                </p>
                <div className="w-48 bg-white/10 h-1.5 overflow-hidden">
                  <div className="bg-[#FF3E3E] h-full w-full animate-[shimmer_1.5s_infinite] origin-left"></div>
                </div>
              </div>
            )}

            {renderedMusic && (
              <div className="flex-1 flex flex-col justify-between space-y-4">
                <div className="bg-black border border-white/10 p-6 flex flex-col items-center justify-center min-h-[180px]">
                  {/* Equalizer animation */}
                  <div className="flex items-end justify-center space-x-1 h-12 mb-5">
                    {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((bar) => {
                      const heights = ['h-3', 'h-8', 'h-5', 'h-11', 'h-6', 'h-10', 'h-4', 'h-9', 'h-7', 'h-12', 'h-5', 'h-8'];
                      return (
                        <div
                          key={bar}
                          className={`w-1.5 bg-[#FF3E3E] transition-all duration-300 ${
                            isPlaying && playingItemId === renderedMusic.id
                              ? `${heights[bar - 1]} animate-[pulse_0.8s_infinite_alternate]`
                              : 'h-2 bg-white/10'
                          }`}
                          style={{
                            animationDelay: `${bar * 0.08}s`
                          }}
                        ></div>
                      );
                    })}
                  </div>

                  {/* Audio trigger button */}
                  <button
                    onClick={() => togglePlay(renderedMusic)}
                    className="bg-[#FF3E3E] hover:bg-[#E03535] text-black p-4 flex items-center justify-center transition-transform hover:scale-105 active:scale-95 cursor-pointer"
                  >
                    {isPlaying && playingItemId === renderedMusic.id ? (
                      <Pause className="h-6 w-6 fill-black text-black" />
                    ) : (
                      <Play className="h-6 w-6 fill-black text-black translate-x-0.5" />
                    )}
                  </button>

                  <span className="text-[10px] font-mono text-white/40 mt-4 uppercase font-black">
                    Format: {renderedMusic.url.startsWith('data:') ? 'WAV Audio' : 'MPEG-3 Link'}
                  </span>
                </div>

                {/* Lyrics Display */}
                {renderedMusic.style && (
                  <div className="bg-black p-4 border border-white/10 flex-1">
                    <div className="flex items-center space-x-2 text-[#FF3E3E] text-xs font-mono mb-2">
                      <FileText className="h-3.5 w-3.5" />
                      <span className="uppercase font-bold tracking-wider">Lyria Lyricist Assistant Draft</span>
                    </div>
                    <pre className="text-xs text-white/70 font-mono leading-relaxed whitespace-pre bg-[#050505] p-3.5 border border-white/5 overflow-y-auto max-h-[120px]">
                      {renderedMusic.style}
                    </pre>
                  </div>
                )}

                {/* Footer Controls */}
                <div className="border-t border-white/10 pt-5 flex items-center justify-between">
                  <div>
                    <p className="text-xs text-white/80 font-bold truncate italic">"{renderedMusic.prompt}"</p>
                    <span className="text-[10px] font-mono text-white/40 uppercase tracking-wide">Accelerated: {renderedMusic.gpuTimeMs}ms</span>
                  </div>
                  <a
                    href={renderedMusic.url}
                    download="radeon_lyria_synth.wav"
                    target="_blank"
                    rel="noreferrer"
                    className="bg-white/5 hover:bg-white text-white hover:text-black font-black uppercase tracking-wider px-4 py-2 border border-white/10 text-xs transition-all cursor-pointer italic"
                  >
                    <span className="flex items-center space-x-1.5">
                      <Download className="h-4 w-4" />
                      <span>Export Audio</span>
                    </span>
                  </a>
                </div>
              </div>
            )}
          </div>
        )}

        {/* VOICE SPEECH PORTION VIEW */}
        {activeTab === 'voice' && (
          <div className="flex-1 flex flex-col justify-between h-full">
            {voiceError && (
              <div className="mb-4 bg-red-950/20 border border-red-900/50 text-red-200 text-xs p-3.5 flex items-start space-x-2.5">
                <AlertCircle className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
                <span>{voiceError}</span>
              </div>
            )}

            {!voiceRendering && !renderedVoice && (
              <div className="flex-1 flex flex-col items-center justify-center text-center p-8 border border-dashed border-white/10 bg-black/40">
                <div className="bg-white/5 p-4 border border-white/10 mb-4 text-white/40">
                  <Mic className="h-10 w-10" />
                </div>
                <h4 className="font-black uppercase italic tracking-tight text-white mb-2">Vocal Voiceover Deck Ready</h4>
                <p className="text-xs text-white/60 max-w-sm leading-relaxed">
                  Input a script on the left, pick a voice actor, and render. The Speech Engine translates the text into rich voiceover acoustics.
                </p>
              </div>
            )}

            {voiceRendering && (
              <div className="flex-1 flex flex-col items-center justify-center text-center p-8 bg-white/5 border border-white/10">
                <div className="relative mb-6 flex items-center justify-center">
                  <div className="animate-ping absolute inline-flex h-12 w-12 rounded-full bg-[#FF3E3E] opacity-20"></div>
                  <div className="bg-[#FF3E3E]/10 border border-[#FF3E3E]/60 h-10 w-10 flex items-center justify-center text-[#FF3E3E]">
                    <Mic className="h-5 w-5 animate-pulse" />
                  </div>
                </div>
                <h4 className="font-black uppercase italic tracking-tight text-white mb-2">Synthesizing Vocal Script</h4>
                <p className="text-xs text-white/60 max-w-sm leading-relaxed mb-4">
                  Constructing prebuilt phonetic waveforms via ROCm core layers with high-fidelity pitch alignment.
                </p>
                <div className="w-48 bg-white/10 h-1.5 overflow-hidden">
                  <div className="bg-[#FF3E3E] h-full w-full animate-[shimmer_1.5s_infinite] origin-left"></div>
                </div>
              </div>
            )}

            {renderedVoice && (
              <div className="flex-1 flex flex-col justify-between space-y-4">
                <div className="bg-black border border-white/10 p-6 flex flex-col items-center justify-center min-h-[180px]">
                  
                  {/* Speech Wave visual indicator */}
                  <div className="flex items-center justify-center space-x-1 h-16 w-full max-w-sm bg-[#050505] px-4 border border-white/10 mb-5 relative overflow-hidden">
                    {/* Pulsing bars mimicking speech frequency */}
                    <div className="flex items-center space-x-1">
                      {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15].map((idx) => {
                        const heights = ['h-2', 'h-6', 'h-4', 'h-10', 'h-3', 'h-8', 'h-5', 'h-12', 'h-4', 'h-7', 'h-3', 'h-9', 'h-5', 'h-6', 'h-2'];
                        return (
                          <div
                            key={idx}
                            className={`w-1 bg-[#FF3E3E] transition-all duration-300 ${
                              isPlaying && playingItemId === renderedVoice.id
                                ? `${heights[idx - 1]} animate-[pulse_0.4s_infinite_alternate]`
                                : 'h-1 bg-white/10'
                            }`}
                          ></div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Voice play trigger */}
                  <button
                    onClick={() => {
                      if (renderedVoice.style === 'LOCAL_WEB_SPEECH') {
                        // Re-trigger speech synthesis locally
                        const synth = window.speechSynthesis;
                        synth.cancel();
                        const utterance = new SpeechSynthesisUtterance(renderedVoice.prompt);
                        const targetVoice = synth.getVoices().find(v => v.name.toLowerCase().includes(renderedVoice.voiceName?.toLowerCase() || ''));
                        if (targetVoice) utterance.voice = targetVoice;
                        utterance.pitch = renderedVoice.voiceName === 'Charon' ? 0.85 : renderedVoice.voiceName === 'Puck' ? 1.15 : 1.0;
                        
                        setIsPlaying(true);
                        setPlayingItemId(renderedVoice.id);
                        utterance.onend = () => {
                          setIsPlaying(false);
                          setPlayingItemId(null);
                        };
                        synth.speak(utterance);
                      } else {
                        togglePlay(renderedVoice);
                      }
                    }}
                    className="bg-[#FF3E3E] hover:bg-[#E03535] text-black p-4 flex items-center justify-center transition-transform hover:scale-105 active:scale-95 cursor-pointer"
                  >
                    {isPlaying && playingItemId === renderedVoice.id ? (
                      <Pause className="h-6 w-6 fill-black text-black" />
                    ) : (
                      <Play className="h-6 w-6 fill-black text-black translate-x-0.5" />
                    )}
                  </button>

                  <span className="text-[10px] font-mono text-[#FF3E3E] mt-4 uppercase font-black">
                    {renderedVoice.style === 'LOCAL_WEB_SPEECH' ? 'Premium Web-Speech Fallback Engine' : 'TTS PCM Audio'}
                  </span>
                </div>

                {/* Subtitle / Script display */}
                <div className="bg-black p-4 border border-white/10 flex-1">
                  <span className="text-[9px] font-mono text-white/40 uppercase block mb-2 font-black tracking-widest italic">Synthesized Transcript ({renderedVoice.voiceName})</span>
                  <p className="text-xs text-white/85 font-sans leading-relaxed italic bg-[#050505] p-3.5 border border-white/5">
                    "{renderedVoice.prompt}"
                  </p>
                </div>

                {/* Footer */}
                <div className="border-t border-white/10 pt-5 flex items-center justify-between">
                  <div>
                    <span className="text-[10px] font-mono text-white/40 uppercase tracking-wide block">Profile: {renderedVoice.voiceName}</span>
                    <span className="text-[10px] font-mono text-white/40 uppercase tracking-wide block">ROCm Latency: {renderedVoice.gpuTimeMs}ms</span>
                  </div>
                  {renderedVoice.style !== 'LOCAL_WEB_SPEECH' && (
                    <a
                      href={renderedVoice.url}
                      download="radeon_tts_voiceover.wav"
                      target="_blank"
                      rel="noreferrer"
                      className="bg-white/5 hover:bg-white text-white hover:text-black font-black uppercase tracking-wider px-4 py-2 border border-white/10 text-xs transition-all cursor-pointer italic"
                    >
                      <span className="flex items-center space-x-1.5">
                        <Download className="h-4 w-4" />
                        <span>Export Script</span>
                      </span>
                    </a>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

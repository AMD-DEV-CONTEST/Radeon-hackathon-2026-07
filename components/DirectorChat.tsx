import React, { useState, useRef, useEffect } from 'react';
import { ChatMessage, MediaItem } from '../types';
import { MessageSquare, Send, Bot, User, Sparkles, Zap, ArrowRight, CornerDownLeft } from 'lucide-react';

interface DirectorChatProps {
  galleryItems: MediaItem[];
  onPromptInject: (tab: 'image' | 'video' | 'audio', prompt: string) => void;
  activePrecision: 'FP32' | 'FP16' | 'INT8';
}

export default function DirectorChat({ galleryItems, onPromptInject, activePrecision }: DirectorChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'init',
      role: 'model',
      text: "Greetings, Creator! I am your resident AI Creative Director, Aura. Running on AMD Radeon GPUs, we can rapidly construct high-resolution textures, orchestral scores, and cinematic video elements.\n\nTell me about your project brief, or ask me to draft a script, compile an Image-to-Video storyboard, or refine your visual prompt!",
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      suggestions: [
        'Draft a script for a high-performance GPU launch video',
        'Compose a cyberpunk laboratory prompt with crimson lighting',
        'Suggest an electronic synth music style for an energetic presentation'
      ]
    }
  ]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(false);
  const chatBottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleSend = async (e?: React.FormEvent, overrideText?: string) => {
    if (e) e.preventDefault();
    const textToSend = overrideText || inputText;
    if (!textToSend.trim() || loading) return;

    const userMsg: ChatMessage = {
      id: `usr_${Date.now()}`,
      role: 'user',
      text: textToSend.trim(),
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputText('');
    setLoading(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [...messages, userMsg].map((m) => ({
            role: m.role,
            text: m.text
          })),
          precision: activePrecision
        })
      });

      if (!response.ok) throw new Error('Director was disconnected.');

      const data = await response.json();
      
      const directorMsg: ChatMessage = {
        id: `dir_${Date.now()}`,
        role: 'model',
        text: data.text,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        suggestions: data.suggestions || []
      };

      setMessages((prev) => [...prev, directorMsg]);
    } catch (err) {
      console.error(err);
      const errorMsg: ChatMessage = {
        id: `err_${Date.now()}`,
        role: 'model',
        text: "My communications seem slightly delayed. Let's try compiling that visual brief again, or toggle the Radeon execution precision to FP16 mixed mode.",
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  // Helper: Detect type of action pill and route to parent
  const handlePillClick = (pill: string) => {
    const lower = pill.toLowerCase();
    if (lower.includes('video') || lower.includes('clip') || lower.includes('render')) {
      onPromptInject('video', pill.replace(/^(synthesize|generate|create|render)\s+/gi, ''));
    } else if (lower.includes('music') || lower.includes('lyria') || lower.includes('synth') || lower.includes('song')) {
      onPromptInject('audio', pill.replace(/^(synthesize|generate|create|render)\s+/gi, ''));
    } else {
      onPromptInject('image', pill.replace(/^(synthesize|generate|create|render)\s+/gi, ''));
    }
  };

  return (
    <div className="flex flex-col bg-black border border-white/10 h-full">
      <div className="p-4 border-b border-white/10 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <Bot className="h-5 w-5 text-[#FF3E3E] animate-pulse" />
          <div>
            <h3 className="font-black text-xs text-white uppercase tracking-wider italic font-sans">Creative Director</h3>
            <p className="text-[9px] text-[#FF3E3E] font-mono uppercase font-bold tracking-widest">Aura Assistant v3.1</p>
          </div>
        </div>
        <span className="text-[9px] bg-white text-black px-2 py-0.5 font-bold font-mono uppercase">
          Prec: {activePrecision}
        </span>
      </div>

      {/* Message list area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin scrollbar-thumb-neutral-850 scrollbar-track-transparent">
        {messages.map((m) => {
          const isDirector = m.role === 'model';
          return (
            <div key={m.id} className={`flex flex-col ${isDirector ? 'items-start' : 'items-end'}`}>
              <div className={`flex items-start space-x-2.5 max-w-[85%] ${isDirector ? '' : 'flex-row-reverse space-x-reverse'}`}>
                <div className={`h-7 w-7 rounded-none flex items-center justify-center flex-shrink-0 border ${
                  isDirector ? 'bg-white/5 border-white/10 text-[#FF3E3E]' : 'bg-[#FF3E3E]/10 border-[#FF3E3E]/30 text-[#FF3E3E]'
                }`}>
                  {isDirector ? <Bot className="h-4 w-4" /> : <User className="h-4 w-4" />}
                </div>

                <div className={`p-3 text-xs leading-relaxed font-sans ${
                  isDirector ? 'bg-white/5 text-white/90 border border-white/10' : 'bg-[#FF3E3E] text-black font-bold'
                }`}>
                  <p className="whitespace-pre-line">{m.text}</p>
                  <span className={`text-[9px] block text-right mt-1.5 font-mono ${isDirector ? 'text-white/30' : 'text-black/60'}`}>
                    {m.timestamp}
                  </span>
                </div>
              </div>

              {/* Render suggestions inside model chat bubble */}
              {isDirector && m.suggestions && m.suggestions.length > 0 && (
                <div className="ml-9 mt-3 space-y-1.5 max-w-[80%]">
                  <span className="text-[9px] text-white/40 font-black font-mono uppercase tracking-widest italic block">Aura Quick Actions:</span>
                  <div className="flex flex-col space-y-1">
                    {m.suggestions.map((s, idx) => (
                      <button
                        key={idx}
                        onClick={() => handlePillClick(s)}
                        className="text-left text-xs bg-white/5 hover:bg-white text-white/80 hover:text-black font-sans font-bold uppercase tracking-wide p-2.5 border border-white/10 flex items-center justify-between transition-all group cursor-pointer"
                      >
                        <span className="truncate pr-3">{s}</span>
                        <ArrowRight className="h-3 w-3 text-white/40 group-hover:text-black flex-shrink-0 transform translate-x-0 group-hover:translate-x-1 transition-transform" />
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {loading && (
          <div className="flex items-start space-x-2.5">
            <div className="h-7 w-7 rounded-none bg-white/5 border border-white/10 text-[#FF3E3E] flex items-center justify-center animate-spin">
              <Bot className="h-4 w-4" />
            </div>
            <div className="bg-white/5 border border-white/10 p-3.5 flex items-center space-x-2">
              <span className="w-1.5 h-1.5 bg-[#FF3E3E] rounded-none animate-bounce"></span>
              <span className="w-1.5 h-1.5 bg-[#FF3E3E] rounded-none animate-bounce" style={{ animationDelay: '0.1s' }}></span>
              <span className="w-1.5 h-1.5 bg-[#FF3E3E] rounded-none animate-bounce" style={{ animationDelay: '0.2s' }}></span>
            </div>
          </div>
        )}
        <div ref={chatBottomRef}></div>
      </div>

      {/* Chat footer input bar */}
      <form onSubmit={(e) => handleSend(e)} className="p-3 border-t border-white/10 flex items-center space-x-2 bg-black">
        <input
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          placeholder="Refine visual prompts or draft scripts..."
          className="flex-1 bg-white/5 border border-white/10 focus:border-[#FF3E3E] text-xs text-white placeholder-white/35 py-2.5 px-3 outline-none transition-all font-sans"
          maxLength={300}
        />
        <button
          type="submit"
          disabled={loading || !inputText.trim()}
          className="bg-[#FF3E3E] hover:bg-[#E03535] disabled:bg-white/5 disabled:text-white/20 text-black font-bold px-3 py-2.5 transition-all flex items-center justify-center cursor-pointer flex-shrink-0"
        >
          <Send className="h-4 w-4" />
        </button>
      </form>
    </div>
  );
}

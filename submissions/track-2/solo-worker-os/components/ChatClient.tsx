'use client';

import { useEffect, useRef, useState, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import ChatMessage, { type ToolChip } from './ChatMessage';
import { useLang } from './LanguageProvider';

export interface UIMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  tools?: ToolChip[];
  timestamp: number;
  /** FunctionRouter result — which subagent handled this turn */
  route?: {
    subagent: string;
    confidence: number;
    routedBy: string;
    reason: string;
  };
}

// ─── Web Speech API types (minimal) ────────────────────────────────────────────
type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
};

interface Props { initialMessages: UIMessage[] }

const SUGGESTED_PROMPTS_EN = [
  { icon: 'user', text: "I have a new client — let me give you the details" },
  { icon: 'clock', text: "Which projects are overdue or due soon?" },
  { icon: 'doc', text: "Generate a contract for my most recent project" },
  { icon: 'chat', text: "Write a payment reminder for an unpaid invoice" },
];

// ─── Linear-style SVG icons for suggested prompts ────────────────────────────
function SuggestedIcon({ name }: { name: string }) {
  const icons: Record<string, JSX.Element> = {
    user: (
      <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
        <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
      </svg>
    ),
    clock: (
      <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
      </svg>
    ),
    doc: (
      <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
      </svg>
    ),
    chat: (
      <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
        <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-5l-4 3v-3Z" />
      </svg>
    ),
  };
  return icons[name] ?? null;
}

const STORAGE_KEY = 'solo_chat_history';

function loadHistory(): UIMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    return [];
  } catch { return []; }
}

function saveHistory(msgs: UIMessage[]) {
  try {
    // Only save if there are messages (don't overwrite with empty)
    if (msgs.length > 0) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(msgs));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch { /* quota exceeded or unavailable */ }
}

function ChatClientInner({ initialMessages }: Props) {
  const { t, lang } = useLang();
  const suggestedPrompts = t.chat.suggested ?? SUGGESTED_PROMPTS_EN;
  const searchParams = useSearchParams();
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const [restored, setRestored] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const conversationIdRef = useRef<string | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const messagesRef = useRef<UIMessage[]>([]);
  const lastMsg = messages[messages.length - 1];

  // Keep messagesRef in sync so cleanup can flush the latest state
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // Load chat history from localStorage on first mount
  useEffect(() => {
    const saved = loadHistory();
    if (saved.length > 0) {
      setMessages(saved);
    }
    setRestored(true);
  }, []);

  // Save to localStorage whenever messages change (debounced to avoid
  // excessive serialization during streaming delta updates)
  useEffect(() => {
    if (!restored) return;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => saveHistory(messages), 500);
  }, [messages, restored]);

  // Cleanup on unmount: abort SSE stream, stop voice recognition, flush save
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      recognitionRef.current?.stop();
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
        // Flush pending save synchronously using latest messages via ref
        saveHistory(messagesRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const prefill = searchParams.get('prefill');
    const isDemo = searchParams.get('demo') === 'true';
    if (isDemo) setDemoMode(true);
    if (prefill) {
      let decoded: string;
      try { decoded = decodeURIComponent(prefill); } catch { decoded = prefill; }
      setInput(decoded);
      // Auto-send when coming from /demo (demo=true param)
      if (isDemo) {
        // Clear the prefill from URL to prevent re-trigger on refresh
        const params = new URLSearchParams(window.location.search);
        params.delete('demo');
        params.delete('prefill');
        const qs = params.toString();
        const newUrl = window.location.pathname + (qs ? `?${qs}` : '');
        window.history.replaceState({}, '', newUrl);
        // Use setTimeout to ensure input state is set before send
        setTimeout(() => void send(decoded), 100);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px';
    }
  }, [input]);

  function updateMessage(id: string, updater: (m: UIMessage) => UIMessage) {
    setMessages((prev) => prev.map((m) => (m.id === id ? updater(m) : m)));
  }

  function stopStreaming() {
    abortRef.current?.abort();
  }

  function clearConversation() {
    if (streaming) return;
    setMessages([]);
    conversationIdRef.current = null;
    try { localStorage.removeItem(STORAGE_KEY); } catch { /* */ }
  }

  // ── Voice input via Web Speech API ──────────────────────────────────────────
  function toggleVoice() {
    if (isRecording) {
      recognitionRef.current?.stop();
      setIsRecording(false);
      return;
    }

    // Get SpeechRecognition constructor (cross-browser)
    const SR = (window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike }).SpeechRecognition
      ?? (window as unknown as { webkitSpeechRecognition?: new () => SpeechRecognitionLike }).webkitSpeechRecognition;
    if (!SR) {
      // Fallback: browsers without Web Speech API
      alert(lang === 'zh' ? '当前浏览器不支持语音输入，请使用 Chrome 或 Edge。' : 'Voice input not supported. Please use Chrome or Edge.');
      return;
    }

    const recognition = new SR();
    recognition.lang = 'zh-CN';
    recognition.continuous = true;
    recognition.interimResults = true;

    let finalTranscript = '';
    const baseText = input ? input + ' ' : '';

    recognition.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const transcript = e.results[i][0].transcript;
        if (e.results[i].isFinal) {
          finalTranscript += transcript;
        } else {
          interim += transcript;
        }
      }
      setInput(baseText + finalTranscript + interim);
    };

    recognition.onend = () => {
      setIsRecording(false);
    };

    recognition.onerror = () => {
      setIsRecording(false);
    };

    recognitionRef.current = recognition;
    recognition.start();
    setIsRecording(true);
  }

  async function send(overrideText?: string) {
    const text = (overrideText ?? input).trim();
    if (!text || streaming) return;

    const userMsg: UIMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      tools: [],
      timestamp: Date.now(),
    };
    const assistantId = crypto.randomUUID();
    const history = [...messages, userMsg];

    setMessages([
      ...history,
      { id: assistantId, role: 'assistant', content: '', tools: [], timestamp: Date.now() },
    ]);
    setInput('');
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: history.map((m) => ({ role: m.role, content: m.content })),
          ...(conversationIdRef.current && {
            conversation_id: conversationIdRef.current,
            load_history: true,
          }),
        }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        const errText = await res.text().catch(() => 'Request failed');
        updateMessage(assistantId, (m) => ({ ...m, content: `Error: ${errText}` }));
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split('\n\n');
        buffer = chunks.pop() ?? '';
        for (const chunk of chunks) {
          const line = chunk.trim();
          if (!line.startsWith('data: ')) continue;
          let data: { type: string; delta?: string; name?: string; summary?: string; message?: string; attempt?: number };
          try { data = JSON.parse(line.slice(6)); } catch { continue; }
          if (data.type === 'text' && data.delta) {
            updateMessage(assistantId, (m) => ({ ...m, content: m.content + data.delta }));
          } else if (data.type === 'tool' && data.name) {
            updateMessage(assistantId, (m) => ({
              ...m,
              tools: [...(m.tools ?? []), { name: data.name!, summary: data.summary ?? '' }],
            }));
            // Broadcast data-changed event for dashboard real-time updates
            const dataModifyingTools = ['create_project', 'update_project_status', 'record_payment', 'generate_invoice'];
            if (dataModifyingTools.includes(data.name!)) {
              window.dispatchEvent(new CustomEvent('solo:data-changed'));
            }
          } else if (data.type === 'conversation') {
            // Track conversation ID for multi-turn persistence
            const convData = data as { type: string; conversation_id?: string };
            if (convData.conversation_id) {
              conversationIdRef.current = convData.conversation_id;
            }
          } else if (data.type === 'route') {
            // Capture FunctionRouter result to display as a badge on this message
            const routeData = data as { type: string; route?: { subagent: string; confidence: number; routedBy: string; reason: string } };
            if (routeData.route) {
              updateMessage(assistantId, (m) => ({ ...m, route: routeData.route }));
            }
          } else if (data.type === 'retry') {
            // Show retry indicator on the message
            updateMessage(assistantId, (m) => ({
              ...m,
              content: m.content + `\n\n*Retrying (attempt ${data.attempt ?? 1})...*\n\n`,
            }));
          } else if (data.type === 'error') {
            updateMessage(assistantId, (m) => ({
              ...m,
              content: m.content + `\n\n**[Error]** ${data.message ?? 'Unknown error'}`,
            }));
          }
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        updateMessage(assistantId, (m) => ({
          ...m,
          content: m.content || t.chat.stoppedGen,
        }));
      } else {
        const msg = err instanceof Error ? err.message : String(err);
        updateMessage(assistantId, (m) => ({ ...m, content: m.content + `\n\n**[Error]** ${msg}` }));
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  const charCount = input.length;
  const isLastStreaming = streaming && lastMsg?.role === 'assistant';
  const userCount = messages.filter((m) => m.role === 'user').length;

  return (
    <div className="flex h-full flex-col gap-3">
      {/* Conversation bar */}
      {messages.length > 0 && (
        <div className="flex items-center justify-between rounded-xl border border-gray-200 dark:border-white/[0.05] bg-gray-50 dark:bg-white/[0.02] px-3.5 py-2">
          <div className="flex items-center gap-2">
            {isLastStreaming && (
              <span className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500/80 dark:bg-amber-400/80" />
                <span className="text-[12px] text-amber-600/70 dark:text-amber-300/70 font-medium">{t.chat.working}</span>
              </span>
            )}
            {!isLastStreaming && (
              <span className="text-[12px] text-gray-400 dark:text-white/25 font-mono">
                {userCount} {userCount === 1 ? t.chat.message : t.chat.messages}
              </span>
            )}
          </div>
          <button
            onClick={clearConversation}
            disabled={streaming}
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[12px] text-gray-400 dark:text-white/30 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.04] hover:text-gray-600 dark:hover:text-white/60 disabled:cursor-not-allowed disabled:opacity-30"
          >
            <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clipRule="evenodd" />
            </svg>
            {t.chat.clear}
          </button>
        </div>
      )}

      {/* Messages area */}
      <div ref={scrollRef} className="chat-scroll flex-1 space-y-5 overflow-y-auto rounded-2xl glass p-5 sm:p-6">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-6 text-center">
            <div>
              <p className="text-[15px] font-semibold text-gray-700 dark:text-white/70">{t.chat.startConversation}</p>
              <p className="mt-1.5 max-w-xs text-[12px] leading-relaxed text-gray-400 dark:text-white/30">{t.chat.tryExample}</p>
            </div>

            {/* Suggested prompts */}
            <div className="grid w-full max-w-lg grid-cols-1 gap-2 sm:grid-cols-2">
              {suggestedPrompts.map((p, i) => (
                <button
                  key={p.text}
                  type="button"
                  onClick={() => void send(p.text)}
                  className={`card-interactive group rounded-xl px-4 py-3 text-left transition-all duration-200 stagger-${i + 1} animate-fade-up`}
                >
                  <span className="mb-1 block text-gray-400 dark:text-white/30"><SuggestedIcon name={p.icon} /></span>
                  <span className="block text-[12px] font-medium leading-snug text-gray-500 dark:text-white/50 group-hover:text-gray-700 dark:group-hover:text-white/75">
                    {p.text}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((m, idx) => {
            // Find the most recent user message before this assistant message
            let prevUserMessage: string | undefined;
            if (m.role === 'assistant') {
              for (let j = idx - 1; j >= 0; j--) {
                if (messages[j].role === 'user') {
                  prevUserMessage = messages[j].content;
                  break;
                }
              }
            }
            return (
              <ChatMessage
                key={m.id}
                role={m.role}
                content={m.content}
                tools={m.tools}
                timestamp={m.timestamp}
                route={m.route}
                userMessage={prevUserMessage}
                demoMode={demoMode}
                lang={lang}
                isStreaming={isLastStreaming && m.id === lastMsg?.id}
              />
            );
          })
        )}
      </div>

      {/* Input area */}
      <div className="glass focus-within:border-amber-500/20 dark:focus-within:border-amber-400/20 rounded-2xl border border-gray-200 dark:border-white/[0.06] transition-colors duration-200">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder={t.chat.placeholder}
          className="max-h-48 w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-[14px] leading-relaxed text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 focus:outline-none"
        />
        <div className="flex items-center justify-between px-3 pb-3 pt-1.5">
          <span className="select-none text-[11px] text-gray-300 dark:text-white/20">
            {charCount > 300 ? (
              <span className={charCount > 900 ? 'text-red-500 dark:text-red-400' : 'text-gray-400 dark:text-white/35'}>
                {charCount} {t.chat.message}
              </span>
            ) : (
              <span className="hidden sm:inline">{t.chat.newLine}</span>
            )}
          </span>
          <div className="flex items-center gap-2">
            {streaming && (
              <button
                onClick={stopStreaming}
                type="button"
                className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-gray-300 dark:border-white/10 bg-gray-100 dark:bg-white/[0.04] px-3 text-[12px] font-semibold text-gray-600 dark:text-white/55 transition-colors duration-200 hover:bg-gray-200 dark:hover:bg-white/[0.08] hover:text-gray-800 dark:hover:text-white/80"
              >
                <svg className="h-3 w-3" viewBox="0 0 16 16" fill="currentColor">
                  <rect x="3" y="3" width="10" height="10" rx="1.5" />
                </svg>
                {t.chat.stop}
              </button>
            )}
            {/* Voice input button */}
            <button
              type="button"
              onClick={toggleVoice}
              title={lang === 'zh' ? '语音输入' : 'Voice input'}
              className={`inline-flex h-9 w-9 items-center justify-center rounded-xl border transition-colors duration-200 ${
                isRecording
                  ? 'border-red-500/40 bg-red-500/15 text-red-500 dark:border-red-400/40 dark:bg-red-400/15 dark:text-red-400 animate-pulse-soft'
                  : 'border-gray-300 dark:border-white/10 bg-gray-100 dark:bg-white/[0.04] text-gray-400 dark:text-white/40 hover:bg-gray-200 dark:hover:bg-white/[0.08] hover:text-gray-700 dark:hover:text-white/70'
              }`}
            >
              {isRecording ? (
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
              ) : (
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                  <path d="M19 10a1 1 0 1 0-2 0 5 5 0 0 1-10 0 1 1 0 1 0-2 0 7 7 0 0 0 6 6.93V20H8a1 1 0 1 0 0 2h8a1 1 0 1 0 0-2h-3v-3.07A7 7 0 0 0 19 10Z" />
                </svg>
              )}
            </button>
            <button
              type="button"
              onClick={() => void send()}
              disabled={streaming || !input.trim()}
              className="inline-flex h-9 items-center gap-2 rounded-xl bg-amber-500 dark:bg-amber-400 px-4 text-[13px] font-bold text-black transition-all duration-200 hover:bg-amber-400 dark:hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-amber-500 dark:disabled:hover:bg-amber-400"
            >
              {streaming ? (
                <>
                  <span className="h-3 w-3 rounded-full bg-black/60" />
                  {t.chat.working}
                </>
              ) : (
                <>
                  {t.chat.send}
                  <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                    <path d="M3.105 2.288a.75.75 0 0 0-.826.95l1.903 6.115a.75.75 0 0 0 .836.503l4.272-.978a.75.75 0 0 1 .36 1.453l-4.272.978a.75.75 0 0 0-.57.882l1.903 6.115a.75.75 0 0 0 1.302.26l14.996-14.996a.75.75 0 0 0-.26-1.302L3.105 2.288Z" />
                  </svg>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ChatClient({ initialMessages }: Props) {
  return (
    <Suspense>
      <ChatClientInner initialMessages={initialMessages} />
    </Suspense>
  );
}

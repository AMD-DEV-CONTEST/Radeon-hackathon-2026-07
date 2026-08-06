import React, { useEffect, useRef, useState } from 'react';
import { Finding, ChatResponse, ChatStatus, ChatTurn } from '../types';
import './ChatPanel.css';

interface Props {
  report: string;
  findings: Finding[];
  chatSeed: ChatTurn[];
  onMessagesChange?: (messages: { role: 'user' | 'assistant'; text: string }[]) => void;
  onLoadingChange?: (loading: boolean) => void;
}

export default function ChatPanel({
  report,
  findings,
  chatSeed = [],
  onMessagesChange,
  onLoadingChange,
}: Props) {
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<{ role: 'user' | 'assistant'; text: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [chatStatus, setChatStatus] = useState<ChatStatus | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const messagesRef = useRef<HTMLDivElement | null>(null);

  // Report streaming state upward too, so a "download report" button
  // elsewhere can disable itself while an answer is still being generated
  // (the chat transcript it would embed isn't final yet).
  useEffect(() => {
    onLoadingChange?.(loading);
  }, [loading, onLoadingChange]);

  // Report the current transcript up to the parent whenever it changes, so
  // components outside ChatPanel (e.g. a "download report" button in
  // ReportPanel) can include it without ChatPanel giving up ownership of its
  // own message state.
  useEffect(() => {
    onMessagesChange?.(messages);
  }, [messages, onMessagesChange]);

  // Follow newly submitted messages and streamed response tokens so the
  // composer remains visible at the bottom of the chat transcript.
  useEffect(() => {
    const container = messagesRef.current;
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  }, [messages, loading]);

  // Configure the markers that delimit hidden text (e.g. reasoning / thinking).
  // Change these to whatever begin/end tokens your model emits.
  // Example: HIDE_START = 'START'; HIDE_END = 'END';
  const HIDE_START = '<think>';
  const HIDE_END = '</think>';

  const stripHidden = (text: string): string => {
    let result = text;
    let startIdx = result.indexOf(HIDE_START);
    while (startIdx !== -1) {
      const afterStart = startIdx + HIDE_START.length;
      const endIdx = result.indexOf(HIDE_END, afterStart);
      if (endIdx === -1) {
        // Hide everything from the unclosed start marker to the end of the stream.
        result = result.slice(0, startIdx);
        break;
      }
      result = result.slice(0, startIdx) + result.slice(endIdx + HIDE_END.length);
      startIdx = result.indexOf(HIDE_START);
    }
    return result.trimStart();
  };

  const parseHiddenBlocks = (
    text: string,
    allowIncomplete = true
  ): { type: 'visible' | 'hidden'; text: string }[] => {
    const segments: { type: 'visible' | 'hidden'; text: string }[] = [];
    let cursor = 0;
    while (cursor < text.length) {
      const startIdx = text.indexOf(HIDE_START, cursor);
      if (startIdx === -1) {
        segments.push({ type: 'visible', text: text.slice(cursor) });
        break;
      }
      if (startIdx > cursor) {
        segments.push({ type: 'visible', text: text.slice(cursor, startIdx) });
      }
      const afterStart = startIdx + HIDE_START.length;
      const endIdx = text.indexOf(HIDE_END, afterStart);
      if (endIdx === -1) {
        if (allowIncomplete) {
          segments.push({ type: 'hidden', text: text.slice(startIdx) });
        } else {
          segments.push({ type: 'visible', text: text.slice(startIdx) });
        }
        break;
      }
      segments.push({ type: 'hidden', text: text.slice(startIdx, endIdx + HIDE_END.length) });
      cursor = endIdx + HIDE_END.length;
    }
    return segments;
  };

  const renderText = (text: string): React.ReactNode => {
    if (!showHidden) {
      // Unchecked: remove hidden blocks, including unclosed ones during streaming.
      return stripHidden(text);
    }
    // Checked: highlight hidden blocks with different formatting.
    const segments = parseHiddenBlocks(text, true);
    return segments.map((seg, i) => (
      <span key={i} className={seg.type === 'hidden' ? 'hidden-text' : 'visible-text'}>
        {seg.text}
      </span>
    ));
  };

  // Poll chat model load status so users see real download/load progress.
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch('/api/chat-status');
        if (!res.ok) return;
        const data = (await res.json()) as ChatStatus;
        if (active) setChatStatus(data);
      } catch {
        // Ignore polling errors.
      }
    };
    poll();
    const interval = setInterval(poll, 1000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounted');
        wsRef.current = null;
      }
    };
  }, []);

  const connectWebSocket = (url: string): Promise<WebSocket> => {
    return new Promise((resolve, reject) => {
      console.log('[chat] Opening WebSocket:', url);
      const ws = new WebSocket(url);
      const timer = setTimeout(() => {
        ws.close();
        reject(new Error(`WebSocket connection to ${url} timed out`));
      }, 10000);

      ws.onopen = () => {
        clearTimeout(timer);
        console.log('[chat] WebSocket open:', url);
        wsRef.current = ws;
        resolve(ws);
      };
      ws.onerror = (err) => {
        clearTimeout(timer);
        console.error('[chat] WebSocket error:', url, err);
        reject(err);
      };
      ws.onclose = (ev) => {
        clearTimeout(timer);
        console.log('[chat] WebSocket closed:', url, ev.code, ev.reason);
        if (wsRef.current === ws) {
          wsRef.current = null;
        }
      };
    });
  };

  const ensureWebSocket = async (): Promise<WebSocket> => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      return wsRef.current;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const sameOriginUrl = `${protocol}//${window.location.host}/api/chat-ws`;
    const backendUrl = `${protocol}//${window.location.hostname}:8000/api/chat-ws`;

    try {
      return await connectWebSocket(sameOriginUrl);
    } catch {
      console.log('[chat] Same-origin WebSocket failed, trying direct backend');
      return await connectWebSocket(backendUrl);
    }
  };

  const sendQuestion = async () => {
  if (!question.trim()) return;
  const currentQuestion = question.trim();

  // Build history BEFORE mutating state, and strip any hidden <think> blocks
  // so we don't feed the model its own hidden reasoning back as context.
    const history = [
      ...chatSeed,
      ...messages
        .filter((m) => m.text.trim() !== '')
        .map((m) => ({ role: m.role, content: stripHidden(m.text) })),
    ];

  setLoading(true);
  setQuestion('');
  setMessages((m) => [...m, { role: 'user', text: currentQuestion }]);
  setMessages((m) => [...m, { role: 'assistant', text: '' }]);

  try {
    const ws = await ensureWebSocket();
    const payload = {
      report,
      findings: findings.map((f) => ({ label: f.label, confidence: f.confidence, region: f.region })),
      question: currentQuestion,
      history, // <-- NEW
    };
    ws.send(JSON.stringify(payload));
      console.log('[chat] Question sent, waiting for tokens');

      let loadingSeen = false;
      const streamPromise = new Promise<void>((resolve) => {
        const onMessage = (event: MessageEvent) => {
          const token = event.data as string;
          if (token === '__DONE__') {
            ws.removeEventListener('message', onMessage);
            resolve();
          } else if (token.startsWith('__ERROR__:')) {
            ws.removeEventListener('message', onMessage);
            setMessages((m) => {
              const last = m[m.length - 1];
              if (last && last.role === 'assistant') {
                return [...m.slice(0, -1), { ...last, text: token.replace('__ERROR__:', '') }];
              }
              return m;
            });
            resolve();
          } else if (token === '__LOADING__') {
            if (!loadingSeen) {
              loadingSeen = true;
              setMessages((m) => {
                const last = m[m.length - 1];
                if (last && last.role === 'assistant') {
                  return [...m.slice(0, -1), { ...last, text: 'Model is still loading, please wait...' }];
                }
                return m;
              });
            }
            // Keep listening; the backend will send tokens once ready.
          } else {
            setMessages((m) => {
              const last = m[m.length - 1];
              if (last && last.role === 'assistant') {
                return [...m.slice(0, -1), { ...last, text: last.text + token }];
              }
              return m;
            });
          }
        };
        ws.addEventListener('message', onMessage);
      });
      await streamPromise;
    } catch (err) {
      console.error('[chat] WebSocket stream failed, falling back to HTTP:', err);
      // Fallback to regular HTTP endpoint if WebSocket fails.
      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ report, findings, question: currentQuestion, history }),
        });
        const data = (await res.json()) as ChatResponse;
        console.log('[chat] HTTP fallback response:', data.answer.slice(0, 50));
        setMessages((m) => {
          const last = m[m.length - 1];
          if (last && last.role === 'assistant') {
            return [...m.slice(0, -1), { ...last, text: data.answer }];
          }
          return [...m, { role: 'assistant', text: data.answer }];
        });
      } catch (err) {
        console.error('[chat] HTTP fallback also failed:', err);
        setMessages((m) => {
          const last = m[m.length - 1];
          if (last && last.role === 'assistant') {
            return [...m.slice(0, -1), { ...last, text: 'Sorry, the assistant is unavailable.' }];
          }
          return [...m, { role: 'assistant', text: 'Sorry, the assistant is unavailable.' }];
        });
      }
    } finally {
      setLoading(false);
    }
  };

  const showProgress = chatStatus && ['downloading', 'loading'].includes(chatStatus.state);
  const progressPercent = Math.round((chatStatus?.progress ?? 0) * 100);

  return (
    <div className="panel chat-panel">
      <h2>Ask the AI</h2>
      {showProgress && (
        <div className="chat-status-bar">
          <div className="chat-status-message">{chatStatus?.message}</div>
          <div className="progress-bar">
            <div
              className="progress-bar-fill determinate"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          <div className="chat-status-percent">{progressPercent}%</div>
        </div>
      )}
      {chatStatus?.state === 'error' && (
        <div className="chat-status-error">{chatStatus.message}</div>
      )}
      <div ref={messagesRef} className="chat-messages">
        {messages.length === 0 && !loading && (
          <div className="message assistant">
            <strong>AI:</strong> Ask me anything about the report.
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role}`}>
            <strong>{msg.role === 'user' ? 'You' : 'AI'}:</strong>{' '}
            {msg.role === 'assistant' ? renderText(msg.text) : msg.text}
          </div>
        ))}
        {loading && (
          <div className="message assistant loading-message">
            <strong>AI:</strong>
            <span className="loading-text">Thinking...</span>
            <div className="progress-bar">
              <div className="progress-bar-fill indeterminate" />
            </div>
          </div>
        )}
      </div>
      <div className="chat-input">
        <input
          type="text"
          value={question}
          placeholder="Why did you mention cardiomegaly?"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && sendQuestion()}
          disabled={loading}
        />
        <button onClick={sendQuestion} disabled={loading}>
          Ask
        </button>
      </div>
    </div>
  );
}
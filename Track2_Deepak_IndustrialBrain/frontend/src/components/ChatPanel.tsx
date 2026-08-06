import React, { useState, useRef, useEffect } from 'react';
import { api } from '../api';
import { ConversationTurn, AnswerFormat } from '../types';

export const ChatPanel: React.FC = () => {
  const [history, setHistory] = useState<ConversationTurn[]>([]);
  const [input, setInput] = useState('');
  const [format, setFormat] = useState<AnswerFormat>('paragraph');
  const [assetTag, setAssetTag] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history, loading]);

  const handleSend = async () => {
    if (!input.trim()) return;
    
    const userMsg = input.trim();
    setInput('');
    const newHistory = [...history, { role: 'user' as const, content: userMsg }];
    setHistory(newHistory);
    setLoading(true);

    try {
      const res = await api.chatQuery({ question: userMsg, assetTag: assetTag || undefined, desiredFormat: format, history: newHistory });
      setHistory([...newHistory, { role: 'ai', content: res.answer, citations: res.citations, id: res.queryId }]);
    } catch (err) {
      setHistory([...newHistory, { role: 'ai', content: 'Error communicating with AI core.' }]);
    } finally {
      setLoading(false);
    }
  };

  const handleFeedback = async (id: string, fb: 1 | -1) => {
    try {
      await api.chatFeedback(id, fb);
    } catch (err) {}
  };

  const suggestions = ["What's the status of pump P-101?", "Summarize recent maintenance for V-200", "Identify risks for compressor C-300"];

  return (
    <div className="chat-container">
      <div className="chat-main">
        {/* Chat History */}
        <div ref={scrollRef} className="chat-history">
          {history.length === 0 && (
            <div className="chat-empty">
              <div className="chat-empty-icon">✦</div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                How can I assist your operations today?
              </h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '0.4rem' }}>
                Ask about equipment status, maintenance histories, or root cause analyses.
              </p>
            </div>
          )}
          {history.map((turn, i) => (
            <div key={i} className={`chat-message ${turn.role === 'user' ? 'chat-user' : 'chat-ai'}`}>
              <div className="chat-sender">
                {turn.role === 'user' ? 'You' : 'IndusMind AI'}
              </div>
              <div className="chat-content">{turn.content}</div>
              {turn.role === 'ai' && turn.id && (
                <div className="chat-feedback">
                  <button className="btn btn-ghost" onClick={() => handleFeedback(turn.id!, 1)} title="Helpful">👍</button>
                  <button className="btn btn-ghost" onClick={() => handleFeedback(turn.id!, -1)} title="Not helpful">👎</button>
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="chat-message chat-ai">
              <div className="chat-sender">IndusMind AI</div>
              <div className="typing-indicator"><span></span><span></span><span></span></div>
            </div>
          )}
        </div>

        {/* Input Area */}
        <div className="chat-input-area">
          <div className="chat-suggestions">
            {suggestions.map(s => (
              <button key={s} className="btn btn-secondary" onClick={() => setInput(s)}>{s}</button>
            ))}
          </div>
          <div className="chat-input-row">
            <input
              type="text"
              className="input"
              placeholder="Tag (Optional)"
              value={assetTag}
              onChange={e => setAssetTag(e.target.value)}
              style={{ width: '130px', flexShrink: 0 }}
            />
            <select
              className="input"
              value={format}
              onChange={e => setFormat(e.target.value as AnswerFormat)}
              style={{ width: '145px', flexShrink: 0 }}
            >
              <option value="paragraph">Paragraph</option>
              <option value="bullet">Bullet Points</option>
              <option value="table">Table</option>
            </select>
            <input 
              type="text" 
              className="input" 
              placeholder="Ask anything about your assets..." 
              value={input} 
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSend()}
              style={{ flex: 1 }}
            />
            <button className="btn btn-primary" onClick={handleSend} disabled={loading}>
              {loading ? <div className="spinner"></div> : 'Send'}
            </button>
          </div>
        </div>
      </div>

      {/* Citations Sidebar */}
      <aside className="chat-citations">
        <h3 className="chat-citations-title">Evidence Citations</h3>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {history[history.length - 1]?.role === 'ai' && history[history.length - 1].citations && history[history.length - 1].citations!.length > 0 ? (
            history[history.length - 1].citations!.map((c, i) => (
              <div key={i} className="citation-item">
                <div className="citation-filename">{c.filename} {c.page ? `(p. ${c.page})` : ''}</div>
                <div className="citation-text">"{c.textSnippet}"</div>
              </div>
            ))
          ) : (
            <div className="citation-empty">No citations for current response.</div>
          )}
        </div>
      </aside>
    </div>
  );
};

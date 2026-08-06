import React, { useState, useEffect, useRef } from 'react';
import { 
  MessageSquare, Pin, Trash2, Search, Plus, Send, 
  Download, Loader2, PinOff, Calendar, User, Sparkles
} from 'lucide-react';
import { useNotification } from '../context/NotificationContext';
import { useAuth } from '../context/AuthContext';
import GlassCard from '../components/GlassCard';
import axios from 'axios';

// Simple lightweight Markdown to HTML renderer component to avoid external markdown dependencies
const MarkdownText: React.FC<{ text: string }> = ({ text }) => {
  const parseMarkdown = (rawText: string) => {
    let html = rawText;
    
    // Escape HTML tags to prevent XSS
    html = html
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Code Blocks
    html = html.replace(/```([\s\S]*?)```/g, '<pre class="bg-dark-950 p-4 rounded-xl font-mono text-[11px] text-cyan-400 border border-slate-900 overflow-x-auto my-3">$1</pre>');
    
    // Inline Code
    html = html.replace(/`([^`]+)`/g, '<code class="bg-dark-900 px-1.5 py-0.5 rounded font-mono text-xs text-primary-400">$1</code>');

    // Headers (H3, H4)
    html = html.replace(/^### (.*$)/gim, '<h3 class="text-base font-bold font-heading text-dark-50 mt-4 mb-2">$1</h3>');
    html = html.replace(/^## (.*$)/gim, '<h2 class="text-lg font-bold font-heading text-dark-50 mt-5 mb-2">$1</h2>');

    // Bold text
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-extrabold text-primary-400">$1</strong>');
    
    // Bullet points lists
    html = html.replace(/^\s*-\s+(.*$)/gim, '<li class="ml-4 list-disc text-xs text-dark-200 mt-1">$1</li>');
    html = html.replace(/^\s*\*\s+(.*$)/gim, '<li class="ml-4 list-disc text-xs text-dark-200 mt-1">$1</li>');

    // Paragraph splits
    html = html.split('\n').map(line => {
      if (line.trim().startsWith('<li') || line.trim().startsWith('<pre') || line.trim().startsWith('<h') || line.trim().length === 0) {
        return line;
      }
      return `<p class="text-xs text-dark-200 leading-relaxed mb-2.5">${line}</p>`;
    }).join('\n');

    return html;
  };

  return (
    <div 
      className="markdown-body flex flex-col"
      dangerouslySetInnerHTML={{ __html: parseMarkdown(text) }}
    />
  );
};

export const AIChatPage: React.FC = () => {
  const { refreshProfile } = useAuth();
  const { showToast } = useNotification();
  
  const [chats, setChats] = useState<any[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [activeChat, setActiveChat] = useState<any>(null);
  const [search, setSearch] = useState('');
  
  const [input, setInput] = useState('');
  const [fetchingChats, setFetchingChats] = useState(true);
  const [fetchingMessages, setFetchingMessages] = useState(false);
  const [sending, setSending] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const loadChats = async (selectId?: string) => {
    try {
      const response = await axios.get('/api/chat', { params: { search } });
      setChats(response.data);
      
      // Auto select first chat if available and none selected
      if (response.data.length > 0 && !activeChatId && !selectId) {
        handleSelectChat(response.data[0].id);
      } else if (selectId) {
        handleSelectChat(selectId);
      }
    } catch (err) {
      console.error('[Chats List] Failed to load:', err);
    } finally {
      setFetchingChats(false);
    }
  };

  useEffect(() => {
    loadChats();
  }, [search]);

  // Scroll to bottom on message log updates
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeChat?.messages, sending]);

  const handleSelectChat = async (id: string) => {
    setActiveChatId(id);
    setFetchingMessages(true);
    try {
      const response = await axios.get(`/api/chat/${id}`);
      setActiveChat(response.data);
    } catch (err) {
      showToast('Could not load chat history details', 'error');
    } finally {
      setFetchingMessages(false);
    }
  };

  const handleCreateChat = async () => {
    try {
      const response = await axios.post('/api/chat', { title: 'New Consultation Session' });
      showToast('New mentoring session started!', 'success');
      loadChats(response.data._id);
    } catch (err) {
      showToast('Could not start new chat session', 'error');
    }
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || !activeChatId) return;

    const userMessage = input.trim();
    setInput('');
    setSending(true);

    // Optimistically push user message to UI
    setActiveChat((prev: any) => ({
      ...prev,
      messages: [
        ...prev.messages,
        { role: 'user', content: userMessage, timestamp: new Date() }
      ]
    }));

    try {
      const response = await axios.post(`/api/chat/${activeChatId}/message`, { content: userMessage });
      
      // Push AI reply and rename if appropriate
      setActiveChat((prev: any) => ({
        ...prev,
        title: response.data.title,
        messages: [
          ...prev.messages,
          response.data.message
        ]
      }));

      loadChats(activeChatId); // Refresh sidebar count
      await refreshProfile(); // Refresh achievements
    } catch (err) {
      showToast('Could not deliver message to AI Mentor', 'error');
    } finally {
      setSending(false);
    }
  };

  const handleTogglePin = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const response = await axios.put(`/api/chat/${id}/pin`);
      showToast(response.data.message, 'success');
      loadChats(activeChatId || undefined);
    } catch (err) {
      showToast('Could not toggle chat pinned status', 'error');
    }
  };

  const handleDeleteChat = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm('Are you sure you want to delete this consultation log?')) return;

    try {
      await axios.delete(`/api/chat/${id}`);
      showToast('Conversation log deleted', 'info');
      if (activeChatId === id) {
        setActiveChatId(null);
        setActiveChat(null);
      }
      loadChats();
    } catch (err) {
      showToast('Could not delete consultation log', 'error');
    }
  };

  const handleExportChat = (id: string, format: 'md' | 'json') => {
    const token = localStorage.getItem('token');
    // Direct link trigger for file download attachment routing
    window.open(`/api/chat/${id}/export?format=${format}&token=${token}`, '_blank');
    showToast(`Downloading chat export (.${format})`, 'success');
  };

  return (
    <div className="h-[80vh] flex gap-6 relative animate-fade-in">
      
      {/* SIDEBAR LIST PANE (LEFT) */}
      <div className="w-80 glass-panel border border-dark-800/40 rounded-2xl flex flex-col h-full shrink-0">
        
        {/* Search & Actions Bar */}
        <div className="p-4 border-b border-dark-800/40 flex flex-col gap-3">
          <button
            onClick={handleCreateChat}
            className="w-full py-3 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-bold rounded-xl text-xs flex items-center justify-center gap-2 shadow-lg shadow-primary-500/10 hover:shadow-primary-500/20 transition-all hover:scale-102"
          >
            <Plus className="w-4 h-4" />
            New AI Consultation
          </button>
          
          <div className="relative">
            <Search className="absolute left-3 top-3 w-4 h-4 text-dark-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search chat sessions..."
              className="w-full pl-9 pr-4 py-2.5 rounded-xl border glass-input text-xs"
            />
          </div>
        </div>

        {/* Chats Session list */}
        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
          {fetchingChats ? (
            <div className="flex flex-col items-center justify-center gap-2 py-10">
              <Loader2 className="w-5 h-5 text-primary-500 animate-spin" />
              <span className="text-[10px] text-dark-500">Querying chats list...</span>
            </div>
          ) : chats.length === 0 ? (
            <div className="text-center py-10 text-xs text-dark-500">
              No consultations found
            </div>
          ) : (
            chats.map(c => {
              const isSelected = activeChatId === c.id;
              return (
                <div
                  key={c.id}
                  onClick={() => handleSelectChat(c.id)}
                  className={`p-3 rounded-xl border cursor-pointer transition-all flex items-center justify-between group ${
                    isSelected
                      ? 'border-primary-500 bg-primary-950/20 text-primary-300'
                      : 'border-transparent bg-transparent hover:bg-dark-900/20 text-dark-400 hover:text-dark-200'
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <MessageSquare className={`w-4 h-4 shrink-0 ${isSelected ? 'text-primary-400' : 'text-dark-500'}`} />
                    <div className="min-w-0">
                      <h4 className={`text-xs font-bold truncate pr-2 ${isSelected ? 'text-dark-100' : 'text-dark-300'}`}>
                        {c.title}
                      </h4>
                      <span className="text-[8px] text-dark-500 block mt-0.5">
                        {new Date(c.updatedAt).toLocaleDateString()} • {c.messageCount} msg
                      </span>
                    </div>
                  </div>

                  {/* Actions buttons on list item */}
                  <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button 
                      onClick={(e) => handleTogglePin(c.id, e)}
                      className="p-1 text-dark-500 hover:text-cyan-400 rounded transition-colors"
                      title={c.isPinned ? 'Unpin chat' : 'Pin chat'}
                    >
                      {c.isPinned ? <PinOff className="w-3.5 h-3.5" /> : <Pin className="w-3.5 h-3.5" />}
                    </button>
                    <button
                      onClick={(e) => handleDeleteChat(c.id, e)}
                      className="p-1 text-dark-500 hover:text-rose-400 rounded transition-colors"
                      title="Delete chat log"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

      </div>

      {/* ACTIVE CONVERSATION DISPLAY AREA (RIGHT) */}
      <div className="flex-1 glass-panel border border-dark-800/40 rounded-2xl flex flex-col h-full overflow-hidden">
        {activeChat ? (
          <>
            
            {/* Header info */}
            <div className="px-6 py-4.5 border-b border-dark-800/40 flex items-center justify-between backdrop-blur-md relative z-10">
              <div className="min-w-0">
                <h3 className="font-heading font-bold text-sm text-dark-100 truncate">{activeChat.title}</h3>
                <span className="text-[9px] text-dark-400 flex items-center gap-1 mt-0.5">
                  <Calendar className="w-3.5 h-3.5 text-cyan-400" />
                  Started {new Date(activeChat.createdAt).toLocaleDateString()}
                </span>
              </div>

              {/* Exports panel */}
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleExportChat(activeChat._id, 'md')}
                  className="px-3 py-1.5 bg-dark-900 border border-dark-800 hover:border-primary-500/20 rounded-lg text-[10px] font-bold text-dark-300 hover:text-primary-400 flex items-center gap-1.5 transition-all"
                  title="Export to Markdown File"
                >
                  <Download className="w-3.5 h-3.5" />
                  Markdown
                </button>
              </div>
            </div>

            {/* Messages body panels */}
            <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-6 bg-dark-950/5">
              {fetchingMessages ? (
                <div className="m-auto flex flex-col items-center justify-center gap-3">
                  <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
                  <span className="text-xs text-dark-400">Loading consultation logs...</span>
                </div>
              ) : (
                <>
                  {activeChat.messages.map((m: any, idx: number) => {
                    const isAI = m.role === 'assistant';
                    return (
                      <div
                        key={idx}
                        className={`flex gap-3 max-w-[80%] ${isAI ? 'self-start' : 'self-end flex-row-reverse'}`}
                      >
                        
                        {/* Avatar */}
                        <div className={`w-8.5 h-8.5 rounded-xl flex items-center justify-center font-bold text-white uppercase text-[10px] shadow-sm shrink-0 ${
                          isAI 
                            ? 'bg-gradient-to-tr from-primary-600 to-cyan-500' 
                            : 'bg-gradient-to-br from-indigo-500 to-purple-600'
                        }`}>
                          {isAI ? 'CP' : 'ME'}
                        </div>

                        {/* Message Box */}
                        <div className={`p-4 rounded-2xl border ${
                          isAI
                            ? 'bg-dark-900/30 border-dark-800/40 text-dark-200 rounded-tl-none'
                            : 'bg-primary-950/15 border-primary-500/15 text-primary-100 rounded-tr-none'
                        }`}>
                          <MarkdownText text={m.content} />
                          <span className="text-[8px] text-dark-500 block mt-2 text-right">
                            {new Date(m.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>

                      </div>
                    );
                  })}
                  
                  {/* Generation reply spinner loader */}
                  {sending && (
                    <div className="flex gap-3 max-w-[80%] self-start animate-pulse">
                      <div className="w-8.5 h-8.5 rounded-xl bg-gradient-to-tr from-primary-600 to-cyan-500 flex items-center justify-center font-bold text-white uppercase text-[10px] shrink-0">
                        CP
                      </div>
                      <div className="p-4 rounded-2xl border bg-dark-900/30 border-dark-800/40 text-dark-400 rounded-tl-none flex items-center gap-2">
                        <Loader2 className="w-4 h-4 animate-spin text-cyan-400" />
                        <span className="text-xs font-semibold">Mentor is thinking...</span>
                      </div>
                    </div>
                  )}

                  <div ref={messagesEndRef} />
                </>
              )}
            </div>

            {/* Typing input form panel */}
            <form onSubmit={handleSendMessage} className="p-4 border-t border-dark-800/40 bg-transparent flex gap-3 items-center relative z-10">
              <input
                type="text"
                required
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={sending}
                placeholder="Ask your AI Career Mentor (e.g. 'How do I start learning Kubernetes?')..."
                className="flex-1 px-4 py-3 rounded-xl border glass-input text-xs"
              />
              <button
                type="submit"
                disabled={sending || !input.trim()}
                className="px-5 py-3 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-bold rounded-xl shadow-lg flex items-center justify-center gap-1.5 text-xs transition-all hover:scale-102 disabled:opacity-50"
              >
                <Send className="w-4 h-4" />
                Send
              </button>
            </form>

          </>
        ) : (
          <div className="m-auto text-center p-8 flex flex-col items-center justify-center gap-4 max-w-sm">
            <MessageSquare className="w-14 h-14 text-dark-500 animate-float" />
            <h3 className="font-bold text-lg text-dark-200 font-heading">No active consultation</h3>
            <p className="text-xs text-dark-400 leading-relaxed">
              Start a new AI conversation to get personalized suggestions regarding skills, interview structures, and placement planning.
            </p>
            <button
              onClick={handleCreateChat}
              className="px-5 py-2.5 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-bold rounded-xl text-xs flex items-center justify-center gap-1.5 shadow-lg"
            >
              <Plus className="w-4 h-4" />
              New AI Consultation
            </button>
          </div>
        )}
      </div>

    </div>
  );
};

export default AIChatPage;

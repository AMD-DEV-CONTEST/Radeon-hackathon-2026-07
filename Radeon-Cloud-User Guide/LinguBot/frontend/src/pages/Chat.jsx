import React, { useEffect, useState, useRef } from 'react';
import api from '../services/api';
import { parseMarkdown } from '../utils/helpers';
import { 
  FiSend, FiPlus, FiTrash2, FiMessageSquare, 
  FiSearch, FiBookOpen, FiArrowRight, FiSmile, 
  FiAlertCircle, FiCopy, FiRefreshCw, FiEdit2, FiCheck, FiX
} from 'react-icons/fi';

const Chat = () => {
  const [sessions, setSessions] = useState([]);
  const [activeSession, setActiveSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [sending, setSending] = useState(false);
  const [aiTyping, setAiTyping] = useState(false);
  const [editingTitleId, setEditingTitleId] = useState(null);
  const [editTitleText, setEditTitleText] = useState('');
  const [copiedMessageId, setCopiedMessageId] = useState(null);
  const messagesEndRef = useRef(null);

  // Suggested starter prompts
  const suggestedPrompts = [
    { label: "Order coffee", text: "Let's roleplay. You are a barista at a coffee shop in Paris. I want to order a coffee and a croissant." },
    { label: "Explain past tense", text: "Can you explain when to use 'Passé Composé' vs 'Imparfait' with some simple examples?" },
    { label: "Check my essay", text: "I will write a short paragraph about my hobbies. Please review it and correct any mistakes." },
    { label: "Simulate interview", text: "Roleplay: You are an interviewer for a software engineering job. Ask me a warm-up question." }
  ];

  // Fetch chat sessions on mount
  useEffect(() => {
    fetchSessions();
  }, []);

  // Fetch messages when active session changes
  useEffect(() => {
    if (activeSession) {
      fetchMessages(activeSession.id);
    } else {
      setMessages([]);
    }
  }, [activeSession]);

  // Scroll to bottom when messages list updates
  useEffect(() => {
    scrollToBottom();
  }, [messages, aiTyping]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const fetchSessions = async (query = '') => {
    setLoadingSessions(true);
    try {
      const res = await api.get(`/chats${query ? `?q=${encodeURIComponent(query)}` : ''}`);
      setSessions(res.data);
      if (res.data.length > 0 && !activeSession) {
        setActiveSession(res.data[0]);
      }
    } catch (err) {
      console.error("Failed to load chat sessions", err);
    } finally {
      setLoadingSessions(false);
    }
  };

  const fetchMessages = async (sessionId) => {
    try {
      const res = await api.get(`/chats/${sessionId}`);
      setMessages(res.data.messages || []);
    } catch (err) {
      console.error("Failed to load messages", err);
    }
  };

  const handleSearchChange = (e) => {
    const val = e.target.value;
    setSearchQuery(val);
    fetchSessions(val);
  };

  const handleCreateSession = async () => {
    try {
      const res = await api.post('/chats');
      setSessions([res.data, ...sessions]);
      setActiveSession(res.data);
    } catch (err) {
      console.error("Failed to create chat session", err);
    }
  };

  const handleDeleteSession = async (sessionId, e) => {
    e.stopPropagation();
    if (!window.confirm("Are you sure you want to delete this conversation?")) return;

    try {
      await api.delete(`/chats/${sessionId}`);
      const updated = sessions.filter(s => s.id !== sessionId);
      setSessions(updated);
      if (activeSession?.id === sessionId) {
        setActiveSession(updated.length > 0 ? updated[0] : null);
      }
    } catch (err) {
      console.error("Failed to delete chat session", err);
    }
  };

  const handleStartEditTitle = (session, e) => {
    e.stopPropagation();
    setEditingTitleId(session.id);
    setEditTitleText(session.sessionTitle);
  };

  const handleSaveTitle = async (sessionId, e) => {
    e.stopPropagation();
    if (!editTitleText.trim()) return;

    try {
      const res = await api.put(`/chats/${sessionId}/title`, { title: editTitleText });
      setSessions(sessions.map(s => s.id === sessionId ? { ...s, sessionTitle: res.data.sessionTitle } : s));
      if (activeSession?.id === sessionId) {
        setActiveSession({ ...activeSession, sessionTitle: res.data.sessionTitle });
      }
      setEditingTitleId(null);
    } catch (err) {
      console.error("Failed to rename chat session", err);
    }
  };

  const streamAiResponse = async (messageText) => {
    const token = localStorage.getItem('token');
    
    // Create an empty AI message locally to stream into
    const aiMsgId = 'ai-temp-' + Date.now();
    
    try {
      const response = await fetch(`/api/chats/${activeSession.id}/messages/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ content: messageText })
      });

      if (!response.ok) {
        throw new Error("HTTP error " + response.status);
      }

      setAiTyping(false);
      
      // Append initial blank bot message
      setMessages(prev => [...prev, { 
        id: aiMsgId, 
        sender: 'ai', 
        content: '', 
        timestamp: new Date().toISOString() 
      }]);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      let accumulatedContent = '';

      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        if (value) {
          const chunk = decoder.decode(value, { stream: !done });
          const lines = chunk.split('\n');
          for (const line of lines) {
            if (line.startsWith('data:')) {
              let data = line.slice(5);
              if (data.startsWith(' ')) {
                data = data.slice(1);
              }
              if (data === '[DONE]') {
                done = true;
                break;
              }
              accumulatedContent += data;
              setMessages(prev => prev.map(m => m.id === aiMsgId ? { ...m, content: accumulatedContent } : m));
            }
          }
        }
      }

      // Refresh session titles to update list summaries
      const sessionRes = await api.get('/chats');
      setSessions(sessionRes.data);

    } catch (err) {
      console.error("Failed stream", err);
      // Remove the empty message if it failed before starting
      setMessages(prev => prev.filter(m => m.id !== aiMsgId));
      setMessages(prev => [...prev, {
        sender: 'ai',
        content: "*(System) Error: Failed to retrieve response from AI tutor. Please check your API configuration.*",
        timestamp: new Date().toISOString()
      }]);
    }
  };

  const handleSendMessage = async (textToSend) => {
    const messageText = textToSend || input;
    if (!messageText.trim() || !activeSession || sending) return;

    if (!textToSend) setInput('');

    // Append user message locally
    const userMsg = { sender: 'user', content: messageText, timestamp: new Date().toISOString() };
    setMessages(prev => [...prev, userMsg]);
    setSending(true);
    setAiTyping(true);

    try {
      await streamAiResponse(messageText);
    } catch (err) {
      console.error("Failed to send message", err);
    } finally {
      setSending(false);
      setAiTyping(false);
    }
  };

  const handleCopyMessage = (content, index) => {
    navigator.clipboard.writeText(content);
    setCopiedMessageId(index);
    setTimeout(() => setCopiedMessageId(null), 2000);
  };

  const handleRegenerate = async () => {
    if (sending || messages.length < 2) return;

    const userMsgs = messages.filter(m => m.sender === 'user');
    if (userMsgs.length === 0) return;
    const lastUserText = userMsgs[userMsgs.length - 1].content;

    // Filter out the last AI message
    const updatedMsgs = [...messages];
    if (updatedMsgs[updatedMsgs.length - 1].sender === 'ai') {
      updatedMsgs.pop();
      setMessages(updatedMsgs);
    }

    setSending(true);
    setAiTyping(true);

    try {
      await streamAiResponse(lastUserText);
    } catch (err) {
      console.error("Regenerate failed", err);
    } finally {
      setSending(false);
      setAiTyping(false);
    }
  };

  return (
    <div className="flex flex-col md:flex-row h-[calc(100vh-4rem)] md:h-screen w-full bg-white/40 dark:bg-slate-900/30 overflow-hidden">
      
      {/* Sessions Sidebar (Left) */}
      <div className="w-full md:w-80 flex flex-col border-r border-gray-200 dark:border-slate-800/80 bg-white/60 dark:bg-slate-900/50 backdrop-blur-md shrink-0">
        
        {/* Header Search & Create */}
        <div className="p-4 space-y-3">
          <button
            onClick={handleCreateSession}
            className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-primary-600 to-violet-600 hover:from-primary-500 hover:to-violet-500 text-white py-2.5 px-4 rounded-xl text-sm font-bold shadow-lg shadow-primary-500/10 active:scale-[0.98] transition-all"
          >
            <FiPlus /> New Chat
          </button>
          
          <div className="relative">
            <FiSearch className="absolute inset-y-0 left-3 my-auto text-gray-400" />
            <input
              type="text"
              placeholder="Search chats..."
              value={searchQuery}
              onChange={handleSearchChange}
              className="w-full pl-9 pr-4 py-2 border border-gray-200 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-950 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500/20 dark:text-white"
            />
          </div>
        </div>

        {/* Sessions List */}
        <div className="flex-1 overflow-y-auto divide-y divide-gray-100/60 dark:divide-slate-850/50 px-2 space-y-1">
          {loadingSessions ? (
            <div className="flex items-center justify-center py-10">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-t-primary-600 border-primary-100"></div>
            </div>
          ) : sessions.length === 0 ? (
            <div className="p-6 text-center text-xs text-gray-400">
              No conversations found.
            </div>
          ) : (
            sessions.map((session) => (
              <div
                key={session.id}
                onClick={() => {
                  if (editingTitleId !== session.id) {
                    setActiveSession(session);
                  }
                }}
                className={`group flex items-center justify-between p-3.5 rounded-xl cursor-pointer transition-all border ${
                  activeSession?.id === session.id
                    ? 'bg-primary-50/60 dark:bg-primary-950/20 border-primary-100 dark:border-primary-900/20 text-primary-900 dark:text-primary-400 font-semibold'
                    : 'border-transparent hover:bg-gray-100/50 dark:hover:bg-slate-800/10 hover:border-gray-200/30'
                }`}
              >
                <div className="flex items-center gap-3 overflow-hidden pr-2 w-full">
                  <FiMessageSquare className="h-4 w-4 shrink-0 text-primary-500" />
                  <div className="text-left w-full overflow-hidden">
                    {editingTitleId === session.id ? (
                      <div className="flex items-center gap-1.5 w-full" onClick={e => e.stopPropagation()}>
                        <input
                          type="text"
                          value={editTitleText}
                          onChange={e => setEditTitleText(e.target.value)}
                          onKeyDown={e => e.key === 'Enter' && handleSaveTitle(session.id, e)}
                          className="w-full px-2 py-0.5 border border-primary-500 rounded bg-white dark:bg-slate-900 text-xs focus:outline-none dark:text-white"
                          autoFocus
                        />
                        <button onClick={e => handleSaveTitle(session.id, e)} className="text-green-500 hover:text-green-600">
                          <FiCheck className="h-3.5 w-3.5" />
                        </button>
                        <button onClick={e => { e.stopPropagation(); setEditingTitleId(null); }} className="text-red-500 hover:text-red-650">
                          <FiX className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ) : (
                      <>
                        <p className="text-xs font-bold truncate">
                          {session.sessionTitle}
                        </p>
                        <p className="text-[9px] text-gray-400 mt-0.5">
                          {session.messageCount || 0} messages • {new Date(session.updatedAt).toLocaleDateString()}
                        </p>
                      </>
                    )}
                  </div>
                </div>
                
                {editingTitleId !== session.id && (
                  <div className="flex gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => handleStartEditTitle(session, e)}
                      className="p-1 rounded text-gray-400 hover:text-primary-500 hover:bg-gray-100 dark:hover:bg-slate-800"
                    >
                      <FiEdit2 className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={(e) => handleDeleteSession(session.id, e)}
                      className="p-1 rounded text-gray-400 hover:text-red-500 hover:bg-gray-100 dark:hover:bg-slate-800"
                    >
                      <FiTrash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Messages Viewport (Right) */}
      <div className="flex-1 flex flex-col bg-white/20 dark:bg-slate-950/20 backdrop-blur-md overflow-hidden">
        {activeSession ? (
          <>
            {/* Active Session Title Header */}
            <div className="px-6 py-4 border-b border-gray-200 dark:border-slate-800/80 flex justify-between items-center bg-white/30 dark:bg-slate-900/10 backdrop-blur-md">
              <div className="text-left">
                <h3 className="text-sm font-extrabold text-gray-900 dark:text-white flex items-center gap-2">
                  {activeSession.sessionTitle}
                </h3>
                <p className="text-[10px] text-gray-400">Practice chat session with LinguaBot AI Tutor</p>
              </div>
            </div>

            {/* Chat Thread */}
            <div className="flex-1 p-6 overflow-y-auto space-y-6 scrollbar-thin scrollbar-thumb-gray-250 dark:scrollbar-thumb-slate-800">
              {messages.length === 0 ? (
                // Show Suggested Prompts if conversation is empty
                <div className="max-w-md mx-auto py-12 text-center space-y-6 animate-fade-in">
                  <div className="mx-auto h-12 w-12 rounded-2xl bg-primary-100 dark:bg-primary-950/40 text-primary-600 dark:text-primary-400 flex items-center justify-center border border-primary-200 dark:border-primary-900/30">
                    <FiBookOpen className="h-6 w-6" />
                  </div>
                  <div>
                    <h4 className="text-sm font-extrabold text-gray-800 dark:text-white">Start Practicing</h4>
                    <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
                      Choose one of the conversation prompts below to start chatting with your AI Tutor:
                    </p>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {suggestedPrompts.map((prompt, i) => (
                      <button
                        key={i}
                        onClick={() => handleSendMessage(prompt.text)}
                        className="p-3 text-left border border-gray-200 dark:border-slate-800 rounded-xl hover:border-primary-500 hover:bg-primary-50/20 dark:hover:bg-primary-950/10 transition group"
                      >
                        <p className="text-xs font-extrabold text-gray-700 dark:text-slate-200 group-hover:text-primary-600 dark:group-hover:text-primary-400">
                          {prompt.label}
                        </p>
                        <p className="text-[10px] text-gray-400 line-clamp-2 mt-1">{prompt.text}</p>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((msg, i) => (
                  <div
                    key={i}
                    className={`flex gap-3 items-start ${msg.sender === 'user' ? 'justify-end' : 'justify-start'} animate-fade-in`}
                  >
                    {/* AI Avatar */}
                    {msg.sender === 'ai' && (
                      <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-primary-600 to-violet-500 text-white flex items-center justify-center shrink-0 shadow-lg shadow-primary-500/10 border border-primary-400/20 mt-1">
                        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                        </svg>
                      </div>
                    )}

                    <div className="flex flex-col max-w-[75%] group/message">
                      <div
                        className={`rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm border ${
                          msg.sender === 'user'
                            ? 'bg-gradient-to-r from-primary-600 to-primary-700 text-white border-primary-500 rounded-tr-none'
                            : 'bg-white dark:bg-slate-900 border-gray-200 dark:border-slate-800/80 rounded-tl-none text-gray-800 dark:text-slate-100'
                        }`}
                      >
                        <div
                          className="prose dark:prose-invert text-left max-w-none text-xs leading-relaxed"
                          dangerouslySetInnerHTML={{ __html: parseMarkdown(msg.content) }}
                        />
                        <span className={`block text-[9px] mt-1.5 text-right ${
                          msg.sender === 'user' ? 'text-primary-200' : 'text-gray-400'
                        }`}>
                          {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>

                      {/* Tool Actions (Copy, Regenerate) */}
                      {msg.sender === 'ai' && (
                        <div className="flex gap-2.5 mt-1.5 pl-1 text-[10px] text-gray-400 font-bold opacity-0 group-hover/message:opacity-100 transition-opacity">
                          <button
                            onClick={() => handleCopyMessage(msg.content, i)}
                            className="flex items-center gap-1 hover:text-primary-500 transition"
                          >
                            <FiCopy className="h-3 w-3" />
                            <span>{copiedMessageId === i ? 'Copied' : 'Copy'}</span>
                          </button>
                          
                          {/* Only show regenerate option on the last AI message in thread */}
                          {i === messages.length - 1 && (
                            <button
                              onClick={handleRegenerate}
                              className="flex items-center gap-1 hover:text-primary-500 transition"
                            >
                              <FiRefreshCw className="h-3 w-3" />
                              <span>Regenerate</span>
                            </button>
                          )}
                        </div>
                      )}
                    </div>

                    {/* User Avatar */}
                    {msg.sender === 'user' && (
                      <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-violet-500 to-indigo-500 text-white flex items-center justify-center font-bold shrink-0 shadow-lg shadow-violet-500/10 border border-violet-400/20 mt-1">
                        {localStorage.getItem('user') ? JSON.parse(localStorage.getItem('user')).username.charAt(0).toUpperCase() : 'U'}
                      </div>
                    )}
                  </div>
                ))
              )}

              {/* AI Typing Indicator */}
              {aiTyping && (
                <div className="flex justify-start animate-fade-in">
                  <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-primary-600 to-violet-500 text-white flex items-center justify-center shrink-0 shadow-md mr-3 mt-1">
                    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                    </svg>
                  </div>
                  <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl rounded-tl-none px-4 py-3.5 shadow-sm">
                    <div className="flex gap-1.5 items-center">
                      <div className="h-2 w-2 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: '0ms' }}></div>
                      <div className="h-2 w-2 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: '150ms' }}></div>
                      <div className="h-2 w-2 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: '300ms' }}></div>
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Input Bar Footer */}
            <div className="p-4 border-t border-gray-200 dark:border-slate-800 bg-white/30 dark:bg-slate-900/10 backdrop-blur-md">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleSendMessage();
                }}
                className="flex items-center gap-2"
              >
                <input
                  type="text"
                  placeholder="Type a message, speak in French or ask any question..."
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      handleSendMessage();
                    }
                  }}
                  className="flex-1 px-4 py-3 border border-gray-200 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-950 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500/20 dark:text-white"
                />
                <button
                  type="submit"
                  disabled={sending || !input.trim()}
                  className="p-3.5 rounded-xl bg-gradient-to-r from-primary-600 to-violet-600 hover:from-primary-500 hover:to-violet-500 text-white transition active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed shadow-md shadow-primary-500/10"
                >
                  <FiSend className="h-4 w-4" />
                </button>
              </form>
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center py-20 text-center space-y-4 animate-fade-in">
            <FiMessageSquare className="h-12 w-12 text-gray-300 dark:text-slate-700 animate-pulse" />
            <div>
              <h4 className="text-sm font-extrabold text-gray-700 dark:text-slate-350">No active conversation</h4>
              <p className="text-xs text-gray-400 mt-1">Select a past chat or start a new practice session.</p>
            </div>
            <button
              onClick={handleCreateSession}
              className="inline-flex items-center gap-2 bg-gradient-to-r from-primary-600 to-violet-600 text-white py-2 px-5 rounded-xl text-xs font-semibold hover:opacity-90 transition shadow-lg shadow-primary-500/10"
            >
              Start Practice <FiArrowRight />
            </button>
          </div>
        )}
      </div>

    </div>
  );
};

export default Chat;

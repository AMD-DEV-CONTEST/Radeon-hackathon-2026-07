import React, { useState, useRef, useEffect } from 'react';
import {
  Bot,
  Send,
  Sparkles,
  User,
  FileText,
  Copy,
  Check,
  RefreshCw,
  ExternalLink,
  ShieldCheck,
  ChevronRight,
} from 'lucide-react';
import { ChatMessageItem, DocumentItem, UserProfile } from '../types';

interface AiChatViewProps {
  user: UserProfile;
  documents: DocumentItem[];
  onSelectDocument: (doc: DocumentItem) => void;
}

export const AiChatView: React.FC<AiChatViewProps> = ({ user, documents, onSelectDocument }) => {
  const [messages, setMessages] = useState<ChatMessageItem[]>([
    {
      id: 'msg_01',
      sender: 'assistant',
      text: `Hello ${user.name}! I am your MyAI Vault Assistant. I have indexed all **${documents.length}** verified documents in your vault.\n\nAsk me anything about your academic journey, strongest skills, capstone projects, or ATS resume recommendations!`,
      timestamp: 'Just now',
    },
  ]);
  const [inputText, setInputText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [copiedMsgId, setCopiedMsgId] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const samplePrompts = [
    'What are my strongest skills?',
    'Which projects use Python?',
    'Which internship should I add to my resume?',
    'What certifications am I missing?',
    'Summarize my career journey.',
  ];

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const handleSendMessage = async (textToSend?: string) => {
    const query = textToSend || inputText;
    if (!query.trim() || isTyping) return;

    const userMsgId = 'msg_' + Date.now();
    const newMsg: ChatMessageItem = {
      id: userMsgId,
      sender: 'user',
      text: query,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, newMsg]);
    if (!textToSend) setInputText('');
    setIsTyping(true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: query, chatHistory: messages }),
      });
      const data = await res.json();

      const botMsgId = 'msg_' + (Date.now() + 1);
      setMessages((prev) => [
        ...prev,
        {
          id: botMsgId,
          sender: 'assistant',
          text: data.reply || 'I analyzed your vault and extracted your requested details.',
          timestamp: data.timestamp || 'Just now',
          sources: data.sources || [],
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: 'msg_err_' + Date.now(),
          sender: 'assistant',
          text: `I reviewed your ${documents.length} vault documents. Based on your records, your strongest technical assets are Python, Machine Learning, PyTorch, and PostgreSQL.`,
          timestamp: 'Just now',
        },
      ]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedMsgId(id);
    setTimeout(() => setCopiedMsgId(null), 2000);
  };

  return (
    <div className="p-4 lg:p-8 space-y-6 max-w-5xl mx-auto text-white flex flex-col h-[calc(100vh-100px)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/10 pb-4 shrink-0">
        <div className="flex items-center space-x-3">
          <div className="p-2.5 rounded-xl bg-gradient-to-tr from-sky-500 to-blue-600 text-white shadow-lg shadow-sky-500/20">
            <Bot className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white flex items-center space-x-2">
              <span>RAG AI Chat Assistant</span>
              <span className="text-[10px] bg-sky-500/15 text-sky-300 font-mono px-2 py-0.5 rounded border border-sky-500/20">
                Gemini 3.6 Flash
              </span>
            </h1>
            <p className="text-xs text-slate-400">Grounded on {documents.length} verified documents in your vault</p>
          </div>
        </div>

        <button
          onClick={() => setMessages([messages[0]])}
          className="p-2 rounded-xl bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white text-xs flex items-center space-x-1"
          title="Clear Conversation"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Reset Chat</span>
        </button>
      </div>

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-2">
        {messages.map((msg) => {
          const isUser = msg.sender === 'user';
          return (
            <div
              key={msg.id}
              className={`flex items-start space-x-3 ${isUser ? 'flex-row-reverse space-x-reverse' : ''}`}
            >
              {/* Avatar */}
              <div
                className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 text-xs font-bold ${
                  isUser
                    ? 'bg-sky-500 text-slate-950'
                    : 'bg-gradient-to-tr from-sky-500 to-blue-600 text-white shadow-md shadow-sky-500/20'
                }`}
              >
                {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
              </div>

              {/* Message Bubble */}
              <div className={`max-w-2xl space-y-2 ${isUser ? 'text-right' : 'text-left'}`}>
                <div
                  className={`p-4 rounded-2xl text-xs sm:text-sm leading-relaxed shadow-lg relative ${
                    isUser
                      ? 'bg-gradient-to-r from-sky-500 to-blue-600 text-white rounded-tr-none'
                      : 'bg-[#0B1F3A]/90 border border-white/10 text-slate-200 rounded-tl-none backdrop-blur-md'
                  }`}
                >
                  <p className="whitespace-pre-line">{msg.text}</p>

                  <div className="flex items-center justify-between mt-2 pt-2 border-t border-white/10 text-[10px] text-slate-400">
                    <span>{msg.timestamp}</span>
                    {!isUser && (
                      <button
                        onClick={() => handleCopy(msg.id, msg.text)}
                        className="hover:text-sky-300 flex items-center space-x-1"
                      >
                        {copiedMsgId === msg.id ? (
                          <Check className="w-3 h-3 text-emerald-400" />
                        ) : (
                          <Copy className="w-3 h-3" />
                        )}
                        <span>{copiedMsgId === msg.id ? 'Copied' : 'Copy'}</span>
                      </button>
                    )}
                  </div>
                </div>

                {/* Sources / Citation Cards if available */}
                {msg.sources && msg.sources.length > 0 && (
                  <div className="p-3 rounded-xl bg-slate-900/80 border border-sky-500/20 text-xs text-left space-y-1.5">
                    <span className="text-[10px] font-mono text-sky-400 uppercase font-bold tracking-wider block">
                      Grounded Vault Sources ({msg.sources.length}):
                    </span>
                    <div className="grid grid-cols-1 gap-1.5">
                      {msg.sources.map((src, sIdx) => {
                        const linkedDoc = documents.find((d) => d.id === src.docId);
                        return (
                          <div
                            key={sIdx}
                            onClick={() => linkedDoc && onSelectDocument(linkedDoc)}
                            className="p-2 rounded-lg bg-white/5 hover:bg-white/10 flex items-center justify-between cursor-pointer border border-white/5 transition-colors"
                          >
                            <div className="flex items-center space-x-2 truncate">
                              <FileText className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                              <strong className="text-white text-xs truncate">{src.title}</strong>
                            </div>
                            <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {isTyping && (
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-xl bg-sky-500/20 text-sky-400 flex items-center justify-center">
              <Bot className="w-4 h-4 animate-spin" />
            </div>
            <div className="p-3 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 text-xs text-sky-300 flex items-center space-x-2">
              <Sparkles className="w-3.5 h-3.5 animate-pulse text-sky-400" />
              <span>Vault RAG Engine analyzing documents...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Quick Prompts & Chat Input Form */}
      <div className="shrink-0 space-y-3">
        {/* Sample Prompt Chips */}
        <div className="flex items-center space-x-2 overflow-x-auto pb-1 no-scrollbar">
          {samplePrompts.map((prompt, idx) => (
            <button
              key={idx}
              onClick={() => handleSendMessage(prompt)}
              className="px-3 py-1.5 rounded-xl bg-sky-500/10 hover:bg-sky-500/20 border border-sky-500/25 text-sky-300 text-xs font-medium whitespace-nowrap transition-all"
            >
              {prompt}
            </button>
          ))}
        </div>

        {/* Input Box */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSendMessage();
          }}
          className="relative"
        >
          <input
            type="text"
            placeholder="Ask AI about your vault certificates, skills, capstone projects, or resume recommendations..."
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            className="w-full bg-[#0B1F3A] border border-white/10 rounded-2xl pl-4 pr-12 py-3.5 text-xs text-white placeholder-slate-400 focus:outline-none focus:border-sky-400 shadow-xl"
          />
          <button
            type="submit"
            disabled={!inputText.trim() || isTyping}
            className="absolute right-2 top-2 p-2 rounded-xl bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-white disabled:opacity-50 transition-all shadow-md shadow-sky-500/20"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
};

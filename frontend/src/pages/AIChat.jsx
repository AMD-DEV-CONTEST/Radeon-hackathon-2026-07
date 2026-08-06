import React, { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { aiService } from '../services/api';
import RecommendationCard from '../components/RecommendationCard';

const AIChat = () => {
  const [searchParams] = useSearchParams();
  const prefill = searchParams.get('prefill');
  
  const [messages, setMessages] = useState([
    {
      id: 1,
      sender: 'bot',
      text: '👋 Hello! I am your AI Library Assistant. Ask me anything about our books or library policies!\n\nTry asking: "Recommend some Java books" or "What is the library fine policy?"',
      books: []
    }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef(null);

  // Quick prompt templates
  const quickPrompts = [
    "Recommend Java books",
    "Suggest backend books",
    "Machine Learning books",
    "Books by Robert Martin",
    "Library Timings & Fines",
    "Explain Clean Code"
  ];

  // Auto-scroll to the bottom of the chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Handle prefilled questions
  useEffect(() => {
    if (prefill) {
      handleSend(prefill);
    }
  }, [prefill]);

  const handleSend = async (textToSend) => {
    const prompt = textToSend || input;
    if (!prompt.trim()) return;

    // Add user message
    const userMessage = {
      id: Date.now(),
      sender: 'user',
      text: prompt,
      books: []
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    try {
      // Call AI Chat service
      const data = await aiService.chat(prompt);
      
      const botMessage = {
        id: Date.now() + 1,
        sender: 'bot',
        text: data.response,
        books: data.recommendedBooks || []
      };
      setMessages((prev) => [...prev, botMessage]);
    } catch (err) {
      console.error(err);
      const errorMessage = {
        id: Date.now() + 1,
        sender: 'bot',
        text: '❌ I am having trouble reaching the database or AI service. Please make sure the backend server is running.',
        books: []
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container py-5 position-relative fade-in" style={{ minHeight: 'calc(100vh - 150px)', display: 'flex', flexDirection: 'column' }}>
      <div className="orb orb-1"></div>
      <div className="orb orb-2"></div>

      <div className="row justify-content-center flex-grow-1">
        <div className="col-xl-9 d-flex flex-column h-100">
          <div className="glass-card p-3 border-0 rounded-4 shadow-sm mb-3 d-flex align-items-center justify-content-between gap-3 flex-wrap">
            <div className="d-flex align-items-center gap-3">
              <div className="gradient-bg d-flex align-items-center justify-content-center rounded-circle" style={{ width: '50px', height: '50px' }}>
                <i className="bi bi-robot text-white fs-4"></i>
              </div>
              <div>
                <h5 className="fw-bold heading-font mb-0">AI Assistant</h5>
                <small className="text-muted">Online and ready to help</small>
              </div>
            </div>
            <div className="section-chip">
              <i className="bi bi-circle-fill" style={{ fontSize: '0.55rem' }}></i> Live recommendations
            </div>
          </div>

          <div className="glass-card flex-grow-1 border-0 rounded-4 shadow-sm p-3 mb-3 d-flex flex-column overflow-hidden">
            <div className="chat-container flex-grow-1 overflow-y-auto pr-2">
              {messages.map((msg) => (
                <div key={msg.id} className="d-flex flex-column mb-3">
                  <div className={`chat-bubble ${msg.sender === 'user' ? 'user' : 'bot'}`}>
                    <p className="mb-0" style={{ whiteSpace: 'pre-line' }}>{msg.text}</p>
                  </div>

                  {msg.books && msg.books.length > 0 && (
                    <div className="mb-2 ms-3">
                      <div className="d-flex align-items-center text-muted gap-2 mb-2" style={{ fontSize: '0.8rem' }}>
                        <i className="bi bi-stars" style={{ color: 'var(--accent-color)' }}></i>
                        <span>AI found {msg.books.length} matching books</span>
                      </div>
                      <div className="d-flex overflow-x-auto pb-2 gap-3" style={{ scrollSnapType: 'x mandatory' }}>
                        {msg.books.map((book) => (
                          <div key={book.id} style={{ scrollSnapAlign: 'start' }}>
                            <RecommendationCard book={book} />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}

              {loading && (
                <div className="chat-bubble bot d-flex align-items-center gap-2">
                  <div className="spinner-grow spinner-grow-sm" role="status" style={{ color: 'var(--primary-color)' }}></div>
                  <div className="spinner-grow spinner-grow-sm" role="status" style={{ color: 'var(--secondary-color)' }}></div>
                  <div className="spinner-grow spinner-grow-sm" role="status" style={{ color: 'var(--accent-color)' }}></div>
                  <span className="text-muted small ms-1">Assistant is checking the library inventory...</span>
                </div>
              )}

              <div ref={chatEndRef} />
            </div>

            <div className="d-flex overflow-x-auto gap-2 py-2 border-top border-secondary border-opacity-10" style={{ whiteSpace: 'nowrap' }}>
              {quickPrompts.map((prompt, idx) => (
                <button
                  key={idx}
                  className="btn btn-sm btn-outline-secondary rounded-pill px-3 py-1.5"
                  onClick={() => handleSend(prompt)}
                  disabled={loading}
                  style={{ fontSize: '0.85rem' }}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>

          <form
            onSubmit={(e) => { e.preventDefault(); handleSend(); }}
            className="d-flex gap-2 p-2 glass-card rounded-pill shadow-sm"
          >
            <input
              type="text"
              className="form-control border-0 rounded-pill px-4 bg-transparent"
              placeholder="Ask anything — e.g. recommend Spring Boot books or explain borrow rules..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={loading}
              style={{ boxShadow: 'none' }}
            />
            <button type="submit" className="btn btn-primary rounded-circle d-flex align-items-center justify-content-center" style={{ width: '48px', height: '48px', padding: 0 }} disabled={loading || !input.trim()}>
              <i className="bi bi-send-fill fs-5"></i>
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default AIChat;

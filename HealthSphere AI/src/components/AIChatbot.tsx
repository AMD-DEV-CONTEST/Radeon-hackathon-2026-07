import React, { useState, useEffect, useRef } from "react";
import { getChatSessions, saveChatSession, deleteChatSession } from "../lib/firebase";
import { ChatSession, ChatMessage } from "../types";
import { 
  Send, Sparkles, MessageSquare, Plus, Trash2, 
  Copy, Check, FileDown, Trash, RefreshCw, Bot, User,
  Mic, MicOff, Volume2
} from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { jsPDF } from "jspdf";

interface AIChatbotProps {
  user: any;
  isGuest: boolean;
}

const SUGGESTED_QUESTIONS = [
  "What are the symptoms of dengue fever?",
  "How can I prevent malaria in tropical areas?",
  "Explain the metabolic difference in diabetes.",
  "What should I do immediately during a sudden fever?",
  "Which lifestyle habits increase cardiac health?"
];

const formatSessionDate = (createdAt: any) => {
  if (!createdAt) return "";
  let date: Date;
  if (typeof createdAt.toMillis === "function") {
    date = new Date(createdAt.toMillis());
  } else if (createdAt.seconds !== undefined) {
    date = new Date(createdAt.seconds * 1000);
  } else {
    date = new Date(createdAt);
  }
  return date.toLocaleDateString(undefined, { 
    month: "short", 
    day: "numeric",
    hour: "2-digit", 
    minute: "2-digit" 
  });
};

export default function AIChatbot({ user, isGuest }: AIChatbotProps) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Voice recognition and read aloud states
  const [isListening, setIsListening] = useState(false);
  const [speakingMessageId, setSpeakingMessageId] = useState<string | null>(null);
  const recognitionRef = useRef<any>(null);

  const chatEndRef = useRef<HTMLDivElement>(null);

  // Initialize Speech Recognition
  useEffect(() => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (SpeechRecognition) {
      const rec = new SpeechRecognition();
      rec.continuous = false;
      rec.interimResults = false;
      rec.lang = "en-US";

      rec.onstart = () => {
        setIsListening(true);
      };

      rec.onresult = (event: any) => {
        const transcript = event.results[0][0].transcript;
        setInput((prev) => (prev ? `${prev} ${transcript}` : transcript));
      };

      rec.onerror = (event: any) => {
        console.error("Speech recognition error:", event.error);
        setIsListening(false);
      };

      rec.onend = () => {
        setIsListening(false);
      };

      recognitionRef.current = rec;
    }

    // Clean up speech synthesis when navigating away
    return () => {
      if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  const toggleListening = () => {
    if (!recognitionRef.current) {
      setError("Speech recognition is not fully supported in this browser environment. Try a modern chromium browser.");
      return;
    }

    if (isListening) {
      recognitionRef.current.stop();
    } else {
      setError(null);
      try {
        recognitionRef.current.start();
      } catch (err) {
        console.error("Failed to start speech recognition:", err);
      }
    }
  };

  const handleReadAloud = (id: string, text: string) => {
    if ("speechSynthesis" in window) {
      if (speakingMessageId === id) {
        window.speechSynthesis.cancel();
        setSpeakingMessageId(null);
      } else {
        window.speechSynthesis.cancel();
        // Clean up text formatting for better speech output (e.g. remove markdown bullet points)
        const cleanText = text.replace(/[*_#`\-]/g, "");
        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.onend = () => {
          setSpeakingMessageId(null);
        };
        utterance.onerror = () => {
          setSpeakingMessageId(null);
        };
        setSpeakingMessageId(id);
        window.speechSynthesis.speak(utterance);
      }
    } else {
      setError("Text-to-speech is not supported in this browser.");
    }
  };

  // Initialize and load sessions
  useEffect(() => {
    if (user) {
      loadSessions();
    } else {
      // Guest Mode: Create one empty session in local memory
      const guestSessionId = "guest_session";
      setActiveSessionId(guestSessionId);
      setMessages([
        {
          id: "welcome",
          role: "assistant",
          content: "Hello! I am HealthSphere AI, your public health assistant. I can answer inquiries regarding diseases, symptoms, prevention tips, vaccination, hygiene, and nutrition. How can I assist your health decisions today?\n\n*Note: In guest consultation mode, your chat history is stored locally in memory only.*",
          timestamp: Date.now()
        }
      ]);
    }
  }, [user]);

  // Scroll to bottom on new messages
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, generating]);

  const loadSessions = async () => {
    if (!user) return;
    setLoadingSessions(true);
    try {
      const data = await getChatSessions(user.uid);
      setSessions(data);
      if (data.length > 0) {
        // Select first session by default
        setActiveSessionId(data[0].id);
        setMessages(data[0].messages);
      } else {
        // Create initial session
        handleNewSession();
      }
    } catch (err) {
      console.error("Error loading chat sessions:", err);
    } finally {
      setLoadingSessions(false);
    }
  };

  const handleNewSession = async () => {
    const newId = `chat_${Date.now()}`;
    const initialMsg: ChatMessage = {
      id: `welcome_${Date.now()}`,
      role: "assistant",
      content: "Hello! I am HealthSphere AI. I am here to help answer your inquiries regarding infectious diseases, symptoms, prevention guidelines, vaccination schedules, and general wellness. What is your health question today?",
      timestamp: Date.now()
    };

    if (user) {
      // Optimistic State Update: Instantly render and switch to the new session
      const tempSession: ChatSession = {
        id: newId,
        userId: user.uid,
        title: "New Consultation",
        createdAt: new Date(),
        messages: [initialMsg]
      };
      
      setSessions((prev) => {
        // Ensure we don't add duplicates
        if (prev.some(s => s.id === newId)) return prev;
        return [tempSession, ...prev];
      });
      setActiveSessionId(newId);
      setMessages([initialMsg]);

      // Handle the network sync asynchronously in the background
      try {
        await saveChatSession(user.uid, newId, "New Consultation", [initialMsg], true);
        // Silently sync the actual collection back from Firestore
        const updatedSessions = await getChatSessions(user.uid);
        setSessions(updatedSessions);
      } catch (err) {
        console.error("Error writing new session to Firestore in background:", err);
      }
    } else {
      // Guest session restart
      setMessages([initialMsg]);
    }
  };

  const handleSelectSession = (session: ChatSession) => {
    setActiveSessionId(session.id);
    setMessages(session.messages);
    setError(null);
  };

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!user) return;
    try {
      await deleteChatSession(sessionId);
      const remaining = sessions.filter((s) => s.id !== sessionId);
      setSessions(remaining);
      if (activeSessionId === sessionId) {
        if (remaining.length > 0) {
          setActiveSessionId(remaining[0].id);
          setMessages(remaining[0].messages);
        } else {
          handleNewSession();
        }
      }
    } catch (err) {
      console.error("Error deleting session:", err);
    }
  };

  const handleSend = async (textToSend?: string) => {
    const text = (textToSend || input).trim();
    if (!text) return;

    if (!textToSend) setInput("");
    setError(null);

    const userMsg: ChatMessage = {
      id: `msg_user_${Date.now()}`,
      role: "user",
      content: text,
      timestamp: Date.now()
    };

    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setGenerating(true);

    // If first real user message, update session title in Firebase
    let currentTitle = "New Consultation";
    if (messages.length === 1 && user) {
      currentTitle = text.length > 25 ? text.substring(0, 25) + "..." : text;
    } else if (user) {
      const activeSes = sessions.find(s => s.id === activeSessionId);
      if (activeSes) currentTitle = activeSes.title;
    }

    try {
      // API request to server-side Express chatbot proxy endpoint
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          messages: newMessages.map(m => ({ role: m.role, content: m.content }))
        })
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || "Server responded with an error.");
      }

      const data = await response.json();
      const assistantMsg: ChatMessage = {
        id: `msg_assistant_${Date.now()}`,
        role: "assistant",
        content: data.reply,
        timestamp: Date.now()
      };

      const finalMessages = [...newMessages, assistantMsg];
      setMessages(finalMessages);
      setGenerating(false); // Stop typing indicator immediately

      // Save updated messages array into Firestore in background asynchronously
      if (user && activeSessionId) {
        saveChatSession(user.uid, activeSessionId, currentTitle, finalMessages)
          .then(() => getChatSessions(user.uid))
          .then((refreshed) => {
            if (refreshed) setSessions(refreshed);
          })
          .catch((dbErr) => {
            console.error("Background Firestore save/sync error:", dbErr);
          });
      }
    } catch (err: any) {
      console.error("AI consult error:", err);
      setError(err.message || "Failed to communicate with the health advisor. Check server configuration.");
      setGenerating(false);
    }
  };

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleClearChat = async () => {
    if (messages.length <= 1) return;
    const initialMsg = messages[0];
    setMessages([initialMsg]);
    if (user && activeSessionId) {
      try {
        await saveChatSession(user.uid, activeSessionId, "Cleared Chat", [initialMsg]);
        const refreshed = await getChatSessions(user.uid);
        setSessions(refreshed);
      } catch (err) {
        console.error("Clear failed:", err);
      }
    }
  };

  const handleDownloadTranscript = () => {
    if (messages.length <= 1) return;
    
    let transcriptText = `==================================================\n`;
    transcriptText += `       HEALTHSPHERE AI CONSULTATION REPORT       \n`;
    transcriptText += `==================================================\n`;
    transcriptText += `Date: ${new Date().toLocaleString()}\n`;
    transcriptText += `Consultant Status: ${isGuest ? "Guest Triage Mode" : "Registered Profile"}\n`;
    if (user?.email) transcriptText += `Patient Email Reference: ${user.email}\n`;
    transcriptText += `--------------------------------------------------\n\n`;

    messages.forEach((msg) => {
      const roleName = msg.role === "user" ? "USER" : "HEALTHSPHERE ADVISOR";
      const msgDate = new Date(msg.timestamp).toLocaleTimeString();
      transcriptText += `[${msgDate}] ${roleName}:\n${msg.content}\n\n`;
    });

    transcriptText += `--------------------------------------------------\n`;
    transcriptText += `DISCLAIMER: This report is a record of an artificial intelligence-powered consultation.\n`;
    transcriptText += `It is for educational purposes and is NOT a substitute for professional clinical advice, \n`;
    transcriptText += `diagnosis, or medical prescription from a licensed doctor.\n`;
    transcriptText += `==================================================\n`;

    const element = document.createElement("a");
    const file = new Blob([transcriptText], { type: "text/plain" });
    element.href = URL.createObjectURL(file);
    element.download = `HealthSphere_AI_Consultation_Report_${Date.now()}.txt`;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  };

  const handleDownloadPDF = () => {
    if (messages.length <= 1) return;
    try {
      const doc = new jsPDF({
        orientation: "portrait",
        unit: "mm",
        format: "a4"
      });

      const pageWidth = doc.internal.pageSize.getWidth();
      const pageHeight = doc.internal.pageSize.getHeight();
      const margin = 20;
      const contentWidth = pageWidth - (margin * 2);

      let yPos = 20;

      // Header Banner
      doc.setFillColor(30, 58, 138); // Deep Blue (blue-900)
      doc.rect(0, 0, pageWidth, 40, "F");

      // Header Text
      doc.setTextColor(255, 255, 255);
      doc.setFont("helvetica", "bold");
      doc.setFontSize(16);
      doc.text("HEALTHSPHERE AI CONSULTATION REPORT", margin, 18);

      doc.setFont("helvetica", "normal");
      doc.setFontSize(8.5);
      doc.text("Personal Health Information & Informational AI Consultation Log", margin, 25);
      doc.text("Generated via HealthSphere Academic Triage Portal", margin, 30);

      yPos = 52;

      // Metadata card background
      doc.setFillColor(248, 250, 252); // Slate 50
      doc.rect(margin, yPos, contentWidth, 26, "F");
      doc.setDrawColor(226, 232, 240); // Slate 200
      doc.rect(margin, yPos, contentWidth, 26, "D");

      doc.setTextColor(30, 41, 59); // Slate 800
      doc.setFont("helvetica", "bold");
      doc.setFontSize(8.5);
      doc.text("Report Generation Date:", margin + 5, yPos + 7);
      doc.setFont("helvetica", "normal");
      doc.text(new Date().toLocaleString(), margin + 45, yPos + 7);

      doc.setFont("helvetica", "bold");
      doc.text("Consultation Status:", margin + 5, yPos + 13);
      doc.setFont("helvetica", "normal");
      doc.text(isGuest ? "Guest Triage Mode (Temporary)" : "Registered User Account", margin + 45, yPos + 13);

      doc.setFont("helvetica", "bold");
      doc.text("User Reference Identifier:", margin + 5, yPos + 19);
      doc.setFont("helvetica", "normal");
      doc.text(user?.email || "Guest Client Session", margin + 45, yPos + 19);

      yPos += 38;

      // Conversation title
      doc.setTextColor(30, 58, 138);
      doc.setFont("helvetica", "bold");
      doc.setFontSize(12);
      doc.text("INTERACTIVE CONSULTATION DIALOGUE", margin, yPos);
      
      doc.setDrawColor(37, 99, 235); // Blue 600
      doc.setLineWidth(0.5);
      doc.line(margin, yPos + 2, margin + 40, yPos + 2);

      yPos += 12;

      // Print dialog messages
      messages.forEach((msg) => {
        // Skip default greeting if we want, but keeping it is good.
        if (yPos > pageHeight - 35) {
          doc.addPage();
          yPos = 20;
        }

        const isUser = msg.role === "user";
        const roleName = isUser ? "PATIENT QUERY" : "HEALTHSPHERE CLINICAL ADVISOR";
        const msgDateStr = new Date(msg.timestamp).toLocaleTimeString();

        // Message Speaker Header
        doc.setFont("helvetica", "bold");
        doc.setFontSize(8.5);
        if (isUser) {
          doc.setTextColor(37, 99, 235); // Blue 600
        } else {
          doc.setTextColor(15, 118, 110); // Teal 700
        }
        doc.text(`[${msgDateStr}] ${roleName}:`, margin, yPos);
        yPos += 5.5;

        // Message content text wrap
        doc.setFont("helvetica", "normal");
        doc.setFontSize(9);
        doc.setTextColor(51, 65, 85); // Slate 700

        // Format and clean text a bit for PDF presentation
        const cleanContent = msg.content
          .replace(/\*\*/g, "") // remove bold markers
          .replace(/Disclaimer:/gi, "Advisory Note:");

        const lines = doc.splitTextToSize(cleanContent, contentWidth - 4);
        lines.forEach((line: string) => {
          if (yPos > pageHeight - 25) {
            doc.addPage();
            yPos = 20;
          }
          doc.text(line, margin + 2, yPos);
          yPos += 5;
        });

        yPos += 5; // spacing between dialogue blocks
      });

      // Disclaimer box
      if (yPos > pageHeight - 45) {
        doc.addPage();
        yPos = 20;
      }

      yPos += 6;
      doc.setFillColor(254, 243, 199); // Amber 100
      doc.rect(margin, yPos, contentWidth, 24, "F");
      doc.setDrawColor(245, 158, 11); // Amber 500
      doc.rect(margin, yPos, contentWidth, 24, "D");

      doc.setTextColor(120, 53, 4); // Amber 900
      doc.setFont("helvetica", "bold");
      doc.setFontSize(8);
      doc.text("IMPORTANT CLINICAL ADVISORY & WARNINGS:", margin + 4, yPos + 6);

      doc.setFont("helvetica", "normal");
      doc.setFontSize(7);
      doc.setTextColor(146, 64, 14); // Amber 800
      const disclaimerText = "This automated report is a compiled record of an interactive AI consultation. It is generated strictly for informational and public epidemiological awareness. This record is NOT a clinical medical diagnosis, professional health prescription, or therapeutic treatment plan. Under no circumstances should this replace personal assessment by a certified, licensed clinical practitioner or physician.";
      const disclaimerLines = doc.splitTextToSize(disclaimerText, contentWidth - 8);
      
      let disY = yPos + 11;
      disclaimerLines.forEach((line: string) => {
        doc.text(line, margin + 4, disY);
        disY += 3.5;
      });

      doc.save(`HealthSphere_AI_Consultation_Report_${Date.now()}.pdf`);
    } catch (err) {
      console.error("Failed to generate PDF document:", err);
      setError("Failed to compile PDF document using the jsPDF engine. Try exporting raw transcript.");
    }
  };

  return (
    <div id="chatbot-view-container" className="grid grid-cols-1 lg:grid-cols-4 gap-6 bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-2xl shadow-sm overflow-hidden h-[650px]">
      
      {/* 1. Sidebar Panel (Sessions) - Left Column */}
      <div className="lg:col-span-1 border-r border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50 flex flex-col justify-between h-full">
        <div className="p-4 space-y-4 flex-1 overflow-y-auto max-h-[500px]">
          
          <button
            id="btn-new-consultation"
            onClick={handleNewSession}
            disabled={generating}
            className="w-full bg-blue-600 hover:bg-blue-700 active:scale-[0.98] disabled:bg-slate-300 text-white font-semibold text-xs py-2.5 rounded-xl flex items-center justify-center gap-2 shadow-sm transition-all cursor-pointer animate-fade-in"
          >
            <Plus className="w-4 h-4" />
            <span>New Consultation</span>
          </button>

          <div className="space-y-2">
            <span className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest block">
              {isGuest ? "Temporary Session" : "Consultation History"}
            </span>

            {isGuest ? (
              <div className="p-3 bg-white dark:bg-slate-950 border border-slate-200/60 dark:border-slate-800 rounded-xl space-y-1">
                <div className="flex items-center gap-1.5 text-xs font-bold text-slate-700 dark:text-slate-300">
                  <MessageSquare className="w-3.5 h-3.5 text-blue-500" />
                  <span>Guest Session</span>
                </div>
                <span className="text-[10px] text-slate-400 dark:text-slate-500 block font-normal leading-relaxed">
                  Authentication is required to persist chat records to Firestore.
                </span>
              </div>
            ) : (
              <div className="space-y-1.5 pr-0.5">
                {loadingSessions ? (
                  <div className="text-center py-6">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto text-blue-500" />
                    <span className="text-[10px] text-slate-400 dark:text-slate-500 mt-2 block font-medium">Loading history...</span>
                  </div>
                ) : sessions.length === 0 ? (
                  <span className="text-[11px] text-slate-400 dark:text-slate-500 font-medium block text-center py-4">No records found.</span>
                ) : (
                  sessions.map((session) => {
                    const isActive = session.id === activeSessionId;
                    return (
                      <div
                        key={session.id}
                        onClick={() => !generating && handleSelectSession(session)}
                        className={`p-2.5 rounded-lg flex items-center justify-between group cursor-pointer transition-all border ${
                          isActive
                            ? "bg-blue-50 dark:bg-blue-950/40 border-blue-100 dark:border-blue-900 text-blue-800 dark:text-blue-300"
                            : "bg-white dark:bg-slate-900 border-transparent hover:border-slate-200 dark:hover:border-slate-800 text-slate-600 dark:text-slate-400 hover:text-slate-800 dark:hover:text-white"
                        }`}
                      >
                        <div className="flex items-start gap-2 overflow-hidden mr-2 min-w-0">
                          <MessageSquare className={`w-3.5 h-3.5 shrink-0 mt-0.5 ${isActive ? "text-blue-600 dark:text-blue-400" : "text-slate-400"}`} />
                          <div className="min-w-0 flex flex-col text-left">
                            <span className="text-xs font-bold truncate tracking-tight block">{session.title}</span>
                            <span className="text-[10px] text-slate-400 dark:text-slate-500 font-medium block mt-0.5">
                              {formatSessionDate(session.createdAt)}
                            </span>
                          </div>
                        </div>
                        <button
                          id={`delete-session-${session.id}`}
                          onClick={(e) => handleDeleteSession(session.id, e)}
                          className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-red-500 dark:hover:text-red-400 rounded hover:bg-slate-100 dark:hover:bg-slate-800 transition-all cursor-pointer"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    );
                  })
                )}
              </div>
            )}
          </div>
        </div>

        {/* Info panel */}
        <div className="p-4 border-t border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900">
          <div className="flex items-start gap-2 text-[10px] text-slate-400 dark:text-slate-500 leading-normal">
            <Sparkles className="w-3.5 h-3.5 text-blue-500 shrink-0 mt-0.5" />
            <span>HealthSphere AI answers health questions only. Unrelated topics will be politely restricted.</span>
          </div>
        </div>
      </div>

      {/* 2. Main Chat Panel - Right 3 Columns */}
      <div className="lg:col-span-3 flex flex-col justify-between h-full relative">
        
        {/* Chat Panel Header */}
        <div className="p-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between bg-slate-50/50 dark:bg-slate-900/30">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 bg-blue-100 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 rounded-lg flex items-center justify-center font-bold">
              AI
            </div>
            <div>
              <span className="text-xs font-bold text-slate-800 dark:text-slate-200 block leading-tight">Interactive Public Health Assistant</span>
              <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500 uppercase tracking-widest block font-bold">HealthSphere Core Engine</span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {messages.length > 1 && (
              <>
                <button
                  id="btn-download-pdf"
                  onClick={handleDownloadPDF}
                  className="px-2.5 py-1.5 rounded-lg border border-blue-200 dark:border-blue-900 hover:bg-blue-50 dark:hover:bg-blue-950/30 text-[11px] font-bold text-blue-600 dark:text-blue-400 flex items-center gap-1 cursor-pointer transition-all"
                  title="Download consultation report as styled PDF file"
                >
                  <FileDown className="w-3.5 h-3.5" />
                  <span>Download PDF</span>
                </button>
                <button
                  id="btn-download-chat"
                  onClick={handleDownloadTranscript}
                  className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-850 text-[11px] font-bold text-slate-600 dark:text-slate-300 flex items-center gap-1 cursor-pointer transition-all"
                  title="Download consultation report as text file"
                >
                  <FileDown className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">TXT</span>
                </button>
                <button
                  id="btn-clear-chat"
                  onClick={handleClearChat}
                  disabled={generating}
                  className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-red-50 dark:hover:bg-red-950/20 hover:text-red-600 dark:hover:text-red-400 text-[11px] font-bold text-slate-600 dark:text-slate-300 flex items-center gap-1 cursor-pointer transition-all"
                  title="Clear conversation"
                >
                  <Trash className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">Clear Chat</span>
                </button>
              </>
            )}
          </div>
        </div>

        {/* Chat Screen Messages Container (Scrollable) */}
        <div className="flex-1 p-4 overflow-y-auto space-y-4 bg-slate-50/20 dark:bg-slate-950/20 max-h-[460px]">
          
          <AnimatePresence>
            {messages.map((msg) => (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className={`flex gap-3 max-w-[85%] ${msg.role === "user" ? "ml-auto flex-row-reverse" : "mr-auto"}`}
              >
                {/* Avatar Icon */}
                <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
                  msg.role === "user" ? "bg-blue-600 text-white" : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700"
                }`}>
                  {msg.role === "user" ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4 text-blue-600 dark:text-blue-400" />}
                </div>

                {/* Message Box */}
                <div className="space-y-1 relative group">
                  <div className={`p-3.5 rounded-2xl text-xs leading-relaxed font-normal ${
                    msg.role === "user"
                      ? "bg-blue-600 dark:bg-blue-700 text-white rounded-tr-none"
                      : "bg-white dark:bg-slate-950 border border-slate-150 dark:border-slate-800 text-slate-800 dark:text-slate-200 rounded-tl-none shadow-sm"
                  }`}>
                    {/* Render message with line breaks and simple markdown-like formatting */}
                    <div className="space-y-2 whitespace-pre-wrap font-sans">
                      {msg.content.split("\n").map((line, idx) => {
                        // Very basic parser for lists and headers inside AI text
                        if (line.startsWith("* ")) {
                          return (
                            <div key={idx} className="flex items-start gap-1.5 pl-2">
                              <span className="w-1.5 h-1.5 bg-blue-500 rounded-full mt-1.5 shrink-0" />
                              <span>{line.substring(2)}</span>
                            </div>
                          );
                        }
                        if (line.startsWith("Disclaimer:") || line.startsWith("Warning:")) {
                          return (
                            <span key={idx} className="block text-[10px] font-semibold text-slate-400 dark:text-slate-500 mt-2 italic border-t border-slate-100 dark:border-slate-800 pt-2 leading-relaxed">
                              {line}
                            </span>
                          );
                        }
                        return <p key={idx}>{line}</p>;
                      })}
                    </div>
                  </div>

                  {/* Actions inside message: Copy response and Read Aloud */}
                  <div className={`absolute bottom-2 ${msg.role === "user" ? "left-2" : "right-2"} opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 bg-white/95 dark:bg-slate-900/95 rounded-lg p-0.5 shadow-sm border border-slate-150 dark:border-slate-800`}>
                    <button
                      type="button"
                      onClick={() => handleCopy(msg.id, msg.content)}
                      className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition cursor-pointer"
                      title="Copy response to clipboard"
                    >
                      {copiedId === msg.id ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                    </button>
                    {msg.role === "assistant" && (
                      <button
                        type="button"
                        onClick={() => handleReadAloud(msg.id, msg.content)}
                        className={`p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition cursor-pointer ${
                          speakingMessageId === msg.id 
                            ? "text-blue-600 dark:text-blue-400 animate-bounce" 
                            : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                        }`}
                        title={speakingMessageId === msg.id ? "Stop Reading Aloud" : "Read Aloud"}
                      >
                        <Volume2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>

          {generating && (
            <div className="flex gap-3 mr-auto max-w-[85%]">
              <div className="w-8 h-8 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center shrink-0">
                <Bot className="w-4 h-4 text-blue-600" />
              </div>
              <div className="bg-white border border-slate-150 p-3.5 rounded-2xl rounded-tl-none shadow-sm flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-600 animate-bounce" style={{ animationDelay: "0ms" }}></span>
                <span className="w-1.5 h-1.5 rounded-full bg-blue-600 animate-bounce" style={{ animationDelay: "150ms" }}></span>
                <span className="w-1.5 h-1.5 rounded-full bg-blue-600 animate-bounce" style={{ animationDelay: "300ms" }}></span>
              </div>
            </div>
          )}

          {error && (
            <div className="p-3 bg-rose-50 dark:bg-rose-950/30 border border-rose-100 dark:border-rose-900 text-rose-600 dark:text-rose-400 rounded-xl text-xs font-semibold text-center max-w-md mx-auto animate-pulse">
              {error}
            </div>
          )}

          <div ref={chatEndRef} />
        </div>

        {/* Suggestion questions drawer (only visible if messages are empty or only has greeting) */}
        {messages.length <= 1 && (
          <div className="px-4 py-2 bg-slate-50 dark:bg-slate-900/40 border-t border-slate-100 dark:border-slate-800 space-y-2">
            <span className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest block">Suggested consultations</span>
            <div className="flex flex-wrap gap-1.5 pb-1">
              {SUGGESTED_QUESTIONS.map((question, i) => (
                <button
                  key={i}
                  id={`suggested-q-${i}`}
                  onClick={() => !generating && handleSend(question)}
                  className="px-2.5 py-1.5 bg-white dark:bg-slate-950 hover:bg-blue-50 dark:hover:bg-blue-950/40 border border-slate-200 dark:border-slate-800 hover:border-blue-300 dark:hover:border-blue-900 text-slate-700 dark:text-slate-300 text-[10px] font-semibold rounded-xl text-left transition cursor-pointer shadow-sm"
                >
                  {question}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Chat input form */}
        <form
          id="chat-input-form"
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="p-3 border-t border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 flex items-center gap-2"
        >
          <input
            id="chat-text-input"
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={generating}
            className="flex-1 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 focus:border-blue-500 dark:focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 rounded-xl px-4 py-3 text-xs font-medium transition outline-none placeholder:text-slate-400 dark:placeholder:text-slate-500 text-slate-800 dark:text-slate-100"
            placeholder="Type your health question (e.g. Symptoms of COVID-19)..."
          />
          <button
            id="btn-chat-mic"
            type="button"
            onClick={toggleListening}
            className={`p-3 rounded-xl transition cursor-pointer ${
              isListening 
                ? "bg-red-500 hover:bg-red-600 text-white animate-pulse" 
                : "bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
            }`}
            title={isListening ? "Listening... Click to stop" : "Use Voice Input"}
          >
            {isListening ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
          </button>
          <button
            id="btn-chat-send"
            type="submit"
            disabled={!input.trim() || generating}
            className="p-3 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-100 dark:disabled:bg-slate-800 disabled:text-slate-400 dark:disabled:text-slate-600 disabled:shadow-none text-white rounded-xl shadow-md shadow-blue-500/10 transition cursor-pointer"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>

      </div>

    </div>
  );
}

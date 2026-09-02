"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { Bot, ImagePlus, LoaderCircle, RotateCcw, Send, Sparkles, UserRound, X } from "lucide-react";

type Message = { id: string; role: "assistant" | "user"; content: string; imageName?: string };

const VISITOR_ID_KEY = "h5-chat-visitor-id";

function makeVisitorId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `visitor-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function makeMessageId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `message-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function ChatIndexPage() {
  const [visitorId] = useState(() => {
    if (typeof window === "undefined") return "";
    const stored = window.localStorage.getItem(VISITOR_ID_KEY) || makeVisitorId();
    window.localStorage.setItem(VISITOR_ID_KEY, stored);
    return stored;
  });
  const [visitorName, setVisitorName] = useState("访客");
  const [draft, setDraft] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "assistant",
      content: "你好，我是在线助手。请告诉我你遇到的问题，我会尽快帮你排查。",
    },
  ]);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = scrollRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, [messages, isSending]);

  async function sendMessage(event?: FormEvent) {
    event?.preventDefault();
    const content = draft.trim();
    if ((!content && !image) || isSending) return;

    setError("");
    setDraft("");
    setMessages((current) => [...current, { id: makeMessageId(), role: "user", content, imageName: image?.name }]);
    const selectedImage = image;
    setImage(null);
    setImagePreview("");
    setIsSending(true);

    try {
      const form = new FormData();
      form.append("visitor_id", visitorId || "");
      form.append("visitor_name", visitorName || "访客");
      form.append("content", content || "请分析这张图片中的摄像头问题。");
      form.append("lang", "cn");
      if (selectedImage) form.append("image", selectedImage, selectedImage.name);
      const response = await fetch("/api/v1/9808/conring/robot/chat", { method: "POST", body: form });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.error === "string" ? body.error : "发送失败，请稍后再试");
      setMessages((current) => [
        ...current,
        {
          id: body.message_id || makeMessageId(),
          role: "assistant",
          content: body.answer || body.content || "暂时没有收到有效回复。",
        },
      ]);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "发送失败，请稍后再试");
    } finally {
      setIsSending(false);
    }
  }

  function selectImage(file: File | undefined) {
    if (!file) return;
    if (!["image/jpeg", "image/png", "image/webp", "image/gif"].includes(file.type)) {
      setError("请选择 JPG、PNG、WEBP 或 GIF 图片");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError("图片不能超过 10 MB");
      return;
    }
    setError("");
    setImage(file);
    setImagePreview(URL.createObjectURL(file));
  }

  async function resetConversation() {
    await fetch("/api/v1/9808/conring/robot/chat", { method: "DELETE" }).catch(() => undefined);
    setMessages([
      {
        id: `welcome-${Date.now()}`,
        role: "assistant",
        content: "新的对话已准备好。请告诉我你遇到的问题。",
      },
    ]);
    setError("");
    setImage(null);
    setImagePreview("");
  }

  return (
    <main className="h5-chat-shell">
      <section className="h5-chat-panel" aria-label="在线客服">
        <header className="h5-chat-header">
          <div className="h5-chat-brand">
            <span className="h5-chat-brand-mark"><Sparkles size={18} aria-hidden="true" /></span>
            <div>
              <h1>在线助手</h1>
              <p><span className="h5-online-dot" /> 在线服务中</p>
            </div>
          </div>
          <button className="h5-icon-button" type="button" onClick={resetConversation} aria-label="开始新对话" title="开始新对话">
            <RotateCcw size={18} aria-hidden="true" />
          </button>
        </header>

        <div className="h5-chat-messages" ref={scrollRef} aria-live="polite">
          {messages.map((message) => (
            <div className={`h5-message-row ${message.role}`} key={message.id}>
              <span className="h5-message-avatar" aria-hidden="true">
                {message.role === "assistant" ? <Bot size={17} /> : <UserRound size={17} />}
              </span>
              <div className="h5-message-bubble">{message.imageName && <span className="h5-image-note">图片：{message.imageName}</span>}{message.content && <p>{message.content}</p>}</div>
            </div>
          ))}
          {isSending && (
            <div className="h5-message-row assistant">
              <span className="h5-message-avatar" aria-hidden="true"><Bot size={17} /></span>
              <p className="h5-message-bubble h5-typing"><LoaderCircle size={16} className="h5-spin" /> 正在整理回复</p>
            </div>
          )}
        </div>

        <form className="h5-chat-composer" onSubmit={sendMessage}>
          <label className="h5-name-field">
            <span>称呼</span>
            <input value={visitorName} onChange={(event) => setVisitorName(event.target.value.slice(0, 80))} maxLength={80} />
          </label>
          {imagePreview && <div className="h5-image-preview"><img src={imagePreview} alt="待发送的故障图片" /><button type="button" onClick={() => { setImage(null); setImagePreview(""); }} aria-label="移除图片" title="移除图片"><X size={15} /></button></div>}
          <div className="h5-input-row">
            <label className="h5-upload-button" aria-label="上传故障图片" title="上传故障图片"><ImagePlus size={18} /><input type="file" accept="image/jpeg,image/png,image/webp,image/gif" onChange={(event) => { selectImage(event.target.files?.[0]); event.currentTarget.value = ""; }} /></label>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendMessage();
                }
              }}
              placeholder="输入你想咨询的内容"
              maxLength={4000}
              rows={2}
              aria-label="消息内容"
            />
            <button className="h5-send-button" type="submit" disabled={isSending || (!draft.trim() && !image)} aria-label="发送消息" title="发送消息">
              {isSending ? <LoaderCircle size={19} className="h5-spin" /> : <Send size={19} aria-hidden="true" />}
            </button>
          </div>
          {error && <p className="h5-chat-error" role="alert">{error}</p>}
          <p className="h5-chat-footnote">请勿在对话中发送身份证号、银行卡号等敏感信息</p>
        </form>
      </section>
    </main>
  );
}

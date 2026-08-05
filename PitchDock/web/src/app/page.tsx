"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Navbar from "@/components/Navbar";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://www.pitchdock.xyz";

interface Feedback {
  id: number;
  name: string;
  rating: number;
  comment: string;
  created_at: string;
}

interface ChatMessage {
  id: string;
  sender: "in" | "out";
  time: string;
  content: React.ReactNode;
}

export default function LandingPage() {
  const router = useRouter();
  const [selectedHighlight, setSelectedHighlight] = useState<"fullstack" | "aws" | "backend">("fullstack");
  const [isAnnual, setIsAnnual] = useState(false);
  const [displayedText, setDisplayedText] = useState("");

  const loadRazorpayScript = () => {
    return new Promise((resolve) => {
      if (typeof window === "undefined") return resolve(false);
      if ((window as any).Razorpay) return resolve(true);
      const script = document.createElement("script");
      script.src = "https://checkout.razorpay.com/v1/checkout.js";
      script.onload = () => resolve(true);
      script.onerror = () => resolve(false);
      document.body.appendChild(script);
    });
  };

  const handleSubscribe = async (tier: string) => {
    if (tier === "free") {
      router.push("/signup");
      return;
    }

    const token = typeof window !== "undefined" ? localStorage.getItem("authToken") : null;
    if (!token) {
      router.push(`/signup?plan=${tier}`);
      return;
    }

    try {
      const scriptLoaded = await loadRazorpayScript();
      if (!scriptLoaded) {
        alert("Failed to load Razorpay SDK. Please check your internet connection.");
        return;
      }

      const res = await fetch(`${API_BASE}/api/payments/create-order`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          plan_tier: tier,
          billing_cycle: isAnnual ? "annual" : "monthly"
        })
      });

      if (!res.ok) {
        router.push(`/login?plan=${tier}`);
        return;
      }

      const orderData = await res.json();
      const options = {
        key: orderData.key,
        amount: orderData.amount,
        currency: orderData.currency,
        name: orderData.name,
        description: orderData.description,
        order_id: orderData.order_id,
        prefill: orderData.prefill,
        handler: async function (response: any) {
          try {
            await fetch(`${API_BASE}/api/payments/verify`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
              },
              body: JSON.stringify({
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_order_id: response.razorpay_order_id,
                razorpay_signature: response.razorpay_signature,
                plan_tier: tier,
                billing_cycle: isAnnual ? "annual" : "monthly"
              })
            });
            alert(`Successfully upgraded plan to ${tier.toUpperCase()}!`);
            router.push("/dashboard");
          } catch (verifyErr: any) {
            alert(`Payment verification failed: ${verifyErr.message}`);
          }
        },
        theme: { color: "#FF5A2E" }
      };

      const paymentObj = new (window as any).Razorpay(options);
      paymentObj.open();
    } catch (e: any) {
      router.push(`/signup?plan=${tier}`);
    }
  };

  // Interactive Telegram Phone Chat simulation state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    {
      id: "1",
      sender: "in",
      time: "14:02",
      content: (
        <>
          Account linked — <b>you@gmail.com</b>. Type "status" or "send 5 emails".
        </>
      )
    },
    {
      id: "2",
      sender: "out",
      time: "14:04",
      content: "status"
    },
    {
      id: "3",
      sender: "in",
      time: "14:05",
      content: (
        <>
          <b>Live campaign status</b><br />
          Quota: 18 / 50 sent today<br />
          Queue: 32 pending contacts<br />
          Channel: Gmail API — connected
        </>
      )
    },
    {
      id: "4",
      sender: "out",
      time: "14:06",
      content: "send 5 emails"
    },
    {
      id: "5",
      sender: "in",
      time: "14:06",
      content: (
        <>
          <b>Dispatched</b><br />
          5 personalized emails sent with résumé attached to Apple, Google & Meta recruiters.
        </>
      )
    }
  ]);
  const [chatInput, setChatInput] = useState("");
  const [isBotTyping, setIsBotTyping] = useState(false);

  const handleSendChat = (commandText?: string) => {
    const textToSend = commandText || chatInput;
    if (!textToSend.trim()) return;

    const now = new Date();
    const timeStr = `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}`;

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      sender: "out",
      time: timeStr,
      content: textToSend
    };

    setChatMessages((prev) => [...prev, userMsg]);
    if (!commandText) setChatInput("");
    setIsBotTyping(true);

    setTimeout(() => {
      setIsBotTyping(false);
      let botReply: React.ReactNode = "";
      const lower = textToSend.toLowerCase();

      if (lower.includes("status")) {
        botReply = (
          <>
            <b>Live campaign status</b><br />
            Quota: 23 / 50 sent today<br />
            Queue: 27 pending contacts<br />
            Channel: Gmail API — connected
          </>
        );
      } else if (lower.includes("send")) {
        botReply = (
          <>
            <b>Dispatched</b><br />
            5 personalized emails sent with résumé attached to target recruiters.
          </>
        );
      } else {
        botReply = (
          <>
            <b>Agent Response</b><br />
            Command "{textToSend}" received. Type "status" or "send 5 emails".
          </>
        );
      }

      setChatMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          sender: "in",
          time: timeStr,
          content: botReply
        }
      ]);
    }, 650);
  };

  // Feedback states
  const [feedbacks, setFeedbacks] = useState<Feedback[]>([]);
  const [feedbackName, setFeedbackName] = useState("");
  const [feedbackRating, setFeedbackRating] = useState(5);
  const [feedbackComment, setFeedbackComment] = useState("");
  const [feedbackSubmitSuccess, setFeedbackSubmitSuccess] = useState(false);
  const [isSubmittingFeedback, setIsSubmittingFeedback] = useState(false);

  // Support Form states
  const [supportName, setSupportName] = useState("");
  const [supportEmail, setSupportEmail] = useState("");
  const [supportSubject, setSupportSubject] = useState("General Query");
  const [supportMessage, setSupportMessage] = useState("");
  const [supportSubmitSuccess, setSupportSubmitSuccess] = useState("");
  const [supportError, setSupportError] = useState("");
  const [isSubmittingSupport, setIsSubmittingSupport] = useState(false);

  useEffect(() => {
    const fetchFeedbacks = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/feedback`);
        if (res.ok) {
          const data = await res.json();
          setFeedbacks(data.feedbacks || []);
        }
      } catch (e) {
        console.error("Error loading feedbacks:", e);
      }
    };
    fetchFeedbacks();
  }, []);

  const getEmailBodyText = () => {
    if (selectedHighlight === "fullstack") {
      return `Hi Sarah,\n\nI noticed Apple Inc. is expanding its full-stack engineering team. Over the past 3 years, I architected React & Node.js microservices handling high-throughput traffic with sub-50ms response times.\n\nI've attached my updated résumé (PDF). Would love 10 mins to chat about how my experience aligns with your upcoming engineering roadmap.\n\nBest,\nAlex`;
    }
    if (selectedHighlight === "aws") {
      return `Hi Sarah,\n\nSaw that Apple is building out cloud infrastructure. Recently, I spearheaded an enterprise migration to AWS ECS & Terraform, reducing cloud infrastructure overhead by $120k annually and accelerating CI/CD pipeline deployments.\n\nMy résumé is attached below for your review. Looking forward to connecting!\n\nBest,\nAlex`;
    }
    return `Hi Sarah,\n\nImpressive growth on Apple's developer platform! I recently built high-throughput gRPC & REST APIs serving 2M daily active users with 99.99% uptime.\n\nI've attached my résumé for your review. Would love to share how I can contribute to your core backend engineering team.\n\nBest,\nAlex`;
  };

  useEffect(() => {
    const fullText = getEmailBodyText();
    setDisplayedText("");
    let currentIdx = 0;
    let switchTimer: NodeJS.Timeout | null = null;
    
    const interval = setInterval(() => {
      if (currentIdx < fullText.length) {
        setDisplayedText(fullText.substring(0, currentIdx + 1));
        currentIdx++;
      } else {
        clearInterval(interval);
        switchTimer = setTimeout(() => {
          setSelectedHighlight((prev) => {
            if (prev === "fullstack") return "aws";
            if (prev === "aws") return "backend";
            return "fullstack";
          });
        }, 3200);
      }
    }, 14);
    
    return () => {
      clearInterval(interval);
      if (switchTimer) clearTimeout(switchTimer);
    };
  }, [selectedHighlight]);

  const handleSupportSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSupportError("");
    setSupportSubmitSuccess("");
    if (!supportName.trim() || !supportEmail.trim() || !supportMessage.trim()) {
      setSupportError("Please fill out all required fields.");
      return;
    }
    setIsSubmittingSupport(true);
    try {
      const res = await fetch(`${API_BASE}/api/support`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: supportName,
          email: supportEmail,
          subject: supportSubject,
          message: supportMessage
        })
      });
      if (res.ok) {
        setSupportSubmitSuccess("Your query has been submitted. Our team will get back to you shortly!");
        setSupportName("");
        setSupportEmail("");
        setSupportMessage("");
      } else {
        setSupportError("Failed to submit support query. Please try again.");
      }
    } catch (e) {
      setSupportError("Connection error. Please check your network and try again.");
    } finally {
      setIsSubmittingSupport(false);
    }
  };

  const handleFeedbackSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!feedbackName.trim() || !feedbackComment.trim()) return;
    setIsSubmittingFeedback(true);
    try {
      const res = await fetch(`${API_BASE}/api/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: feedbackName,
          rating: feedbackRating,
          comment: feedbackComment
        })
      });
      if (res.ok) {
        setFeedbackSubmitSuccess(true);
        setFeedbackName("");
        setFeedbackComment("");
        setFeedbackRating(5);
        const refRes = await fetch(`${API_BASE}/api/feedback`);
        if (refRes.ok) {
          const data = await refRes.json();
          setFeedbacks(data.feedbacks || []);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsSubmittingFeedback(false);
    }
  };

  return (
    <>
      <div className="grid-backdrop"></div>
      <Navbar />

      {/* HERO SECTION */}
      <section className="hero">
        <div className="wrap hero-grid">
          <div>
            <div className="eyebrow">AI recruiter outreach · cold email automator</div>
            <h1>Skip the filter.<br />Land in the <span className="accent">inbox.</span></h1>
            <p className="lede">
              PitchDock writes a personalized email for every recruiter you target, attaches your résumé, and paces delivery so it never reads as a bulk send — you spend your time interviewing, not following up.
            </p>
            <div className="hero-ctas">
              <Link href="/signup" className="btn btn-primary">Start for free &rarr;</Link>
              <a href="#agent" className="tertiary">📱 Telegram mobile agent</a>
              <a href="#demo" className="tertiary">See a sample email &darr;</a>
            </div>
            <div className="rating-row">
              <span className="stars">★★★★★</span> 4.9/5 — from 300+ engineers
            </div>
          </div>

          {/* SIGNAL PANEL ROUTE TRACER */}
          <div className="signal-panel">
            <div className="panel-label">
              <span>route.trace</span>
              <span><span className="dot">●</span> live</span>
            </div>
            <svg id="routeSvg" viewBox="0 0 520 300" fill="none" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <pattern id="p1" width="26" height="26" patternUnits="userSpaceOnUse">
                  <path d="M 26 0 L 0 0 0 26" fill="none" stroke="rgba(139,147,161,0.08)" strokeWidth="1"/>
                </pattern>
              </defs>
              <rect width="520" height="300" fill="url(#p1)"/>

              {/* ATS Filter Wall */}
              <g opacity="0.85">
                <line x1="255" y1="20" x2="255" y2="280" stroke="rgba(92,122,158,0.35)" strokeWidth="1.5" strokeDasharray="3 5"/>
                <g fill="none" stroke="#5C7A9E" strokeWidth="1.6" opacity="0.55">
                  <path d="M245 40 L265 60 M265 40 L245 60"/>
                  <path d="M245 90 L265 110 M265 90 L245 110"/>
                  <path d="M245 140 L265 160 M265 140 L245 160"/>
                  <path d="M245 190 L265 210 M265 190 L245 210"/>
                  <path d="M245 240 L265 260 M265 240 L245 260"/>
                </g>
                <text x="255" y="14" textAnchor="middle" fontFamily="IBM Plex Mono" fontSize="9" fill="#5C7A9E">ATS FILTER</text>
              </g>

              {/* You node */}
              <g className="you-node">
                <circle cx="60" cy="150" r="22" fill="#161A22" stroke="#2A313D" strokeWidth="1.4"/>
                <text x="60" y="154" textAnchor="middle" fontSize="10" fill="#ECE9E1" fontWeight="600">YOU</text>
              </g>

              {/* Recruiter node */}
              <g className="human-node">
                <circle cx="456" cy="150" r="32" fill="#161A22" stroke="#FF5A2E" strokeWidth="1.6"/>
                <text x="456" y="153" textAnchor="middle" fontSize="8.5" fill="#FF8A5C" fontWeight="600" letterSpacing="0.03em">RECRUITER</text>
              </g>

              {/* Routing Path */}
              <path id="routePath" d="M82,150 C140,150 170,70 255,60 C330,50 370,90 424,150" fill="none" stroke="rgba(255,90,46,0.18)" strokeWidth="2"/>
              <circle r="4.5" fill="#FF5A2E">
                <animateMotion dur="3.2s" repeatCount="indefinite" rotate="auto">
                  <mpath href="#routePath"/>
                </animateMotion>
              </circle>

              <text x="150" y="230" fontFamily="IBM Plex Mono" fontSize="9" fill="#5B6270">resume.pdf attached</text>
              <text x="150" y="245" fontFamily="IBM Plex Mono" fontSize="9" fill="#5B6270">send-pace: staggered</text>
            </svg>
          </div>
        </div>
      </section>

      {/* TRUST BAR */}
      <div className="trust-bar">
        <div className="wrap trust-inner">
          <span className="trust-label">Outreach sent to recruiters at</span>
          <div className="trust-logos">
            <span>Google</span>
            <span>Amazon</span>
            <span>Apple</span>
            <span>Meta</span>
            <span>Netflix</span>
          </div>
        </div>
      </div>

      {/* DEMO SECTION */}
      <section className="demo" id="demo">
        <div className="wrap">
          <div className="section-head">
            <div className="eyebrow blue">Watch it write the email</div>
            <h2>Pick a recruiter. Watch the pitch rewrite itself.</h2>
            <p>See how PitchDock rewrites the outreach for Sarah, a technical recruiter at Apple — before it ever leaves your outbox.</p>
          </div>

          <div className="demo-grid">
            <div className="recruiter-card">
              <div className="r-head">
                <div className="r-avatar">SJ</div>
                <div>
                  <div className="r-name">Sarah Jenkins</div>
                  <div className="r-role">Lead Technical Recruiter · Apple Inc.</div>
                </div>
              </div>
              <div className="eyebrow" style={{ marginBottom: "6px" }}>Message focus</div>
              <div className="tag-row">
                <button
                  type="button"
                  onClick={() => setSelectedHighlight("fullstack")}
                  className={`tag ${selectedHighlight === "fullstack" ? "active" : ""}`}
                >
                  Full-Stack Development
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedHighlight("aws")}
                  className={`tag ${selectedHighlight === "aws" ? "active" : ""}`}
                >
                  AWS Cloud & CI/CD
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedHighlight("backend")}
                  className={`tag ${selectedHighlight === "backend" ? "active" : ""}`}
                >
                  Backend & High-Throughput APIs
                </button>
              </div>
            </div>

            <div className="email-mock">
              <div className="toolbar">
                <span className="dotr"></span>
                <span className="dotr"></span>
                <span className="dotr"></span>
                <span className="fname">compose.eml</span>
              </div>
              <div className="email-body">
                <div className="email-row"><b>To</b> sjenkins@apple.com</div>
                <div className="email-subject">Exploring Senior Software Engineer opportunities at Apple Inc.</div>
                <div className="email-content">
                  <div style={{ height: "235px", overflow: "hidden" }}>
                    <pre style={{ whiteSpace: "pre-wrap", fontFamily: "var(--font-body)", fontSize: "14px", color: "var(--text-muted)", lineHeight: "1.55", margin: 0 }}>
                      {displayedText}
                      <span style={{ color: "var(--signal)", fontWeight: "bold" }}>|</span>
                    </pre>
                  </div>
                  <div style={{ marginTop: "10px", paddingTop: "10px", borderTop: "1px dashed var(--border)" }}>
                    <span className="attach">📎 candidate_resume_2026.pdf — attached</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* VIDEO WALKTHROUGH SECTION */}
      <section className="video-section" id="video" style={{ padding: "100px 0", position: "relative", overflow: "hidden", background: "radial-gradient(circle at 50% 30%, rgba(255, 90, 46, 0.08) 0%, rgba(10, 14, 23, 1) 70%)" }}>
        {/* Glow backdrop */}
        <div style={{
          position: "absolute",
          top: "45%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: "85%",
          height: "65%",
          background: "radial-gradient(ellipse at center, rgba(255, 90, 46, 0.18) 0%, rgba(0, 0, 0, 0) 75%)",
          filter: "blur(60px)",
          pointerEvents: "none"
        }}></div>

        <div className="wrap" style={{ maxWidth: "1200px", textAlign: "center", position: "relative", zIndex: 1 }}>
          {/* Browser Container Frame */}
          <div style={{
            borderRadius: "20px",
            border: "1px solid rgba(255, 255, 255, 0.12)",
            boxShadow: "0 30px 90px rgba(0, 0, 0, 0.85), 0 0 45px rgba(255, 90, 46, 0.15)",
            background: "#0d1117",
            overflow: "hidden"
          }}>
            {/* Header bar */}
            <div style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "14px 20px",
              background: "rgba(255, 255, 255, 0.03)",
              borderBottom: "1px solid rgba(255, 255, 255, 0.08)"
            }}>
              <div style={{ display: "flex", gap: "8px" }}>
                <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: "#FF5F56", display: "inline-block" }}></span>
                <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: "#FFBD2E", display: "inline-block" }}></span>
                <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: "#27C93F", display: "inline-block" }}></span>
              </div>
              <div style={{ fontSize: "13px", fontFamily: "var(--font-mono)", color: "rgba(255, 255, 255, 0.45)", fontWeight: "500", display: "flex", alignItems: "center", gap: "6px" }}>
                <span style={{ color: "var(--signal)" }}>▶</span> pitchdock_product_walkthrough.mp4
              </div>
              <div style={{ width: "52px" }}></div>
            </div>

            {/* Video Player 16:9 Wrapper */}
            <div style={{
              position: "relative",
              paddingBottom: "56.25%",
              height: 0,
              overflow: "hidden",
              background: "#000000"
            }}>
              <iframe
                src="https://www.youtube.com/embed/f5x53-gkbyQ?autoplay=1&mute=1&playlist=f5x53-gkbyQ&loop=1&start=43&rel=0&controls=0&modestbranding=1&showinfo=0&iv_load_policy=3"
                title="PitchDock Product Walkthrough"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                allowFullScreen
                style={{
                  position: "absolute",
                  top: "-5%",
                  left: "-5%",
                  width: "110%",
                  height: "110%",
                  border: "none",
                  pointerEvents: "none"
                }}
              />
            </div>
          </div>
        </div>
      </section>

      {/* MOBILE AGENT */}
      <section className="agent" id="agent">
        <div className="wrap agent-grid">
          <div>
            <div className="eyebrow">Included in all plans</div>
            <h2 style={{ fontSize: "clamp(26px,3.4vw,36px)", maxWidth: "480px" }}>Run your whole outreach from Telegram.</h2>
            <p style={{ color: "var(--text-muted)", marginTop: "14px", maxWidth: "460px" }}>
              Never lose momentum mid-search. Your personal AI outreach manager lives in your pocket — pair your account once, then run campaigns from anywhere.
            </p>

            <div className="agent-features">
              <div className="agent-feature">
                <div className="ico">💬</div>
                <div>
                  <h4>Natural language chat</h4>
                  <p>Ask for live campaign status, remaining daily quota, or pending drafts — in plain English.</p>
                </div>
              </div>
              <div className="agent-feature">
                <div className="ico">⚡</div>
                <div>
                  <h4>On-the-go dispatch</h4>
                  <p>Type "send 5 emails" or "launch campaign" and PitchDock sends, wherever you are.</p>
                </div>
              </div>
              <div className="agent-feature">
                <div className="ico">🔒</div>
                <div>
                  <h4>Secure one-click linking</h4>
                  <p>Pair your Telegram chat with a single-use token generated from your dashboard.</p>
                </div>
              </div>
            </div>
          </div>

          <div style={{ position: "relative", width: "100%", maxWidth: "315px", margin: "0 auto", display: "flex", justifyContent: "center" }}>
            <img 
              src="/iphonewithchat.png" 
              alt="PitchDock Telegram Mobile Agent" 
              style={{ width: "100%", height: "auto", display: "block", filter: "drop-shadow(0 15px 35px rgba(0,0,0,0.8))" }} 
            />
          </div>
        </div>
      </section>

      {/* FEATURES */}
      <section className="features" id="features">
        <div className="wrap">
          <div className="section-head">
            <div className="eyebrow">The pipeline</div>
            <h2>Five steps, every send.</h2>
            <p>Matching, writing, attaching, pacing, and mobile control — in that order — so nothing that leaves your account ever looks like a bulk blast.</p>
          </div>

          <div className="feature-grid">
            <div className="feature-cell">
              <div className="feature-num">01 / MATCHING</div>
              <div>
                <h3>Company category matcher</h3>
                <p>Every recruiter's company is sorted — MNC product, IT services, staffing agency — so the message matches what that recruiter actually screens for.</p>
              </div>
            </div>
            <div className="feature-cell">
              <div className="feature-num">02 / WRITING</div>
              <div>
                <h3>AI-powered personalization</h3>
                <p>Your strongest accomplishments are rewritten for the recruiter's company and role, automatically, for every single send.</p>
              </div>
            </div>
            <div className="feature-cell">
              <div className="feature-num">03 / ATTACHING</div>
              <div>
                <h3>Direct résumé attachments</h3>
                <p>Your CV goes out as a real file attachment — not a link recruiters have to click and trust.</p>
              </div>
            </div>
            <div className="feature-cell">
              <div className="feature-num">04 / PACING</div>
              <div>
                <h3>Deliverability & stagger queue</h3>
                <p>A built-in delay guard spaces out sends across each batch, so your domain never reads as a bulk mailer to spam filters.</p>
              </div>
            </div>
            <div className="feature-cell">
              <div className="feature-num">05 / MOBILE</div>
              <div>
                <h3>Telegram remote control</h3>
                <p>Check campaign status, remaining limits, and trigger dispatches from your phone via the official bot.</p>
              </div>
            </div>
            <div className="feature-cell" style={{ background: "var(--signal-dim)" }}>
              <div className="feature-num" style={{ color: "var(--signal-soft)" }}>06 / RESULT</div>
              <div>
                <h3 style={{ color: "var(--signal-soft)" }}>Interviews, not silence</h3>
                <p>The pipeline exists for one outcome: your email gets opened by a person, not archived by a filter.</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* COMPARISON */}
      <section className="compare">
        <div className="wrap">
          <div className="section-head">
            <div className="eyebrow blue">Why engineers switch</div>
            <h2>Set next to the alternatives.</h2>
            <p>Manual pitching doesn't scale. Bulk mailers get filtered. Here's where PitchDock sits between them.</p>
          </div>

          <div style={{ overflowX: "auto" }}>
            <table className="cmp">
              <thead>
                <tr>
                  <th>Capability</th>
                  <th className="hicol">PitchDock</th>
                  <th>Manual pitching</th>
                  <th>Bulk mailers</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Personalized per-recruiter accomplishments</td>
                  <td className="hicol"><span className="yes">✓</span> AI-powered, automatic</td>
                  <td><span className="yes">✓</span> Manual, slow</td>
                  <td><span className="no">✕</span> Single template only</td>
                </tr>
                <tr>
                  <td>Résumé PDFs & documents</td>
                  <td className="hicol"><span className="yes">✓</span> Attached automatically</td>
                  <td><span className="yes">✓</span> Supported</td>
                  <td><span className="no">✕</span> Links only, often blocked</td>
                </tr>
                <tr>
                  <td>Send-pacing & stagger safety</td>
                  <td className="hicol"><span className="yes">✓</span> Delay guard on every batch</td>
                  <td>— not applicable</td>
                  <td><span className="no">✕</span> Bulk blasts, spam risk</td>
                </tr>
                <tr>
                  <td>Category-specific recruiter targeting</td>
                  <td className="hicol"><span className="yes">✓</span> IT services / MNC filter</td>
                  <td><span className="yes">✓</span> Manual lookup</td>
                  <td><span className="no">✕</span> Static list filter only</td>
                </tr>
                <tr>
                  <td>Cached résumé rewrites per company</td>
                  <td className="hicol"><span className="yes">✓</span> 15 / month included</td>
                  <td>— not applicable</td>
                  <td>— not applicable</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* PRICING */}
      <section className="pricing" id="pricing">
        <div className="wrap">
          <div className="section-head">
            <div className="eyebrow">Plans</div>
            <h2>Fair, transparent pricing.</h2>
            <p>Built around how many recruiters you're reaching this month. Start free — upgrade only when you're ready to scale.</p>
          </div>

          <div className="price-toggle">
            <button
              type="button"
              className={!isAnnual ? "active" : ""}
              onClick={() => setIsAnnual(false)}
            >
              Monthly billing
            </button>
            <button
              type="button"
              className={isAnnual ? "active" : ""}
              onClick={() => setIsAnnual(true)}
            >
              Annual billing — save 20%
            </button>
          </div>

          <div className="price-grid">
            <div className="price-card">
              <div className="plan-name">Free starter</div>
              <div className="plan-price">₹0<span>/mo</span></div>
              <div className="plan-desc">Try AI-tailored drafts and see how the personalizer works, at a small volume.</div>
              <ul className="plan-feats">
                <li><span className="m">✓</span> AI drafts (first 5)</li>
                <li><span className="m">✓</span> 5 emails / day</li>
                <li><span className="m">✓</span> Company category filter</li>
                <li><span className="m">📱</span> Telegram mobile agent</li>
                <li className="off"><span className="m">✕</span> Custom SMTP config</li>
                <li className="off"><span className="m">✕</span> Company HR search</li>
              </ul>
              <button type="button" onClick={() => handleSubscribe("free")} className="btn btn-ghost btn-block">Start free</button>
            </div>

            <div className="price-card">
              <div className="plan-name">Basic AI</div>
              <div className="plan-price">{isAnnual ? "₹239" : "₹299"}<span>/mo</span></div>
              <div className="plan-desc">For job hunters starting a real, automated outreach campaign.</div>
              <ul className="plan-feats">
                <li><span className="m">✓</span> AI drafts (first 20)</li>
                <li><span className="m">✓</span> 20 emails / day</li>
                <li><span className="m">✓</span> Company category filter</li>
                <li><span className="m">✓</span> Custom SMTP config</li>
                <li><span className="m">📱</span> Telegram mobile agent</li>
                <li className="off"><span className="m">✕</span> Company HR search</li>
              </ul>
              <button type="button" onClick={() => handleSubscribe("basic")} className="btn btn-ghost btn-block">Choose Basic</button>
            </div>

            <div className="price-card hi" style={{ gridColumn: "span 2", maxWidth: "520px", margin: "0 auto", width: "100%" }}>
              <div className="plan-name">Standard Pro</div>
              <div className="plan-price">{isAnnual ? "₹399" : "₹499"}<span>/mo</span></div>
              <div className="plan-desc">For serious job hunters wanting full outreach automation & custom targeting.</div>
              <ul className="plan-feats">
                <li><span className="m">✓</span> AI drafts & personalizations</li>
                <li><span className="m">✓</span> 200 emails / day</li>
                <li><span className="m">✓</span> Dynamic JD-based résumé rewrite</li>
                <li><span className="m">✓</span> Company category filter</li>
                <li><span className="m">✓</span> HR & recruiter search</li>
                <li><span className="m">✓</span> Custom SMTP config</li>
                <li><span className="m">📱</span> Telegram mobile agent</li>
              </ul>
              <button type="button" onClick={() => handleSubscribe("standard")} className="btn btn-primary btn-block">Choose Standard Pro ({isAnnual ? "₹399" : "₹499"})</button>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="faq" id="faq">
        <div className="wrap">
          <div className="section-head">
            <div className="eyebrow blue">FAQ</div>
            <h2>Everything you need to know.</h2>
          </div>
          <div className="faq-list">
            <details>
              <summary>How does the AI personalize each email?</summary>
              <div className="a">PitchDock reads the recruiter's company and role focus, then rewrites your strongest accomplishments to match what that specific recruiter screens for — no shared template across sends.</div>
            </details>
            <details>
              <summary>Can I send attachments on the Free plan?</summary>
              <div className="a">Yes. Every plan, including Free Starter, attaches your résumé as a real PDF file rather than a link.</div>
            </details>
            <details>
              <summary>What is the sending stagger delay?</summary>
              <div className="a">A built-in pacing guard spaces sends out across each batch so your domain never reads as a bulk mailer to spam filters.</div>
            </details>
            <details>
              <summary>How does the résumé customizer cache work?</summary>
              <div className="a">PitchDock rewrites your résumé achievements against the recruiter's job description and caches the result, so repeat sends to similar roles stay fast and consistent.</div>
            </details>
          </div>
        </div>
      </section>

      {/* SUPPORT & FEEDBACK SECTION */}
      <section style={{ padding: "80px 0", borderTop: "1px solid var(--border)", background: "var(--surface)" }}>
        <div className="wrap" style={{ maxWidth: "800px" }}>
          <div className="section-head" style={{ textAlign: "center", margin: "0 auto 40px" }}>
            <div className="eyebrow">Support & Queries</div>
            <h2>Need help with your campaign?</h2>
            <p>Send a query directly to our support team and we will assist you within 24 hours.</p>
          </div>

          {supportSubmitSuccess ? (
            <div style={{ padding: "16px", borderRadius: "8px", background: "rgba(87,217,163,0.1)", border: "1px solid var(--good)", color: "var(--good)", textAlign: "center", fontSize: "14px" }}>
              {supportSubmitSuccess}
            </div>
          ) : (
            <form onSubmit={handleSupportSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              {supportError && (
                <div style={{ padding: "12px", borderRadius: "6px", background: "rgba(255,90,46,0.1)", border: "1px solid var(--signal)", color: "var(--signal-soft)", fontSize: "13px" }}>
                  {supportError}
                </div>
              )}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
                <div>
                  <label style={{ fontSize: "12px", color: "var(--text-muted)", fontFamily: "var(--font-mono)", display: "block", marginBottom: "6px" }}>Your Name</label>
                  <input
                    type="text"
                    value={supportName}
                    onChange={(e) => setSupportName(e.target.value)}
                    placeholder="Alex Mercer"
                    style={{ width: "100%", padding: "10px 14px", borderRadius: "8px", background: "var(--bg-elevated)", border: "1px solid var(--border-strong)", color: "var(--text)", outline: "none", fontSize: "14px" }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: "12px", color: "var(--text-muted)", fontFamily: "var(--font-mono)", display: "block", marginBottom: "6px" }}>Email Address</label>
                  <input
                    type="email"
                    value={supportEmail}
                    onChange={(e) => setSupportEmail(e.target.value)}
                    placeholder="alex@example.com"
                    style={{ width: "100%", padding: "10px 14px", borderRadius: "8px", background: "var(--bg-elevated)", border: "1px solid var(--border-strong)", color: "var(--text)", outline: "none", fontSize: "14px" }}
                  />
                </div>
              </div>
              <div>
                <label style={{ fontSize: "12px", color: "var(--text-muted)", fontFamily: "var(--font-mono)", display: "block", marginBottom: "6px" }}>Message</label>
                <textarea
                  rows={4}
                  value={supportMessage}
                  onChange={(e) => setSupportMessage(e.target.value)}
                  placeholder="How can we help your job search campaign?"
                  style={{ width: "100%", padding: "10px 14px", borderRadius: "8px", background: "var(--bg-elevated)", border: "1px solid var(--border-strong)", color: "var(--text)", outline: "none", fontSize: "14px", resize: "none" }}
                ></textarea>
              </div>
              <button
                type="submit"
                disabled={isSubmittingSupport}
                className="btn btn-primary"
                style={{ width: "100%" }}
              >
                {isSubmittingSupport ? "Submitting..." : "Submit Support Query"}
              </button>
            </form>
          )}
        </div>
      </section>

      {/* SECURITY */}
      <section className="security" id="security">
        <div className="wrap">
          <div className="section-head">
            <div className="eyebrow">Security & data trust</div>
            <h2>Built on the Gmail API. Nothing more.</h2>
            <p>Strict Google API Services User Data Policy compliance, by design.</p>
          </div>
          <div className="sec-grid">
            <div className="sec-card">
              <h3>🎯 Application purpose</h3>
              <p>PitchDock is an AI-powered recruiter outreach engine that drafts personalized cold email pitches from your accomplishments and routes them to recruiters and hiring managers — built to help candidates bypass automated ATS filters, not human review.</p>
            </div>
            <div className="sec-card">
              <h3>🛡️ Google OAuth scope</h3>
              <p>PitchDock authenticates your Gmail mailbox to send outreach via Google's official <code style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>gmail.send</code> scope.</p>
              <ul>
                <li>Used exclusively to send outreach you authorize</li>
                <li>Zero inbox access — no reading, storing, or deleting mail</li>
                <li>Compliant with Google's User Data Policy</li>
              </ul>
              <div className="sec-links">
                <Link href="/privacy">Privacy policy &rarr;</Link>
                <Link href="/terms">Terms of service &rarr;</Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* FINAL CTA */}
      <section className="final-cta">
        <div className="wrap">
          <div className="eyebrow" style={{ justifyContent: "center" }}>Ready when you are</div>
          <h2>Reach the recruiter, not the filter.</h2>
          <p>Start free. Upgrade the moment you're ready to scale your search.</p>
          <Link href="/signup" className="btn btn-primary">Start for free &rarr;</Link>
        </div>
      </section>

      {/* FOOTER */}
      <footer>
        <div className="wrap foot-row">
          <div className="foot-tag" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <img src="/orangelogo.png" alt="PitchDock Logo" style={{ height: "20px", width: "20px", borderRadius: "50%", objectFit: "cover" }} />
            <span>PitchDock — reach the recruiter, not the filter.</span>
          </div>
          <div className="foot-links">
            <a href="#features">Features</a>
            <a href="#pricing">Pricing</a>
            <Link href="/privacy">Privacy policy</Link>
            <Link href="/terms">Terms & conditions</Link>
            <Link href="/refund">Refund policy</Link>
            <Link href="/contact">Contact us</Link>
          </div>
        </div>
      </footer>
    </>
  );
}

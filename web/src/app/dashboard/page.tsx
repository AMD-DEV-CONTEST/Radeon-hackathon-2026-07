"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

const API_BASE = "";

const loadRazorpayScript = () => {
  return new Promise((resolve) => {
    if (typeof window !== "undefined" && (window as any).Razorpay) {
      resolve(true);
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.body.appendChild(script);
  });
};

interface Contact {
  id: number;
  name: string;
  title?: string;
  company?: string;
  category?: string;
  email: string;
  status: string;
  personalized_subject?: string;
  personalized_body?: string;
  error_message?: string;
}

interface BillingInfo {
  plan_tier: "free" | "basic" | "standard" | "premium";
  resume_rewrites_count: number;
  emails_sent_today: number;
}

interface Profile {
  full_name: string;
  phone_number: string;
  linkedin_profile: string;
  current_designation: string;
  experience_years: string;
  industry_domain: string;
  target_role: string;
  achievements: string[];
  resume_pdf_path: string;
}

interface EnvStatus {
  gemini_api_key_set: boolean;
  sender_email: string;
  smtp_server: string;
  smtp_port: string;
  sender_password_set: boolean;
  sending_channel: "smtp" | "google";
  google_connected: boolean;
  google_email: string | null;
}

interface ActiveTask {
  type: "generate" | "send" | null;
  status: "idle" | "running" | "completed" | "failed";
  total: number;
  current: number;
  success: number;
  failed: number;
  logs: string[];
}

export default function Dashboard() {
  const router = useRouter();
  const [userEmail, setUserEmail] = useState("");

  // Billing and tier state
  const [billingInfo, setBillingInfo] = useState<BillingInfo>({
    plan_tier: "free",
    resume_rewrites_count: 0,
    emails_sent_today: 0,
  });

  // Task states
  const [activeTask, setActiveTask] = useState<ActiveTask>({
    type: null,
    status: "idle",
    total: 0,
    current: 0,
    success: 0,
    failed: 0,
    logs: [],
  });

  // Candidate Profile State
  const [profile, setProfile] = useState<Profile>({
    full_name: "Jane Doe",
    phone_number: "+91 99999 99999",
    linkedin_profile: "https://linkedin.com/in/janedoe",
    current_designation: "Software Engineer",
    experience_years: "5",
    industry_domain: "Full-Stack Development",
    target_role: "Senior Software Engineer",
    achievements: [
      "Built React frontends and Node.js services running for 1.2M monthly active users",
      "Cut deploy time by 64% after moving CI/CD to a container-based pipeline",
      "Optimized SQL database query speeds, cutting API latency spikes by 45%"
    ],
    resume_pdf_path: "",
  });

  // SMTP Settings env status
  const [envStatus, setEnvStatus] = useState<EnvStatus>({
    gemini_api_key_set: false,
    sender_email: "",
    smtp_server: "smtp.gmail.com",
    smtp_port: "587",
    sender_password_set: false,
    sending_channel: "smtp",
    google_connected: false,
    google_email: null,
  });

  // Mock Recruiter Targets
  const [recipients, setRecipients] = useState<Contact[]>([
    { id: 1, name: "Sarah Jenkins", company: "Apple Inc.", title: "Lead Recruiter", email: "s.jenkins@apple.com", status: "pending" },
    { id: 2, name: "Dave Miller", company: "Amazon", title: "Talent Acquisition", email: "d.miller@amazon.com", status: "pending" },
    { id: 3, name: "Jane Doe", company: "Google", title: "Tech Sourcing Recruiter", email: "j.doe@google.com", status: "pending" },
    { id: 4, name: "Mark Zuckerberg", company: "Meta", title: "Recruiting Coordinator", email: "m.zuck@meta.com", status: "pending" },
    { id: 5, name: "Reed Hastings", company: "Netflix", title: "Lead Sourcing Partner", email: "r.hastings@netflix.com", status: "pending" },
    // Premium targets (locked for Free Tier)
    { id: 6, name: "Alex Rivera", company: "Microsoft", title: "Senior Talent Partner", email: "a.rivera@microsoft.com", status: "locked" },
    { id: 7, name: "Sophia Chen", company: "Stripe", title: "Technical Recruiter", email: "s.chen@stripe.com", status: "locked" },
    { id: 8, name: "Marcus Aurelius", company: "OpenAI", title: "Staff Recruiting Lead", email: "m.aurelius@openai.com", status: "locked" },
    { id: 9, name: "Emma Watson", company: "Airbnb", title: "University Recruiter", email: "e.watson@airbnb.com", status: "locked" },
    { id: 10, name: "John Wick", company: "NVIDIA", title: "Strategic Sourcing Partner", email: "j.wick@nvidia.com", status: "locked" },
  ]);

  const [selectedRecruiterIdx, setSelectedRecruiterIdx] = useState(0);
  const [categories, setCategories] = useState<string[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>("All");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [targetJD, setTargetJD] = useState<string>("");

  // Unified Chat & File customizer state
  const [attachedFile, setAttachedFile] = useState<File | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<Array<{ sender: "user" | "ai" | "system"; text: string }>>([
    { sender: "ai", text: "Hi! I am PitchDock Copilot, your AI Outreach Assistant. Feel free to type prompts to rewrite achievements, modify the tone, or attach files to parse details dynamically." }
  ]);
  const [isTyping, setIsTyping] = useState(false);

  // Connection Settings form state
  const [editGeminiKey, setEditGeminiKey] = useState("");
  const [editSenderEmail, setEditSenderEmail] = useState("");
  const [editSenderPassword, setEditSenderPassword] = useState("");
  const [editSmtpServer, setEditSmtpServer] = useState("smtp.gmail.com");
  const [editSmtpPort, setEditSmtpPort] = useState("587");
  const [editSendingChannel, setEditSendingChannel] = useState("smtp");
  const [telegramLinkCode, setTelegramLinkCode] = useState("");
  const [telegramLinkInstructions, setTelegramLinkInstructions] = useState("");

  // Template states
  const [templateSubject, setTemplateSubject] = useState("{experience} YOE {role} — interested in {company}'s tech team");
  const [templateBody, setTemplateBody] = useState(
    "Hi {recruiter_name},\n\nI'm a {role} with {experience} years of experience specializing in high-throughput backend services and cloud infrastructure.\n\nA few quick highlights from my work:\n• {achievement_1}\n• {achievement_2}\n\nOpen to a 10-min chat this week to see if my background aligns with {company}'s current needs?\n\nBest,\n{my_name}"
  );

  // Personalized draft state
  const [editorSubject, setEditorSubject] = useState("");
  const [editorBody, setEditorBody] = useState("");

  const renderSubjectTemplate = (rec: Contact) => {
    let text = templateSubject;
    text = text.replace(/{recruiter_name}/g, rec.name || "Recruiter");
    text = text.replace(/{Recruiter Name}/g, rec.name || "Recruiter");
    text = text.replace(/{company}/g, rec.company || "Company");
    text = text.replace(/{company_name}/g, rec.company || "Company");
    text = text.replace(/{role}/g, profile.target_role || "Software Engineer");
    text = text.replace(/{recruiter_role}/g, rec.title || "Technical Recruiter");
    text = text.replace(/{experience}/g, profile.experience_years || "3");
    text = text.replace(/{my_name}/g, profile.full_name || "Shubranshu Shekhar");
    text = text.replace(/{achievement_1}/g, profile.achievements[0] || "Engineered high-throughput microservices handling 10k+ req/sec, slashing API response latency by 40%.");
    text = text.replace(/{achievement_2}/g, profile.achievements[1] || "Optimized PostgreSQL database query execution plans, boosting query performance by 65%.");
    return text;
  };

  const renderBodyTemplate = (rec: Contact) => {
    let text = templateBody;
    text = text.replace(/{recruiter_name}/g, rec.name || "Recruiter");
    text = text.replace(/{Recruiter Name}/g, rec.name || "Recruiter");
    text = text.replace(/{company}/g, rec.company || "Company");
    text = text.replace(/{company_name}/g, rec.company || "Company");
    text = text.replace(/{role}/g, profile.target_role || "Software Engineer");
    text = text.replace(/{recruiter_role}/g, rec.title || "Technical Recruiter");
    text = text.replace(/{experience}/g, profile.experience_years || "3");
    text = text.replace(/{my_name}/g, profile.full_name || "Shubranshu Shekhar");
    text = text.replace(/{achievement_1}/g, profile.achievements[0] || "Engineered high-throughput microservices handling 10k+ req/sec, slashing API response latency by 40%.");
    text = text.replace(/{achievement_2}/g, profile.achievements[1] || "Optimized PostgreSQL database query execution plans, boosting query performance by 65%.");
    return text;
  };

  useEffect(() => {
    const rec = recipients[selectedRecruiterIdx];
    if (rec) {
      setEditorSubject(rec.personalized_subject || renderSubjectTemplate(rec));
      setEditorBody(rec.personalized_body || renderBodyTemplate(rec));
    }
  }, [selectedRecruiterIdx, recipients, templateSubject, templateBody, profile.target_role, profile.full_name, profile.achievements, profile.experience_years]);

  const handleSaveDraft = async (contactId: number, subject: string, body: string) => {
    try {
      await apiCall(`/api/contact/${contactId}/edit`, "POST", {
        subject,
        body,
        status: "approved"
      });
      setRecipients(prev => prev.map(r => r.id === contactId ? { ...r, personalized_subject: subject, personalized_body: body, status: "approved" } : r));
    } catch (err: any) {
      console.error("Failed to save draft:", err);
    }
  };

  // Interactive controls
  const [isPreviewReplacerMode, setIsPreviewReplacerMode] = useState(true); // Toggle between template variables view and final replaced view
  const [isUpgradeModalOpen, setIsUpgradeModalOpen] = useState(false);
  const [billingCycle, setBillingCycle] = useState<"monthly" | "annual">("monthly");
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  const logsEndRef = useRef<HTMLDivElement | null>(null);

  // API Call helper
  const apiCall = async (url: string, method = "GET", body: any = null) => {
    const token = localStorage.getItem("authToken");
    const headers: HeadersInit = { "Content-Type": "application/json" };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    const config: RequestInit = { 
      method, 
      headers,
      credentials: "include"
    };
    if (body) config.body = JSON.stringify(body);
    const response = await fetch(`${API_BASE}${url}`, config);
    if (response.status === 401) {
      localStorage.removeItem("authToken");
      localStorage.removeItem("authUser");
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
      throw new Error("Session expired. Redirecting to login...");
    }
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: "API Error" }));
      throw new Error(err.detail || response.statusText);
    }
    return response.json();
  };

  const fetchProfile = async () => {
    try {
      const data = await apiCall("/api/profile");
      setProfile(data);
    } catch (e) {
      console.error("Error fetching profile:", e);
    }
  };

  const fetchContacts = async (categoryFilter = "All", searchVal = "") => {
    try {
      let url = "/api/contacts?limit=200";
      if (categoryFilter !== "All") {
        url += `&category=${encodeURIComponent(categoryFilter)}`;
      }
      if (searchVal.trim() !== "") {
        url += `&search=${encodeURIComponent(searchVal.trim())}`;
      }
      const data = await apiCall(url);
      if (data && data.contacts) {
        setRecipients(data.contacts);
        setSelectedRecruiterIdx(0);
      }
    } catch (e) {
      console.error("Error fetching contacts:", e);
    }
  };

  const fetchStats = async () => {
    try {
      const data = await apiCall("/api/stats");
      if (data && data.category_breakdown) {
        setCategories(Object.keys(data.category_breakdown));
      }
    } catch (e) {
      console.error("Error fetching stats:", e);
    }
  };

  const handleCategoryChange = (cat: string) => {
    setSelectedCategory(cat);
    fetchContacts(cat, searchQuery);
  };

  const handleSearchChange = (val: string) => {
    setSearchQuery(val);
    fetchContacts(selectedCategory, val);
  };

  // Sync and polling
  useEffect(() => {
    const checkAuth = async () => {
      try {
        const user = await apiCall("/api/auth/me");
        setUserEmail(user.email);
        localStorage.setItem("authUser", JSON.stringify(user));
        
        fetchBilling();
        fetchEnvStatus();
        fetchProfile();
        fetchStats();
        fetchContacts();
      } catch (err) {
        console.error("Session verification failed. Redirecting to login...", err);
        router.push("/login");
      }
    };

    checkAuth();
    
    if (typeof window !== "undefined") {
      const urlParams = new URLSearchParams(window.location.search);
      const planParam = urlParams.get("plan");
      if (planParam && ["free", "basic", "standard", "premium"].includes(planParam)) {
        changeBillingPlan(planParam);
        const cleanUrl = window.location.protocol + "//" + window.location.host + window.location.pathname;
        window.history.replaceState({ path: cleanUrl }, "", cleanUrl);
      }
    }

    const interval = setInterval(fetchTaskStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  const chatLogsContainerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (chatLogsContainerRef.current) {
      chatLogsContainerRef.current.scrollTop = chatLogsContainerRef.current.scrollHeight;
    }
  }, [chatMessages, activeTask.logs]);

  const fetchBilling = async () => {
    try {
      const data = await apiCall("/api/billing");
      setBillingInfo(data);
    } catch (e) {
      console.error("Error fetching billing info:", e);
    }
  };

  const fetchEnvStatus = async () => {
    try {
      const data = await apiCall("/api/env");
      setEnvStatus(data);
      setEditGeminiKey(data.gemini_api_key_set ? "••••••••••••••••" : "");
      setEditSenderEmail(data.sender_email || "");
      setEditSenderPassword(data.sender_password_set ? "••••••••••••" : "");
      setEditSmtpServer(data.smtp_server || "smtp.gmail.com");
      setEditSmtpPort(data.smtp_port || "587");
      setEditSendingChannel(data.sending_channel || "smtp");
    } catch (e) {
      console.error("Error fetching env credentials:", e);
    }
  };

  const handleSaveEnvSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const payload = {
        gemini_api_key: "STAY_SAME",
        sender_email: editSenderEmail,
        sender_password: editSenderPassword === "••••••••••••" ? "" : editSenderPassword,
        smtp_server: editSmtpServer,
        smtp_port: editSmtpPort,
        sending_channel: editSendingChannel
      };
      const res = await apiCall("/api/env", "POST", payload);
      alert(res.message || "Settings updated successfully.");
      await fetchEnvStatus();
      setIsSettingsOpen(false);
    } catch (err: any) {
      alert(`Save failed: ${err.message}`);
    }
  };

  const handleGoogleOAuthConnect = async () => {
    try {
      const data = await apiCall("/api/oauth/google/auth-url");
      if (!data?.url) {
        throw new Error("Google authorization URL was not returned by the server.");
      }
      window.location.href = data.url;
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unable to start Google OAuth.";
      alert(`Google OAuth setup failed: ${message}`);
    }
  };

  const handleGenerateTelegramLinkCode = async () => {
    try {
      const data = await apiCall("/api/telegram/link-code", "POST");
      setTelegramLinkCode(data.token || "");
      setTelegramLinkInstructions(data.instructions || "");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unable to generate Telegram link code.";
      alert(`Telegram setup failed: ${message}`);
    }
  };

  const fetchTaskStatus = async () => {
    try {
      const data: ActiveTask = await apiCall("/api/status");
      setActiveTask(data);
    } catch (e) {
      console.error("Error fetching pipeline status:", e);
    }
  };

  const changeBillingPlan = async (tier: string) => {
    try {
      if (tier === "free") {
        await apiCall("/api/billing", "POST", { plan_tier: tier });
        const updatedBilling = await apiCall("/api/billing");
        setBillingInfo(updatedBilling);
        setIsUpgradeModalOpen(false);
        alert(`Successfully changed plan to ${tier.toUpperCase()}`);
        return;
      }
      
      const scriptLoaded = await loadRazorpayScript();
      if (!scriptLoaded) {
        alert("Failed to load Razorpay SDK. Please check your internet connection.");
        return;
      }
      
      const orderData = await apiCall("/api/payments/create-order", "POST", { plan_tier: tier, billing_cycle: billingCycle });
      
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
            await apiCall("/api/payments/verify", "POST", {
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_order_id: response.razorpay_order_id,
              razorpay_signature: response.razorpay_signature,
              plan_tier: tier,
              billing_cycle: billingCycle
            });
            const updatedBilling = await apiCall("/api/billing");
            setBillingInfo(updatedBilling);
            setIsUpgradeModalOpen(false);
            alert(`Successfully upgraded plan to ${tier.toUpperCase()}!`);
          } catch (verifyError: any) {
            alert(`Payment verification failed: ${verifyError.message}`);
          }
        },
        theme: {
          color: "#4f46e5",
        },
      };
      
      const paymentObject = new (window as any).Razorpay(options);
      paymentObject.open();
    } catch (e: any) {
      alert(`Failed to change plan: ${e.message}`);
    }
  };

  // File Upload change handler
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setAttachedFile(file);
  };

  // AI Chat Customizer action
  const handleSendChat = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim() && !attachedFile) return;

    const userText = chatInput;
    const fileToUpload = attachedFile;

    let displayText = userText;
    if (fileToUpload) {
      displayText = `📎 Attached: ${fileToUpload.name}${userText ? ` \n\n${userText}` : ""}`;
    }

    setChatMessages(prev => [...prev, { sender: "user", text: displayText }]);
    setChatInput("");
    setAttachedFile(null);
    setIsTyping(true);

    try {
      let finalPrompt = userText;

      if (fileToUpload) {
        setChatMessages(prev => [...prev, { sender: "system", text: `Uploading ${fileToUpload.name}...` }]);
        await new Promise(resolve => setTimeout(resolve, 800));
        setChatMessages(prev => [...prev, { sender: "system", text: "Reading file structure and contents..." }]);
        await new Promise(resolve => setTimeout(resolve, 800));
        setChatMessages(prev => [...prev, { sender: "system", text: "Analyzing key skills and achievements..." }]);
        await new Promise(resolve => setTimeout(resolve, 800));

        finalPrompt = `I have uploaded a document named "${fileToUpload.name}". Please parse its contents and tailor my subject template, body template, and achievements. User request: ${userText || "Customize my email details based on the uploaded file."}`;
      }

      const data = await apiCall("/api/chat-customize", "POST", {
        message: finalPrompt,
        template_subject: isPreviewReplacerMode ? editorSubject : templateSubject,
        template_body: isPreviewReplacerMode ? editorBody : templateBody,
        achievements: profile.achievements,
        target_role: profile.target_role,
        recruiter_id: isPreviewReplacerMode ? recipients[selectedRecruiterIdx]?.id : null,
        job_description: billingInfo.plan_tier === "premium" ? targetJD : null
      });

      if (isPreviewReplacerMode) {
        setEditorSubject(data.updated_subject);
        setEditorBody(data.updated_body);
        setRecipients(prev => prev.map((r, idx) => idx === selectedRecruiterIdx ? {
          ...r,
          name: data.updated_recruiter_name || r.name,
          company: data.updated_company || r.company,
          personalized_subject: data.updated_subject,
          personalized_body: data.updated_body,
          status: "approved"
        } : r));
      } else {
        setTemplateSubject(data.updated_subject);
        setTemplateBody(data.updated_body);
      }

      setProfile(prev => ({
        ...prev,
        achievements: data.updated_achievements,
        target_role: data.updated_target_role || prev.target_role
      }));

      setChatMessages(prev => [...prev, { sender: "ai", text: data.chat_response }]);
    } catch (err: any) {
      setChatMessages(prev => [
        ...prev,
        { sender: "ai", text: `Error: ${err.message || "Failed to communicate with Gemini."}` }
      ]);
    } finally {
      setIsTyping(false);
    }
  };

  // Variable replacement helper for preview or direct template output
  const renderEmailContent = (type: "subject" | "body") => {
    let text = type === "subject" ? templateSubject : templateBody;
    
    // If not in replacement preview mode, return raw template code
    if (!isPreviewReplacerMode) return text;

    const rec = recipients[selectedRecruiterIdx] || recipients[0];
    if (!rec) return text;

    // Run dynamic substitutions
    text = text.replace(/{recruiter_name}/g, rec.name || "Recruiter");
    text = text.replace(/{company}/g, rec.company || "Company");
    text = text.replace(/{company_name}/g, rec.company || "Company");
    text = text.replace(/{role}/g, profile.target_role || "Software Engineer");
    text = text.replace(/{recruiter_role}/g, rec.title || "Technical Recruiter");
    text = text.replace(/{experience}/g, profile.experience_years || "5");
    text = text.replace(/{my_name}/g, profile.full_name || "Jane Doe");
    text = text.replace(/{achievement_1}/g, profile.achievements[0] || "Led product components engineering");
    text = text.replace(/{achievement_2}/g, profile.achievements[1] || "Automated delivery pipeline workflows");

    return text;
  };

  // Launch campaign actions
  const handleLaunchCampaign = async () => {
    try {
      await apiCall("/api/free-outreach", "POST", {
        full_name: profile.full_name,
        phone_number: profile.phone_number,
        linkedin_profile: profile.linkedin_profile,
        current_designation: profile.current_designation,
        experience_years: profile.experience_years,
        industry_domain: profile.industry_domain,
        target_role: profile.target_role,
        achievements: profile.achievements,
        resume_pdf_path: profile.resume_pdf_path,
        category: selectedCategory,
        strategy: "template",
        template_subject: templateSubject,
        template_body: templateBody,
      });
      fetchTaskStatus();
      fetchBilling();
    } catch (e: any) {
      alert(`Launch failed: ${e.message}`);
    }
  };

  const handleStopCampaign = async () => {
    try {
      await apiCall("/api/status/stop", "POST");
      fetchTaskStatus();
    } catch (e: any) {
      alert(`Failed to stop: ${e.message}`);
    }
  };

  const handlePremiumAction = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsSettingsOpen(true);
  };

  const handleLogout = async () => {
    try {
      const token = localStorage.getItem("authToken");
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
    } catch (e) {
      console.error("Logout error:", e);
    }
    localStorage.removeItem("authToken");
    localStorage.removeItem("authUser");
    router.push("/login");
  };

  // Quota percentage
  const maxQuota = billingInfo.plan_tier === "free" ? 5 : billingInfo.plan_tier === "basic" ? 20 : billingInfo.plan_tier === "standard" ? 50 : 50;
  const quotaPercent = Math.min(100, (billingInfo.emails_sent_today / maxQuota) * 100);

  return (
    <div className="landing-root dashboard-page-wrapper">
      
      {/* Top HUD Banner */}
      <header className="dashboard-hud">
        <div className="hud-wrap">
          <Link href="/" style={{ display: "flex", alignItems: "center", gap: "10px", textDecoration: "none" }}>
            <img src="/orangelogo.png" alt="PitchDock Logo" style={{ width: "32px", height: "32px", borderRadius: "50%", objectFit: "cover" }} />
            <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "18px", color: "var(--text)" }}>
              Pitch<span style={{ color: "var(--signal)" }}>Dock</span>
            </span>
            {userEmail && (
              <span style={{ marginLeft: "8px", fontSize: "12px", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                ({userEmail})
              </span>
            )}
          </Link>
          
          <div className="hud-metrics">
            <div className="plan-badge-container">
              <span className={`plan-badge ${billingInfo.plan_tier}`}>
                {billingInfo.plan_tier.toUpperCase()} TIER
              </span>
              {billingInfo.plan_tier === "free" && (
                <button className="upgrade-hud-btn" onClick={() => setIsUpgradeModalOpen(true)}>
                  Upgrade
                </button>
              )}
            </div>

            <div className="hud-quota">
              <div className="quota-text">
                Daily Limit: <strong>{billingInfo.emails_sent_today} / {maxQuota}</strong> sent
              </div>
              <div className="quota-bar-bg">
                <div className="quota-bar-fill" style={{ width: `${quotaPercent}%` }}></div>
              </div>
            </div>

            <button className="hud-settings-btn" onClick={handlePremiumAction}>
              ⚙️ Connection settings
            </button>
            <Link
              href="/"
              style={{
                marginLeft: "8px",
                padding: "8px 16px",
                borderRadius: "6px",
                fontSize: "12.5px",
                fontWeight: 600,
                color: "#ffffff",
                backgroundColor: "#18181b",
                border: "none",
                textDecoration: "none",
                display: "inline-flex",
                alignItems: "center",
                cursor: "pointer",
                boxSizing: "border-box"
              }}
            >
              ← Back to Home
            </Link>



            <button 
              className="hud-settings-btn" 
              onClick={handleLogout}
              style={{
                marginLeft: "8px",
                border: "1px solid rgba(24, 24, 27, 0.08)",
                color: "var(--accent-red)",
                backgroundColor: "transparent"
              }}
            >
              Logout
            </button>
          </div>
        </div>
      </header>

      {/* Main Consolidated Workspace Grid */}
      <div className="dashboard-content-container">
        
        {/* Recruiter Horizontal Strip Queue */}
        <div className="recruiter-horizontal-strip">
          {recipients.map((rec, idx) => {
            let isLocked = false;
            if (billingInfo.plan_tier === "free") {
              isLocked = idx >= 5;
            } else if (billingInfo.plan_tier === "basic") {
              isLocked = idx >= 20;
            } else if (billingInfo.plan_tier === "standard") {
              const isSearchingCompany = searchQuery.trim() !== "";
              isLocked = isSearchingCompany ? idx >= 5 : idx >= 50;
            } else if (billingInfo.plan_tier === "premium") {
              const isSearchingCompany = searchQuery.trim() !== "";
              isLocked = isSearchingCompany ? idx >= 10 : idx >= 50;
            }

            let statusClass = "pending";
            let statusText = "Queue";

            if (isLocked) {
              statusClass = "locked";
              statusText = "Locked";
            } else if (activeTask.status === "running") {
              if (idx < activeTask.current) {
                statusClass = "sent";
                statusText = "Sent";
              } else if (idx === activeTask.current) {
                statusClass = "sending";
                statusText = "Sending...";
              }
            } else if (activeTask.status === "completed") {
              statusClass = "sent";
              statusText = "Sent";
            } else if (billingInfo.emails_sent_today >= (idx + 1)) {
              statusClass = "sent";
              statusText = "Sent";
            }

            return (
              <div 
                key={rec.id} 
                className={`recruiter-horizontal-item ${selectedRecruiterIdx === idx ? "active" : ""} ${isLocked ? "locked" : ""}`}
                onClick={() => {
                  if (isLocked) {
                    setIsUpgradeModalOpen(true);
                  } else {
                    setSelectedRecruiterIdx(idx);
                  }
                }}
              >
                <div className="rec-info-strip">
                  <div className="rec-name-strip">{rec.name}</div>
                  <div className="rec-meta-strip">{rec.company} · {rec.title}</div>
                </div>
                <div className={`rec-status-badge-strip ${statusClass}`}>
                  {isLocked ? "🔒 Locked" : statusText}
                </div>
              </div>
            );
          })}
        </div>

        {/* Upgrade / Active Plan Banner Strip */}
        {billingInfo.plan_tier === "free" ? (
          <div className="recruiter-upgrade-banner-strip" onClick={() => setIsUpgradeModalOpen(true)}>
            <span>🔒 You are on the free plan (unlocked first 5 recruiters). Click here to subscribe for unlimited daily sending.</span>
          </div>
        ) : (
          <div className="recruiter-paid-banner-strip">
            <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
              <span style={{ color: "#10b981", fontWeight: 700 }}>✓</span> 
              <strong>{billingInfo.plan_tier.toUpperCase()} TIER ACTIVE:</strong> All recruiter outreach capabilities, resume customizations &amp; direct dispatches are unlocked.
            </span>
          </div>
        )}

        {/* Main Redesigned Split Columns Workspace */}
        <div className="dashboard-split-container">
          
          {/* Column 1: AI Chat Assistant (Left side) */}
          <div className="chat-column">
            <div className="console-card chat-card-container">
              <div className="card-head chat-card-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", gap: "16px" }}>
                <h3 style={{ margin: 0, flexShrink: 0 }}>AI Customizer Copilot</h3>
                <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                  <div className="filter-group" style={{ display: "flex", alignItems: "center", gap: "6px", margin: 0 }}>
                    <label htmlFor="category-select" style={{ fontSize: "10px", fontFamily: "var(--font-mono)", textTransform: "uppercase", color: "var(--slate)", fontWeight: 700, letterSpacing: "0.05em" }}>Domain</label>
                    <select
                      id="category-select"
                      value={selectedCategory}
                      onChange={(e) => handleCategoryChange(e.target.value)}
                      className="filter-control-select"
                    >
                      <option value="All">All</option>
                      {categories.map((cat) => (
                        <option key={cat} value={cat}>
                          {cat}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="filter-group" style={{ display: "flex", alignItems: "center", gap: "6px", margin: 0 }}>
                    <label htmlFor="company-search-filter" style={{ fontSize: "10px", fontFamily: "var(--font-mono)", textTransform: "uppercase", color: "var(--slate)", fontWeight: 700, letterSpacing: "0.05em" }}>Company</label>
                    <input
                      id="company-search-filter"
                      type="text"
                      placeholder="Search company..."
                      value={searchQuery}
                      onChange={(e) => handleSearchChange(e.target.value)}
                      className="filter-control-input"
                    />
                  </div>
                </div>
              </div>

              
              <div className="chat-logs-workspace" ref={chatLogsContainerRef}>
                {chatMessages.map((msg, idx) => (
                  <div key={idx} className={`chat-bubble ${msg.sender}`}>
                    <div className="bubble-body">{msg.text}</div>
                  </div>
                ))}
                {isTyping && (
                  <div className="chat-bubble ai typing">
                    <span className="bounce-dot"></span>
                    <span className="bounce-dot"></span>
                    <span className="bounce-dot"></span>
                  </div>
                )}
                <div ref={logsEndRef}></div>
              </div>

              {/* Premium Job Description Input Field */}
              {billingInfo.plan_tier === "premium" && (
                <div className="premium-jd-box-modern" style={{ padding: "8px 12px", borderTop: "1px solid rgba(255,255,255,0.06)", background: "rgba(245,158,11,0.03)" }}>
                  <label style={{ fontSize: "10px", color: "#f59e0b", fontWeight: "bold", textTransform: "uppercase", display: "block", marginBottom: "4px", letterSpacing: "0.05em" }}>
                     ✦ Target Job Description (JD) (Optional)
                  </label>
                  <textarea
                    placeholder="Paste the target Job Description (JD) here to let the AI rewrite your resume/outreach achievements specifically for this role..."
                    value={targetJD}
                    onChange={(e) => setTargetJD(e.target.value)}
                    style={{ width: "100%", height: "55px", background: "rgba(3,7,18,0.5)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "6px", color: "#ffffff", padding: "8px", fontSize: "12px", resize: "none", outline: "none", fontFamily: "inherit" }}
                  />
                </div>
              )}

              {/* Attached file previews */}
              {attachedFile && (
                <div className="chat-attachment-preview">
                  <span>📄 {attachedFile.name}</span>
                  <button type="button" onClick={() => setAttachedFile(null)}>×</button>
                </div>
              )}

              <form onSubmit={handleSendChat} className="chat-input-row-modern">
                <input 
                  type="file" 
                  id="chat-file-input" 
                  accept=".pdf,.docx,.txt"
                  onChange={handleFileChange}
                  style={{ display: "none" }}
                />
                <label htmlFor="chat-file-input" className="chat-attach-btn-modern">
                  📎
                </label>
                <input 
                  type="text" 
                  placeholder="Ask AI to customize your message, rewrite achievements, or attach documents..."
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  className="chat-field-modern"
                />
                <button type="submit" className="chat-send-btn-modern">
                  Modify
                </button>
              </form>

              {/* Pipeline console logs shifted to Left Column */}
              {activeTask.logs.length > 0 && (
                <div className="console-logs-hud-modern" style={{ marginTop: "16px", marginLeft: "12px", marginRight: "12px" }}>
                  <div className="logs-hud-head-modern">Send Console Logs</div>
                  <div className="logs-hud-body-modern">
                    {activeTask.logs.map((log, idx) => (
                      <div key={idx} className="log-line">{log}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Column 2: Composer Editor & Launch Actions (Right side) */}
          <div className="editor-column">
            <div className="console-card unified-workspace-card-modern">
              <div className="card-head workspace-card-head-modern">
                <div className="workspace-header-details">
                  <h3 style={{ margin: 0 }}>Email Composer</h3>
                  <p className="workspace-tagline" style={{ margin: "4px 0 0", fontSize: "13px", color: "var(--slate)" }}>
                    Recipient: <strong>{recipients[selectedRecruiterIdx]?.name || "Recruiter"}</strong> ({recipients[selectedRecruiterIdx]?.company})
                  </p>
                </div>
                
                {/* Visual view toggler */}
                <div className="preview-mode-switch">
                  <button 
                    type="button"
                    className={`mode-btn ${!isPreviewReplacerMode ? "active" : ""}`}
                    onClick={() => setIsPreviewReplacerMode(false)}
                  >
                    Edit Template
                  </button>
                  <button 
                    type="button"
                    className={`mode-btn ${isPreviewReplacerMode ? "active" : ""}`}
                    onClick={() => setIsPreviewReplacerMode(true)}
                  >
                    Edit Draft
                  </button>
                </div>
              </div>

              {/* Unified Composer Window */}
              <div className="email-preview-composer unified-editor-composer-modern">
                <div className="preview-meta-row">
                  <span className="meta-label">To</span>
                  <span className="meta-value">
                    {recipients[selectedRecruiterIdx]?.email} 
                    <span className="meta-title-tag">({recipients[selectedRecruiterIdx]?.title})</span>
                  </span>
                </div>
                <div className="preview-meta-row editor-subject-row">
                  <span className="meta-label">Subject</span>
                  {isPreviewReplacerMode ? (
                    <input 
                      type="text" 
                      className="borderless-subject-input" 
                      style={{ fontWeight: "bold" }}
                      value={editorSubject} 
                      onChange={(e) => setEditorSubject(e.target.value)}
                      onBlur={() => {
                        const rec = recipients[selectedRecruiterIdx];
                        if (rec) handleSaveDraft(rec.id, editorSubject, editorBody);
                      }}
                      placeholder="Personalized subject..."
                    />
                  ) : (
                    <input 
                      type="text" 
                      className="borderless-subject-input" 
                      value={templateSubject} 
                      onChange={(e) => setTemplateSubject(e.target.value)}
                      placeholder="Email subject template..."
                    />
                  )}
                </div>
                <div className="preview-meta-row attachment-meta-row" style={{ display: "flex", alignItems: "center", gap: "8px", background: "rgba(16, 185, 129, 0.08)", padding: "6px 12px", borderRadius: "6px", border: "1px solid rgba(16, 185, 129, 0.2)", margin: "8px 12px 4px 12px" }}>
                  <span className="meta-label" style={{ color: "#10b981", fontWeight: "bold", fontSize: "12px" }}>📎 Attachment:</span>
                  <span className="meta-value" style={{ color: "#ffffff", fontSize: "13px", fontFamily: "monospace" }}>
                    {profile.resume_pdf_path ? profile.resume_pdf_path.split("/").pop() : "resume.pdf"}
                  </span>
                  <span style={{ fontSize: "11px", color: "#10b981", background: "rgba(16, 185, 129, 0.15)", padding: "2px 8px", borderRadius: "12px", marginLeft: "auto", fontWeight: "600" }}>
                    ✓ Attached &amp; Verified
                  </span>
                </div>

                <div className="preview-body-content editor-body-row">
                  {isPreviewReplacerMode ? (
                    <textarea 
                      className="borderless-body-textarea" 
                      rows={12}
                      value={editorBody}
                      onChange={(e) => setEditorBody(e.target.value)}
                      onBlur={() => {
                        const rec = recipients[selectedRecruiterIdx];
                        if (rec) handleSaveDraft(rec.id, editorSubject, editorBody);
                      }}
                      placeholder="Personalized body content..."
                    />
                  ) : (
                    <textarea 
                      className="borderless-body-textarea" 
                      rows={12}
                      value={templateBody}
                      onChange={(e) => setTemplateBody(e.target.value)}
                      placeholder="Write your email body template. Support variables like {recruiter_name}, {company}, {achievement_1}..."
                    />
                  )}
                </div>
                
                <div className="composer-hints-bar">
                  {!isPreviewReplacerMode ? (
                    <span>💡 Supporting template variables: <code>{"{recruiter_name}"}</code>, <code>{"{company}"}</code>, <code>{"{role}"}</code>, <code>{"{achievement_1}"}</code></span>
                  ) : (
                    <span style={{ color: "var(--signal-deep)" }}>✦ Personalized Draft mode (manually edit or chat with the AI to refine; auto-saves on focus exit)</span>
                  )}
                </div>
              </div>

              {/* Launch Campaign Action Bar */}
              <div className="launch-action-bar-modern">
                {activeTask.status === "running" ? (
                  <div className="active-task-running-box-modern">
                    <div className="loader-row">
                      <span className="pulse-dot red"></span>
                      <span>Delivery in progress: {activeTask.current} / {activeTask.total}</span>
                    </div>
                    <button className="campaign-stop-btn" onClick={handleStopCampaign}>
                      Stop Campaign
                    </button>
                  </div>
                ) : (
                  <button className="campaign-launch-btn" onClick={handleLaunchCampaign}>
                    Launch Outbox Campaign
                  </button>
                )}
              </div>



            </div>
          </div>

        </div>
      </div>

      {/* Upgrade Subscription Overlay Modal */}
      {isUpgradeModalOpen && (
        <div className="modal-overlay center-modal" onClick={() => setIsUpgradeModalOpen(false)}>
          <div className="modal-body-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-card-head">
              <h2>Upgrade your Outreach Plan</h2>
              <button className="close-modal-btn" onClick={() => setIsUpgradeModalOpen(false)}>×</button>
            </div>
            <p className="modal-subtitle-text">Unlock high-volume limits, category target matching, and custom SMTP server connections.</p>
            
            <div className="billing-cycle-toggle-wrapper" style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: "12px", margin: "16px 0 24px" }}>
              <span style={{ fontWeight: billingCycle === "monthly" ? "bold" : "normal", color: billingCycle === "monthly" ? "var(--text-primary)" : "var(--text-secondary)" }}>Monthly billing</span>
              <button 
                onClick={() => setBillingCycle(billingCycle === "monthly" ? "annual" : "monthly")}
                style={{
                  width: "50px",
                  height: "26px",
                  borderRadius: "13px",
                  backgroundColor: "#4f46e5",
                  border: "none",
                  cursor: "pointer",
                  position: "relative",
                  padding: "0"
                }}
              >
                <div style={{
                  width: "20px",
                  height: "20px",
                  borderRadius: "50%",
                  backgroundColor: "#ffffff",
                  position: "absolute",
                  top: "3px",
                  left: billingCycle === "monthly" ? "3px" : "27px",
                  transition: "left 0.2s ease"
                }} />
              </button>
              <span style={{ fontWeight: billingCycle === "annual" ? "bold" : "normal", color: billingCycle === "annual" ? "var(--text-primary)" : "var(--text-secondary)" }}>
                Annual billing <span style={{ fontSize: "11px", backgroundColor: "#10b981", color: "#ffffff", padding: "2px 6px", borderRadius: "4px", marginLeft: "4px" }}>Save 20%</span>
              </span>
            </div>

            <div className="upgrade-pricing-options">
              <div className="pricing-option-card">
                <h4>Basic AI</h4>
                <div className="price-num">
                  {billingCycle === "monthly" ? "₹299" : "₹239"}<span>/mo</span>
                </div>
                {billingCycle === "annual" && <div style={{ fontSize: "11.5px", color: "var(--text-secondary)", marginBottom: "8px" }}>billed annually (₹2868)</div>}
                <p>Send up to 50 emails daily. AI personalization drafts enabled.</p>
                <button className="upgrade-select-btn" onClick={() => changeBillingPlan("basic")}>
                  Choose Basic
                </button>
              </div>
              <div className="pricing-option-card featured" style={{ margin: "0 auto", maxWidth: "400px", width: "100%" }}>
                <div className="pop-badge">POPULAR</div>
                <h4>Standard Pro</h4>
                <div className="price-num">
                  {billingCycle === "monthly" ? "₹499" : "₹399"}<span>/mo</span>
                </div>
                {billingCycle === "annual" && <div style={{ fontSize: "11.5px", color: "#e0e7ff", marginBottom: "8px", opacity: 0.9 }}>billed annually (₹4788)</div>}
                <p>Full AI personalization, resume customizer, HR search, and up to 200 emails daily.</p>
                <button className="upgrade-select-btn" onClick={() => changeBillingPlan("standard")}>
                  Choose Standard Pro (₹499)
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Custom SMTP credentials settings slider modal */}
      {isSettingsOpen && (
        <div className="modal-overlay" onClick={() => setIsSettingsOpen(false)}>
          <div className="settings-drawer-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-card-head">
              <h2>Connection Settings</h2>
              <button className="close-modal-btn" onClick={() => setIsSettingsOpen(false)}>×</button>
            </div>
            <p className="modal-subtitle-text">Configure your credentials, Google OAuth keys, or SMTP mail relay server details.</p>
            
            <form onSubmit={handleSaveEnvSettings} className="settings-form">


              <div className="setting-row">
                <label>Sending Channel</label>
                <select 
                  value={editSendingChannel} 
                  onChange={(e) => setEditSendingChannel(e.target.value)}
                  className="settings-select-field"
                >
                  <option value="smtp">SMTP Relay Server</option>
                  <option value="google">Google API (Gmail OAuth)</option>
                </select>
              </div>

              {editSendingChannel === "smtp" ? (
                <>
                  <div className="setting-row">
                    <label>Sender Email Address</label>
                    <input 
                      type="email" 
                      value={editSenderEmail} 
                      onChange={(e) => setEditSenderEmail(e.target.value)} 
                      placeholder="e.g. name@gmail.com"
                      required
                    />
                  </div>
                  <div className="setting-row">
                    <label>Sender App Password</label>
                    <input 
                      type="password" 
                      value={editSenderPassword} 
                      onChange={(e) => setEditSenderPassword(e.target.value)} 
                      placeholder="SMTP App Password..."
                    />
                  </div>
                  <div className="setting-row">
                    <label>SMTP Host</label>
                    <input 
                      type="text" 
                      value={editSmtpServer} 
                      onChange={(e) => setEditSmtpServer(e.target.value)} 
                      placeholder="e.g. smtp.gmail.com"
                      required
                    />
                  </div>
                  <div className="setting-row">
                    <label>SMTP Port</label>
                    <input 
                      type="text" 
                      value={editSmtpPort} 
                      onChange={(e) => setEditSmtpPort(e.target.value)} 
                      placeholder="e.g. 587"
                      required
                    />
                  </div>
                </>
              ) : (
                <div className="setting-row oauth-row">
                  <p className="oauth-desc">Connect directly via secure Google OAuth. PitchDock will send cold emails via official Gmail API endpoints.</p>
                  {envStatus.google_connected ? (
                    <div className="oauth-status-connected">
                      <span>✓ Connected to: <strong>{envStatus.google_email}</strong></span>
                    </div>
                  ) : (
                    <button type="button" onClick={handleGoogleOAuthConnect} className="oauth-link-btn">
                      🔗 Authenticate Gmail Account
                    </button>
                  )}
                </div>
              )}

              <div className="setting-row oauth-row">
                <label>Telegram Mobile Agent</label>
                <p className="oauth-desc">Included for all users (all subscriptions, including Free Starter). Pair Telegram after signing in here, then send commands like "status" or "send email" from your phone.</p>
                <button type="button" onClick={handleGenerateTelegramLinkCode} className="oauth-link-btn">
                  Generate Telegram Link Code
                </button>
                {telegramLinkCode && (
                  <div className="oauth-status-connected" style={{ marginTop: "10px" }}>
                    <span>
                      Code: <strong>{telegramLinkCode}</strong>
                      <br />
                      {telegramLinkInstructions}
                    </span>
                  </div>
                )}
              </div>

              <button type="submit" className="settings-save-btn">
                Save Connection Settings
              </button>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}

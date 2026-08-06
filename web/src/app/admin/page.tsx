"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://www.pitchdock.xyz";

interface User {
  id: number;
  email: string;
  full_name: string;
  created_at: string;
  plan_tier: string;
  subscription_expires_at: string | null;
  emails_sent_today: number;
}

interface Payment {
  id: number;
  payment_id: string;
  order_id: string;
  amount: number;
  plan_tier: string;
  status: string;
  created_at: string;
  user_email: string;
}

interface Metrics {
  total_users: number;
  total_payments_count: number;
  total_revenue: number;
  total_emails_today: number;
  active_subscriptions: number;
  total_recruiters?: number;
}

interface TrendPoint {
  date: string;
  value: number;
}

interface Trends {
  signups: TrendPoint[];
  revenue: TrendPoint[];
}

interface RecruiterContactInput {
  email: string;
  name?: string;
  company?: string;
  title?: string;
  category?: string;
}

interface RecruiterRecord {
  id: number;
  name: string;
  title?: string;
  company?: string;
  category?: string;
  email: string;
  status: string;
}

export default function AdminPage() {
  const router = useRouter();
  
  // Auth state
  const [isAdminLoggedIn, setIsAdminLoggedIn] = useState(false);
  const [adminToken, setAdminToken] = useState<string | null>(null);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  
  // Dashboard data state
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [trends, setTrends] = useState<Trends>({ signups: [], revenue: [] });
  const [isLoading, setIsLoading] = useState(true);
  
  // Tab control & interactive charts
  const [activeTab, setActiveTab] = useState<"users" | "payments" | "recruiters" | "oauth">("users");
  const [trendView, setTrendView] = useState<"signups" | "revenue">("signups");
  const [searchQuery, setSearchQuery] = useState("");

  // OAuth config state
  const [oauthClientId, setOauthClientId] = useState("");
  const [oauthClientSecret, setOauthClientSecret] = useState("");
  const [oauthRedirectUri, setOauthRedirectUri] = useState("");
  const [oauthFrontendUrl, setOauthFrontendUrl] = useState("");
  const [isSavingOauth, setIsSavingOauth] = useState(false);
  const [oauthSaveMessage, setOauthSaveMessage] = useState("");
  const [oauthSaveError, setOauthSaveError] = useState("");

  // Recruiter intake & management state
  const [recruiterBulkText, setRecruiterBulkText] = useState("");
  const [seedAllUsers, setSeedAllUsers] = useState(true);
  const [isAddingRecruiters, setIsAddingRecruiters] = useState(false);
  const [recruiterAddMessage, setRecruiterAddMessage] = useState("");
  const [recruiterAddError, setRecruiterAddError] = useState("");
  const [recruiterInputMode, setRecruiterInputMode] = useState<"single" | "bulk">("single");
  const [singleRecruiter, setSingleRecruiter] = useState<RecruiterContactInput>({
    email: "",
    name: "",
    company: "",
    title: "",
    category: ""
  });
  const [recruitersList, setRecruitersList] = useState<RecruiterRecord[]>([]);
  const [recruiterSearchQuery, setRecruiterSearchQuery] = useState("");
  
  useEffect(() => {
    const token = localStorage.getItem("adminToken");
    if (token) {
      setAdminToken(token);
      setIsAdminLoggedIn(true);
    } else {
      setIsLoading(false);
    }
  }, []);
  
  useEffect(() => {
    if (isAdminLoggedIn && adminToken) {
      fetchAnalytics();
    }
  }, [isAdminLoggedIn, adminToken]);
  
  const fetchAnalytics = async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/admin/analytics`, {
        headers: {
          "Authorization": `Bearer ${adminToken}`
        }
      });
      if (res.status === 401) {
        handleLogout();
        return;
      }
      if (!res.ok) {
        throw new Error("Failed to fetch analytics");
      }
      const data = await res.json();
      setMetrics(data.metrics);
      setUsers(data.users || []);
      setPayments(data.payments || []);
      setTrends(data.trends || { signups: [], revenue: [] });
      
      // Load OAuth configs and recruiter list
      fetchOauthConfig();
      fetchRecruiters();
    } catch (e) {
      console.error(e);
      alert("Error loading admin data");
    } finally {
      setIsLoading(false);
    }
  };

  const fetchRecruiters = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/recruiters`, {
        headers: {
          "Authorization": `Bearer ${adminToken}`
        }
      });
      if (res.ok) {
        const data = await res.json();
        setRecruitersList(data.recruiters || []);
      }
    } catch (err) {
      console.error("Failed to load recruiters list:", err);
    }
  };

  const fetchOauthConfig = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/config`, {
        headers: {
          "Authorization": `Bearer ${adminToken}`
        }
      });
      if (res.ok) {
        const data = await res.json();
        setOauthClientId(data.google_client_id || "");
        setOauthClientSecret(data.google_client_secret || "");
        setOauthRedirectUri(data.google_redirect_uri || "https://www.pitchdock.xyz/api/oauth/google/callback");
        setOauthFrontendUrl(data.frontend_url || "https://www.pitchdock.xyz");
      }
    } catch (err) {
      console.error("Failed to load OAuth config:", err);
    }
  };

  const handleOauthSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingOauth(true);
    setOauthSaveMessage("");
    setOauthSaveError("");
    try {
      const res = await fetch(`${API_BASE}/api/admin/config`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${adminToken}`
        },
        body: JSON.stringify({
          google_client_id: oauthClientId,
          google_client_secret: oauthClientSecret,
          google_redirect_uri: oauthRedirectUri,
          frontend_url: oauthFrontendUrl
        })
      });
      if (res.ok) {
        setOauthSaveMessage("Google OAuth and base redirection configurations updated in environment memory successfully!");
      } else {
        const data = await res.json();
        setOauthSaveError(data.detail || "Failed to save settings.");
      }
    } catch (err) {
      setOauthSaveError("Network error. Unable to connect to configuration server.");
    } finally {
      setIsSavingOauth(false);
    }
  };

  const parseRecruiterBulkText = (): RecruiterContactInput[] => {
    return recruiterBulkText
      .split("\n")
      .map(line => line.trim())
      .filter(line => line && !line.toLowerCase().startsWith("email"))
      .map(line => {
        const delimiter = line.includes("|") ? "|" : line.includes("\t") ? "\t" : ",";
        const parts = line.split(delimiter).map(part => part.trim());
        return {
          email: parts[0] || "",
          name: parts[1] || "",
          company: parts[2] || "",
          title: parts[3] || "",
          category: parts[4] || ""
        };
      })
      .filter(contact => contact.email !== "");
  };

  const handleRecruiterAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setRecruiterAddMessage("");
    setRecruiterAddError("");

    let contacts: RecruiterContactInput[] = [];

    if (recruiterInputMode === "single") {
      const email = singleRecruiter.email.trim();
      if (!email) {
        setRecruiterAddError("Recruiter Email address is required.");
        return;
      }
      const emailRegex = /^[\w\.-]+@[\w\.-]+\.\w+$/;
      if (!emailRegex.test(email)) {
        setRecruiterAddError("Please enter a valid email address (e.g. recruiter@company.com).");
        return;
      }
      contacts = [{
        email: email,
        name: singleRecruiter.name?.trim() || undefined,
        company: singleRecruiter.company?.trim() || undefined,
        title: singleRecruiter.title?.trim() || undefined,
        category: singleRecruiter.category?.trim() || undefined
      }];
    } else {
      contacts = parseRecruiterBulkText();
      if (contacts.length === 0) {
        setRecruiterAddError("Please enter or paste at least one valid recruiter row before submitting.");
        return;
      }
    }

    setIsAddingRecruiters(true);
    try {
      const res = await fetch(`${API_BASE}/api/admin/recruiters/add`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${adminToken}`
        },
        body: JSON.stringify({
          contacts,
          seed_all_users: seedAllUsers
        })
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Failed to add recruiter contacts.");
      }

      const result = data.result || {};
      setRecruiterAddMessage(
        `Successfully processed ${result.contacts_received || 0} contact(s)! Added ${result.inserted_rows || 0} recruiter record(s) across ${result.target_users || 0} user queue(s). (Skipped ${result.duplicate_rows || 0} duplicates and ${result.invalid_contacts || 0} invalid rows).`
      );

      if (recruiterInputMode === "single") {
        setSingleRecruiter({ email: "", name: "", company: "", title: "", category: "" });
      } else {
        setRecruiterBulkText("");
      }

      await fetchAnalytics();
      await fetchRecruiters();
    } catch (err: any) {
      setRecruiterAddError(err.message || "Unable to add recruiter contacts.");
    } finally {
      setIsAddingRecruiters(false);
    }
  };
  
  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError("");
    try {
      const res = await fetch(`${API_BASE}/api/admin/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          email: loginEmail,
          password: loginPassword
        })
      });
      if (!res.ok) {
        throw new Error("Invalid credentials");
      }
      const data = await res.json();
      localStorage.setItem("adminToken", data.admin_token);
      setAdminToken(data.admin_token);
      setIsAdminLoggedIn(true);
    } catch (err) {
      setLoginError("Invalid email or password. Please try again.");
    }
  };
  
  const handleLogout = () => {
    localStorage.removeItem("adminToken");
    setAdminToken(null);
    setIsAdminLoggedIn(false);
  };
  
  // Filtered lists
  const filteredUsers = users.filter(user => 
    (user.email || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
    (user.full_name || "").toLowerCase().includes(searchQuery.toLowerCase())
  );
  
  const filteredPayments = payments.filter(pay => 
    (pay.user_email || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
    (pay.payment_id || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
    (pay.order_id || "").toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Remaining days calculation
  const getRemainingDays = (expiresAtStr: string | null) => {
    if (!expiresAtStr) return "Lifetime";
    const expiresAt = new Date(expiresAtStr);
    const today = new Date();
    const diffTime = expiresAt.getTime() - today.getTime();
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays > 0 ? `${diffDays} days left` : "Expired";
  };

  // Compute conversion rate
  const totalUserCount = users.length || 1;
  const paidCount = users.filter(u => ["basic", "standard", "premium"].includes(u.plan_tier)).length;
  const conversionRate = ((paidCount / totalUserCount) * 100).toFixed(1);

  // Compute plan split details
  const planAllocations = {
    free: users.filter(u => !u.plan_tier || u.plan_tier === "free").length,
    basic: users.filter(u => u.plan_tier === "basic").length,
    standard: users.filter(u => u.plan_tier === "standard").length,
    premium: users.filter(u => u.plan_tier === "premium").length
  };

  // Generate SVG path for the Line Chart
  const renderTrendChartPath = () => {
    const dataPoints = trendView === "signups" ? trends.signups : trends.revenue;
    if (!dataPoints || dataPoints.length === 0) return { linePath: "", areaPath: "", coordinates: [] };

    const width = 600;
    const height = 180;
    const padding = 20;

    const maxVal = Math.max(...dataPoints.map(p => p.value), trendView === "signups" ? 5 : 1000);
    const minVal = 0;

    const coordinates = dataPoints.map((point, index) => {
      const x = padding + (index * (width - 2 * padding)) / (dataPoints.length - 1);
      const y = height - padding - ((point.value - minVal) * (height - 2 * padding)) / (maxVal - minVal);
      return { x, y, label: point.date, val: point.value };
    });

    const linePath = coordinates.reduce((path, p, i) => {
      return i === 0 ? `M ${p.x} ${p.y}` : `${path} L ${p.x} ${p.y}`;
    }, "");

    const areaPath = `${linePath} L ${coordinates[coordinates.length - 1].x} ${height - padding} L ${coordinates[0].x} ${height - padding} Z`;

    return { linePath, areaPath, coordinates };
  };

  const chartData = renderTrendChartPath();

  if (!isAdminLoggedIn) {
     return (
        <div className="admin-login-wrapper">
          <style>{customStyles}</style>
          <div className="login-card">
             <div className="logo-section">
                <img src="/orangelogo.png" alt="Logo" style={{ borderRadius: "50%", objectFit: "cover" }} />
                <h1>Pitch<span>Dock</span> Admin</h1>
             </div>
             <p className="subtitle">Enter your master administrator credentials to access platform-wide analytics and transaction tables.</p>
             
             {loginError && <div className="error-banner">{loginError}</div>}
             
             <form onSubmit={handleLogin}>
                <div className="form-group">
                   <label>Admin Email</label>
                   <input 
                      type="email" 
                      required 
                      placeholder="admin@pitchdock.xyz" 
                      value={loginEmail}
                      onChange={e => setLoginEmail(e.target.value)}
                   />
                </div>
                <div className="form-group">
                   <label>Password</label>
                   <input 
                      type="password" 
                      required 
                      placeholder="••••••••" 
                      value={loginPassword}
                      onChange={e => setLoginPassword(e.target.value)}
                   />
                </div>
                <button type="submit" className="login-btn">Secure Login</button>
             </form>
             <div className="login-footer">
               <Link href="/">Back to PitchDock Homepage</Link>
             </div>
          </div>
        </div>
     );
  }

  return (
     <div className="admin-dashboard-root">
        <style>{customStyles}</style>
        
        {/* Header HUD */}
        <header className="admin-header">
           <div className="header-wrap">
              <div className="brand-title">
                 <img src="/orangelogo.png" alt="Logo" style={{ borderRadius: "50%", objectFit: "cover" }} />
                 <h2>PitchDock Admin <span>Console</span></h2>
              </div>
              <div className="header-actions">
                 <button onClick={fetchAnalytics} className="header-btn" disabled={isLoading}>
                    {isLoading ? "Refreshing..." : "Refresh Stats"}
                 </button>
                 <button onClick={handleLogout} className="header-btn logout">
                    Sign Out
                 </button>
              </div>
           </div>
        </header>

        <main className="admin-content">
           
           {/* Metric Cards Grid */}
           <div className="metrics-grid">
              <div className="metric-card bg-glow-blue">
                 <div className="card-header">
                    <span>Total Accounts</span>
                    <span className="icon">👥</span>
                 </div>
                 <div className="value">{isLoading ? "..." : metrics?.total_users}</div>
                 <div className="detail">Registered users base</div>
              </div>
              
              <div className="metric-card bg-glow-purple">
                 <div className="card-header">
                    <span>Total Revenue</span>
                    <span className="icon">💰</span>
                 </div>
                 <div className="value">
                    {isLoading ? "..." : `₹${metrics?.total_revenue?.toLocaleString("en-IN")}`}
                 </div>
                 <div className="detail">Cumulative transaction value</div>
              </div>

              <div className="metric-card bg-glow-emerald">
                 <div className="card-header">
                    <span>Daily Emails</span>
                    <span className="icon">✉️</span>
                 </div>
                 <div className="value">{isLoading ? "..." : metrics?.total_emails_today}</div>
                 <div className="detail">System volume today</div>
              </div>

              <div className="metric-card bg-glow-gold">
                 <div className="card-header">
                    <span>Paid Subscriptions</span>
                    <span className="icon">👑</span>
                 </div>
                 <div className="value">{isLoading ? "..." : metrics?.active_subscriptions}</div>
                 <div className="detail">
                    {conversionRate}% paid conversion
                 </div>
              </div>
           </div>

           {/* Core Visual Charts & Analytics */}
           <div className="charts-split-section">
              
              {/* Line Chart Component (SVG Based) */}
              <div className="chart-wrapper-card flex-2">
                 <div className="chart-header-row">
                    <h3>Platform Performance Metrics</h3>
                    <div className="pill-selector">
                       <button 
                          className={trendView === "signups" ? "active" : ""}
                          onClick={() => setTrendView("signups")}
                       >
                          User Signups
                       </button>
                       <button 
                          className={trendView === "revenue" ? "active" : ""}
                          onClick={() => setTrendView("revenue")}
                       >
                          Revenue Trend
                       </button>
                    </div>
                 </div>
                 
                 <div className="svg-chart-container">
                    {isLoading ? (
                       <div className="chart-placeholder">Loading trends...</div>
                    ) : chartData.coordinates.length === 0 ? (
                       <div className="chart-placeholder">No historical data available.</div>
                    ) : (
                       <svg viewBox="0 0 600 180" className="trend-svg">
                          <defs>
                             <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor={trendView === "signups" ? "#3b82f6" : "#8b5cf6"} stopOpacity="0.4" />
                                <stop offset="100%" stopColor={trendView === "signups" ? "#3b82f6" : "#8b5cf6"} stopOpacity="0.0" />
                             </linearGradient>
                          </defs>

                          {/* Grid Lines */}
                          <line x1="20" y1="20" x2="580" y2="20" stroke="rgba(255, 255, 255, 0.04)" strokeDasharray="3,3" />
                          <line x1="20" y1="80" x2="580" y2="80" stroke="rgba(255, 255, 255, 0.04)" strokeDasharray="3,3" />
                          <line x1="20" y1="140" x2="580" y2="140" stroke="rgba(255, 255, 255, 0.04)" strokeDasharray="3,3" />

                          {/* Area under the line */}
                          <path d={chartData.areaPath} fill="url(#chartGrad)" />

                          {/* Main line path */}
                          <path 
                             d={chartData.linePath} 
                             fill="none" 
                             stroke={trendView === "signups" ? "#3b82f6" : "#a78bfa"} 
                             strokeWidth="3.5" 
                             strokeLinecap="round"
                             className="glow-path"
                          />

                          {/* Interactive data dots */}
                          {chartData.coordinates.map((c, i) => (
                             <g key={i} className="chart-point-group">
                                <circle 
                                   cx={c.x} 
                                   cy={c.y} 
                                   r="5.5" 
                                   fill={trendView === "signups" ? "#3b82f6" : "#8b5cf6"} 
                                   stroke="#080b11" 
                                   strokeWidth="2" 
                                />
                                <text 
                                   x={c.x} 
                                   y={c.y - 12} 
                                   textAnchor="middle" 
                                   className="chart-dot-value"
                                >
                                   {trendView === "signups" ? c.val : `₹${c.val}`}
                                </text>
                                <text 
                                   x={c.x} 
                                   y="174" 
                                   textAnchor="middle" 
                                   className="chart-dot-label"
                                >
                                   {c.label}
                                </text>
                             </g>
                          ))}
                       </svg>
                    )}
                 </div>
              </div>

              {/* Plan Distribution Progress Bars */}
              <div className="chart-wrapper-card flex-1">
                 <h3>Subscription Breakdown</h3>
                 
                 <div className="plan-stats-list">
                    <div className="plan-bar-item">
                       <div className="plan-label-wrap">
                          <span className="badge tier-free">Free Tier</span>
                          <strong>{planAllocations.free} users ({Math.round((planAllocations.free / totalUserCount) * 100)}%)</strong>
                       </div>
                       <div className="track-bar">
                          <div className="fill-bar fill-free" style={{ width: `${(planAllocations.free / totalUserCount) * 100}%` }} />
                       </div>
                    </div>

                    <div className="plan-bar-item">
                       <div className="plan-label-wrap">
                          <span className="badge tier-basic">Basic AI</span>
                          <strong>{planAllocations.basic} users ({Math.round((planAllocations.basic / totalUserCount) * 100)}%)</strong>
                       </div>
                       <div className="track-bar">
                          <div className="fill-bar fill-basic" style={{ width: `${(planAllocations.basic / totalUserCount) * 100}%` }} />
                       </div>
                    </div>

                    <div className="plan-bar-item">
                       <div className="plan-label-wrap">
                          <span className="badge tier-standard">Standard Pro</span>
                          <strong>{planAllocations.standard} users ({Math.round((planAllocations.standard / totalUserCount) * 100)}%)</strong>
                       </div>
                       <div className="track-bar">
                          <div className="fill-bar fill-standard" style={{ width: `${(planAllocations.standard / totalUserCount) * 100}%` }} />
                       </div>
                    </div>

                    <div className="plan-bar-item">
                       <div className="plan-label-wrap">
                          <span className="badge tier-premium">Premium Master</span>
                          <strong>{planAllocations.premium} users ({Math.round((planAllocations.premium / totalUserCount) * 100)}%)</strong>
                       </div>
                       <div className="track-bar">
                          <div className="fill-bar fill-premium" style={{ width: `${(planAllocations.premium / totalUserCount) * 100}%` }} />
                       </div>
                    </div>
                 </div>
              </div>

           </div>

           {/* Data Tables Explorer */}
           <div className="table-container-card">
              <div className="card-hud">
                 <div className="tabs">
                    <button 
                       className={`tab-btn ${activeTab === "users" ? "active" : ""}`}
                       onClick={() => { setActiveTab("users"); setSearchQuery(""); }}
                    >
                       User Database ({users.length})
                    </button>
                    <button 
                       className={`tab-btn ${activeTab === "payments" ? "active" : ""}`}
                       onClick={() => { setActiveTab("payments"); setSearchQuery(""); }}
                    >
                       Transaction Logs ({payments.length})
                    </button>
                    <button 
                       className={`tab-btn ${activeTab === "recruiters" ? "active" : ""}`}
                       onClick={() => { setActiveTab("recruiters"); setSearchQuery(""); }}
                    >
                       Recruiter Intake
                    </button>
                    <button 
                       className={`tab-btn ${activeTab === "oauth" ? "active" : ""}`}
                       onClick={() => { setActiveTab("oauth"); setSearchQuery(""); }}
                    >
                       🔑 Google API Config
                    </button>
                 </div>
                 {(activeTab === "users" || activeTab === "payments") && (
                    <div className="search-bar">
                       <input 
                          type="text" 
                          placeholder={activeTab === "users" ? "Search users by name or email..." : "Search transactions by email, Order ID, or Payment ID..."} 
                          value={searchQuery}
                          onChange={e => setSearchQuery(e.target.value)}
                       />
                    </div>
                 )}
              </div>

              {isLoading ? (
                 <div className="loading-spinner-state">
                    <div className="spinner"></div>
                    <p>Fetching active database logs...</p>
                 </div>
              ) : activeTab === "users" ? (
                 <div className="table-wrapper">
                    <table className="admin-table">
                       <thead>
                          <tr>
                             <th>ID</th>
                             <th>Name</th>
                             <th>Email</th>
                             <th>Joined Date</th>
                             <th>Active Tier</th>
                             <th>Emails Sent Today</th>
                             <th>Subscription Expiration</th>
                          </tr>
                       </thead>
                       <tbody>
                          {filteredUsers.length === 0 ? (
                             <tr>
                                <td colSpan={7} className="no-records">No registered users match your query.</td>
                             </tr>
                          ) : (
                             filteredUsers.map(user => (
                                <tr key={user.id}>
                                   <td>#{user.id}</td>
                                   <td className="strong">{user.full_name || "N/A"}</td>
                                   <td>{user.email}</td>
                                   <td>{user.created_at ? new Date(user.created_at).toLocaleDateString() : "N/A"}</td>
                                   <td>
                                      <span className={`badge tier-${user.plan_tier || "free"}`}>
                                         {(user.plan_tier || "free").toUpperCase()}
                                      </span>
                                   </td>
                                   <td className="center">{user.emails_sent_today || 0}</td>
                                   <td>
                                      <span className={user.subscription_expires_at ? "expires-warn" : "expires-none"}>
                                         {getRemainingDays(user.subscription_expires_at)}
                                      </span>
                                   </td>
                                </tr>
                             ))
                          )}
                       </tbody>
                    </table>
                 </div>
              ) : activeTab === "payments" ? (
                 <div className="table-wrapper">
                    <table className="admin-table">
                       <thead>
                          <tr>
                             <th>Payment ID</th>
                             <th>Order ID</th>
                             <th>Buyer Email</th>
                             <th>Amount Paid</th>
                             <th>Subscribed Tier</th>
                             <th>Log Date</th>
                             <th>Status</th>
                          </tr>
                       </thead>
                       <tbody>
                          {filteredPayments.length === 0 ? (
                             <tr>
                                <td colSpan={7} className="no-records">No payment logs match your query.</td>
                             </tr>
                          ) : (
                             filteredPayments.map(pay => (
                                <tr key={pay.id}>
                                   <td className="strong text-code">{pay.payment_id || "N/A"}</td>
                                   <td className="text-code">{pay.order_id}</td>
                                   <td>{pay.user_email || "Deleted User"}</td>
                                   <td className="price">₹{(pay.amount / 100).toFixed(2)}</td>
                                   <td>
                                      <span className={`badge tier-${pay.plan_tier?.toLowerCase() || "free"}`}>
                                         {pay.plan_tier?.toUpperCase()}
                                      </span>
                                   </td>
                                   <td>{pay.created_at ? new Date(pay.created_at).toLocaleDateString() : "N/A"}</td>
                                   <td>
                                      <span className={`badge status-${pay.status === "success" ? "success" : "failed"}`}>
                                         {pay.status.toUpperCase()}
                                      </span>
                                   </td>
                                </tr>
                             ))
                          )}
                       </tbody>
                    </table>
                 </div>
              ) : activeTab === "recruiters" ? (
                  <div className="oauth-config-panel" style={{ padding: "32px", color: "var(--text-p)" }}>
                     <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "16px", marginBottom: "24px" }}>
                        <div>
                           <h3 style={{ fontSize: "20px", fontWeight: "700", marginBottom: "6px", display: "flex", alignItems: "center", gap: "10px" }}>
                              Recruiter Database Manager
                           </h3>
                           <p style={{ color: "var(--text-s)", fontSize: "13.5px", margin: 0, lineHeight: "1.5" }}>
                              Add, validate, and distribute recruiter records without touching the database manually.
                           </p>
                        </div>

                        {/* Mode Toggle Buttons */}
                        <div className="pill-selector">
                           <button 
                              type="button"
                              className={recruiterInputMode === "single" ? "active" : ""}
                              onClick={() => { setRecruiterInputMode("single"); setRecruiterAddMessage(""); setRecruiterAddError(""); }}
                           >
                              Single Entry
                           </button>
                           <button 
                              type="button"
                              className={recruiterInputMode === "bulk" ? "active" : ""}
                              onClick={() => { setRecruiterInputMode("bulk"); setRecruiterAddMessage(""); setRecruiterAddError(""); }}
                           >
                              Advanced Bulk Import
                           </button>
                        </div>
                     </div>

                     {recruiterAddMessage && (
                        <div style={{ background: "rgba(16, 185, 129, 0.15)", border: "1px solid var(--emerald-accent)", color: "#34d399", padding: "14px 18px", borderRadius: "10px", fontSize: "13.5px", marginBottom: "24px" }}>
                           {recruiterAddMessage}
                        </div>
                     )}

                     {recruiterAddError && (
                        <div style={{ background: "rgba(239, 68, 68, 0.15)", border: "1px solid #ef4444", color: "#fca5a5", padding: "14px 18px", borderRadius: "10px", fontSize: "13.5px", marginBottom: "24px" }}>
                           ✕ {recruiterAddError}
                        </div>
                     )}

                     <form onSubmit={handleRecruiterAdd} style={{ maxWidth: "900px", marginBottom: "40px" }}>
                        {recruiterInputMode === "single" ? (
                           <div style={{ background: "rgba(3, 7, 18, 0.4)", border: "1px solid var(--panel-border)", borderRadius: "12px", padding: "24px", marginBottom: "20px" }}>
                              <h4 style={{ fontSize: "15px", fontWeight: "600", color: "#ffffff", marginTop: 0, marginBottom: "18px" }}>
                                 Add Recruiter Record
                              </h4>

                              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "18px", marginBottom: "18px" }}>
                                 {/* Recruiter Email */}
                                 <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                                    <label style={{ fontSize: "12px", fontWeight: "bold", textTransform: "uppercase", color: "var(--text-s)", letterSpacing: "0.5px" }}>
                                       Recruiter Email <span style={{ color: "#ef4444" }}>*</span>
                                    </label>
                                    <input
                                       type="email"
                                       required
                                       placeholder="e.g. recruiter@company.com"
                                       value={singleRecruiter.email}
                                       onChange={e => setSingleRecruiter({ ...singleRecruiter, email: e.target.value })}
                                       style={{ width: "100%", padding: "12px 16px", borderRadius: "8px", background: "rgba(3, 7, 18, 0.8)", border: "1px solid var(--panel-border)", color: "#f3f4f6", fontSize: "13.5px", outline: "none" }}
                                    />
                                 </div>

                                 {/* Recruiter Name */}
                                 <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                                    <label style={{ fontSize: "12px", fontWeight: "bold", textTransform: "uppercase", color: "var(--text-s)", letterSpacing: "0.5px" }}>
                                       Full Name
                                    </label>
                                    <input
                                       type="text"
                                       placeholder="e.g. Ananya Rao (defaults to 'HR Manager' if blank)"
                                       value={singleRecruiter.name}
                                       onChange={e => setSingleRecruiter({ ...singleRecruiter, name: e.target.value })}
                                       style={{ width: "100%", padding: "12px 16px", borderRadius: "8px", background: "rgba(3, 7, 18, 0.8)", border: "1px solid var(--panel-border)", color: "#f3f4f6", fontSize: "13.5px", outline: "none" }}
                                    />
                                 </div>

                                 {/* Company Name */}
                                 <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                                    <label style={{ fontSize: "12px", fontWeight: "bold", textTransform: "uppercase", color: "var(--text-s)", letterSpacing: "0.5px" }}>
                                       Company / Organization
                                    </label>
                                    <input
                                       type="text"
                                       placeholder="e.g. Razorpay, Google, Microsoft"
                                       value={singleRecruiter.company}
                                       onChange={e => setSingleRecruiter({ ...singleRecruiter, company: e.target.value })}
                                       style={{ width: "100%", padding: "12px 16px", borderRadius: "8px", background: "rgba(3, 7, 18, 0.8)", border: "1px solid var(--panel-border)", color: "#f3f4f6", fontSize: "13.5px", outline: "none" }}
                                    />
                                 </div>

                                 {/* Job Title */}
                                 <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                                    <label style={{ fontSize: "12px", fontWeight: "bold", textTransform: "uppercase", color: "var(--text-s)", letterSpacing: "0.5px" }}>
                                       Job Title / Designation
                                    </label>
                                    <input
                                       type="text"
                                       placeholder="e.g. Talent Acquisition Partner, Lead Technical Recruiter"
                                       value={singleRecruiter.title}
                                       onChange={e => setSingleRecruiter({ ...singleRecruiter, title: e.target.value })}
                                       style={{ width: "100%", padding: "12px 16px", borderRadius: "8px", background: "rgba(3, 7, 18, 0.8)", border: "1px solid var(--panel-border)", color: "#f3f4f6", fontSize: "13.5px", outline: "none" }}
                                    />
                                 </div>

                                 {/* Category / Industry */}
                                 <div style={{ display: "flex", flexDirection: "column", gap: "6px", gridColumn: "1 / -1" }}>
                                    <label style={{ fontSize: "12px", fontWeight: "bold", textTransform: "uppercase", color: "var(--text-s)", letterSpacing: "0.5px" }}>
                                       Category / Domain / Industry
                                    </label>
                                    <input
                                       type="text"
                                       placeholder="e.g. Fintech, FAANG, AI, EdTech, E-commerce"
                                       value={singleRecruiter.category}
                                       onChange={e => setSingleRecruiter({ ...singleRecruiter, category: e.target.value })}
                                       style={{ width: "100%", padding: "12px 16px", borderRadius: "8px", background: "rgba(3, 7, 18, 0.8)", border: "1px solid var(--panel-border)", color: "#f3f4f6", fontSize: "13.5px", outline: "none" }}
                                    />
                                 </div>
                              </div>
                           </div>
                        ) : (
                           <div style={{ background: "rgba(3, 7, 18, 0.4)", border: "1px solid var(--panel-border)", borderRadius: "12px", padding: "24px", marginBottom: "20px" }}>
                              <h4 style={{ fontSize: "15px", fontWeight: "600", color: "#ffffff", marginTop: 0, marginBottom: "12px" }}>
                                 Advanced Bulk Import
                              </h4>
                              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                                 <textarea
                                    required
                                    rows={10}
                                    placeholder={"email, name, company, title, category\nrecruiter@company.com, Ananya Rao, Razorpay, Talent Partner, Fintech\nhr@startup.com | HR Manager | Startup Labs | Recruiter | Startups"}
                                    value={recruiterBulkText}
                                    onChange={e => setRecruiterBulkText(e.target.value)}
                                    style={{ width: "100%", padding: "14px 16px", borderRadius: "8px", background: "rgba(3, 7, 18, 0.8)", border: "1px solid var(--panel-border)", color: "#f3f4f6", fontSize: "13.5px", lineHeight: "1.5", fontFamily: "var(--font-geist-mono, monospace)", resize: "vertical" }}
                                 />
                                 <small style={{ color: "var(--text-s)", fontSize: "12px", lineHeight: "1.5" }}>
                                    Accepted column order: <strong>email, name, company, title, category</strong>. Supports comma (<code>,</code>), pipe (<code>|</code>), or tab (<code>\t</code>) separators.
                                 </small>
                              </div>
                           </div>
                        )}

                        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                           <label style={{ display: "flex", alignItems: "center", gap: "10px", color: "var(--text-p)", fontSize: "13.5px", cursor: "pointer" }}>
                              <input
                                 type="checkbox"
                                 checked={seedAllUsers}
                                 onChange={e => setSeedAllUsers(e.target.checked)}
                                 style={{ width: "17px", height: "17px", accentColor: "var(--emerald-accent)" }}
                              />
                              Add recruiter to all registered user queues as well as the master recruiter pool
                           </label>

                           <button 
                              type="submit" 
                              disabled={isAddingRecruiters}
                              style={{ padding: "12px 28px", borderRadius: "8px", background: "var(--emerald-accent)", color: "#ffffff", border: "none", fontWeight: "600", fontSize: "14px", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: "8px", alignSelf: "flex-start", opacity: isAddingRecruiters ? 0.7 : 1 }}
                           >
                              {isAddingRecruiters ? "Saving recruiter..." : recruiterInputMode === "single" ? "Save Recruiter Record" : "Import Recruiter Records"}
                           </button>
                        </div>
                     </form>

                     {/* Master Database Recruiters Table */}
                     <div style={{ marginTop: "40px", borderTop: "1px solid var(--panel-border)", paddingTop: "32px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "16px", marginBottom: "20px" }}>
                           <div>
                              <h4 style={{ fontSize: "16px", fontWeight: "600", color: "#ffffff", margin: 0 }}>
                                 Master Recruiter Database ({recruitersList.length} Contacts)
                              </h4>
                              <p style={{ color: "var(--text-s)", fontSize: "12.5px", margin: "4px 0 0 0" }}>
                                 Recruiter contacts stored in the default master queue (user #1).
                              </p>
                           </div>

                           <div className="search-bar">
                              <input 
                                 type="text" 
                                 placeholder="Search recruiters by name, email, company..." 
                                 value={recruiterSearchQuery}
                                 onChange={e => setRecruiterSearchQuery(e.target.value)}
                              />
                           </div>
                        </div>

                        <div className="table-wrapper">
                           <table className="admin-table">
                              <thead>
                                 <tr>
                                    <th>ID</th>
                                    <th>Name</th>
                                    <th>Email</th>
                                    <th>Company</th>
                                    <th>Title</th>
                                    <th>Category</th>
                                    <th>Status</th>
                                 </tr>
                              </thead>
                              <tbody>
                                 {recruitersList
                                    .filter(r => 
                                       (r.name || "").toLowerCase().includes(recruiterSearchQuery.toLowerCase()) ||
                                       (r.email || "").toLowerCase().includes(recruiterSearchQuery.toLowerCase()) ||
                                       (r.company || "").toLowerCase().includes(recruiterSearchQuery.toLowerCase()) ||
                                       (r.title || "").toLowerCase().includes(recruiterSearchQuery.toLowerCase()) ||
                                       (r.category || "").toLowerCase().includes(recruiterSearchQuery.toLowerCase())
                                    )
                                    .length === 0 ? (
                                    <tr>
                                       <td colSpan={7} className="no-records">
                                          {recruitersList.length === 0 ? "No recruiter contacts stored in the master pool." : "No recruiters match your search."}
                                       </td>
                                    </tr>
                                 ) : (
                                    recruitersList
                                       .filter(r => 
                                          (r.name || "").toLowerCase().includes(recruiterSearchQuery.toLowerCase()) ||
                                          (r.email || "").toLowerCase().includes(recruiterSearchQuery.toLowerCase()) ||
                                          (r.company || "").toLowerCase().includes(recruiterSearchQuery.toLowerCase()) ||
                                          (r.title || "").toLowerCase().includes(recruiterSearchQuery.toLowerCase()) ||
                                          (r.category || "").toLowerCase().includes(recruiterSearchQuery.toLowerCase())
                                       )
                                       .map(rec => (
                                          <tr key={rec.id}>
                                             <td>#{rec.id}</td>
                                             <td className="strong">{rec.name || "HR Manager"}</td>
                                             <td>{rec.email}</td>
                                             <td>{rec.company || "N/A"}</td>
                                             <td>{rec.title || "N/A"}</td>
                                             <td>
                                                <span className="badge tier-basic" style={{ background: "rgba(59, 130, 246, 0.12)", color: "#93c5fd" }}>
                                                   {rec.category || "General"}
                                                </span>
                                             </td>
                                             <td>
                                                <span className={`badge status-${rec.status === "sent" ? "success" : "success"}`} style={{ background: "rgba(16, 185, 129, 0.12)", color: "#6ee7b7" }}>
                                                   {(rec.status || "pending").toUpperCase()}
                                                </span>
                                             </td>
                                          </tr>
                                       ))
                                 )}
                              </tbody>
                           </table>
                        </div>
                     </div>
                  </div>
              ) : (
                 <div className="oauth-config-panel" style={{ padding: "32px", color: "var(--text-p)" }}>
                    <h3 style={{ fontSize: "18px", fontWeight: "600", marginBottom: "8px", display: "flex", alignItems: "center", gap: "10px" }}>
                       🔑 Google OAuth Configuration
                    </h3>
                    <p style={{ color: "var(--text-s)", fontSize: "13.5px", marginBottom: "24px", lineHeight: "1.6" }}>
                       Configure the global Google Cloud Console OAuth App credentials. These settings allow users to securely authenticate their personal Gmail accounts via OAuth and delegate outreach dispatches directly via Google's official Gmail APIs.
                    </p>

                    {oauthSaveMessage && (
                       <div style={{ background: "rgba(16, 185, 129, 0.15)", border: "1px solid var(--emerald-accent)", color: "#34d399", padding: "12px", borderRadius: "8px", fontSize: "13.5px", marginBottom: "20px" }}>
                          ✓ {oauthSaveMessage}
                       </div>
                    )}

                    {oauthSaveError && (
                       <div style={{ background: "rgba(239, 68, 68, 0.15)", border: "1px solid #ef4444", color: "#fca5a5", padding: "12px", borderRadius: "8px", fontSize: "13.5px", marginBottom: "20px" }}>
                          ✕ {oauthSaveError}
                       </div>
                    )}

                    <form onSubmit={handleOauthSave} style={{ display: "flex", flexDirection: "column", gap: "20px", maxWidth: "680px" }}>
                       <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                          <label style={{ fontSize: "12px", fontWeight: "bold", textTransform: "uppercase", color: "var(--text-s)", letterSpacing: "0.5px" }}>Google Client ID</label>
                          <input 
                             type="text" 
                             required 
                             placeholder="e.g. 104812345678-abcdefgh.apps.googleusercontent.com" 
                             value={oauthClientId}
                             onChange={e => setOauthClientId(e.target.value)}
                             style={{ width: "100%", padding: "12px 16px", borderRadius: "8px", background: "rgba(3, 7, 18, 0.6)", border: "1px solid var(--panel-border)", color: "#f3f4f6", fontSize: "13.5px" }}
                          />
                       </div>

                       <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                          <label style={{ fontSize: "12px", fontWeight: "bold", textTransform: "uppercase", color: "var(--text-s)", letterSpacing: "0.5px" }}>Google Client Secret</label>
                          <input 
                             type="password" 
                             required 
                             placeholder="e.g. GOCSPX-abcdefghijklmnop" 
                             value={oauthClientSecret}
                             onChange={e => setOauthClientSecret(e.target.value)}
                             style={{ width: "100%", padding: "12px 16px", borderRadius: "8px", background: "rgba(3, 7, 18, 0.6)", border: "1px solid var(--panel-border)", color: "#f3f4f6", fontSize: "13.5px" }}
                          />
                       </div>

                       <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                          <label style={{ fontSize: "12px", fontWeight: "bold", textTransform: "uppercase", color: "var(--text-s)", letterSpacing: "0.5px" }}>Google Authorized Redirect URI</label>
                          <input 
                             type="text" 
                             required 
                             placeholder="e.g. https://www.pitchdock.xyz/api/oauth/google/callback" 
                             value={oauthRedirectUri}
                             onChange={e => setOauthRedirectUri(e.target.value)}
                             style={{ width: "100%", padding: "12px 16px", borderRadius: "8px", background: "rgba(3, 7, 18, 0.6)", border: "1px solid var(--panel-border)", color: "#f3f4f6", fontSize: "13.5px" }}
                          />
                          <small style={{ display: "block", color: "var(--text-s)", fontSize: "11px", marginTop: "4px" }}>
                             * You must add this exact URI under <strong>Authorized redirect URIs</strong> in your Google Cloud Console Credentials manager.
                          </small>
                       </div>

                       <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                          <label style={{ fontSize: "12px", fontWeight: "bold", textTransform: "uppercase", color: "var(--text-s)", letterSpacing: "0.5px" }}>Application Base URL (Frontend Redirect Target)</label>
                          <input 
                             type="text" 
                             required 
                             placeholder="e.g. https://www.pitchdock.xyz" 
                             value={oauthFrontendUrl}
                             onChange={e => setOauthFrontendUrl(e.target.value)}
                             style={{ width: "100%", padding: "12px 16px", borderRadius: "8px", background: "rgba(3, 7, 18, 0.6)", border: "1px solid var(--panel-border)", color: "#f3f4f6", fontSize: "13.5px" }}
                          />
                       </div>

                       <button 
                          type="submit" 
                          disabled={isSavingOauth}
                          style={{ padding: "12px 24px", borderRadius: "8px", background: "var(--emerald-accent)", color: "#ffffff", border: "none", fontWeight: "600", fontSize: "13.5px", cursor: "pointer", display: "inline-flex", alignSelf: "flex-start", opacity: isSavingOauth ? 0.7 : 1 }}
                       >
                          {isSavingOauth ? "Applying configurations..." : "Save Connection Settings"}
                       </button>
                    </form>
                 </div>
              )}
           </div>
        </main>
     </div>
  );
}

// Sleek dark-mode, glassmorphic admin styles
const customStyles = `
  :root {
     --admin-bg: #0b0f19;
     --panel-bg: rgba(17, 24, 39, 0.7);
     --panel-border: rgba(255, 255, 255, 0.08);
     --gold-accent: #f59e0b;
     --emerald-accent: #10b981;
     --blue-accent: #3b82f6;
     --purple-accent: #8b5cf6;
     --text-p: #f3f4f6;
     --text-s: #9ca3af;
  }
  
  .admin-login-wrapper {
     display: flex;
     justify-content: center;
     align-items: center;
     min-height: 100vh;
     background: radial-gradient(circle at top right, #111827 0%, #030712 100%);
     font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
     color: #f3f4f6;
     padding: 20px;
  }
  
  .login-card {
     background: rgba(17, 24, 39, 0.75);
     backdrop-filter: blur(12px);
     -webkit-backdrop-filter: blur(12px);
     border: 1px solid rgba(255, 255, 255, 0.08);
     border-radius: 16px;
     padding: 40px;
     width: 100%;
     max-width: 480px;
     box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
  }
  
  .logo-section {
     display: flex;
     align-items: center;
     gap: 12px;
     margin-bottom: 16px;
     justify-content: center;
  }
  .logo-section img {
     width: 40px;
     height: 40px;
     border-radius: 8px;
  }
  .logo-section h1 {
     font-size: 24px;
     font-weight: 800;
     letter-spacing: -0.5px;
     margin: 0;
  }
  .logo-section h1 span {
     color: #4f46e5;
  }
  
  .subtitle {
     text-align: center;
     color: #9ca3af;
     font-size: 13.5px;
     line-height: 1.6;
     margin-bottom: 28px;
  }
  
  .error-banner {
     background: rgba(239, 68, 68, 0.15);
     border: 1px solid rgba(239, 68, 68, 0.3);
     color: #fca5a5;
     padding: 12px;
     border-radius: 8px;
     font-size: 13px;
     text-align: center;
     margin-bottom: 20px;
  }
  
  .form-group {
     margin-bottom: 20px;
  }
  .form-group label {
     display: block;
     font-size: 12.5px;
     font-weight: 500;
     color: #9ca3af;
     margin-bottom: 6px;
     text-transform: uppercase;
     letter-spacing: 0.5px;
  }
  .form-group input {
     width: 100%;
     padding: 12px 16px;
     border-radius: 8px;
     background: rgba(3, 7, 18, 0.6);
     border: 1px solid rgba(255, 255, 255, 0.1);
     color: #f3f4f6;
     font-size: 14px;
     outline: none;
     transition: border 0.2s;
  }
  .form-group input:focus {
     border-color: #4f46e5;
  }
  
  .login-btn {
     width: 100%;
     padding: 14px;
     border-radius: 8px;
     background: #4f46e5;
     color: #ffffff;
     border: none;
     font-size: 14.5px;
     font-weight: 600;
     cursor: pointer;
     transition: background 0.2s, transform 0.1s;
     margin-top: 10px;
  }
  .login-btn:hover {
     background: #4338ca;
  }
  .login-btn:active {
     transform: scale(0.99);
  }
  
  .login-footer {
     text-align: center;
     margin-top: 24px;
     font-size: 13px;
  }
  .login-footer a {
     color: #9ca3af;
     text-decoration: none;
     transition: color 0.2s;
  }
  .login-footer a:hover {
     color: #4f46e5;
  }
  
  /* Dashboard layout */
  .admin-dashboard-root {
     min-height: 100vh;
     background: #080b11;
     color: #f3f4f6;
     font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  }
  
  .admin-header {
     background: rgba(13, 17, 28, 0.85);
     backdrop-filter: blur(10px);
     border-bottom: 1px solid rgba(255, 255, 255, 0.06);
     position: sticky;
     top: 0;
     z-index: 100;
  }
  .header-wrap {
     max-width: 1400px;
     margin: 0 auto;
     padding: 16px 24px;
     display: flex;
     justify-content: space-between;
     align-items: center;
  }
  .brand-title {
     display: flex;
     align-items: center;
     gap: 10px;
  }
  .brand-title img {
     width: 32px;
     height: 32px;
     border-radius: 6px;
  }
  .brand-title h2 {
     font-size: 18px;
     font-weight: 700;
     margin: 0;
  }
  .brand-title h2 span {
     color: #6366f1;
     font-weight: 400;
  }
  
  .header-actions {
     display: flex;
     gap: 12px;
  }
  .header-btn {
     background: rgba(255, 255, 255, 0.08);
     border: 1px solid rgba(255, 255, 255, 0.15);
     color: #f3f4f6;
     padding: 8px 16px;
     border-radius: 6px;
     font-size: 13px;
     font-weight: 500;
     cursor: pointer;
     transition: background 0.2s;
  }
  .header-btn:hover {
     background: rgba(255, 255, 255, 0.15);
  }
  .header-btn.logout {
     background: rgba(239, 68, 68, 0.15);
     border-color: rgba(239, 68, 68, 0.3);
     color: #fca5a5;
  }
  .header-btn.logout:hover {
     background: rgba(239, 68, 68, 0.25);
  }
  
  .admin-content {
     max-width: 1400px;
     margin: 0 auto;
     padding: 32px 24px;
  }
  
  .metrics-grid {
     display: grid;
     grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
     gap: 20px;
     margin-bottom: 32px;
  }
  
  .metric-card {
     background: rgba(17, 24, 39, 0.55);
     border: 1px solid rgba(255, 255, 255, 0.06);
     border-radius: 12px;
     padding: 24px;
     transition: transform 0.2s, border-color 0.2s;
     position: relative;
     overflow: hidden;
  }
  .metric-card::before {
     content: '';
     position: absolute;
     top: 0;
     left: 0;
     right: 0;
     height: 3px;
  }
  .metric-card:hover {
     transform: translateY(-2px);
     border-color: rgba(255, 255, 255, 0.12);
  }
  
  .bg-glow-blue::before { background: #3b82f6; }
  .bg-glow-purple::before { background: #8b5cf6; }
  .bg-glow-emerald::before { background: #10b981; }
  .bg-glow-gold::before { background: #f59e0b; }
  
  .metric-card .card-header {
     display: flex;
     justify-content: space-between;
     font-size: 13px;
     font-weight: 600;
     color: #9ca3af;
     text-transform: uppercase;
     letter-spacing: 0.5px;
  }
  .metric-card .value {
     font-size: 32px;
     font-weight: 800;
     margin: 12px 0 6px;
     letter-spacing: -1px;
  }
  .metric-card .detail {
     font-size: 12.5px;
     color: #9ca3af;
  }
  
  /* Graph & Split layout */
  .charts-split-section {
     display: flex;
     gap: 24px;
     margin-bottom: 32px;
     flex-wrap: wrap;
  }
  
  .flex-2 { flex: 2 1 600px; }
  .flex-1 { flex: 1 1 320px; }
  
  .chart-wrapper-card {
     background: rgba(17, 24, 39, 0.55);
     border: 1px solid rgba(255, 255, 255, 0.06);
     border-radius: 14px;
     padding: 24px;
     display: flex;
     flex-direction: column;
  }
  .chart-wrapper-card h3 {
     font-size: 16px;
     margin: 0 0 20px 0;
     font-weight: 600;
  }
  
  .chart-header-row {
     display: flex;
     justify-content: space-between;
     align-items: center;
     margin-bottom: 16px;
     flex-wrap: wrap;
     gap: 12px;
  }
  .chart-header-row h3 {
     margin: 0;
  }
  
  .pill-selector {
     display: flex;
     background: rgba(3, 7, 18, 0.6);
     padding: 3px;
     border-radius: 8px;
     border: 1px solid rgba(255, 255, 255, 0.08);
  }
  .pill-selector button {
     background: transparent;
     border: none;
     color: #9ca3af;
     padding: 6px 12px;
     font-size: 12.5px;
     font-weight: 500;
     border-radius: 6px;
     cursor: pointer;
     transition: all 0.2s;
  }
  .pill-selector button.active {
     background: #4f46e5;
     color: #ffffff;
  }
  
  .svg-chart-container {
     position: relative;
     width: 100%;
     height: 180px;
     margin-top: 10px;
  }
  .chart-placeholder {
     display: flex;
     justify-content: center;
     align-items: center;
     height: 100%;
     color: #9ca3af;
     font-size: 13.5px;
  }
  
  .trend-svg {
     width: 100%;
     height: 100%;
     overflow: visible;
  }
  
  .glow-path {
     filter: drop-shadow(0px 4px 10px rgba(99, 102, 241, 0.45));
  }
  
  .chart-point-group circle {
     transition: r 0.2s ease, fill 0.2s ease;
     cursor: pointer;
  }
  .chart-point-group:hover circle {
     r: 7.5;
     fill: #ffffff;
  }
  
  .chart-dot-value {
     fill: #ffffff;
     font-size: 10.5px;
     font-weight: bold;
     opacity: 0;
     transition: opacity 0.2s ease;
  }
  .chart-point-group:hover .chart-dot-value {
     opacity: 1;
  }
  
  .chart-dot-label {
     fill: #9ca3af;
     font-size: 10px;
  }
  
  /* Progress stats list */
  .plan-stats-list {
     display: flex;
     flex-direction: column;
     gap: 16px;
  }
  
  .plan-bar-item {
     display: flex;
     flex-direction: column;
     gap: 6px;
  }
  .plan-label-wrap {
     display: flex;
     justify-content: space-between;
     font-size: 12.5px;
     align-items: center;
  }
  .plan-label-wrap strong {
     color: #ffffff;
  }
  
  .track-bar {
     height: 8px;
     background: rgba(3, 7, 18, 0.6);
     border-radius: 4px;
     width: 100%;
     overflow: hidden;
  }
  .fill-bar {
     height: 100%;
     border-radius: 4px;
  }
  .fill-free { background: #6b7280; box-shadow: 0 0 8px rgba(107, 114, 128, 0.5); }
  .fill-basic { background: #3b82f6; box-shadow: 0 0 8px rgba(59, 130, 246, 0.5); }
  .fill-standard { background: #8b5cf6; box-shadow: 0 0 8px rgba(139, 92, 246, 0.5); }
  .fill-premium { background: #f59e0b; box-shadow: 0 0 8px rgba(245, 158, 11, 0.5); }

  /* Database table styling */
  .table-container-card {
     background: rgba(17, 24, 39, 0.5);
     backdrop-filter: blur(8px);
     border: 1px solid rgba(255, 255, 255, 0.06);
     border-radius: 14px;
     overflow: hidden;
  }
  
  .card-hud {
     padding: 16px 24px;
     background: rgba(13, 17, 28, 0.5);
     border-bottom: 1px solid rgba(255, 255, 255, 0.06);
     display: flex;
     justify-content: space-between;
     align-items: center;
     gap: 20px;
     flex-wrap: wrap;
  }
  
  .tabs {
     display: flex;
     gap: 8px;
  }
  .tab-btn {
     background: transparent;
     border: none;
     color: #9ca3af;
     padding: 8px 16px;
     border-radius: 6px;
     font-size: 13.5px;
     font-weight: 600;
     cursor: pointer;
     transition: all 0.2s;
  }
  .tab-btn.active {
     background: rgba(255, 255, 255, 0.08);
     color: #ffffff;
  }
  .tab-btn:hover:not(.active) {
     color: #ffffff;
  }
  
  .search-bar input {
     background: rgba(3, 7, 18, 0.6);
     border: 1px solid rgba(255, 255, 255, 0.08);
     color: #f3f4f6;
     padding: 8px 16px;
     border-radius: 6px;
     font-size: 13px;
     width: 320px;
     outline: none;
     transition: border 0.2s;
  }
  .search-bar input:focus {
     border-color: #6366f1;
  }
  
  .loading-spinner-state {
     padding: 60px;
     text-align: center;
     color: #9ca3af;
  }
  .spinner {
     width: 36px;
     height: 36px;
     border: 3px solid rgba(255, 255, 255, 0.08);
     border-top-color: #6366f1;
     border-radius: 50%;
     margin: 0 auto 16px;
     animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
     to { transform: rotate(360deg); }
  }
  
  .table-wrapper {
     overflow-x: auto;
  }
  .admin-table {
     width: 100%;
     border-collapse: collapse;
     font-size: 13.5px;
     text-align: left;
  }
  .admin-table th {
     background: rgba(3, 7, 18, 0.25);
     padding: 14px 24px;
     font-weight: 600;
     color: #9ca3af;
     border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }
  .admin-table td {
     padding: 14px 24px;
     border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  }
  .admin-table tbody tr:hover {
     background: rgba(255, 255, 255, 0.02);
  }
  
  .admin-table td.strong {
     font-weight: 600;
     color: #ffffff;
  }
  .admin-table td.center {
     text-align: center;
  }
  .admin-table td.price {
     font-family: monospace;
     font-size: 14px;
     color: #10b981;
     font-weight: 600;
  }
  .text-code {
     font-family: monospace;
     font-size: 12.5px;
     opacity: 0.85;
  }
  
  .no-records {
     text-align: center;
     padding: 40px;
     color: #9ca3af;
  }
  
  /* Badges */
  .badge {
     display: inline-block;
     padding: 3px 8px;
     border-radius: 4px;
     font-size: 11px;
     font-weight: 700;
     letter-spacing: 0.5px;
  }
  .badge.tier-free { background: rgba(107, 114, 128, 0.15); color: #9ca3af; }
  .badge.tier-basic { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }
  .badge.tier-standard { background: rgba(139, 92, 246, 0.15); color: #a78bfa; }
  .badge.tier-premium { background: rgba(245, 158, 11, 0.15); color: #fbbf24; }
  
  .badge.status-success { background: rgba(16, 185, 129, 0.15); color: #34d399; }
  .badge.status-failed { background: rgba(239, 68, 68, 0.15); color: #fca5a5; }
  
  .expires-warn {
     color: #fbbf24;
     font-size: 12.5px;
  }
  .expires-none {
     color: #9ca3af;
     font-size: 12.5px;
  }
`;

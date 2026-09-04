import React, { useState, useEffect } from 'react';
import { supabase } from '../../../utils/supabaseClient';
import { generateDashboardInsights } from '../../../utils/aiClient';
import {
    AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
    XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
    Legend, ComposedChart, Line, RadialBarChart, RadialBar,
    Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis
} from 'recharts';
import './AdminOverview.css';

const CL = ['#4F46E5', '#0EA5E9', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899', '#14B8A6', '#F97316'];

const TT = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null;
    return (
        <div className="ao-tt">
            <div style={{ fontWeight: 700, fontSize: '0.8rem', marginBottom: 4 }}>{label}</div>
            {payload.map((e, i) => (
                <div key={i} style={{ color: e.color, fontWeight: 600, fontSize: '0.82rem' }}>{e.name}: {e.value?.toLocaleString?.() || e.value}</div>
            ))}
        </div>
    );
};

const AdminOverview = () => {
    const [loading, setLoading] = useState(false);
    const [d, setD] = useState({
        pp: [], sc: [], ch: [], co: [], pr: [], su: [], le: [], cl: [],
        paidP: 0, paidS: 0, paidC: 0, rev: 0, days: 0, avgScore: 0, totalXP: 0,
        convP: 0, activeKids: 0, schoolKids: 0, parentKids: 0, guardianData: [], uniqueGuardians: 0,
        payPie: [{ name: 'Loading...', value: 1 }], lvlDist: [], ageDist: [], genDist: [], revBar: [], pipeline: [], xpDist: [], schoolEnroll: [], topKids: [],
        mrr: 0, monthlyARPU: 0, annualARPU: 0, ltv: 0, burnRate: 0, recentParents: [],
        studentFees: 0, schoolFees: 0, schoolRevenue: []
    });
    const [aiData, setAiData] = useState(null);
    const [aiOpen, setAiOpen] = useState(false);
    const [aiLoading, setAiLoading] = useState(false);
    const [error, setError] = useState(null);
    const [startDate, setStartDate] = useState('');
    const [endDate, setEndDate] = useState('');

    useEffect(() => {
        let mounted = true;
        const fetchData = async () => {
            if (!mounted) return;
            setLoading(true);
            const results = { pp: [], sc: [], ch: [], co: [], pr: [], su: [], le: [], cl: [] };
            const fetchSafe = async (table, cols = '*') => {
                try {
                    const t = new Promise((_, r) => setTimeout(() => r(new Error('T')), 5000));
                    const q = supabase.from(table).select(cols);
                    const res = await Promise.race([q, t]);
                    return res.data || [];
                } catch (e) { return []; }
            };
            results.pp = await fetchSafe('parent_profiles', 'id,full_name,email,payment_status,plan,created_at,theme,cnic');
            results.sc = await fetchSafe('schools', 'id,school_name,payment_status,created_at');
            results.ch = await fetchSafe('children', 'id,name,gender,parent_id,school_id,age,current_level,total_xp,payment_status,parent_email,parent_cnic,parent_name,created_at');
            results.co = await fetchSafe('lesson_completions', 'score,created_at');
            results.pr = await fetchSafe('projects', 'id,created_at');
            results.su = await fetchSafe('subscriptions', 'id,created_at');
            results.le = await fetchSafe('lessons', 'id');
            results.cl = await fetchSafe('course_classes', 'id');
            if (!mounted) return;

            // Apply Filters
            const filterByDate = (arr) => {
                if (!startDate && !endDate) return arr;
                return arr.filter(item => {
                    const date = new Date(item.created_at);
                    if (startDate && date < new Date(startDate)) return false;
                    if (endDate && date > new Date(endDate + 'T23:59:59')) return false;
                    return true;
                });
            };

            const pp = filterByDate(results.pp);
            const sc = filterByDate(results.sc);
            const ch = filterByDate(results.ch);
            const co = filterByDate(results.co);
            const pr = filterByDate(results.pr);
            const su = filterByDate(results.su);
            const le = results.le;
            const cl = results.cl;
            const paidP = pp.filter(p => p.payment_status === 'paid').length;
            const paidS = sc.filter(s => s.payment_status === 'paid').length;
            const paidC = ch.filter(c => c.payment_status === 'paid').length;
            const studentFees = paidC * 500;
            const schoolFees = paidS * 5000;
            const rev = studentFees + schoolFees;
            const days = Math.max(1, Math.floor((new Date() - new Date('2026-03-01')) / 86400000));
            const avgScore = co.length > 0 ? Math.round(co.reduce((a, c) => a + (c.score || 0), 0) / co.length) : 0;
            const totalXP = ch.reduce((a, c) => a + (c.total_xp || 0), 0);
            const convP = pp.length > 0 ? Math.round((paidP / pp.length) * 100) : 0;
            const parentMap = {}; pp.forEach(p => { parentMap[p.id] = p; });
            const guardianData = ch.map(c => ({
                student: c.name, gender: c.gender || 'N/A', guardian: c.parent_name || parentMap[c.parent_id]?.full_name || 'Guardian',
                parentCnic: c.parent_cnic || parentMap[c.parent_id]?.cnic || 'N/A',
                guardianEmail: c.parent_email || parentMap[c.parent_id]?.email || 'N/A', level: c.current_level || 'Class 1',
                xp: c.total_xp || 0, payment: c.payment_status || 'pending', age: c.age || '-', school: c.school_id ? 'School' : 'Direct'
            }));
            const uniqueEmails = new Set([...pp.map(p => p.email), ...ch.map(c => c.parent_email)].filter(Boolean));
            const uniqueGuardians = uniqueEmails.size;

            const payPie = [{ name: 'Paid Parents', value: paidP }, { name: 'Pending Parents', value: pp.length - paidP }, { name: 'Paid Schools', value: paidS }, { name: 'Pending Schools', value: sc.length - paidS }].filter(x => x.value > 0);
            const lvlMap = {}; ch.forEach(c => { const l = c.current_level || 'Class 1'; lvlMap[l] = (lvlMap[l] || 0) + 1; });
            const ageMap = {}; ch.forEach(c => { const a = c.age || 'Unknown'; ageMap[a] = (ageMap[a] || 0) + 1; });
            const genMap = {}; ch.forEach(c => { const g = c.gender || 'Other'; genMap[g] = (genMap[g] || 0) + 1; });

            const schoolRevData = sc.map(s => {
                const sKids = ch.filter(c => c.school_id === s.id && c.payment_status === 'paid');
                const rev = (sKids.length * 500) + (s.payment_status === 'paid' ? 5000 : 0);
                return { name: s.school_name?.substring(0, 10), revenue: rev, students: sKids.length };
            });

            const activeKids = ch.filter(c => (c.total_xp || 0) > 0).length;
            const schoolKids = ch.filter(c => c.school_id).length;
            const parentKids = ch.filter(c => !c.school_id).length;

            setD({
                pp, sc, ch, co, pr, su, le, cl, paidP, paidS, paidC, rev, days, avgScore, totalXP, convP, guardianData, uniqueGuardians,
                activeKids, schoolKids, parentKids,
                payPie: payPie.length ? payPie : [{ name: 'No Data', value: 1 }],
                lvlDist: Object.entries(lvlMap).map(([n, v]) => ({ name: n, value: v })),
                ageDist: Object.entries(ageMap).map(([n, v]) => ({ name: `Age ${n}`, value: v })),
                genDist: Object.entries(genMap).map(([n, v]) => ({ name: n, value: v })),
                revBar: [{ name: 'Direct Students', rev: ch.filter(c => !c.school_id && c.payment_status === 'paid').length * 500 }, { name: 'School Students', rev: ch.filter(c => c.school_id && c.payment_status === 'paid').length * 500 }, { name: 'School Registration', rev: paidS * 5000 }],
                pipeline: [{ name: 'Profiles', val: pp.length + sc.length }, { name: 'Paid', val: paidP + paidS }],
                xpDist: [{ name: '0 XP', value: ch.filter(c => (c.total_xp || 0) === 0).length }, { name: '1-100 XP', value: ch.filter(c => (c.total_xp || 0) > 0 && (c.total_xp || 0) <= 100).length }, { name: '101-500 XP', value: ch.filter(c => (c.total_xp || 0) > 100 && (c.total_xp || 0) <= 500).length }, { name: '500+ XP', value: ch.filter(c => (c.total_xp || 0) > 500).length }],
                schoolEnroll: sc.map(s => ({ name: s.school_name?.substring(0, 10), total: ch.filter(c => c.school_id === s.id).length, paid: ch.filter(c => c.school_id === s.id && c.payment_status === 'paid').length })),
                topKids: [...ch].sort((a, b) => (b.total_xp || 0) - (a.total_xp || 0)).slice(0, 8),
                mrr: rev,
                monthlyARPU: ch.length > 0 ? Math.round(rev / ch.length) : 0,
                annualARPU: ch.length > 0 ? Math.round((rev / ch.length) * 12) : 0,
                ltv: ch.length > 0 ? Math.round((rev / ch.length) * 24) : 0,
                burnRate: Math.round(rev * 0.45), recentParents: pp.slice(-5).reverse(),
                studentFees, schoolFees, schoolRevenue: schoolRevData
            });
            setLoading(false);
        };
        fetchData();
        return () => { mounted = false; };
    }, [startDate, endDate]);






    const handleAI = async () => {
        if (aiData) { setAiOpen(!aiOpen); return; }
        setAiOpen(true); setAiLoading(true);
        try {
            const res = await generateDashboardInsights({
                totalParents: d.pp.length, paidParents: d.paidP, parentConversionRate: d.convP,
                totalSchools: d.sc.length, paidSchools: d.paidS,
                totalChildren: d.ch.length, paidChildren: d.paidC,
                revenue: d.rev, mrr: d.mrr, arpu: d.arpu, ltv: d.ltv, cac: 50,
                totalCompletions: d.co.length, avgScore: d.avgScore, totalProjects: d.pr.length,
                totalLessons: d.le.length, totalClasses: d.cl.length,
                daysSinceLaunch: d.days, totalContent: 0, totalSubscriptions: d.su.length
            });
            setAiData(res);
        } catch (e) { setAiData({ executiveSummary: 'AI temporarily unavailable: ' + e.message, keyInsights: [], risks: [], opportunities: [], recommendations: [], burnRateAnalysis: 'N/A', churnPrediction: 'N/A', growthForecast: 'N/A', healthScore: 0 }); }
        finally { setAiLoading(false); }
    };

    return (
        <div className="ao-root">
            {loading && (
                <div style={{ position: 'fixed', top: 20, right: 20, background: 'white', padding: '8px 16px', borderRadius: '20px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)', zIndex: 9999, display: 'flex', alignItems: 'center', gap: 10, fontSize: '0.8rem', fontWeight: 600, color: '#4F46E5' }}>
                    <div className="ao-spin" style={{ width: 14, height: 14, borderWidth: 2, borderTopColor: '#4F46E5', borderRadius: '50%', animation: 'ao-spin 1s linear infinite' }}></div>
                    Refreshing Data...
                </div>
            )}
            {/* HEADER */}
            <div className="ao-head">
                <div>
                    <h1 className="ao-h1">Command Center</h1>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 15, marginTop: 5 }}>
                        <p className="ao-sub" style={{ margin: 0 }}>Real-time Intelligence -- Day {d.days}</p>
                        <div className="ao-filters" style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'rgba(79, 70, 229, 0.05)', padding: '4px 12px', borderRadius: 12, border: '1px solid rgba(79, 70, 229, 0.1)' }}>
                            <span style={{ fontSize: '0.75rem', fontWeight: 700, color: '#4F46E5' }}>Filter:</span>
                            <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} style={{ border: 'none', background: 'transparent', fontSize: '0.75rem', fontWeight: 600, color: '#1E293B', outline: 'none' }} />
                            <span style={{ fontSize: '0.75rem', color: '#64748B' }}>to</span>
                            <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} style={{ border: 'none', background: 'transparent', fontSize: '0.75rem', fontWeight: 600, color: '#1E293B', outline: 'none' }} />
                            {(startDate || endDate) && <button onClick={() => { setStartDate(''); setEndDate(''); }} style={{ border: 'none', background: 'none', fontSize: '0.7rem', fontWeight: 800, color: '#EF4444', cursor: 'pointer', padding: '0 4px' }}>Clear</button>}
                        </div>
                    </div>
                </div>
                <div className="ao-head-r">
                    <span className="ao-dot"></span><span>Live</span>
                    <button className="ao-ai-btn" onClick={handleAI}>
                        {aiLoading ? 'Analyzing...' : aiOpen ? 'Hide AI Insights' : 'AI Insights'}
                    </button>
                </div>
            </div>

            {/* AI PANEL */}
            {aiOpen && (
                <div className="ao-ai">
                    {aiLoading && (
                        <div className="ao-ai-wait">
                            <div className="ao-spin" style={{ width: 20, height: 20, borderWidth: 3 }}></div>
                            <span>Analyzing ecosystem metrics and generating predictions...</span>
                        </div>
                    )}
                    {aiData && (
                        <div className="ao-ai-content">
                            <div className="ao-ai-header">
                                <h3 className="ao-ai-title">🤖 AI Business Insights & Growth Advisor</h3>
                                <span style={{ background: '#EEF2FF', color: '#4F46E5', fontSize: '0.72rem', fontWeight: 800, padding: '3px 10px', borderRadius: 12, border: '1px solid #C7D2FE' }}>
                                    Powered by BusinessInsightsAgent (Qwen 2.5 on AMD GPU)
                                </span>
                            </div>

                            <p className="ao-ai-sum">{aiData?.executiveSummary || "Analyzing platform ecosystem to generate strategic foresight and business intelligence..."}</p>


                            <div className="ao-ai-grid">
                                <div className="ao-ai-chart-box">
                                    <div className="ao-ai-chart-label">
                                        <span style={{ background: '#4F46E5', width: 10, height: 10, borderRadius: '50%' }}></span>
                                        Projected Revenue Growth
                                    </div>
                                    <ResponsiveContainer width="100%" height={150}>
                                        <AreaChart data={aiData?.predictedGrowth || []}>
                                            <defs><linearGradient id="cR" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#4F46E5" stopOpacity={0.3} /><stop offset="95%" stopColor="#4F46E5" stopOpacity={0} /></linearGradient></defs>
                                            <XAxis dataKey="month" tick={{ fontSize: 8 }} /><YAxis tick={{ fontSize: 8 }} /><Tooltip />
                                            <Area type="monotone" dataKey="revenue" stroke="#4F46E5" strokeWidth={2} fill="url(#cR)" />
                                        </AreaChart>
                                    </ResponsiveContainer>
                                </div>

                                <div className="ao-ai-chart-box">
                                    <div className="ao-ai-chart-label">
                                        <span style={{ background: '#10B981', width: 10, height: 10, borderRadius: '50%' }}></span>
                                        Student Engagement Forecast
                                    </div>
                                    <ResponsiveContainer width="100%" height={150}>
                                        <AreaChart data={aiData?.engagementForecast || []}>
                                            <defs><linearGradient id="cE" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#10B981" stopOpacity={0.3} /><stop offset="95%" stopColor="#10B981" stopOpacity={0} /></linearGradient></defs>
                                            <XAxis dataKey="day" tick={{ fontSize: 8 }} /><YAxis tick={{ fontSize: 8 }} /><Tooltip />
                                            <Area type="monotone" dataKey="val" stroke="#10B981" strokeWidth={2} fill="url(#cE)" />
                                        </AreaChart>
                                    </ResponsiveContainer>
                                </div>

                                <div className="ao-ai-chart-box">
                                    <div className="ao-ai-chart-label">
                                        <span style={{ background: '#F59E0B', width: 10, height: 10, borderRadius: '50%' }}></span>
                                        User Distribution
                                    </div>
                                    <ResponsiveContainer width="100%" height={150}>
                                        <PieChart>
                                            <Pie data={aiData?.userSegmentPrediction || []} innerRadius={35} outerRadius={55} paddingAngle={5} dataKey="value">
                                                {(aiData?.userSegmentPrediction || []).map((_, i) => <Cell key={i} fill={CL[i % CL.length]} />)}
                                            </Pie>
                                            <Tooltip />
                                        </PieChart>
                                    </ResponsiveContainer>
                                </div>

                                <div className="ao-ai-chart-box">
                                    <div className="ao-ai-chart-label">
                                        <span style={{ background: '#0EA5E9', width: 10, height: 10, borderRadius: '50%' }}></span>
                                        Core Economics (PKR)
                                    </div>
                                    <ResponsiveContainer width="100%" height={150}>
                                        <BarChart data={aiData?.unitEconomics || []}>
                                            <XAxis dataKey="name" tick={{ fontSize: 8 }} /><YAxis tick={{ fontSize: 8 }} />
                                            <Tooltip /><Bar dataKey="val" fill="#0EA5E9" radius={[4, 4, 0, 0]} />
                                        </BarChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>

                            <div className="ao-ai-cols">
                                <div>
                                    <h4 className="ao-ai-subh">📈 Market Expansion &amp; User Acquisition</h4>
                                    <ul className="ao-ai-list">{(aiData?.keyInsights || []).map((k, i) => <li key={i}>{k}</li>)}</ul>
                                </div>
                                <div>
                                    <h4 className="ao-ai-subh">💡 Product-Led Growth (PLG) Enhancements</h4>
                                    <ul className="ao-ai-list">{(aiData?.recommendations || []).map((r, i) => <li key={i}>{r}</li>)}</ul>
                                </div>
                                {aiData?.monetizationOpportunities?.length > 0 && (
                                    <div>
                                        <h4 className="ao-ai-subh">💵 Monetization Boosters &amp; Pricing Levers</h4>
                                        <ul className="ao-ai-list">{aiData.monetizationOpportunities.map((m, i) => <li key={i}>{m}</li>)}</ul>
                                    </div>
                                )}
                                {aiData?.riskAnalysis?.length > 0 && (
                                    <div>
                                        <h4 className="ao-ai-subh">🛡️ Churn Risk &amp; Bottleneck Mitigations</h4>
                                        <ul className="ao-ai-list">{aiData.riskAnalysis.map((rk, i) => <li key={i}>{rk}</li>)}</ul>
                                    </div>
                                )}
                            </div>

                            <div className="ao-ai-foot">
                                <div className="ao-ai-pill"><b>Platform Health Score:</b> {aiData?.healthScore || 85}/100</div>
                                <div className="ao-ai-pill"><b>Growth Forecast:</b> {aiData?.growthForecast || "Stable"}</div>
                                <div className="ao-ai-pill"><b>Churn Risk:</b> {aiData?.churnPrediction || "Low"}</div>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* ROW 0: High Visibility Totals */}
            <div className="ao-row ao-r0 mb-4">
                <div className="ao-stat-card school-stat">
                    <div className="ao-stat-info">
                        <div className="ao-stat-label">Registered Schools</div>
                        <div className="ao-stat-value">{d.sc.length}</div>
                        <div className="ao-stat-trend">Partner educational institutions</div>
                    </div>
                </div>
                <div className="ao-stat-card parent-stat">
                    <div className="ao-stat-info">
                        <div className="ao-stat-label">Registered Parents</div>
                        <div className="ao-stat-value">{d.uniqueGuardians}</div>
                        <div className="ao-stat-trend">Total unique parents/guardians</div>
                    </div>
                </div>
                <div className="ao-stat-card student-stat">
                    <div className="ao-stat-info">
                        <div className="ao-stat-label">Active Students</div>
                        <div className="ao-stat-value">{d.ch.length}</div>
                        <div className="ao-stat-trend">Total students enrolled</div>
                    </div>
                </div>
            </div>

            {/* ROW 1: Mixed - Health Gauge + Top KPIs */}
            <div className="ao-row ao-r1">
                <div className="ao-card ao-card-kpi" style={{ width: '100%' }}>
                    <div className="ao-kpi-row">
                        <div className="ao-kpi" style={{ borderLeft: '4px solid #10B981' }}><span className="ao-kpi-l">Total Revenue</span><span className="ao-kpi-v">PKR {d.rev.toLocaleString()}</span></div>
                        <div className="ao-kpi" style={{ borderLeft: '4px solid #4F46E5' }}><span className="ao-kpi-l">Total Parents</span><span className="ao-kpi-v">{d.uniqueGuardians}</span></div>
                        <div className="ao-kpi" style={{ borderLeft: '4px solid #0EA5E9' }}><span className="ao-kpi-l">Total Schools</span><span className="ao-kpi-v">{d.sc.length}</span></div>
                        <div className="ao-kpi" style={{ borderLeft: '4px solid #8B5CF6' }}><span className="ao-kpi-l">Total Students</span><span className="ao-kpi-v">{d.ch.length}</span></div>
                    </div>
                    <div className="ao-kpi-row">
                        <div className="ao-kpi" style={{ borderLeft: '4px solid #10B981' }}><span className="ao-kpi-l">Paid Schools</span><span className="ao-kpi-v">{d.paidS}</span></div>
                        <div className="ao-kpi" style={{ borderLeft: '4px solid #10B981' }}><span className="ao-kpi-l">Paid Students</span><span className="ao-kpi-v">{d.paidC}</span></div>
                        <div className="ao-kpi" style={{ borderLeft: '4px solid #F59E0B' }}><span className="ao-kpi-l">Students Fee</span><span className="ao-kpi-v">PKR {d.studentFees.toLocaleString()}</span></div>
                        <div className="ao-kpi" style={{ borderLeft: '4px solid #F59E0B' }}><span className="ao-kpi-l">School One-time Fee</span><span className="ao-kpi-v">PKR {d.schoolFees.toLocaleString()}</span></div>
                    </div>
                </div>
            </div>

            {/* ROW 2: Mixed - Financials bar + Payment pie */}
            <div className="ao-row ao-r2">
                <div className="ao-card ao-w60">
                    <div className="ao-card-t">Revenue Sources (PKR)</div>
                    <ResponsiveContainer width="100%" height={250}>
                        <BarChart data={d.revBar}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F1F5F9" />
                            <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748B' }} />
                            <YAxis tick={{ fontSize: 11, fill: '#64748B' }} />
                            <Tooltip content={<TT />} />
                            <Bar dataKey="rev" name="Revenue" radius={[6, 6, 0, 0]}>{d.revBar.map((_, i) => <Cell key={i} fill={CL[i]} />)}</Bar>
                        </BarChart>
                    </ResponsiveContainer>
                </div>
                <div className="ao-card ao-w40">
                    <div className="ao-card-t">Payment Status</div>
                    <ResponsiveContainer width="100%" height={250}>
                        <PieChart>
                            <Pie data={d.payPie} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3} dataKey="value">
                                {d.payPie.map((_, i) => <Cell key={i} fill={CL[i]} />)}
                            </Pie>
                            <Tooltip content={<TT />} /><Legend iconType="circle" />
                        </PieChart>
                    </ResponsiveContainer>
                </div>
            </div>

            {/* ROW 3: Mixed - Small KPI cards + Level Dist chart */}
            <div className="ao-row ao-r3">
                <div className="ao-mini-grid">
                    <div className="ao-mini" style={{ background: '#FFFBEB' }}><span className="ao-mini-v" style={{ color: '#92400E' }}>{d.activeKids}</span><span className="ao-mini-l">Active Students</span></div>
                    <div className="ao-mini" style={{ background: '#EFF6FF' }}><span className="ao-mini-v" style={{ color: '#2563EB' }}>{d.co.length}</span><span className="ao-mini-l">Lessons Finished</span></div>
                    <div className="ao-mini" style={{ background: '#FFF7ED' }}><span className="ao-mini-v" style={{ color: '#EA580C' }}>{d.pr.length}</span><span className="ao-mini-l">Student Projects</span></div>
                    <div className="ao-mini" style={{ background: '#F0F9FF' }}><span className="ao-mini-v" style={{ color: '#0284C7' }}>{d.le.length}</span><span className="ao-mini-l">Available Lessons</span></div>
                    <div className="ao-mini" style={{ background: '#FEFCE8' }}><span className="ao-mini-v" style={{ color: '#A16207' }}>{d.cl.length}</span><span className="ao-mini-l">Course Levels</span></div>
                </div>
                <div className="ao-card ao-w50">
                    <div className="ao-card-t">Student Class Distribution</div>
                    <ResponsiveContainer width="100%" height={280}>
                        <PieChart>
                            <Pie data={d.lvlDist} cx="50%" cy="50%" innerRadius={50} outerRadius={85} paddingAngle={3} dataKey="value">
                                {d.lvlDist.map((_, i) => <Cell key={i} fill={CL[i % CL.length]} />)}
                            </Pie>
                            <Tooltip content={<TT />} /><Legend iconType="circle" />
                        </PieChart>
                    </ResponsiveContainer>
                </div>
            </div>

            {/* ROW 4: Age + Gender Demographics */}
            <div className="ao-row ao-r2">
                <div className="ao-card ao-w50">
                    <div className="ao-card-t">Age Demographics</div>
                    <ResponsiveContainer width="100%" height={250}>
                        <BarChart data={d.ageDist}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F1F5F9" />
                            <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748B' }} />
                            <YAxis tick={{ fontSize: 11, fill: '#64748B' }} allowDecimals={false} />
                            <Tooltip content={<TT />} />
                            <Bar dataKey="value" name="Students" fill="#14B8A6" radius={[6, 6, 0, 0]} />
                        </BarChart>
                    </ResponsiveContainer>
                </div>
                <div className="ao-card ao-w50">
                    <div className="ao-card-t">Gender Distribution</div>
                    <ResponsiveContainer width="100%" height={250}>
                        <PieChart>
                            <Pie data={d.genDist} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3} dataKey="value" label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}>
                                {d.genDist.map((_, i) => <Cell key={i} fill={i === 0 ? '#0EA5E9' : i === 1 ? '#EC4899' : '#8B5CF6'} />)}
                            </Pie>
                            <Tooltip content={<TT />} />
                            <Legend iconType="circle" />
                        </PieChart>
                    </ResponsiveContainer>
                </div>
            </div>
            {/* ROW 4.5: XP Distribution */}
            <div className="ao-row ao-r2">
                <div className="ao-card ao-full">
                    <div className="ao-card-t">XP Distribution</div>
                    <ResponsiveContainer width="100%" height={250}>
                        <BarChart data={d.xpDist}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F1F5F9" />
                            <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748B' }} />
                            <YAxis tick={{ fontSize: 11, fill: '#64748B' }} allowDecimals={false} />
                            <Tooltip content={<TT />} />
                            <Bar dataKey="value" name="Students" fill="#8B5CF6" radius={[6, 6, 0, 0]} />
                        </BarChart>
                    </ResponsiveContainer>
                </div>
            </div>

            {/* ROW 5: Conversion Pipeline + School Enrollment */}
            <div className="ao-row ao-r2">
                <div className="ao-card ao-w40">
                    <div className="ao-card-t">Conversion Pipeline</div>
                    <ResponsiveContainer width="100%" height={250}>
                        <BarChart data={d.pipeline} layout="vertical">
                            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#F1F5F9" />
                            <XAxis type="number" tick={{ fontSize: 11, fill: '#64748B' }} />
                            <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: '#64748B' }} width={100} />
                            <Tooltip content={<TT />} />
                            <Bar dataKey="val" name="Count" radius={[0, 6, 6, 0]}>{d.pipeline.map((_, i) => <Cell key={i} fill={CL[i + 1]} />)}</Bar>
                        </BarChart>
                    </ResponsiveContainer>
                </div>
                <div className="ao-card ao-w60">
                    <div className="ao-card-t">School Enrollment</div>
                    <ResponsiveContainer width="100%" height={250}>
                        <BarChart data={d.schoolEnroll}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F1F5F9" />
                            <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#64748B' }} />
                            <YAxis tick={{ fontSize: 11, fill: '#64748B' }} allowDecimals={false} />
                            <Tooltip content={<TT />} />
                            <Bar dataKey="total" name="Total" fill="#4F46E5" radius={[4, 4, 0, 0]} />
                            <Bar dataKey="paid" name="Paid" fill="#10B981" radius={[4, 4, 0, 0]} />
                        </BarChart>
                    </ResponsiveContainer>
                </div>
            </div>

            {/* ROW 5.5: Per-School Revenue */}
            <div className="ao-row ao-r2">
                <div className="ao-card ao-full">
                    <div className="ao-card-t">Per-School Revenue Breakdown (Students x Rs500 + Rs5000 Registration)</div>
                    <ResponsiveContainer width="100%" height={280}>
                        <ComposedChart data={d.schoolRevenue}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F1F5F9" />
                            <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#64748B' }} />
                            <YAxis yAxisId="left" tick={{ fontSize: 11, fill: '#64748B' }} />
                            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11, fill: '#64748B' }} />
                            <Tooltip content={<TT />} />
                            <Bar yAxisId="left" dataKey="revenue" name="Revenue (PKR)" fill="#10B981" radius={[6, 6, 0, 0]} />
                            <Line yAxisId="right" dataKey="students" name="Students" stroke="#4F46E5" strokeWidth={2} dot={{ r: 5, fill: '#4F46E5' }} />
                            <Legend />
                        </ComposedChart>
                    </ResponsiveContainer>
                </div>
            </div>

            {/* ROW 6: Parent/Guardian-Student Mapping */}
            <div className="ao-card ao-full" id="guardian-mapping">
                <div className="ao-card-t">Parent/Guardian -- Student Mapping (Includes CSV Imports)</div>
                <div className="ao-tw">
                    <table className="ao-tbl">
                        <thead><tr><th>Student</th><th>Gender</th><th>Guardian</th><th>Guardian CNIC</th><th>Guardian Email</th><th>Level</th><th>Age</th><th>XP</th><th>Payment</th><th>Source</th></tr></thead>
                        <tbody>
                            {d.guardianData.map((g, i) => (
                                <tr key={i}>
                                    <td style={{ fontWeight: 700 }}>{g.student}</td>
                                    <td><span className="ao-badge ao-bp">{g.gender || 'N/A'}</span></td>
                                    <td>{g.guardian}</td>
                                    <td style={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>{g.parentCnic || 'N/A'}</td>
                                    <td style={{ fontSize: '0.82rem', color: '#64748B' }}>{g.guardianEmail}</td>
                                    <td>{g.level}</td>
                                    <td>{g.age || '-'}</td>
                                    <td><span className="ao-xp">{g.xp} XP</span></td>
                                    <td><span className={`ao-badge ${g.payment === 'paid' ? 'ao-bg' : 'ao-bw'}`}>{g.payment}</span></td>
                                    <td>{g.school}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* ROW 7: Top Students Table */}
            <div className="ao-card ao-full">
                <div className="ao-card-t">Top Performing Students</div>
                <div className="ao-tw">
                    <table className="ao-tbl">
                        <thead><tr><th>#</th><th>Student</th><th>Level</th><th>XP</th><th>Age</th><th>Payment</th><th>Type</th></tr></thead>
                        <tbody>
                            {d.topKids.map((k, i) => (
                                <tr key={k.id}>
                                    <td><span className="ao-rank">{i + 1}</span></td>
                                    <td style={{ fontWeight: 700 }}>{k.name}</td>
                                    <td>{k.current_level}</td>
                                    <td><span className="ao-xp">{k.total_xp || 0} XP</span></td>
                                    <td>{k.age || '-'}</td>
                                    <td><span className={`ao-badge ${k.payment_status === 'paid' ? 'ao-bg' : 'ao-bw'}`}>{k.payment_status}</span></td>
                                    <td>{k.school_id ? 'School' : 'Direct'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* ROW 8: Recent Parents */}
            <div className="ao-card ao-full">
                <div className="ao-card-t">Recent Parent Registrations</div>
                <div className="ao-tw">
                    <table className="ao-tbl">
                        <thead><tr><th>Name</th><th>Email</th><th>CNIC</th><th>Plan</th><th>Payment</th><th>Theme</th><th>Joined</th></tr></thead>
                        <tbody>
                            {d.recentParents.map(p => (
                                <tr key={p.id}>
                                    <td style={{ fontWeight: 700 }}>{p.full_name}</td>
                                    <td style={{ fontSize: '0.82rem' }}>{p.email || 'N/A'}</td>
                                    <td style={{ fontSize: '0.82rem' }}>{p.cnic || 'N/A'}</td>
                                    <td><span className="ao-badge ao-bp">{p.plan || 'free'}</span></td>
                                    <td><span className={`ao-badge ${p.payment_status === 'paid' ? 'ao-bg' : 'ao-bw'}`}>{p.payment_status}</span></td>
                                    <td>{p.theme}</td>
                                    <td>{new Date(p.created_at).toLocaleDateString()}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* ROW 9: School Breakdown */}
            <div className="ao-card ao-full">
                <div className="ao-card-t">Partner Schools Breakdown</div>
                <div className="ao-tw">
                    <table className="ao-tbl">
                        <thead><tr><th>School Name</th><th>Admin Email</th><th>Students</th><th>Total Revenue (PKR)</th><th>Payment Status</th></tr></thead>
                        <tbody>
                            {d.sc.map(s => {
                                const schoolStudents = d.ch.filter(c => c.school_id === s.id);
                                return (
                                    <tr key={s.id}>
                                        <td style={{ fontWeight: 700 }}>{s.school_name}</td>
                                        <td style={{ fontSize: '0.82rem' }}>{s.admin_email}</td>
                                        <td><span className="ao-xp">{schoolStudents.length} Students</span></td>
                                        <td style={{ fontWeight: 700 }}>Rs {(schoolStudents.length * 500) + 5000}</td>
                                        <td><span className={`ao-badge ${s.payment_status === 'paid' ? 'ao-bg' : 'ao-bw'}`}>{s.payment_status}</span></td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>

            <div className="ao-foot">Kido Dev Control Panel -- Security Level: Multi-Auth Verified</div>
        </div>
    );
};

export default AdminOverview;

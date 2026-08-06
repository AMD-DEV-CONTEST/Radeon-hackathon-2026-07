import { useState, useEffect } from 'react';
import { supabase } from '../../../utils/supabaseClient';

const useDashboardData = () => {
    const [loading, setLoading] = useState(true);
    const [stats, setStats] = useState(null);
    const [charts, setCharts] = useState(null);
    const [tables, setTables] = useState(null);

    useEffect(() => {
        const fetch = async () => {
            try {
                const [
                    { data: parents },
                    { data: schools },
                    { data: children },
                    { data: completions },
                    { data: projects },
                    { data: subs },
                    { data: content },
                    { data: lessons },
                    { data: classes }
                ] = await Promise.all([
                    supabase.from('parent_profiles').select('*'),
                    supabase.from('schools').select('*'),
                    supabase.from('children').select('*'),
                    supabase.from('lesson_completions').select('*'),
                    supabase.from('projects').select('*'),
                    supabase.from('subscriptions').select('*'),
                    supabase.from('content_library').select('*'),
                    supabase.from('lessons').select('*'),
                    supabase.from('course_classes').select('*')
                ]);

                const pp = parents || []; const sc = schools || []; const ch = children || [];
                const co = completions || []; const pr = projects || []; const su = subs || [];
                const cn = content || []; const le = lessons || []; const cl = classes || [];

                const paidP = pp.filter(p => p.payment_status === 'paid').length;
                const paidS = sc.filter(s => s.payment_status === 'paid').length;
                const paidC = ch.filter(c => c.payment_status === 'paid').length;
                const pendP = pp.length - paidP;
                const pendS = sc.length - paidS;
                const pendC = ch.length - paidC;
                const rev = (paidP * 100) + (paidS * 5000);
                const avgScore = co.length > 0 ? Math.round(co.reduce((a, c) => a + (c.score || 0), 0) / co.length) : 0;
                const totalXP = ch.reduce((a, c) => a + (c.total_xp || 0), 0);
                const avgXP = ch.length > 0 ? Math.round(totalXP / ch.length) : 0;

                // Launch date approx
                const launch = new Date('2026-02-28');
                const now = new Date();
                const days = Math.floor((now - launch) / 86400000);
                const convRate = pp.length > 0 ? Math.round((paidP / pp.length) * 100) : 0;
                const schoolConv = sc.length > 0 ? Math.round((paidS / sc.length) * 100) : 0;
                const mrr = rev; // monthly simplified
                const arpu = (paidP + paidS) > 0 ? Math.round(rev / (paidP + paidS)) : 0;
                const ltv = arpu * 12;
                const cac = pp.length > 0 ? Math.round(500 / (pp.length || 1)) : 0;
                const burnRate = Math.round(rev * 0.6);
                const runway = burnRate > 0 ? Math.round(rev / burnRate) : 0;

                // Growth by month
                const monthMap = {};
                pp.forEach(p => {
                    const m = new Date(p.created_at).toLocaleString('default', { month: 'short', year: '2-digit' });
                    monthMap[m] = (monthMap[m] || { parents: 0, schools: 0, students: 0 });
                    monthMap[m].parents++;
                });
                sc.forEach(s => {
                    const m = new Date(s.created_at).toLocaleString('default', { month: 'short', year: '2-digit' });
                    if (!monthMap[m]) monthMap[m] = { parents: 0, schools: 0, students: 0 };
                    monthMap[m].schools++;
                });
                ch.forEach(c => {
                    const m = new Date(c.created_at).toLocaleString('default', { month: 'short', year: '2-digit' });
                    if (!monthMap[m]) monthMap[m] = { parents: 0, schools: 0, students: 0 };
                    monthMap[m].students++;
                });
                const growthData = Object.entries(monthMap).map(([name, v]) => ({ name, ...v }));

                // Level distribution
                const lvlMap = {};
                ch.forEach(c => {
                    const l = c.current_level || 'Level 1';
                    lvlMap[l] = (lvlMap[l] || 0) + 1;
                });
                const levelDist = Object.entries(lvlMap).map(([name, value]) => ({ name, value }));
                if (levelDist.length === 0) levelDist.push({ name: 'No Data', value: 1 });

                // Payment distribution
                const payDist = [
                    { name: 'Paid Parents', value: paidP },
                    { name: 'Pending Parents', value: pendP },
                    { name: 'Paid Schools', value: paidS },
                    { name: 'Pending Schools', value: pendS },
                ].filter(d => d.value > 0);
                if (payDist.length === 0) payDist.push({ name: 'No Data', value: 1 });

                // Revenue breakdown
                const revBreak = [
                    { name: 'Parents', value: paidP * 100 },
                    { name: 'Schools', value: paidS * 5000 }
                ];

                // Top students by XP
                const topStudents = [...ch].sort((a, b) => (b.total_xp || 0) - (a.total_xp || 0)).slice(0, 10);

                // Age distribution
                const ageMap = {};
                ch.forEach(c => {
                    const a = c.age || 'Unknown';
                    ageMap[a] = (ageMap[a] || 0) + 1;
                });
                const ageDist = Object.entries(ageMap).map(([name, value]) => ({ name: `Age ${name}`, value }));

                // School student counts
                const schoolStudents = sc.map(s => ({
                    name: s.school_name,
                    students: ch.filter(c => c.school_id === s.id).length,
                    paid: ch.filter(c => c.school_id === s.id && c.payment_status === 'paid').length
                }));

                // Conversion pipeline
                const pipeline = [
                    { name: 'Registered', value: pp.length + sc.length },
                    { name: 'Onboarded', value: pp.filter(p => p.onboarding_completed).length + sc.length },
                    { name: 'Paid', value: paidP + paidS },
                ];

                // XP distribution buckets
                const xpBuckets = { '0-50': 0, '51-200': 0, '201-500': 0, '500+': 0 };
                ch.forEach(c => {
                    const x = c.total_xp || 0;
                    if (x <= 50) xpBuckets['0-50']++;
                    else if (x <= 200) xpBuckets['51-200']++;
                    else if (x <= 500) xpBuckets['201-500']++;
                    else xpBuckets['500+']++;
                });
                const xpDist = Object.entries(xpBuckets).map(([name, value]) => ({ name, value }));

                setStats({
                    totalParents: pp.length, paidParents: paidP, pendingParents: pendP,
                    totalSchools: sc.length, paidSchools: paidS, pendingSchools: pendS,
                    totalChildren: ch.length, paidChildren: paidC, pendingChildren: pendC,
                    revenue: rev, mrr, arpu, ltv, cac, burnRate, runway,
                    avgScore, totalXP, avgXP,
                    totalCompletions: co.length, totalProjects: pr.length,
                    totalSubscriptions: su.length, totalContent: cn.length,
                    totalLessons: le.length, totalClasses: cl.length,
                    daysSinceLaunch: days, convRate, schoolConv,
                    premiumUsers: paidP + paidS,
                    parentConversionRate: convRate,
                    activeStudents: ch.filter(c => (c.total_xp || 0) > 0).length,
                    inactiveStudents: ch.filter(c => (c.total_xp || 0) === 0).length,
                    avgStudentsPerSchool: sc.length > 0 ? Math.round(ch.filter(c => c.school_id).length / sc.length) : 0,
                    schoolStudentTotal: ch.filter(c => c.school_id).length,
                    parentStudentTotal: ch.filter(c => !c.school_id).length,
                    recentSignups7d: pp.filter(p => (now - new Date(p.created_at)) < 7 * 86400000).length,
                    recentSignups30d: pp.filter(p => (now - new Date(p.created_at)) < 30 * 86400000).length,
                    engagementRate: ch.length > 0 ? Math.round((ch.filter(c => (c.total_xp || 0) > 0).length / ch.length) * 100) : 0,
                    completionRate: (le.length * ch.length) > 0 ? Math.round((co.length / (le.length * ch.length)) * 100) : 0,
                });

                setCharts({
                    growth: growthData, levelDist, payDist, revBreak,
                    ageDist, pipeline, xpDist, schoolStudents,
                });

                setTables({ topStudents, recentParents: pp.slice(-5).reverse(), schools: sc });
            } catch (err) {
                console.error('Dashboard fetch error:', err);
            } finally {
                setLoading(false);
            }
        };
        fetch();
    }, []);

    return { loading, stats, charts, tables };
};

export default useDashboardData;

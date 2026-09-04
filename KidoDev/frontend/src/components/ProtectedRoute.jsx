import React, { useEffect, useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { supabase } from '../utils/supabaseClient';
import SpriteLoader from './Loader/SpriteLoader';

const ProtectedRoute = ({ children }) => {
    const [loading, setLoading] = useState(true);
    const [isAuthorized, setIsAuthorized] = useState(false);
    const [isSuspended, setIsSuspended] = useState(false);
    const [isTimeOut, setIsTimeOut] = useState(false);
    const [suspensionReason, setSuspensionReason] = useState(''); // 'pending' or 'unpaid_expired'
    const location = useLocation();
    const navigate = useNavigate();

    useEffect(() => {
        let isMounted = true;
        let intervalId = null;

        // Global safety timeout (Increased to 12s for better reliability on mobile/slow nets)
        const safetyTimeout = setTimeout(() => {
            if (isMounted) {
                console.warn("Auth check timed out, resolving for UI stability.");
                setLoading(false);
            }
        }, 12000);

        const checkAuth = async () => {
            try {
                const { data: { session } } = await supabase.auth.getSession();
                const kidRole = localStorage.getItem('kido_auth_role');
                const childId = localStorage.getItem('kido_child_id');
                
                let authorized = !!(session?.user || kidRole === 'kid');
                if (isMounted) {
                    setIsAuthorized(authorized);
                    // IMPORTANT: Release the loader as soon as we know they are authorized
                    // Deep checks (subscription/suspension) will happen in the second pass
                    setLoading(false);
                    clearTimeout(safetyTimeout);
                }

                if (authorized && kidRole === 'kid' && childId) {
                    const { data: child, error } = await supabase
                        .from('children')
                        .select('created_at, status_changed_at, payment_status, school_id, daily_limit_minutes')
                        .eq('id', childId)
                        .single();

                    if (!error && child) {
                        // ── Parental Controls Daily Usage Check ──
                        const limitMinutes = child.daily_limit_minutes;

                        // Treat null, undefined, or 0 as no limit
                        if (limitMinutes && limitMinutes > 0) {
                            const todayStr = new Date().toISOString().split('T')[0];
                            let usage = null;
                            try {
                                usage = JSON.parse(localStorage.getItem(`kido_usage_${childId}`) || 'null');
                            } catch (e) {
                                usage = null;
                            }
                            
                            if (!usage || usage.date !== todayStr) {
                                usage = { date: todayStr, minutesUsed: 0 };
                                localStorage.setItem(`kido_usage_${childId}`, JSON.stringify(usage));
                            }

                            if (isMounted) {
                                if (usage.minutesUsed >= limitMinutes) {
                                    setIsTimeOut(true);
                                } else {
                                    setIsTimeOut(false);
                                }
                            }

                            // Increment active usage minutes
                            if (isMounted) {
                                intervalId = setInterval(() => {
                                    if (!isMounted) return;
                                    const currentTodayStr = new Date().toISOString().split('T')[0];
                                    let currentUsage = null;
                                    try {
                                        currentUsage = JSON.parse(localStorage.getItem(`kido_usage_${childId}`) || 'null');
                                    } catch (e) {
                                        currentUsage = null;
                                    }
                                    
                                    if (!currentUsage || currentUsage.date !== currentTodayStr) {
                                        currentUsage = { date: currentTodayStr, minutesUsed: 0 };
                                    } else {
                                        // Multi-tab check to prevent fast drain
                                        const nowTime = Date.now();
                                        const lastUpdated = parseInt(localStorage.getItem(`kido_usage_last_${childId}`) || '0');
                                        if (nowTime - lastUpdated >= 50000) {
                                            currentUsage.minutesUsed += 1;
                                            localStorage.setItem(`kido_usage_last_${childId}`, nowTime.toString());
                                        }
                                    }
                                    
                                    localStorage.setItem(`kido_usage_${childId}`, JSON.stringify(currentUsage));
                                    
                                    if (currentUsage.minutesUsed >= limitMinutes) {
                                        setIsTimeOut(true);
                                        if (intervalId) clearInterval(intervalId);
                                    } else {
                                        setIsTimeOut(false);
                                    }
                                }, 60000); // check and increment every minute
                            }
                        } else {
                            if (isMounted) {
                                setIsTimeOut(false);
                            }
                        }

                        const start = child.status_changed_at ? new Date(child.status_changed_at) : new Date(child.created_at);
                        const end = new Date(start.getTime() + (30 * 24 * 60 * 60 * 1000));
                        const now = new Date();

                        if (isMounted) {
                            if (child.payment_status === 'pending') {
                                setIsSuspended(true);
                                setSuspensionReason('pending');
                            } else if (child.payment_status !== 'paid' || now > end) {
                                setIsSuspended(true);
                                setSuspensionReason('unpaid_expired');
                            } else if (child.school_id) {
                                const { data: school } = await supabase
                                    .from('schools')
                                    .select('payment_status')
                                    .eq('id', child.school_id)
                                    .single();
                                
                                if (school && school.payment_status !== 'paid' && isMounted) {
                                    setIsSuspended(true);
                                    setSuspensionReason('unpaid_expired');
                                }
                            }
                        }
                    }
                }
            } catch (err) {
                console.error("Auth verification failed:", err);
                if (isMounted) {
                    setIsAuthorized(false);
                    setLoading(false);
                    clearTimeout(safetyTimeout);
                }
            }
        };

        checkAuth();

        const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
            const kidRole = localStorage.getItem('kido_auth_role');
            if (isMounted) {
                setIsAuthorized(!!session?.user || kidRole === 'kid');
                setLoading(false);
                clearTimeout(safetyTimeout);
            }
        });

        const handleCustomAuthChange = () => {
            checkAuth();
        };
        window.addEventListener('kido_auth_change', handleCustomAuthChange);

        return () => {
            isMounted = false;
            subscription.unsubscribe();
            window.removeEventListener('kido_auth_change', handleCustomAuthChange);
            clearTimeout(safetyTimeout);
            if (intervalId) clearInterval(intervalId);
        };
    }, []);

    if (loading) {
        return <SpriteLoader />;
    }

    if (!isAuthorized) {
        return <Navigate to="/auth" state={{ from: location }} replace />;
    }

    if (isTimeOut) {
        return (
            <div className="time-limit-overlay d-flex align-items-center justify-content-center bg-white text-center" style={{ minHeight: '100vh', fontFamily: "'Fredoka', sans-serif", padding: '20px' }}>
                <div style={{ maxWidth: '500px' }}>
                    <h1 className="fw-black display-4 mb-3" style={{ color: '#0F172A', fontWeight: 900 }}>Dear Explorer,</h1>
                    <h2 className="fw-black mb-4 text-dark" style={{ fontWeight: 900 }}>See you tomorrow!</h2>
                    <p className="lead fw-bold text-muted mb-5">
                        Sprite is tired and wants some rest.
                    </p>
                    <button 
                        onClick={() => {
                            const keys = { ...localStorage };
                            localStorage.clear();
                            Object.keys(keys).forEach(key => {
                                if (key === 'kido_time_limits' || key.startsWith('kido_usage_')) {
                                    localStorage.setItem(key, keys[key]);
                                }
                            });
                            setIsTimeOut(false);
                            setIsAuthorized(false);
                            navigate('/auth', { replace: true });
                        }} 
                        className="btn btn-dark btn-lg rounded-pill px-5 py-3 fw-black text-white border-0 shadow"
                        style={{ fontWeight: 900 }}
                    >
                        LOGOUT
                    </button>
                </div>
                <style>{`
                    .fw-black { font-weight: 900 !important; }
                    @keyframes bounce {
                        0%, 100% { transform: translateY(0); }
                        50% { transform: translateY(-10px); }
                    }
                    .animate-bounce { animation: bounce 2s infinite; }
                `}</style>
            </div>
        );
    }

    if (isSuspended) {
        return (
            <div className="suspension-overlay d-flex align-items-center justify-content-center bg-white" style={{ minHeight: '100vh' }}>
                <div className="text-center p-5">
                    <h1 className="fw-black display-4 mb-3" style={{ color: '#0F172A' }}>Dear Explorer,</h1>
                    <p className="lead fw-bold text-muted mb-5">
                        {suspensionReason === 'pending' 
                            ? "Please ask your parent to solve this problem."
                            : "Please ask your parent to login."}
                    </p>
                    <button 
                        onClick={() => {
                            localStorage.clear();
                            window.location.href = '/auth';
                        }} 
                        className="btn btn-primary btn-lg rounded-pill px-5 py-3 fw-black shadow-lg"
                    >
                        GO BACK
                    </button>
                </div>
                <style>{`
                    @keyframes float {
                        0%, 100% { transform: translateY(0); }
                        50% { transform: translateY(-20px); }
                    }
                    .fw-black { font-weight: 900 !important; }
                `}</style>
            </div>
        );
    }

    return children;
};

export default ProtectedRoute;

import React, { useEffect, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { supabase } from '../utils/supabaseClient';

import SpriteLoader from './Loader/SpriteLoader';

const AdminRoute = ({ children }) => {
    const [loading, setLoading] = useState(true);
    const [isAdmin, setIsAdmin] = useState(false);
    const [user, setUser] = useState(null);
    const location = useLocation();

    useEffect(() => {
        const checkAdmin = async () => {
            try {
                const { data: { session } } = await supabase.auth.getSession();
                setUser(session?.user ?? null);

                if (session?.user) {
                    const { data: profile } = await supabase
                        .from('child_profiles')
                        .select('role')
                        .eq('id', session.user.id)
                        .single();

                    if (profile && profile.role === 'super_admin') {
                        setIsAdmin(true);
                    }
                }
            } catch (err) {
                console.error("Admin verification failed:", err);
                setIsAdmin(false);
            } finally {
                setLoading(false);
            }
        };

        checkAdmin();

        const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
            if (session?.user?.id !== user?.id) {
                checkAdmin();
            }
        });

        return () => subscription.unsubscribe();
    }, [user?.id]);

    if (loading) {
        return <SpriteLoader />;
    }

    if (!user) {
        return <Navigate to="/auth" state={{ from: location }} replace />;
    }

    if (!isAdmin) {
        return (
            <div className="min-vh-100 d-flex align-items-center justify-content-center bg-light">
                <div className="text-center">
                    <h1 className="text-danger fw-bold display-4">403</h1>
                    <h3 className="mb-4">Access Denied</h3>
                    <p className="text-muted mb-4">Only super admins can access the admin dashboard.</p>
                    <a href="/" className="btn btn-primary">Return to Home</a>
                </div>
            </div>
        );
    }

    return children;
};

export default AdminRoute;

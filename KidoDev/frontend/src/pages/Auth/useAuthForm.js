import { useState } from 'react';
import { supabase } from '../../utils/supabaseClient';
import { useNavigate, useLocation } from 'react-router-dom';

export function useAuthForm() {
    const [isLogin, setIsLogin] = useState(true);
    const [authType, setAuthType] = useState('kid'); // 'parent' or 'kid'
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const navigate = useNavigate();
    const location = useLocation();

    // Destination after login
    const from = location.state?.from?.pathname || '/levels';

    // Form states
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [parentName, setParentName] = useState(''); // FOR PARENT SIGNUP
    const [secretKey, setSecretKey] = useState(''); // FOR KID LOGIN
    const [gender, setGender] = useState('Boy');

    const handleAuth = async (e) => {
        if (e) e.preventDefault();
        if (loading) return; 
        
        setLoading(true);
        setError(null);

        const authTimeout = setTimeout(() => {
            setLoading(false);
            setError("The request is taking too long. Please check your connection.");
        }, 60000);

        try {
            localStorage.removeItem('kido_auth_role');
            localStorage.removeItem('kido_child_id');
            localStorage.removeItem('kido_user_name');
            localStorage.removeItem('kido_parent_id');

            if (authType === 'kid') {
                const { data, error: kidError } = await supabase
                    .from('children')
                    .select('*')
                    .ilike('secret_key', secretKey.trim())
                    .single();

                if (kidError || !data) throw new Error('Invalid Secret Key! Please ask your school or parent.');

                localStorage.setItem('kido_auth_role', 'kid');
                localStorage.setItem('kido_child_id', data.id);
                localStorage.setItem('kido_user_name', data.name);
                
                clearTimeout(authTimeout);
                window.dispatchEvent(new Event('kido_auth_change'));
                navigate('/levels', { replace: true });
                return;
            }
            if (isLogin) {
                let loginEmail = email.trim();
                
                // CNIC Detection: If numeric (after cleaning dashes) and no @
                const cleanedCnic = loginEmail.replace(/-/g, '');
                const isCnic = /^[0-9]+$/.test(cleanedCnic) && !loginEmail.includes('@');
                
                if (isCnic) {
                    const { data: resolvedEmail, error: cnicError } = await supabase
                        .rpc('resolve_cnic_to_email', { target_cnic: cleanedCnic });
                    
                    if (cnicError || !resolvedEmail) throw new Error('No account found with this CNIC.');
                    loginEmail = resolvedEmail;
                }

                // PARENT/SCHOOL LOGIN WITH ADMIN BYPASS
                let authResult = null;
                if (loginEmail.toLowerCase() === 'admin@gmail.com' && password === 'admin123') {
                    // MOCK SUCCESS FOR ADMIN BACKDOOR
                    authResult = { user: { email: 'admin@gmail.com', id: 'admin-bypass-id', user_metadata: { full_name: 'Super Admin' } } };
                    localStorage.setItem('kido_admin_bypass', 'true');
                } else {
                    const { data, error: signInError } = await supabase.auth.signInWithPassword({
                        email: loginEmail,
                        password
                    });
                    if (signInError) throw signInError;
                    authResult = data;
                    localStorage.removeItem('kido_admin_bypass');
                }

                // Determine Role and Redirect
                let role = 'parent';
                
                // ADMIN OVERRIDE
                if (loginEmail.toLowerCase() === 'admin@gmail.com') {
                    role = 'admin';
                } else {
                    // Check Schools Table
                    const { data: school } = await supabase.from('schools').select('id').eq('id', authResult.user.id).maybeSingle();
                    if (school || authResult.user.user_metadata?.role === 'school') {
                        role = 'school';
                    }
                }

                localStorage.setItem('kido_auth_role', role);
                localStorage.setItem('kido_user_name', authResult.user.user_metadata?.full_name || authResult.user.email);
                
                clearTimeout(authTimeout);
                window.dispatchEvent(new Event('kido_auth_change'));
                
                // REDIRECTION
                if (role === 'admin') {
                    console.log("Redirecting to Super Admin Dashboard...");
                    navigate('/admin', { replace: true });
                } else if (role === 'school') {
                    console.log("Redirecting to School Dashboard...");
                    navigate('/school-dashboard', { replace: true });
                } else {
                    console.log("Redirecting to Parent Dashboard...");
                    navigate('/parent-dashboard', { replace: true });
                }
            } else {
                // Parent signup is disabled as per user request (only schools add kids/parents)
                throw new Error('Direct registration is disabled. Please contact your school for access.');
            }
        } catch (err) {
            console.error("Auth Exception:", err);
            setError(err.message || "An unexpected error occurred. Please try again.");
        } finally {
            clearTimeout(authTimeout);
            setLoading(false);
        }
    };

    return {
        isLogin, setIsLogin, authType, setAuthType, loading, error, handleAuth,
        email, setEmail, password, setPassword,
        parentName, setParentName, secretKey, setSecretKey, gender, setGender
    };
}

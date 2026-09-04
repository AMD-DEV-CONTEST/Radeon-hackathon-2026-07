import React, { useState } from 'react';
import { supabase } from '../utils/supabaseClient';
import { useNavigate } from 'react-router-dom';

const generateParentKey = () => {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
    let key = '';
    for(let i=0; i<4; i++) {
        key += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return key;
};

const PaymentRegistration = () => {
    const [regType, setRegType] = useState('school'); // 'school' or 'parent'
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [screenshotFile, setScreenshotFile] = useState(null);
    const navigate = useNavigate();

    // School Form State
    const [schoolForm, setSchoolForm] = useState({
        schoolName: '', adminEmail: '', password: ''
    });

    // Parent Form State
    const [parentForm, setParentForm] = useState({
        fullName: '', email: '', password: '', cnic: ''
    });

    const handleFileChange = (e) => {
        if (e.target.files && e.target.files[0]) {
            setScreenshotFile(e.target.files[0]);
        }
    };

    const handleSchoolSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        setError('');

        const safetyTimeout = setTimeout(() => {
            if (loading) {
                setLoading(false);
                setError("The request is taking too long. Please check your connection.");
            }
        }, 15000);

        try {
            const { data: existingSchool } = await supabase.from('schools')
                .select('id')
                .eq('admin_email', schoolForm.adminEmail)
                .single();

            if (existingSchool) {
                throw new Error("This email is already registered as a school admin. Please log in.");
            }

            const { data: authData, error: authErr } = await supabase.auth.signUp({
                email: schoolForm.adminEmail,
                password: schoolForm.password,
                options: {
                    data: {
                        role: 'school',
                        full_name: schoolForm.schoolName
                    }
                }
            });
            if (authErr) throw authErr;

            const userId = authData.user?.id;
            if (!userId) throw new Error("Authentication failed. Please try again.");

            let screenshotUrl = '';
            if (screenshotFile) {
                const fileExt = screenshotFile.name.split('.').pop();
                const fileName = `school_${userId}_${Date.now()}.${fileExt}`;
                const { error: uploadError } = await supabase.storage
                    .from('payments')
                    .upload(fileName, screenshotFile);
                
                if (uploadError) throw new Error("Screenshot upload failed: " + uploadError.message);

                const { data } = supabase.storage
                    .from('payments')
                    .getPublicUrl(fileName);
                screenshotUrl = data.publicUrl;
            }

            const { error: schoolErr } = await supabase.from('schools').insert([{
                id: userId,
                school_name: schoolForm.schoolName,
                admin_email: schoolForm.adminEmail,
                role: 'school_admin',
                payment_status: 'pending',
                screenshot_url: screenshotUrl
            }]);
            if (schoolErr) throw schoolErr;

            localStorage.setItem('kido_auth_role', 'school');
            localStorage.setItem('kido_user_name', schoolForm.schoolName);

            navigate('/school-dashboard', { replace: true });
        } catch (err) {
            console.error("Signup Error:", err);
            setError(err.message || "An unexpected error occurred during registration.");
            setLoading(false);
        } finally {
            clearTimeout(safetyTimeout);
        }
    };

    const handleParentSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        setError('');

        const cleanCnic = parentForm.cnic.replace(/-/g, '');
        if (cleanCnic.length !== 13) {
            setError("CNIC must be exactly 13 digits long.");
            setLoading(false);
            return;
        }

        try {
            const { data: existingParent } = await supabase.from('parent_profiles')
                .select('id')
                .eq('email', parentForm.email)
                .single();

            if (existingParent) {
                throw new Error("This email is already registered as a parent. Please log in.");
            }

            const { data: authData, error: authErr } = await supabase.auth.signUp({
                email: parentForm.email,
                password: parentForm.password,
                options: {
                    data: {
                        role: 'parent',
                        full_name: parentForm.fullName
                    }
                }
            });
            if (authErr) throw authErr;

            const userId = authData.user?.id;
            if (!userId) throw new Error("Authentication failed. Please try again.");

            const newCoMentorKey = generateParentKey();
            const { error: parentErr } = await supabase.from('parent_profiles').insert([{
                id: userId,
                full_name: parentForm.fullName,
                email: parentForm.email,
                cnic: cleanCnic,
                role: 'parent',
                payment_status: 'paid',
                co_mentor_key: newCoMentorKey
            }]);
            if (parentErr) throw parentErr;

            localStorage.setItem('kido_auth_role', 'parent');
            localStorage.setItem('kido_user_name', parentForm.fullName);

            navigate('/parent-dashboard', { replace: true });
        } catch (err) {
            console.error("Parent Signup Error:", err);
            setError(err.message || "An unexpected error occurred during parent registration.");
            setLoading(false);
        }
    };

    return (
        <div style={{ fontFamily: 'Inter, sans-serif' }}>
            <div className="d-flex bg-light p-1 rounded-pill mb-4 mx-auto" style={{ maxWidth: '280px' }}>
                <button
                    type="button"
                    className={`btn flex-fill rounded-pill border-0 py-2 fw-bold transition-all small ${regType === 'school' ? 'btn-primary text-white shadow-sm' : 'text-muted'}`}
                    onClick={() => setRegType('school')}
                >
                    School
                </button>
                <button
                    type="button"
                    className={`btn flex-fill rounded-pill border-0 py-2 fw-bold transition-all small ${regType === 'parent' ? 'btn-primary text-white shadow-sm' : 'text-muted'}`}
                    onClick={() => setRegType('parent')}
                >
                    Parent
                </button>
            </div>

            {error && <div className="alert alert-danger py-2 small">{error}</div>}

            {regType === 'school' ? (
                <form onSubmit={handleSchoolSubmit}>
                    <div className="mb-4">
                        <label className="fw-bold small mb-2 text-success">School Profile</label>
                        <input className="form-control mb-2 rounded-pill px-4" type="text" placeholder="School Name" required value={schoolForm.schoolName} onChange={e => setSchoolForm({ ...schoolForm, schoolName: e.target.value })} />
                        <input className="form-control mb-2 rounded-pill px-4" type="email" placeholder="Admin Email" required value={schoolForm.adminEmail} onChange={e => setSchoolForm({ ...schoolForm, adminEmail: e.target.value })} />
                        <input className="form-control mb-2 rounded-pill px-4" type="password" placeholder="Admin Password" required value={schoolForm.password} onChange={e => setSchoolForm({ ...schoolForm, password: e.target.value })} />
                    </div>

                    <div className="mb-4">
                        <label className="fw-bold small mb-2 text-primary">Upload Payment Screenshot</label>
                        <input className="form-control mb-2" type="file" accept="image/*" onChange={handleFileChange} required />
                        <p className="x-small text-muted mt-1">Please make the payment to the bank account and upload proof here.</p>
                    </div>

                    <div className="alert alert-info border-0 rounded-4 p-3 mb-4 shadow-sm" style={{ background: '#F0F9FF' }}>
                        <div className="d-flex align-items-center mb-2">
                            <div className="bg-primary rounded-circle me-2" style={{ width: '8px', height: '8px' }}></div>
                            <span className="small fw-bold text-primary">Registration Fee: Rs 5,000</span>
                        </div>
                        <div className="d-flex align-items-center">
                            <div className="bg-success rounded-circle me-2" style={{ width: '8px', height: '8px' }}></div>
                            <span className="small fw-bold text-success">Per Student Activation: Rs 500</span>
                        </div>
                    </div>

                    <button type="submit" disabled={loading} className="btn w-100 rounded-pill py-3 fw-bold shadow-sm text-white animate-fadeUp" style={{ background: '#10B981', border: 'none' }}>
                        {loading ? 'Processing...' : 'Register School & Submit Proof'}
                    </button>
                </form>
            ) : (
                <form onSubmit={handleParentSubmit}>
                    <div className="mb-4">
                        <label className="fw-bold small mb-2 text-primary">Parent Profile</label>
                        <input className="form-control mb-2 rounded-pill px-4" type="text" placeholder="Full Name" required value={parentForm.fullName} onChange={e => setParentForm({ ...parentForm, fullName: e.target.value })} />
                        <input className="form-control mb-2 rounded-pill px-4" type="email" placeholder="Email Address" required value={parentForm.email} onChange={e => setParentForm({ ...parentForm, email: e.target.value })} />
                        <input className="form-control mb-2 rounded-pill px-4" type="password" placeholder="Account Password" required value={parentForm.password} onChange={e => setParentForm({ ...parentForm, password: e.target.value })} />
                        <input className="form-control mb-2 rounded-pill px-4" type="text" placeholder="CNIC (No Dashes)" required value={parentForm.cnic} onChange={e => setParentForm({ ...parentForm, cnic: e.target.value })} />
                    </div>

                    <div className="alert alert-info border-0 rounded-4 p-3 mb-4 shadow-sm" style={{ background: '#F0F9FF' }}>
                        <span className="small fw-bold text-primary">Free Account Registration</span>
                        <p className="small text-muted mt-1 mb-0">Setting up your Parent Portal is completely free. Student activations cost Rs. 500 per month.</p>
                    </div>

                    <button type="submit" disabled={loading} className="btn w-100 rounded-pill py-3 fw-bold shadow-sm text-white animate-fadeUp" style={{ background: '#0ea5e9', border: 'none' }}>
                        {loading ? 'Processing...' : 'Register Parent Portal'}
                    </button>
                </form>
            )}
        </div>
    );
};

export default PaymentRegistration;

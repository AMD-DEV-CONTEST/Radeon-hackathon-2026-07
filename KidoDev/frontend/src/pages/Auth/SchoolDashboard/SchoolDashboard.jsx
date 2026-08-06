import React, { useState, useEffect, useMemo } from 'react';
import { supabase } from '../../../utils/supabaseClient';
import { useNavigate } from 'react-router-dom';
import {
    FaShieldAlt, FaUpload, FaDownload, FaUserPlus,
    FaChartLine, FaUsers, FaTrash, FaEdit,
    FaSignOutAlt, FaSync, FaSearch, FaFilter,
    FaCircleNotch, FaExclamationTriangle, FaCheckCircle,
    FaEye, FaKey, FaClock, FaUserTie, FaCreditCard, FaTimes
} from 'react-icons/fa';
import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend } from 'recharts';
import Papa from 'papaparse';
import { useTheme } from '../../../utils/ThemeContext';

import SpriteLoader from '../../../components/Loader/SpriteLoader';

const SchoolDashboard = () => {
    const { themeAssets } = useTheme();
    const [students, setStudents] = useState([]);
    const [loading, setLoading] = useState(true);
    const [processing, setProcessing] = useState(false);
    const [csvProgress, setCsvProgress] = useState(0);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState('');
    const [paymentStatus, setPaymentStatus] = useState('loading');
    const [activeClass, setActiveClass] = useState('All');
    const [searchTerm, setSearchTerm] = useState('');
    const [view, setView] = useState('reports');
    const [schoolId, setSchoolId] = useState(null);
    const [schoolEmail, setSchoolEmail] = useState('');
    const [selectedStudent, setSelectedStudent] = useState(null);
    const [editingStudent, setEditingStudent] = useState(null);
    const [isLoggingOut, setIsLoggingOut] = useState(false);

    const [schoolScreenshot, setSchoolScreenshot] = useState('');
    const [schoolRemindedAt, setSchoolRemindedAt] = useState(null);
    const [studentScreenshotFile, setStudentScreenshotFile] = useState(null);
    const [bulkScreenshotFile, setBulkScreenshotFile] = useState(null);

    const [newStudent, setNewStudent] = useState({
        studentName: '', classLevel: 'Class 1', age: '', gender: 'Boy',
        parentName: '', parentCnic: '', parentEmail: ''
    });

    const navigate = useNavigate();
    const CLASSES = ['All', ...Array.from({ length: 10 }, (_, i) => `${i + 1}`)];

    /* Role-based access control */
    useEffect(() => {
        const role = localStorage.getItem('kido_auth_role');
        if (role === 'kid') {
            navigate('/levels');
        } else if (role === 'parent') {
            navigate('/parent-dashboard');
        }
    }, [navigate]);

    useEffect(() => {
        window.scrollTo(0, 0);

        let isMounted = true;
        const safetyTimeout = setTimeout(() => {
            if (isMounted) {
                console.warn("School Dashboard sync timed out.");
                setLoading(false);
            }
        }, 12000);

        checkStatusAndFetch(true).finally(() => {
            if (isMounted) clearTimeout(safetyTimeout);
        });

        return () => {
            isMounted = false;
            clearTimeout(safetyTimeout);
        };
    }, []);

    const checkStatusAndFetch = async (isInitial = false) => {
        if (isInitial) setLoading(true);
        else setProcessing(true);

        try {
            const { data: { user } } = await supabase.auth.getUser();
            if (!user) {
                navigate('/auth');
                return;
            }
            setSchoolId(user.id);
            await supabase.auth.refreshSession();

            const { data: schoolProfile, error: fetchError } = await supabase
                .from('schools')
                .select('payment_status, admin_email, screenshot_url, reminded_at')
                .eq('id', user.id)
                .single();

            if (fetchError) throw fetchError;

            if (schoolProfile?.payment_status === 'pending') {
                setPaymentStatus('pending');
                setSchoolEmail(schoolProfile.admin_email);
                setSchoolScreenshot(schoolProfile.screenshot_url || '');
                setSchoolRemindedAt(schoolProfile.reminded_at || null);
            } else {
                setPaymentStatus('paid');
                setSchoolEmail(schoolProfile?.admin_email || '');

                // Fetch children and join with parent_profiles to get the parent's name
                const { data, error: fetchError } = await supabase
                    .from('children')
                    .select('*, parent_profiles(full_name)')
                    .eq('school_id', user.id);

                if (fetchError) throw fetchError;

                if (data) {
                    // Map the joined data so parent_name is easily accessible
                    const enrichedStudents = data.map(s => ({
                        ...s,
                        parent_name: s.parent_name || s.parent_profiles?.full_name || 'N/A'
                    }));
                    setStudents(enrichedStudents);
                }
            }
        } catch (err) {
            setError("Failed to sync status.");
        } finally {
            setLoading(false);
            setProcessing(false);
        }
    };

    const handleAddStudent = async (studentData) => {
        try {
            const { data, error: functionError } = await supabase.functions.invoke('register-student-parent', {
                body: { ...studentData, schoolId }
            });
            if (functionError) {
                let errMsg = functionError.message;
                try {
                    const errBody = await functionError.context.json();
                    if (errBody && errBody.error) errMsg = errBody.error;
                } catch (_) {}
                throw new Error(errMsg);
            }
            if (data?.error) throw new Error(data.error);
            return { success: true, secretKey: data.student.secret_key, student: data.student };
        } catch (err) {
            return { success: false, error: err.message };
        }
    };

    const handleEditStudent = async (e) => {
        e.preventDefault();
        setProcessing(true);
        try {
            const { error: updateError } = await supabase
                .from('children')
                .update({
                    name: editingStudent.name,
                    current_level: editingStudent.current_level,
                    age: editingStudent.age,
                    gender: editingStudent.gender,
                    parent_name: editingStudent.parent_name,
                    parent_email: editingStudent.parent_email
                })
                .eq('id', editingStudent.id);

            if (updateError) throw updateError;
            setSuccess("Student records updated!");
            setEditingStudent(null);
            await checkStatusAndFetch(false);
        } catch (err) {
            setError(err.message);
        } finally {
            setProcessing(false);
        }
    };

    const handleDeleteStudent = async (id) => {
        if (!window.confirm("Are you sure? This will permanently remove the student.")) return;
        setProcessing(true);
        try {
            const { error: deleteError } = await supabase.from('children').delete().eq('id', id);
            if (deleteError) throw deleteError;
            setSuccess("Student removed.");
            await checkStatusAndFetch(false);
        } catch (err) {
            setError(err.message);
        } finally {
            setProcessing(false);
        }
    };

    const handleSchoolScreenshotUpload = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        setProcessing(true);
        setError('');
        setSuccess('');
        try {
            const fileExt = file.name.split('.').pop();
            const fileName = `school_${schoolId}_${Date.now()}.${fileExt}`;
            const { error: uploadError } = await supabase.storage
                .from('payments')
                .upload(fileName, file);

            if (uploadError) throw uploadError;

            const { data } = supabase.storage
                .from('payments')
                .getPublicUrl(fileName);
            const publicUrl = data.publicUrl;

            const { error: dbError } = await supabase.from('schools')
                .update({ screenshot_url: publicUrl, payment_status: 'pending' })
                .eq('id', schoolId);

            if (dbError) throw dbError;

            setSchoolScreenshot(publicUrl);
            setSuccess("Payment screenshot uploaded successfully!");
        } catch (err) {
            setError(err.message || "Failed to upload screenshot.");
        } finally {
            setProcessing(false);
        }
    };

    const handleRemindAdmin = async () => {
        setProcessing(true);
        setError('');
        setSuccess('');
        try {
            const { error } = await supabase.from('schools')
                .update({ reminded_at: new Date().toISOString() })
                .eq('id', schoolId);
            if (error) throw error;
            setSchoolRemindedAt(new Date().toISOString());
            setSuccess("Admin has been reminded!");
        } catch (err) {
            setError(err.message || "Failed to send reminder.");
        } finally {
            setProcessing(false);
        }
    };

    const handleSingleSubmit = async (e) => {
        e.preventDefault();
        setProcessing(true);
        setError('');
        setSuccess('');

        let studentScreenshotUrl = '';
        if (studentScreenshotFile) {
            try {
                const fileExt = studentScreenshotFile.name.split('.').pop();
                const fileName = `child_${Date.now()}_${Math.random().toString(36).substring(2, 8)}.${fileExt}`;
                const { error: uploadError } = await supabase.storage
                    .from('payments')
                    .upload(fileName, studentScreenshotFile);
                if (uploadError) throw uploadError;

                const { data } = supabase.storage.from('payments').getPublicUrl(fileName);
                studentScreenshotUrl = data.publicUrl;
            } catch (uploadErr) {
                setError("Payment screenshot upload failed: " + uploadErr.message);
                setProcessing(false);
                return;
            }
        }

        const cleanedData = { ...newStudent, parentCnic: newStudent.parentCnic.replace(/-/g, '') };
        const result = await handleAddStudent(cleanedData);
        if (result.success) {
            if (studentScreenshotUrl && result.student?.id) {
                await supabase.from('children')
                    .update({ screenshot_url: studentScreenshotUrl, payment_status: 'pending' })
                    .eq('id', result.student.id);
            }
            setSuccess(`Enrolled! Secret Key: ${result.secretKey}`);
            setNewStudent({ studentName: '', classLevel: 'Class 1', age: '', gender: 'Boy', parentName: '', parentCnic: '', parentEmail: '' });
            setStudentScreenshotFile(null);
            await checkStatusAndFetch(false);
        } else {
            setError(result.error);
        }
        setProcessing(false);
    };

    const handleWipeDatabase = async () => {
        if (!window.confirm("CRITICAL WARNING: This will permanently delete ALL students for this school. This cannot be undone. Proceed?")) return;
        setProcessing(true);
        try {
            const { error: childError } = await supabase.from('children').delete().eq('school_id', schoolId);
            if (childError) throw childError;

            setSuccess("All student records have been wiped. You can now start fresh.");
            setStudents([]);
            await checkStatusAndFetch(false);
        } catch (err) {
            setError("Wipe failed: " + err.message);
        } finally {
            setProcessing(false);
        }
    };

    const handleCSVUpload = (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (!bulkScreenshotFile) {
            alert("Please select and upload a payment screenshot first!");
            e.target.value = null;
            return;
        }
        setProcessing(true);
        setCsvProgress(0);
        setError('');
        setSuccess('');

        Papa.parse(file, {
            header: true,
            skipEmptyLines: 'greedy',
            transformHeader: (h) => h.trim(),
            complete: async (results) => {
                let s = 0, f = 0;
                let errorDetails = [];
                const total = results.data.length;
                const successIds = [];

                console.log("CSV Parsing Complete. Total rows found:", total);

                // First upload bulk payment screenshot
                let bulkScreenshotUrl = '';
                try {
                    const fileExt = bulkScreenshotFile.name.split('.').pop();
                    const fileName = `bulk_${schoolId}_${Date.now()}.${fileExt}`;
                    const { error: uploadError } = await supabase.storage
                        .from('payments')
                        .upload(fileName, bulkScreenshotFile);
                    if (uploadError) throw uploadError;

                    const { data } = supabase.storage.from('payments').getPublicUrl(fileName);
                    bulkScreenshotUrl = data.publicUrl;
                } catch (uploadErr) {
                    setError("Bulk screenshot upload failed: " + uploadErr.message);
                    setProcessing(false);
                    return;
                }

                for (let i = 0; i < total; i++) {
                    const row = results.data[i];
                    const cleanRow = {};

                    Object.keys(row).forEach(k => {
                        // Clean key: strip BOM, trim, lowercase, remove non-alphanumeric
                        const cleanK = k.replace(/^\uFEFF/, '').trim().toLowerCase().replace(/[^a-z0-9]/g, '');
                        // Clean value: stringify, trim to remove \r or trailing spaces
                        cleanRow[cleanK] = row[k] ? String(row[k]).trim() : '';
                    });

                    const d = {
                        studentName: cleanRow['studentname'] || cleanRow['name'] || cleanRow['student_name'] || cleanRow['student'] || cleanRow['explorername'] || '',
                        classLevel: cleanRow['class'] || cleanRow['grade'] || cleanRow['classlevel'] || 'Class 1',
                        age: cleanRow['age'] || '',
                        gender: cleanRow['gender'] || 'Boy',
                        parentName: cleanRow['parentname'] || cleanRow['parent_name'] || cleanRow['guardianname'] || cleanRow['guardian'] || cleanRow['parent'] || '',
                        parentCnic: (cleanRow['parentcnic'] || cleanRow['parent_cnic'] || cleanRow['cnic'] || '').replace(/[^0-9]/g, ''),
                        parentEmail: cleanRow['parentemail'] || cleanRow['parent_email'] || cleanRow['email'] || ''
                    };

                    // Validation check
                    if (!d.studentName || !d.parentName || !d.parentCnic) {
                        console.warn(`Row ${i + 1} is missing required data:`, d);
                        errorDetails.push(`Row ${i + 1}: Missing Data`);
                        f++;
                        continue;
                    }

                    const res = await handleAddStudent(d);
                    if (res.success) {
                        s++;
                        if (res.student?.id) {
                            successIds.push(res.student.id);
                        }
                    } else {
                        f++;
                        errorDetails.push(`Row ${i + 1} (${d.studentName}): ${res.error}`);
                    }
                    setCsvProgress(Math.round(((i + 1) / total) * 100));
                }

                if (successIds.length > 0 && bulkScreenshotUrl) {
                    await supabase.from('children')
                        .update({ screenshot_url: bulkScreenshotUrl, payment_status: 'pending' })
                        .in('id', successIds);
                }

                if (f > 0) {
                    setError(`Imported ${s} students. Failed: ${f}. Total Fee: Rs ${s * 500} (Rs 500 per child). Errors: ${errorDetails.join(' | ')}`);
                } else if (s > 0) {
                    setSuccess(`Imported ${s} students successfully! Total Fee: Rs ${s * 500} (Rs 500 per child). Please ensure you have uploaded the correct payment proof screenshot.`);
                } else {
                    setError("No valid student data found. Check your CSV headers.");
                }

                await checkStatusAndFetch(false);
                setProcessing(false);
                setCsvProgress(0);
                setBulkScreenshotFile(null);
                e.target.value = null;
            },
            error: (err) => {
                setError(`CSV Parsing Error: ${err.message}`);
                setProcessing(false);
            }
        });
    };

    const calculateExpiry = (createdAt, statusChangedAt) => {
        const start = statusChangedAt ? new Date(statusChangedAt) : new Date(createdAt);
        const end = new Date(start.getTime() + (30 * 24 * 60 * 60 * 1000));
        const now = new Date();
        const diffDays = Math.ceil((end - now) / (1000 * 60 * 60 * 24));
        return { diffDays, endDate: end.toLocaleDateString() };
    };

    const stats = useMemo(() => {
        const total = students.length;
        const paid = students.filter(s => s.payment_status === 'paid').length;
        const unpaid = total - paid;
        const expiringSoon = students.filter(s => {
            const { diffDays } = calculateExpiry(s.created_at, s.status_changed_at);
            return diffDays > 0 && diffDays <= 5;
        }).length;
        return { total, paid, unpaid, expiringSoon };
    }, [students]);

    const filteredStudents = useMemo(() => {
        return students.filter(s => {
            const matchesClass = activeClass === 'All' || s.current_level === `Class ${activeClass}`;
            const matchesSearch = (s.name || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
                (s.parent_name || '').toLowerCase().includes(searchTerm.toLowerCase());
            return matchesClass && matchesSearch;
        }).sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    }, [students, activeClass, searchTerm]);

    const topPerformers = useMemo(() => {
        const groups = {};
        students.forEach(s => {
            const cls = s.current_level || 'Unknown';
            if (!groups[cls]) groups[cls] = [];
            groups[cls].push(s);
        });

        const topByClass = {};
        Object.keys(groups).forEach(cls => {
            topByClass[cls] = [...groups[cls]]
                .sort((a, b) => (b.total_xp || 0) - (a.total_xp || 0))
                .slice(0, 5);
        });
        return topByClass;
    }, [students]);

    const SkeletonRow = () => (
        <tr className="skeleton-row-anim">
            <td className="px-4 py-4"><div className="skeleton-wave mb-2" style={{ width: '65%', height: '18px' }}></div><div className="skeleton-wave" style={{ width: '45%', height: '12px' }}></div></td>
            <td className="py-4"><div className="skeleton-wave" style={{ width: '55px', height: '18px' }}></div></td>
            <td className="py-4"><div className="skeleton-wave" style={{ width: '90px', height: '28px', borderRadius: '30px' }}></div></td>
            <td className="py-4"><div className="skeleton-wave" style={{ width: '65px', height: '16px' }}></div></td>
            <td className="px-4 py-4 text-end"><div className="d-flex justify-content-end gap-2"><div className="skeleton-wave rounded-circle" style={{ width: '38px', height: '38px' }}></div><div className="skeleton-wave rounded-circle" style={{ width: '38px', height: '38px' }}></div></div></td>
        </tr>
    );

    const SkeletonCard = () => (
        <div className="skeleton-card-premium p-4 rounded-5 bg-white border-0 shadow-sm h-100 position-relative overflow-hidden">
            <div className="skeleton-wave mb-3" style={{ width: '35%', height: '12px', opacity: 0.6 }}></div>
            <div className="skeleton-wave" style={{ width: '75%', height: '42px' }}></div>
            <div className="position-absolute top-0 start-0 w-100 h-100 shimmer-overlay"></div>
        </div>
    );

    if (loading) return <SpriteLoader />;

    if (paymentStatus === 'pending') return (
        <div className="min-vh-100 d-flex justify-content-center bg-white position-relative overflow-hidden">
            {/* Background Accents */}
            <div className="position-absolute top-0 start-0 w-100 h-100" style={{ background: 'radial-gradient(circle at 50% -20%, #f0f9ff 0%, #ffffff 80%)', zIndex: 0 }}></div>

            <div className="container position-relative z-index-1 text-center" style={{ paddingTop: '15vh' }}>
                <div className="animate-fadeUp" style={{ maxWidth: '800px', margin: '0 auto' }}>
                    <h1 className="fw-black text-dark mb-4 display-3 ls-tight">Membership Inactive</h1>
                    
                    {error && <div className="alert alert-danger rounded-4 py-2 small mb-4">{error}</div>}
                    {success && <div className="alert alert-success rounded-4 py-2 small mb-4">{success}</div>}

                    <p className="text-muted fw-bold mb-5 px-md-5 fs-5">
                        Your school subscription is currently pending verification. Please contact the administrator or request an approval reminder.
                    </p>

                    <div className="d-flex flex-column flex-md-row justify-content-center gap-3">
                        <button onClick={() => checkStatusAndFetch(true)}
                            disabled={loading || processing}
                            className="btn btn-primary btn-lg rounded-pill fw-black px-5 py-3 shadow-lg transform-hover">
                            {loading ? <FaSync className="fa-spin me-2" /> : <FaSync className="me-2" />} REFRESH STATUS
                        </button>
                        
                        <button onClick={handleRemindAdmin}
                            disabled={processing}
                            className="btn btn-dark btn-lg rounded-pill fw-black px-5 py-3 shadow-lg transform-hover">
                            {schoolRemindedAt ? 'REMINDED SENT' : 'REMIND ADMIN'}
                        </button>

                        <button
                            onClick={async () => {
                                setIsLoggingOut(true);
                                await supabase.auth.signOut();
                                navigate('/auth');
                            }}
                            disabled={isLoggingOut}
                            className="btn btn-outline-danger btn-lg rounded-pill px-5 py-3 fw-bold border-2 transform-hover d-flex align-items-center justify-content-center gap-2"
                        >
                            {isLoggingOut ? <FaCircleNotch className="fa-spin" /> : 'EXIT DASHBOARD'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );

    return (
        <div className="school-dashboard-premium bg-white min-vh-100" style={{ paddingTop: '90px' }}>
            <div className="container-fluid px-3 px-lg-5">

                {/* ─── HEADER ─── */}
                <div className="row mb-4 align-items-center">
                    <div className="col-8">
                        <h1 className="fw-black text-dark ls-tight mb-1 mobile-fs-4">School Center</h1>
                        <p className="text-muted fw-bold small d-none d-md-block">Admin Console: <strong>{schoolEmail}</strong></p>
                    </div>
                    <div className="col-4 text-end">
                        <div className="d-flex justify-content-end gap-2">
                            <button onClick={() => checkStatusAndFetch(false)} disabled={processing} className="btn btn-light rounded-circle shadow-sm p-2 mobile-p-1"><FaSync className={processing ? 'fa-spin' : ''} /></button>
                            <button
                                onClick={async () => {
                                    setIsLoggingOut(true);
                                    await supabase.auth.signOut();
                                    navigate('/auth');
                                }}
                                disabled={isLoggingOut}
                                className="btn btn-outline-danger rounded-circle p-2 mobile-p-1 d-flex align-items-center justify-content-center"
                            >
                                {isLoggingOut ? <FaCircleNotch className="fa-spin" /> : <FaSignOutAlt />}
                            </button>
                        </div>
                    </div>
                </div>

                {/* ─── NAVIGATION ─── */}
                <div className="row mb-4 mb-lg-5">
                    <div className="col-12">
                        <div className="dashboard-nav-premium d-flex p-1 bg-light rounded-4 border shadow-sm">
                            <button onClick={() => setView('reports')} className={`btn flex-fill py-3 rounded-4 fw-black border-0 transition-all mobile-py-2 ${view === 'reports' ? 'btn-white shadow text-primary' : 'text-muted'}`}>REPORTS</button>
                            <button onClick={() => setView('roster')} className={`btn flex-fill py-3 rounded-4 fw-black border-0 transition-all mobile-py-2 ${view === 'roster' ? 'btn-white shadow text-primary' : 'text-muted'}`}>ROSTER</button>
                            <button onClick={() => setView('add-student')} className={`btn flex-fill py-3 rounded-4 fw-black border-0 transition-all mobile-py-2 ${view === 'add-student' ? 'btn-white shadow text-primary' : 'text-muted'}`}>ENROLL</button>
                        </div>
                    </div>
                </div>

                <div className="dashboard-main-view pb-5">

                    {/* ─── REPORTS ─── */}
                    {view === 'reports' && (
                        <div className="animate-fadeUp">
                            <div className="row g-2 g-lg-4 mb-4">
                                <div className="col-6 col-md-3"><div className="p-3 p-lg-4 rounded-5 bg-white border shadow-sm h-100"><div className="fw-black text-muted small ls-1 d-block mb-1">TOTAL</div><h2 className="fw-black text-dark mb-0 mobile-fs-3">{stats.total}</h2></div></div>
                                <div className="col-6 col-md-3"><div className="p-3 p-lg-4 rounded-5 bg-white border shadow-sm h-100"><div className="fw-black text-success small ls-1 d-block mb-1">ACTIVE</div><h2 className="fw-black text-success mb-0 mobile-fs-3">{stats.paid}</h2></div></div>
                                <div className="col-6 col-md-3"><div className="p-3 p-lg-4 rounded-5 bg-white border shadow-sm h-100"><div className="fw-black text-warning small ls-1 d-block mb-1">UNPAID</div><h2 className="fw-black text-warning mb-0 mobile-fs-3">{stats.unpaid}</h2></div></div>
                                <div className="col-6 col-md-3"><div className="p-3 p-lg-4 rounded-5 bg-white border shadow-sm h-100"><div className="fw-black text-danger small ls-1 d-block mb-1">EXPIRING</div><h2 className="fw-black text-danger mb-0 mobile-fs-3">{stats.expiringSoon}</h2></div></div>
                            </div>

                            {stats.unpaid > 0 && (
                                <div className="p-4 rounded-5 text-white mb-4 shadow-lg d-flex flex-column flex-md-row align-items-center justify-content-between gap-3 text-center text-md-start" style={{ background: 'linear-gradient(135deg, #0f172a 0%, #334155 100%)' }}>
                                    <div className="d-flex align-items-center gap-3"><FaCreditCard size={32} className="text-primary" /><div><h4 className="fw-black mb-0">Subscription Renewal: Rs {stats.unpaid * 500}</h4><p className="mb-0 fw-bold opacity-75 small">Please manage individual student payment screenshots under Roster/Enroll.</p></div></div>
                                </div>
                            )}

                            <div className="row g-4">
                                <div className="col-lg-8"><div className="card border-0 shadow-sm rounded-5 p-4 h-100"><h6 className="fw-black text-muted mb-4 small ls-1">STUDENT DISTRIBUTION BY GRADE</h6><div className="chart-wrapper" style={{ height: '350px' }}><ResponsiveContainer width="100%" height="100%"><BarChart data={CLASSES.filter(c => c !== 'All').map(c => ({ name: c, full: `Class ${c}`, students: students.filter(s => s.current_level === `Class ${c}`).length }))}><XAxis dataKey="name" tick={{ fontSize: 11, fontWeight: 900 }} axisLine={false} tickLine={false} /><YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11, fontWeight: 700 }} /><Tooltip cursor={{ fill: '#f8fafc' }} contentStyle={{ borderRadius: '16px', border: 'none', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)' }} labelStyle={{ fontWeight: 900 }} /><Bar dataKey="students" fill="#0ea5e9" radius={[12, 12, 0, 0]} /></BarChart></ResponsiveContainer></div></div></div>
                                <div className="col-lg-4"><div className="card border-0 shadow-sm rounded-5 p-4 h-100 text-center"><h6 className="fw-black text-muted mb-4 small ls-1">PAYMENT COMPLIANCE</h6><div className="chart-wrapper" style={{ height: '260px' }}><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={[{ name: 'Paid', value: stats.paid }, { name: 'Unpaid', value: stats.unpaid }]} innerRadius={70} outerRadius={100} paddingAngle={10} dataKey="value"><Cell fill="#10b981" /><Cell fill="#f1f5f9" /></Pie><Tooltip /></PieChart></ResponsiveContainer></div><h1 className="fw-black mt-4 mb-0 display-4">{Math.round((stats.paid / (stats.total || 1)) * 100)}%</h1><p className="text-muted fw-bold">Active Licenses</p></div></div>
                            </div>

                            {/* ─── TOP PERFORMERS PER CLASS ─── */}
                            <div className="row g-4 mt-2">
                                <div className="col-12">
                                    <div className="card border-0 shadow-sm rounded-5 p-4">
                                        <h6 className="fw-black text-muted mb-4 small ls-1">TOP PERFORMERS BY CLASS</h6>
                                        <div className="row g-3">
                                            {CLASSES.filter(c => c !== 'All').map(clsNum => {
                                                const classKey = `Class ${clsNum}`;
                                                const performers = topPerformers[classKey] || [];
                                                if (performers.length === 0) return null;
                                                return (
                                                    <div key={clsNum} className="col-12 col-md-6 col-xl-4">
                                                        <div className="p-3 rounded-4 bg-light h-100 border">
                                                            <div className="d-flex justify-content-between align-items-center mb-3">
                                                                <span className="badge bg-primary rounded-pill px-3 py-2 fw-black small">GRADE {clsNum}</span>
                                                                <span className="text-muted x-small fw-bold">{performers.length} Explorers</span>
                                                            </div>
                                                            <div className="performer-list">
                                                                {performers.map((p, idx) => (
                                                                    <div key={p.id} className="d-flex align-items-center justify-content-between mb-2 p-2 bg-white rounded-3 shadow-xs">
                                                                        <div className="d-flex align-items-center gap-2">
                                                                            <div className={`rounded-circle d-flex align-items-center justify-content-center fw-black text-white ${idx === 0 ? 'bg-warning' : idx === 1 ? 'bg-secondary' : 'bg-brown'}`} style={{ width: 24, height: 24, fontSize: '0.7rem' }}>
                                                                                {idx + 1}
                                                                            </div>
                                                                            <span className="fw-bold small text-dark truncate-text" style={{ maxWidth: '100px' }}>{p.name}</span>
                                                                        </div>
                                                                        <div className="text-end">
                                                                            <span className="fw-black text-primary small">{p.total_xp || 0}</span>
                                                                            <span className="text-muted x-small ms-1">XP</span>
                                                                        </div>
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div className="row g-4 mt-2">
                                <div className="col-12">
                                    <div className="card border-0 shadow-sm rounded-5 p-4 bg-danger bg-opacity-10 border-start border-danger border-5">
                                        <div className="d-flex align-items-center justify-content-between flex-wrap gap-3">
                                            <div>
                                                <h5 className="fw-black text-danger mb-1"><FaExclamationTriangle className="me-2" /> Danger Zone</h5>
                                                <p className="text-muted fw-bold small mb-0">Permanently remove all {stats.total} student records and rosters from this school.</p>
                                            </div>
                                            <button onClick={handleWipeDatabase} disabled={processing || stats.total === 0} className="btn btn-danger rounded-pill px-4 fw-black shadow-sm">
                                                {processing ? <FaCircleNotch className="fa-spin me-2" /> : <FaTrash className="me-2" />} BULK DELETE ALL STUDENTS
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* ─── ROSTER ─── */}
                    {view === 'roster' && (
                        <div className="animate-fadeUp">
                            <div className="card border-0 shadow-sm rounded-5 overflow-hidden">
                                <div className="p-3 p-lg-4 bg-white border-bottom">
                                    <div className="row g-2 align-items-center">
                                        <div className="col-12 col-md-5">
                                            <div className="search-bar-premium bg-light rounded-pill px-3 py-1 border d-flex align-items-center">
                                                <FaSearch className="text-muted ms-1" size={14} />
                                                <input type="text" className="form-control border-0 bg-transparent shadow-none fw-bold small" placeholder="Search by name or parent..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} />
                                            </div>
                                        </div>
                                        <div className="col-12 col-md-7 d-flex gap-1 overflow-auto py-1 scrollbar-hide align-items-center">
                                            {CLASSES.map((clsName) => (
                                                <button key={clsName} onClick={() => setActiveClass(clsName)} className={`btn btn-sm rounded-pill px-3 py-2 fw-black text-nowrap transition-all ${activeClass === clsName ? 'btn-dark' : 'btn-light border text-muted small'}`}>{clsName}</button>
                                            ))}
                                            <button onClick={handleWipeDatabase} className="btn btn-sm btn-outline-danger rounded-pill px-3 py-2 fw-black text-nowrap ms-auto border-2">WIPE ALL</button>
                                        </div>
                                    </div>
                                </div>
                                <div className="table-responsive">
                                    <table className="table table-hover align-middle mb-0">
                                        <thead className="bg-light text-muted fw-black ls-1" style={{ fontSize: '0.65rem' }}>
                                            <tr>
                                                <th className="px-4 py-3">EXPLORER IDENTIFICATION</th>
                                                <th className="py-3 d-none d-md-table-cell">GRADE</th>
                                                <th className="py-3">STATUS</th>
                                                <th className="py-3 d-none d-lg-table-cell">REMAINING</th>
                                                <th className="px-4 py-3 text-end">ACTIONS</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {filteredStudents.length > 0 ? filteredStudents.map((s) => {
                                                const { diffDays } = calculateExpiry(s.created_at, s.status_changed_at);
                                                const isExpired = diffDays <= 0;
                                                return (
                                                    <tr key={s.id} className="student-row-hover">
                                                        <td className="px-4 py-3">
                                                            <div className="d-flex align-items-center gap-2 gap-lg-3">
                                                                 <div className="bg-primary text-white rounded-circle d-flex align-items-center justify-content-center fw-black shadow-sm" style={{ width: 42, height: 42, minWidth: 42 }}>{s.name.charAt(0)}</div>
                                                                 <div>
                                                                     <div className="fw-black text-dark mb-0 mobile-fs-small">{s.name}</div>
                                                                     <div className="text-muted fw-bold x-small text-uppercase ls-1">P: {s.parent_name || 'N/A'}</div>
                                                                 </div>
                                                            </div>
                                                        </td>
                                                        <td className="py-3 fw-black text-primary d-none d-md-table-cell">{(s.current_level || '').replace('Class ', '')}</td>
                                                        <td className="py-3">
                                                            <span className={`badge rounded-pill px-3 py-2 fw-black x-small ${s.payment_status === 'paid' && !isExpired ? 'bg-success-light text-success' : 'bg-warning-light text-warning'}`}>
                                                                {isExpired ? 'EXPIRED' : s.payment_status.toUpperCase()}
                                                            </span>
                                                            {s.screenshot_url && (
                                                                <a href={s.screenshot_url} target="_blank" rel="noreferrer" className="d-block small text-primary text-decoration-none mt-1">
                                                                    View Screenshot
                                                                </a>
                                                            )}
                                                        </td>
                                                        <td className="py-3 fw-bold small d-none d-lg-table-cell">
                                                            {isExpired ? <span className="text-danger fw-black">0 DAYS</span> : <span className="text-muted">{diffDays} DAYS</span>}
                                                        </td>
                                                        <td className="px-4 py-3 text-end" onClick={e => e.stopPropagation()}>
                                                            <div className="d-flex justify-content-end gap-1 gap-lg-2">
                                                                <button onClick={() => setSelectedStudent(s)} className="btn btn-sm btn-light border p-2 rounded-circle text-primary"><FaEye size={14} /></button>
                                                                <button onClick={() => setEditingStudent({ ...s })} className="btn btn-sm btn-light border p-2 rounded-circle text-warning d-none d-md-inline-block"><FaEdit size={14} /></button>
                                                                <button onClick={() => handleDeleteStudent(s.id)} disabled={processing} className="btn btn-sm btn-light border p-2 rounded-circle text-danger d-flex align-items-center justify-content-center">
                                                                    {processing ? <FaCircleNotch className="fa-spin" size={14} /> : <FaTrash size={14} />}
                                                                </button>
                                                            </div>
                                                        </td>
                                                    </tr>
                                                );
                                            }) : (
                                                <tr><td colSpan="5" className="text-center py-5 fw-bold text-muted opacity-50">No explorers match your search.</td></tr>
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* ─── ENROLL ─── */}
                    {view === 'add-student' && (
                        <div className="animate-fadeUp">
                            <div className="card border-0 shadow-lg rounded-5 overflow-hidden bg-white">
                                <div className="row g-0">
                                    <div className="col-lg-7 p-4 p-lg-5">
                                        <h2 className="fw-black text-dark mb-4 ls-tight">Manual Enrollment</h2>
                                        {error && <div className="alert alert-danger rounded-4 fw-bold shadow-sm mb-4">{error}</div>}
                                        {success && <div className="alert alert-success rounded-4 fw-bold shadow-sm mb-4">{success}</div>}
                                        <form onSubmit={handleSingleSubmit} className="row g-3">
                                            <div className="col-12"><div className="form-floating"><input className="form-control rounded-4 px-4 bg-light border-0 fw-bold" id="sName" placeholder="Name" required value={newStudent.studentName} onChange={e => setNewStudent({ ...newStudent, studentName: e.target.value })} /><label htmlFor="sName">Explorer Name</label></div></div>
                                            <div className="col-md-6"><div className="form-floating"><select className="form-select rounded-4 px-4 bg-light border-0 fw-bold" id="sClass" value={newStudent.classLevel} onChange={e => setNewStudent({ ...newStudent, classLevel: e.target.value })}>{CLASSES.filter(c => c !== 'All').map(c => <option key={c} value={`Class ${c}`}>{c}</option>)}</select><label htmlFor="sClass">Grade</label></div></div>
                                            <div className="col-md-3"><div className="form-floating"><input className="form-control rounded-4 px-4 bg-light border-0 fw-bold" id="sAge" type="number" value={newStudent.age} onChange={e => setNewStudent({ ...newStudent, age: e.target.value })} /><label htmlFor="sAge">Age</label></div></div>
                                            <div className="col-md-3"><div className="form-floating"><select className="form-select rounded-4 px-4 bg-light border-0 fw-bold" id="sGender" value={newStudent.gender} onChange={e => setNewStudent({ ...newStudent, gender: e.target.value })}><option>Boy</option><option>Girl</option></select><label htmlFor="sGender">Gender</label></div></div>
                                            <div className="col-12 mt-4 mt-lg-5 mb-2"><h6 className="fw-black text-muted text-uppercase ls-1 small">Guardian Profile</h6><hr className="my-1 opacity-10" /></div>
                                            <div className="col-12"><div className="form-floating"><input className="form-control rounded-4 px-4 bg-light border-0 fw-bold" id="pName" placeholder="PName" required value={newStudent.parentName} onChange={e => setNewStudent({ ...newStudent, parentName: e.target.value })} /><label htmlFor="pName">Parent Name</label></div></div>
                                            <div className="col-md-6"><div className="form-floating"><input className="form-control rounded-4 px-4 bg-light border-0 fw-bold font-monospace" id="pCnic" placeholder="PCnic" required value={newStudent.parentCnic} onChange={e => setNewStudent({ ...newStudent, parentCnic: e.target.value })} /><label htmlFor="pCnic">CNIC (No Dashes)</label></div></div>
                                            <div className="col-md-6"><div className="form-floating"><input className="form-control rounded-4 px-4 bg-light border-0 fw-bold" id="pEmail" placeholder="PEmail" type="email" value={newStudent.parentEmail} onChange={e => setNewStudent({ ...newStudent, parentEmail: e.target.value })} /><label htmlFor="pEmail">Email Address</label></div></div>
                                            <div className="col-12">
                                                <label className="fw-bold small mb-2 text-primary">Upload Payment Screenshot</label>
                                                <input className="form-control rounded-4 bg-light border-0 px-4 fw-bold py-2" type="file" accept="image/*" onChange={e => setStudentScreenshotFile(e.target.files[0])} required />
                                                <p className="x-small text-muted mt-1 mb-0">Please upload screenshot of Rs 500 payment for this child.</p>
                                            </div>
                                            <div className="col-12 mt-4"><button type="submit" disabled={processing} className="btn btn-primary btn-lg w-100 py-3 rounded-pill fw-black shadow-lg border-0">{processing ? <FaCircleNotch className="fa-spin" /> : 'CONFIRM ENROLLMENT'}</button></div>
                                        </form>
                                    </div>
                                    <div className="col-lg-5 bg-dark p-4 p-lg-5 text-white d-flex flex-column justify-content-center text-center">
                                        <FaUpload size={48} className="text-primary mb-4 mx-auto" />
                                        <h3 className="fw-black mb-3">Bulk Access</h3>
                                        <p className="opacity-75 mb-3 small fw-bold">Enroll your entire student roster instantly using our standard CSV format.</p>
                                        <div className="mb-4 text-start">
                                            <label className="fw-bold small mb-2 text-white">Upload Payment Screenshot for Bulk Students</label>
                                            <input type="file" accept="image/*" onChange={e => setBulkScreenshotFile(e.target.files[0])} className="form-control bg-dark border-secondary text-white rounded-pill px-4" />
                                            <p className="x-small text-muted mt-1 mb-0">Provide single proof for all bulk enrollments (Rs 500/child).</p>
                                        </div>
                                        <input type="file" id="csvFile" accept=".csv" onChange={handleCSVUpload} className="d-none" />
                                        <label htmlFor="csvFile" className={`btn btn-white btn-lg w-100 py-3 rounded-pill fw-black mb-3 shadow position-relative overflow-hidden ${processing ? 'disabled' : ''}`}>
                                            {processing ? (
                                                <>
                                                    <FaCircleNotch className="fa-spin me-2" /> PROCESSING ({csvProgress}%)
                                                    <div className="position-absolute bottom-0 start-0 h-100 bg-primary opacity-10 progress-fill-active" style={{ width: `${csvProgress}%`, transition: 'width 0.3s ease' }}></div>
                                                </>
                                            ) : (
                                                <>UPLOAD CSV</>
                                            )}
                                        </label>
                                        {processing && (
                                            <div className="progress rounded-pill bg-dark border border-secondary mb-3" style={{ height: '8px' }}>
                                                <div className="progress-bar progress-bar-striped progress-bar-animated bg-primary" role="progressbar" style={{ width: `${csvProgress}%` }}></div>
                                            </div>
                                        )}
                                        <button onClick={() => { }} className="btn btn-link text-white text-decoration-none fw-bold small opacity-50"><FaDownload className="me-2" /> Download Template</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* ─── MODALS ─── */}
            {(editingStudent || selectedStudent) && (
                <div className="modal-overlay-premium" onClick={() => { setEditingStudent(null); setSelectedStudent(null); }}>
                    <div className="modal-card-premium card border-0 shadow-2xl rounded-5 bg-white overflow-hidden" onClick={e => e.stopPropagation()}>
                        {editingStudent ? (
                            <>
                                <div className="p-3 px-4 bg-warning text-white d-flex justify-content-between align-items-center position-relative">
                                    <h5 className="fw-black mb-0">Modify Record</h5>
                                    <button onClick={() => setEditingStudent(null)} className="btn-close-premium" style={{ width: '32px', height: '32px' }}>
                                        <FaTimes size={14} />
                                    </button>
                                </div>
                                <div className="p-4">
                                    <form onSubmit={handleEditStudent} className="row g-2">
                                        <div className="col-12"><div className="form-floating"><input className="form-control rounded-4 px-4 bg-light border-0 fw-bold" id="eName" required value={editingStudent.name} onChange={e => setEditingStudent({ ...editingStudent, name: e.target.value })} /><label htmlFor="eName">Name</label></div></div>
                                        <div className="col-md-6"><div className="form-floating"><select className="form-select rounded-4 px-4 bg-light border-0 fw-bold" id="eClass" value={editingStudent.current_level} onChange={e => setEditingStudent({ ...editingStudent, current_level: e.target.value })}>{CLASSES.filter(c => c !== 'All').map(c => <option key={c} value={`Class ${c}`}>{c}</option>)}</select><label htmlFor="eClass">Grade</label></div></div>
                                        <div className="col-md-6"><div className="form-floating"><input className="form-control rounded-4 px-4 bg-light border-0 fw-bold" id="eAge" type="number" value={editingStudent.age} onChange={e => setEditingStudent({ ...editingStudent, age: e.target.value })} /><label htmlFor="eAge">Age</label></div></div>
                                        <div className="col-12">
                                            <button type="submit" disabled={processing} className="btn btn-warning btn-lg w-100 py-3 rounded-pill fw-black text-white shadow-lg border-0 mt-2 d-flex align-items-center justify-content-center gap-2">
                                                {processing ? <FaCircleNotch className="fa-spin" /> : 'UPDATE PROFILE'}
                                            </button>
                                        </div>
                                    </form>
                                </div>
                            </>
                        ) : (
                            <>
                                <div className="p-3 px-4 bg-primary text-white d-flex align-items-center gap-3 position-relative">
                                    <button onClick={() => setSelectedStudent(null)} className="btn-close-premium" style={{ width: '32px', height: '32px' }}>
                                        <FaTimes size={14} />
                                    </button>
                                    <div className="bg-white text-primary rounded-circle fw-black fs-4 d-flex align-items-center justify-content-center shadow-sm" style={{ width: 42, height: 42, minWidth: 42 }}>{selectedStudent.name.charAt(0)}</div>
                                    <div><h5 className="fw-black mb-0 ls-tight">{selectedStudent.name}</h5><p className="mb-0 fw-bold opacity-75 x-small">{selectedStudent.current_level} Explorer</p></div>
                                </div>
                                <div className="p-3">
                                    <div className="row g-2">
                                        <div className="col-12 col-md-6">
                                            <div className="p-3 bg-light rounded-4 border-start border-primary border-4 mb-2 shadow-sm">
                                                <small className="text-muted fw-black text-uppercase ls-1 x-small">Login Key</small>
                                                <div className="fw-black text-primary font-monospace mt-0 fs-4">{selectedStudent.secret_key}</div>
                                            </div>
                                            <div className="p-3 bg-light rounded-4 border-start border-info border-4 mb-2 shadow-sm">
                                                <div className="row">
                                                    <div className="col-6">
                                                        <small className="text-muted fw-black text-uppercase ls-1 x-small">Age</small>
                                                        <div className="fw-black text-dark">{selectedStudent.age || 'N/A'}</div>
                                                    </div>
                                                    <div className="col-6">
                                                        <small className="text-muted fw-black text-uppercase ls-1 x-small">Gender</small>
                                                        <div className="fw-black text-dark">{selectedStudent.gender || 'N/A'}</div>
                                                    </div>
                                                </div>
                                            </div>
                                            <div className="p-3 bg-light rounded-4 border-start border-success border-4 shadow-sm">
                                                <small className="text-muted fw-black text-uppercase ls-1 x-small">Subscription</small>
                                                <div className="fw-black text-dark mt-0 small">Status: {selectedStudent.payment_status.toUpperCase()}</div>
                                                <div className="text-danger fw-bold x-small">Expiry: {calculateExpiry(selectedStudent.created_at).endDate}</div>
                                            </div>
                                        </div>
                                        <div className="col-12 col-md-6">
                                            <div className="bg-light rounded-4 p-3 border shadow-sm h-100">
                                                <h6 className="fw-black text-muted text-uppercase ls-1 mb-2 x-small">Guardian Profile (CSV Data)</h6>
                                                <div className="mb-2">
                                                    <small className="text-muted fw-bold x-small">Full Name:</small>
                                                    <div className="fw-black text-dark x-small">{selectedStudent.parent_name || 'N/A'}</div>
                                                </div>
                                                <div className="mb-2">
                                                    <small className="text-muted fw-bold x-small">CNIC:</small>
                                                    <div className="fw-black text-primary font-monospace x-small">{selectedStudent.parent_cnic || 'N/A'}</div>
                                                </div>
                                                <div className="mb-2">
                                                    <small className="text-muted fw-bold x-small">Email:</small>
                                                    <div className="fw-black text-dark x-small">{selectedStudent.parent_email || 'N/A'}</div>
                                                </div>
                                                <div className="mt-3 p-2 bg-white rounded-3 border">
                                                    <small className="text-muted fw-bold x-small d-block mb-1">Parent Login Password:</small>
                                                    <div className="badge bg-dark rounded-pill px-3 py-1 font-monospace" style={{ fontSize: '0.75rem' }}>{selectedStudent.parent_cnic || 'N/A'}</div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </>
                        )}
                    </div>
                </div>
            )}

            <style>{`
                @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800;900&display=swap');
                .school-dashboard-premium { font-family: 'Outfit', sans-serif; overflow-x: hidden; }
                .fw-black { font-weight: 900 !important; }
                .ls-1 { letter-spacing: 0.1em; }
                .ls-tight { letter-spacing: -0.05em; }
                .transition-all { transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); }
                
                /* SKELETON PREMIUM */
                .skeleton-wave { background: #f1f5f9; background-image: linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 50%, #f1f5f9 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite linear; border-radius: 16px; opacity: 0.7; }
                @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
                .skeleton-card-premium { position: relative; overflow: hidden; background: white; border: 1px solid #f1f5f9; }
                .shimmer-overlay { background: linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.6) 50%, rgba(255,255,255,0) 100%); animation: sweep 2s infinite linear; width: 100%; height: 100%; top: 0; left: -100%; position: absolute; z-index: 1; }
                @keyframes sweep { 0% { left: -100%; } 100% { left: 100%; } }

                .btn-primary { background: #0ea5e9; border: none; }
                .progress-fill-active { animation: pulse-opacity 2s infinite ease-in-out; }
                @keyframes pulse-opacity { 0% { opacity: 0.1; } 50% { opacity: 0.2; } 100% { opacity: 0.1; } }
                .btn-white { background: white; color: #0ea5e9 !important; border: 1px solid #e2e8f0; }
                .bg-primary-light { background: #f0f9ff; }
                .bg-success-light { background: #f0fdf4; } .text-success { color: #10b981 !important; }
                .bg-warning-light { background: #fffbeb; } .text-warning { color: #f59e0b !important; }
                
                .modal-overlay-premium { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(15, 23, 42, 0.9); backdrop-filter: blur(15px); display: flex; align-items: center; justify-content: center; z-index: 10000; padding: 20px; }
                .modal-card-premium { width: 100%; max-width: 800px; max-height: 90vh; overflow-y: auto; border-radius: 35px; animation: modalIn 0.4s cubic-bezier(0.34, 1.56, 0.64, 1); position: relative; }
                @keyframes modalIn { 0% { transform: scale(0.9) translateY(20px); opacity: 0; } 100% { transform: scale(1) translateY(0); opacity: 1; } }
                
                .btn-close-premium { position: absolute; top: 20px; right: 20px; background: rgba(255, 255, 255, 0.2); border: none; color: white; width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; transition: all 0.3s; z-index: 10; cursor: pointer; }
                .btn-close-premium:hover { background: rgba(255, 255, 255, 0.3); transform: rotate(90deg); }

                .animate-fadeUp { animation: fadeUp 0.6s ease-out forwards; }
                @keyframes fadeUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
                
                .scrollbar-hide::-webkit-scrollbar { display: none; }
                .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }

                /* MOBILE OPTIMIZATIONS */
                @media (max-width: 768px) {
                    .mobile-fs-4 { font-size: 1.4rem !important; }
                    .mobile-fs-3 { font-size: 1.15rem !important; }
                    .mobile-fs-small { font-size: 0.8rem !important; }
                    .x-small { font-size: 0.6rem !important; }
                    .mobile-p-1 { padding: 6px !important; }
                    .mobile-py-2 { padding-top: 8px !important; padding-bottom: 8px !important; font-size: 0.7rem !important; }
                    .chart-wrapper { height: 230px !important; }
                    .container-fluid { padding-left: 12px !important; padding-right: 12px !important; }
                    .modal-card-premium { border-radius: 25px; max-height: 95vh; }
                    .btn-close-premium { top: 15px; right: 15px; width: 32px; height: 32px; }
                }
            `}</style>
        </div>
    );
};

export default SchoolDashboard;

import React from 'react';
import './auth.css';
import { useAuthForm } from './useAuthForm';
import { LoginForm } from './LoginForm';
import PaymentRegistration from '../PaymentRegistration';
import { KidLoginForm } from './KidLoginForm';
import { FaUserShield, FaGamepad, FaSync } from 'react-icons/fa';
import { useTheme } from '../../utils/ThemeContext';
import loginBgForest from '../../assets/no_bg_output/loginbg.jpg';
import loginBgPrincess from '../../assets/no_bg_output/loginbgbarbie.jpg';

const Auth = () => {
    const {
        isLogin, setIsLogin, authType, setAuthType, loading, error, handleAuth,
        email, setEmail, password, setPassword,
        parentName, setParentName, secretKey, setSecretKey
    } = useAuthForm();
    const { theme } = useTheme();

    React.useEffect(() => {
        // Preload background images non-blockingly after mount
        const imgForest = new Image();
        imgForest.src = loginBgForest;
        const imgPrincess = new Image();
        imgPrincess.src = loginBgPrincess;
    }, []);

    const isSignup = !isLogin && authType !== 'kid';
    const colClass = isSignup ? "col-12 col-md-10 col-lg-9" : "col-12 col-md-8 col-lg-6";

    return (
        <section className={`auth-section py-5 theme-${theme}`}>
            <div className="container">
                <div className="row justify-content-center">
                    <div className={colClass}>
                        <div className="card auth-card border-0 rounded-4 overflow-hidden p-4 p-md-5">
                            
                            {/* HEADER */}
                            <div className="text-center mb-4">
                                <h2 className="fw-bold text-dark mb-2">
                                    {isLogin ? 'Welcome Back!' : 'Join the Adventure!'}
                                </h2>
                                <p className="text-muted small">
                                    {isLogin ? 'Log in to continue your adventure.' : 'Register your school to start managing students.'}
                                </p>
                            </div>

                            {/* ROLE SELECTION BUTTONS (NEW LOCATION) */}
                            <div className="d-flex bg-light p-1 rounded-pill mb-4 mx-auto" style={{ maxWidth: '320px' }}>
                                <button
                                    className={`btn flex-fill rounded-pill border-0 py-2 fw-bold transition-all d-flex align-items-center justify-content-center ${authType === 'kid' ? 'btn-primary shadow-sm' : 'text-muted'}`}
                                    onClick={() => setAuthType('kid')}
                                >
                                    <FaGamepad className="me-2" />
                                    <span className="small">Explore</span>
                                </button>
                                <button
                                    className={`btn flex-fill rounded-pill border-0 py-2 fw-bold transition-all d-flex align-items-center justify-content-center ${authType === 'parent' ? 'btn-primary shadow-sm' : 'text-muted'}`}
                                    onClick={() => setAuthType('parent')}
                                >
                                    <FaUserShield className="me-2" />
                                    <span className="small">Manage</span>
                                </button>
                            </div>

                            {error && (
                                <div className="alert alert-danger rounded-3 small py-2 mb-4" role="alert">
                                    {error}
                                </div>
                            )}

                            <div className="form-container">
                                {authType === 'kid' ? (
                                    <form onSubmit={handleAuth}>
                                        <div className="row g-3">
                                            <KidLoginForm 
                                                secretKey={secretKey} 
                                                setSecretKey={setSecretKey} 
                                            />
                                            <div className="col-12 mt-4 text-center">
                                                <button type="submit" className="btn btn-primary w-100 rounded-pill py-3 fw-bold shadow-lg transform-hover" disabled={loading}>
                                                    {loading ? <FaSync className="fa-spin-custom me-2" /> : null}
                                                    Launch Playland!
                                                </button>
                                            </div>
                                        </div>
                                    </form>
                                ) : isLogin ? (
                                    <form onSubmit={handleAuth}>
                                        <div className="row g-3">
                                            <LoginForm
                                                email={email} setEmail={setEmail}
                                                password={password} setPassword={setPassword}
                                            />
                                            <div className="col-12 mt-4 text-center">
                                                <button type="submit" className="btn btn-primary w-100 rounded-pill py-3 fw-bold shadow-lg transform-hover" disabled={loading}>
                                                    {loading ? <FaSync className="fa-spin-custom me-2" /> : null}
                                                    LOG IN
                                                </button>
                                            </div>

                                            <div className="col-12 mt-2 text-center">
                                                <div className="mt-4">
                                                    <p className="small text-muted mb-0">
                                                        Don't have an account? 
                                                        <button type="button" className="btn btn-link text-primary p-0 fw-bold text-decoration-none ms-1" onClick={() => setIsLogin(false)}>
                                                            SIGN UP
                                                        </button>
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                    </form>
                                ) : (
                                    <div className="row g-3">
                                        <PaymentRegistration />
                                        <div className="col-12 mt-2 text-center">
                                            <div className="mt-4">
                                                <p className="small text-muted mb-0">
                                                    Already registered? 
                                                    <button type="button" className="btn btn-link text-primary p-0 fw-bold text-decoration-none ms-1" onClick={() => setIsLogin(true)}>
                                                        LOG IN
                                                    </button>
                                                </p>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <style>{`
                .auth-card { font-family: 'Fredoka', sans-serif; }
                .transition-all { transition: all 0.3s ease; }
                .transform-hover { transition: transform 0.2s; }
                .transform-hover:active { transform: scale(0.98); }
                .btn-primary { background: #0ea5e9; border: none; }
                .btn-primary:hover { background: #0284c7; }
            `}</style>
        </section>
    );
};

export default Auth;

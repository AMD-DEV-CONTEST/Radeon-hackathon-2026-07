import React, { useState, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { supabase } from '../utils/supabaseClient';
import { useTheme } from '../utils/ThemeContext';
import { FaTree, FaMagic, FaCrown, FaChevronDown, FaUserAlt, FaSync, FaCircleNotch, FaGamepad, FaDoorOpen } from 'react-icons/fa';
import SpriteLoader from './Loader/SpriteLoader';

const Navbar = () => {
    const { theme, changeTheme, themes, themeAssets } = useTheme();
    const [scrolled, setScrolled] = useState(false);
    const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
    const [themeDropdownOpen, setThemeDropdownOpen] = useState(false);
    const [user, setUser] = useState(null);
    const [role, setRole] = useState(null); // 'parent' or 'kid'
    const [name, setName] = useState('');
    const [isGlobalLoading, setIsGlobalLoading] = useState(false);
    const location = useLocation();
    const navigate = useNavigate();

    // Auto-close menu on route change
    useEffect(() => {
        setMobileMenuOpen(false);
        setThemeDropdownOpen(false);
    }, [location.pathname]);

    useEffect(() => {
        const handleScroll = () => {
            const isScrolled = window.scrollY > 20;
            if (isScrolled !== scrolled) setScrolled(isScrolled);
        };
        window.addEventListener('scroll', handleScroll);
        return () => window.removeEventListener('scroll', handleScroll);
    }, [scrolled]);

    useEffect(() => {
        const applySession = (session) => {
            const localRole = localStorage.getItem('kido_auth_role');
            const localName = localStorage.getItem('kido_user_name');
            const isAdminBypass = localStorage.getItem('kido_admin_bypass') === 'true';

            if (session?.user || isAdminBypass) {
                setUser(session?.user || { id: 'admin_bypass', user_metadata: { full_name: 'Admin' } });
                const currentRole = isAdminBypass ? 'admin' : (localRole || 'parent');
                setRole(currentRole);
                setName(localName || session?.user?.user_metadata?.full_name || (currentRole === 'school' ? 'School Admin' : currentRole === 'admin' ? 'Super Admin' : 'Parent'));
            } else if (localRole) {
                setUser({ id: localRole + '_session', user_metadata: { full_name: localName } });
                setRole(localRole);
                setName(localName || (localRole === 'kid' ? 'Explorer' : 'User'));
            } else {
                setUser(null);
                setRole(null);
                setName('');
            }
        };

        const initUser = async () => {
            try {
                const { data: { session } } = await supabase.auth.getSession();
                applySession(session);
            } catch (_) {
                applySession(null);
            }
        };

        initUser();

        const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
            applySession(session);
        });

        const handleCustomAuthChange = () => {
            initUser();
        };

        window.addEventListener('kido_auth_change', handleCustomAuthChange);

        return () => {
            subscription.unsubscribe();
            window.removeEventListener('kido_auth_change', handleCustomAuthChange);
        };
    }, []);

    // PERMANENT FIX: Reset global loader on every URL change to prevent "stuck" state
    useEffect(() => {
        setIsGlobalLoading(false);
    }, [location.pathname]);

    const handleEnterPlayland = (e, path = '/levels') => {
        if (location.pathname === path) return;
        setIsGlobalLoading(true);

        // Safety timeout
        const timeout = setTimeout(() => {
            setIsGlobalLoading(false);
        }, 5000);

        // Premium transition delay
        setTimeout(() => {
            navigate(path);
            // Hide loader after a short delay on the next page
            setTimeout(() => {
                setIsGlobalLoading(false);
                clearTimeout(timeout);
            }, 800);
        }, 1200);
    };

    const handleLogout = async () => {
        setIsGlobalLoading(true);

        // Reduced safety timeout for snappier recovery
        const timeout = setTimeout(() => {
            setIsGlobalLoading(false);
            navigate('/auth', { replace: true });
        }, 5000);

        try {
            // Immediately clear local data to unblock UI (preserving child usage tracking limits)
            const keys = { ...localStorage };
            localStorage.clear();
            Object.keys(keys).forEach(key => {
                if (key === 'kido_time_limits' || key.startsWith('kido_usage_')) {
                    localStorage.setItem(key, keys[key]);
                }
            });
            setUser(null);
            setRole(null);
            setName('');
            setMobileMenuOpen(false);
            window.dispatchEvent(new Event('kido_auth_change'));

            // Trigger remote signout in background
            if (role === 'parent' || role === 'school') {
                supabase.auth.signOut().catch(e => console.warn("Silent logout error:", e));
            }

            // Navigate after a small delay for the transition animation
            setTimeout(() => {
                navigate('/auth', { replace: true });
                setTimeout(() => {
                    setIsGlobalLoading(false);
                    clearTimeout(timeout);
                }, 400);
            }, 600);

        } catch (e) {
            console.error("Logout exception:", e);
            const keys = { ...localStorage };
            localStorage.clear();
            Object.keys(keys).forEach(key => {
                if (key === 'kido_time_limits' || key.startsWith('kido_usage_')) {
                    localStorage.setItem(key, keys[key]);
                }
            });
            setUser(null);
            setRole(null);
            setName('');
            window.dispatchEvent(new Event('kido_auth_change'));
            setIsGlobalLoading(false);
            clearTimeout(timeout);
            navigate('/auth', { replace: true });
        }
    };

    const getThemeIcon = (themeKey) => {
        switch (themeKey) {
            case 'forest': return <FaTree />;
            case 'princess': return <FaCrown />;
            default: return <FaMagic />;
        }
    };

    return (
        <>
            <SpriteLoader show={isGlobalLoading} />
            <header className={`wonderbar-header ${theme}-theme ${scrolled ? 'scrolled' : ''} ${location.pathname === '/levels' ? 'navbar-levels-page' : ''} ${location.pathname === '/' ? 'navbar-home-page' : ''} ${location.pathname === '/auth' ? 'navbar-auth-page' : ''}`}>
                <nav className="wonderbar-nav container">
                    <div className="wonderbar-brand-wrapper">
                        <Link to="/" className="wonderbar-brand">
                            <img src={themeAssets.logo} alt="Kido Dev" className="wonderbar-logo" />
                        </Link>
                    </div>

                    <div className="wonderbar-links-wrapper d-none d-lg-flex">
                        <ul className="wonderbar-links">
                            <li className="wb-item">
                                <Link to="/" className={`wb-link color-1 ${location.pathname === '/' ? 'active' : ''}`}>
                                    Home
                                </Link>
                            </li>

                            {(location.pathname !== '/levels' && (!user || location.pathname === '/')) && (
                                <>
                                    <li className="wb-item">
                                        <Link to="/about-us" className={`wb-link color-sdg ${location.pathname === '/about-us' ? 'active' : ''}`}>
                                            About Us
                                        </Link>
                                    </li>
                                    <li className="wb-item">
                                        <Link to="/how-to-use" className={`wb-link color-how ${location.pathname === '/how-to-use' ? 'active' : ''}`}>
                                            How to Use
                                        </Link>
                                    </li>
                                </>
                            )}

                            {(role === 'kid' || location.pathname === '/levels') && location.pathname !== '/' && (
                                <li className="wb-item">
                                    <Link to="/levels" className={`wb-link color-2 ${location.pathname === '/levels' ? 'active' : ''}`}>
                                        Levels
                                    </Link>
                                </li>
                            )}

                            {(role === 'parent' || role === 'school' || role === 'admin') && (
                                <li className="wb-item">
                                    <Link
                                        to={role === 'school' ? "/school-dashboard" : role === 'admin' ? "/admin" : "/parent-dashboard"}
                                        className={`wb-link color-3 ${(location.pathname === '/parent-dashboard' || location.pathname === '/school-dashboard' || location.pathname === '/admin') ? 'active' : ''}`}
                                    >
                                        Dashboard
                                    </Link>
                                </li>
                            )}
                        </ul>
                    </div>

                    <div className="wonderbar-actions">
                        <div className="theme-dropdown-container d-none d-sm-block">
                            <button
                                onClick={() => setThemeDropdownOpen(!themeDropdownOpen)}
                                className={`btn-theme-selector ${theme} ${themeDropdownOpen ? 'open' : ''}`}
                            >
                                {getThemeIcon(theme)}
                                <span>{themes[theme]?.name || 'Theme'}</span>
                                <FaChevronDown className="ms-2 small" />
                            </button>

                            {themeDropdownOpen && (
                                <div className="theme-dropdown-menu shadow-lg">
                                    {Object.keys(themes).map((t) => (
                                        <div
                                            key={t}
                                            className={`theme-dropdown-item ${t} ${theme === t ? 'active' : ''}`}
                                            onClick={() => {
                                                changeTheme(t);
                                                setThemeDropdownOpen(false);
                                            }}
                                        >
                                            {getThemeIcon(t)}
                                            <span>{themes[t].name}</span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        {user ? (
                            <div className="d-flex align-items-center gap-2 gap-md-3">
                                {role === 'kid' && location.pathname === '/' && (
                                    <button onClick={(e) => handleEnterPlayland(e)} disabled={isGlobalLoading} className="btn btn-wonder pulsate px-4 d-flex align-items-center gap-2">
                                        {isGlobalLoading ? <FaCircleNotch className="fa-spin-custom" /> : <FaGamepad />}
                                        <span>Let's Play</span>
                                    </button>
                                )}
                                <div className="wb-user-info-pill">
                                    <FaUserAlt className="me-2" />
                                    <span className="wb-user-greeting">Hi, {name}!</span>
                                </div>
                                <button onClick={handleLogout} disabled={isGlobalLoading} className="btn-exit-playland shadow-sm d-flex align-items-center gap-2">
                                    {isGlobalLoading ? <FaCircleNotch className="fa-spin-custom" /> : <FaDoorOpen />}
                                    <span>Exit Playland</span>
                                </button>
                            </div>
                        ) : (
                            !location.pathname.startsWith('/admin') && (
                                <button onClick={(e) => handleEnterPlayland(e, '/auth')} disabled={isGlobalLoading} className="btn btn-wonder pulsate px-4 d-flex align-items-center gap-2">
                                    {isGlobalLoading ? <FaCircleNotch className="fa-spin-custom" /> : <FaGamepad />}
                                    <span>Enter Playland</span>
                                </button>
                            )
                        )}
                    </div>

                    {role === 'kid' && location.pathname === '/' && (
                        <button
                            onClick={(e) => handleEnterPlayland(e)}
                            disabled={isGlobalLoading}
                            className="btn btn-wonder pulsate px-3 py-1 d-flex align-items-center gap-1 d-lg-none me-2"
                            style={{ borderRadius: '20px', fontSize: '13px', height: '36px', border: 'none' }}
                        >
                            {isGlobalLoading ? <FaCircleNotch className="fa-spin-custom" /> : <FaGamepad />}
                            <span style={{ fontWeight: 'bold' }}>Play</span>
                        </button>
                    )}

                    <button className={`wonderbar-toggler d-lg-none ${mobileMenuOpen ? 'open' : ''}`} onClick={() => setMobileMenuOpen(!mobileMenuOpen)}>
                        <span className="bar bar-1"></span>
                        <span className="bar bar-2"></span>
                        <span className="bar bar-3"></span>
                    </button>
                </nav>

                <div className={`wonderbar-mobile-menu ${mobileMenuOpen ? 'active' : ''}`}>
                    <div className="mobile-links-container px-4 text-center w-100">
                        <Link to="/" className="mobile-link" onClick={() => setMobileMenuOpen(false)}>Home</Link>

                        {(location.pathname !== '/levels' && (!user || location.pathname === '/')) && (
                            <>
                                <Link to="/about-us" className="mobile-link" onClick={() => setMobileMenuOpen(false)}>About Us</Link>
                                <Link to="/how-to-use" className="mobile-link" onClick={() => setMobileMenuOpen(false)}>How to Use</Link>
                            </>
                        )}

                        {(role === 'kid' || location.pathname === '/levels') && location.pathname !== '/' && (
                            <Link to="/levels" className="mobile-link" onClick={() => setMobileMenuOpen(false)}>Levels</Link>
                        )}

                        {(role === 'parent' || role === 'school' || role === 'admin') && (
                            <Link
                                to={role === 'school' ? "/school-dashboard" : role === 'admin' ? "/admin" : "/parent-dashboard"}
                                className="mobile-link"
                                onClick={() => setMobileMenuOpen(false)}
                            >
                                Dashboard
                            </Link>
                        )}

                        <div className="mobile-theme-section w-100 mt-4">
                            <h5 className="mb-3 fw-bold opacity-75" style={{ fontFamily: 'var(--fd)' }}>Pick Your Theme</h5>
                            <div className="mobile-theme-grid d-flex flex-wrap justify-content-center gap-2">
                                {Object.keys(themes).map((t) => (
                                    <button
                                        key={t}
                                        onClick={() => changeTheme(t)}
                                        className={`btn-theme-toggle-pill ${t} ${theme === t ? 'active' : ''}`}
                                    >
                                        {getThemeIcon(t)}
                                        <span>{themes[t].name}</span>
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div className="w-100 mt-5 pt-3 border-top border-white border-opacity-10">
                            {user ? (
                                <div className="d-flex flex-column gap-3">
                                    {role === 'kid' && location.pathname === '/' && (
                                        <button
                                            onClick={(e) => { setMobileMenuOpen(false); handleEnterPlayland(e); }}
                                            disabled={isGlobalLoading}
                                            className="btn btn-wonder w-100 py-3 pulsate d-flex align-items-center justify-content-center gap-3"
                                        >
                                            {isGlobalLoading ? <FaCircleNotch className="fa-spin-custom" /> : <><FaGamepad /> LET'S PLAY</>}
                                        </button>
                                    )}
                                    <div className="wb-user-info-pill mx-auto">
                                        <FaUserAlt className="me-2" />
                                        <span>Hi, {name}!</span>
                                    </div>
                                    <button onClick={handleLogout} disabled={isGlobalLoading} className="btn-exit-playland w-100 py-3 d-flex align-items-center justify-content-center gap-3">
                                        {isGlobalLoading ? <FaCircleNotch className="fa-spin-custom" /> : <><FaDoorOpen /> EXIT PLAYLAND</>}
                                    </button>
                                </div>
                            ) : (
                                <button onClick={(e) => handleEnterPlayland(e, '/auth')} disabled={isGlobalLoading} className="btn btn-wonder w-100 py-3 pulsate d-flex align-items-center justify-content-center gap-3">
                                    {isGlobalLoading ? <FaCircleNotch className="fa-spin-custom" /> : <><FaGamepad /> ENTER PLAYLAND</>}
                                </button>
                            )}
                        </div>
                    </div>
                </div>
            </header>
        </>
    );
};

export default Navbar;

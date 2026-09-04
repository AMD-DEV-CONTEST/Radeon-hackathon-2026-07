import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { supabase } from '../utils/supabaseClient';
import logo from '../assets/logo.png';

const Footer = () => {
    const [email, setEmail] = useState('');
    const [status, setStatus] = useState('idle'); // idle, loading, success, error
    const [errorMsg, setErrorMsg] = useState('');

    const handleSubscribe = async (e) => {
        e.preventDefault();
        if (!email) return;

        setStatus('loading');
        setErrorMsg('');
        
        try {
            // Real Supabase insertion
            const { error } = await supabase
                .from('newsletter_subscriptions')
                .insert([{ email }]);

            if (error) {
                if (error.code === '23505') { // Unique constraint violation
                    setStatus('success'); // Still show success if already subscribed
                } else {
                    throw error;
                }
            } else {
                setStatus('success');
            }
            
            setEmail('');
            // Reset status after a few seconds
            setTimeout(() => setStatus('idle'), 5000);
        } catch (err) {
            console.error('Subscription error:', err);
            setStatus('error');
            setErrorMsg('Magic fizzled out! Please try again.');
            setTimeout(() => setStatus('idle'), 5000);
        }
    };

    const isGamePage = window.location.pathname.startsWith('/games') || window.location.pathname.startsWith('/levels');
    if (isGamePage) return null;

    return (
        <footer className="joyful-footer">
            <div className="container pt-5">
                <div className="row g-5 justify-content-between">
                    {/* Brand Column */}
                    <div className="col-lg-3 col-md-6">
                        <div className="footer-brand mb-4">
                            <img src={logo} alt="Kido Dev" className="footer-logo mb-3" />
                            <h4 className="fw-bold text-primary mb-2">Coding is Magic!</h4>
                            <p className="footer-desc text-muted">
                                We help kids build the future, one block at a time. Join our magical journey of creativity and logic.
                            </p>
                        </div>
                    </div>

                    {/* Explore Column */}
                    <div className="col-lg-2 col-md-6">
                        <h5 className="footer-title text-secondary">Explore</h5>
                        <ul className="list-unstyled footer-links">
                            <li><Link to="/levels" className="footer-link">Our Missions</Link></li>
                            <li><Link to="/how-to-use" className="footer-link">How it Works</Link></li>
                            <li><Link to="/pricing" className="footer-link">Pricing Plans</Link></li>
                            <li><Link to="/auth" className="footer-link">Start Learning</Link></li>
                        </ul>
                    </div>

                    {/* Contact Column */}
                    <div className="col-lg-3 col-md-6">
                        <h5 className="footer-title text-success">Get in Touch</h5>
                        <ul className="list-unstyled footer-links">
                            <li>
                                <a href="mailto:kidodev.app@gmail.com" className="footer-link">
                                    kidodev.app@gmail.com
                                </a>
                            </li>
                            <li>
                                <a href="tel:+923093885154" className="footer-link">
                                    +92 309 3885154
                                </a>
                            </li>
                            <li><Link to="/about-us" className="footer-link">About Us</Link></li>
                            <li><Link to="/privacy-policy" className="footer-link">Privacy Policy</Link></li>
                        </ul>
                    </div>

                    {/* Newsletter Column */}
                    <div className="col-lg-4 col-md-6">
                        <h5 className="footer-title text-info">Unlock Logic Magic</h5>
                        <p className="text-muted small mb-3">Get free coding tips and magical updates delivered to your inbox!</p>
                        
                        <form className="newsletter-form" onSubmit={handleSubscribe}>
                            {status === 'success' ? (
                                <div className="subscribe-success-msg">
                                    <span className="success-check">✓</span> Magic spell cast! You're subscribed.
                                </div>
                            ) : (
                                <>
                                    <div className="input-group mb-2">
                                        <input 
                                            type="email" 
                                            className="form-control rounded-pill-start" 
                                            placeholder="Your Magical Email" 
                                            aria-label="Email"
                                            required
                                            value={email}
                                            onChange={(e) => setEmail(e.target.value)}
                                            disabled={status === 'loading'}
                                        />
                                        <button 
                                            className="btn btn-primary rounded-pill-end" 
                                            type="submit"
                                            disabled={status === 'loading'}
                                        >
                                            {status === 'loading' ? 'Casting...' : 'Cast Spell'}
                                        </button>
                                    </div>
                                    {status === 'error' && (
                                        <div className="text-danger small fw-bold mt-1 ms-2">
                                            {errorMsg}
                                        </div>
                                    )}
                                </>
                            )}
                        </form>
                    </div>
                </div>

                <hr className="footer-divider my-5" />

                {/* Bottom Footer */}
                <div className="row align-items-center py-4">
                    <div className="col-md-6 text-center text-md-start mb-3 mb-md-0">
                        <p className="mb-0 text-muted small">
                            &copy; {new Date().getFullYear()} Kido Dev Inc. 
                            <Link to="/privacy-policy" className="ms-2 text-decoration-none text-muted">Privacy & Terms</Link>
                        </p>
                    </div>
                    <div className="col-md-6 text-center text-md-end">
                        <p className="mb-0 small text-muted developer-credit-wrapper">
                            <a href="https://codenexusltd.com" target="_blank" rel="noopener noreferrer" className="developer-credit">
                                Designed & Developed by <span className="nexus-brand">Code Nexus</span>
                            </a>
                        </p>
                    </div>
                </div>
            </div>

            {/* Floating Clouds Decoration */}
            <div className="footer-cloud cloud-1"></div>
            <div className="footer-cloud cloud-2"></div>
        </footer>
    );
};

export default Footer;

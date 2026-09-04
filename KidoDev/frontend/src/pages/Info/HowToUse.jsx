import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';

const HowToUse = () => {
    useEffect(() => {
        window.scrollTo(0, 0);
    }, []);

    const workflowSteps = [
        {
            num: "01",
            title: "School Registration",
            desc: "Schools join the magical journey by registering on our elite platform. A one-time registration fee of Rs. 5000 unlocks the gateway to future-ready education.",
            price: "Rs. 5000 / One-Time",
            accent: "#0EA5E9"
        },
        {
            num: "02",
            title: "Instant Dashboard",
            desc: "Upon successful registration, schools gain instant access to their professional dashboard to manage their entire digital ecosystem with ease.",
            accent: "#8B5CF6"
        },
        {
            num: "03",
            title: "Student Enrollment",
            desc: "Schools can easily add students to their database. A monthly fee of Rs. 500 per student ensures continuous access to high-quality gamified learning.",
            price: "Rs. 500 / Month per Student",
            accent: "#F59E0B"
        },
        {
            num: "04",
            title: "Auto-Credentials",
            desc: "Our system automatically generates secret keys for students and professional login credentials for parents, ensuring high security and ease of use.",
            accent: "#22C55E"
        },
        {
            num: "05",
            title: "Parental Power",
            desc: "Parents access their dedicated dashboard using their credentials. They can track progress, manage student keys, and stay connected with their child's learning.",
            accent: "#EF4444"
        },
        {
            num: "06",
            title: "Gamified Path",
            desc: "Students select their favorite themes and dive into exciting 3D projects. Solving challenges earns them stars, which are the key to unlocking new levels.",
            accent: "#0EA5E9"
        },
        {
            num: "07",
            title: "Level Progression",
            desc: "To move to the next level, students must earn at least 50% of the stars in their current stage. Each step is designed to build confidence and real skills.",
            accent: "#F59E0B"
        },
        {
            num: "08",
            title: "Co-Mentor AI",
            desc: "Stuck on a tricky puzzle? Our Co-Mentor Agent is there to guide you! Plus, advanced stages feature our elite AI Seekho Prompt Engineering module.",
            accent: "#8B5CF6"
        }
    ];

    return (
        <div className="howto-v3-container">
            {/* Ambient background */}
            <div className="howto-v3-bg">
                <div className="hv3-blob hv3-blob-1"></div>
                <div className="hv3-blob hv3-blob-2"></div>
                <div className="hv3-blob hv3-blob-3"></div>
            </div>

            {/* HERO SECTION */}
            <section className="howto-v3-hero">
                <div className="container">
                    <div className="hv3-hero-inner">
                        <div className="hv3-hero-badge">
                            <span className="hv3-badge-dot"></span>
                            Step-by-Step Guide
                        </div>
                        <h1 className="hv3-hero-title">
                            How to Use
                            <span className="hv3-title-highlight"> Kido Dev</span>
                        </h1>
                        <p className="hv3-hero-subtitle">
                            Welcome to your creative journey! Follow these simple steps to start building
                            your own digital world. It's easy, fun, and totally magical.
                        </p>
                        <div className="hv3-hero-steps-count">
                            <div className="hv3-steps-badge">
                                <span className="hv3-steps-num">8</span>
                                Simple Steps to Get Started
                            </div>
                        </div>
                    </div>
                </div>
                <div className="hv3-hero-wave">
                    <svg viewBox="0 0 1440 80" preserveAspectRatio="none" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M0,40 C360,80 1080,0 1440,40 L1440,80 L0,80 Z" fill="#ffffff" fillOpacity="0.06" />
                    </svg>
                </div>
            </section>

            {/* STEPS GRID */}
            <section className="hv3-steps-section">
                <div className="container">
                    <div className="hv3-steps-grid">
                        {workflowSteps.map((step, index) => (
                            <div
                                key={index}
                                className="hv3-step-card"
                                style={{ '--step-color': step.accent }}
                            >
                                <div className="hv3-step-header">
                                    <div
                                        className="hv3-step-num"
                                        style={{ background: step.accent }}
                                    >
                                        {step.num}
                                    </div>
                                </div>
                                <h3 className="hv3-step-title" style={{ color: step.accent }}>
                                    {step.title}
                                </h3>
                                <p className="hv3-step-desc">{step.desc}</p>
                                {step.price && (
                                    <div
                                        className="hv3-price-pill"
                                        style={{ background: `${step.accent}15`, color: step.accent, border: `1px solid ${step.accent}30` }}
                                    >
                                        {step.price}
                                    </div>
                                )}
                                <div className="hv3-card-accent-line" style={{ background: step.accent }}></div>
                            </div>
                        ))}
                    </div>
                </div>
            </section>

            {/* FINAL CTA */}
            <section className="hv3-cta-section">
                <div className="container">
                    <div className="hv3-cta-card">
                        <div className="hv3-cta-glow"></div>
                        <h2 className="hv3-cta-title">
                            Ready to <span>Start?</span>
                        </h2>
                        <p className="hv3-cta-desc">
                            The future is bright, and it starts with a single step. Join thousands of
                            schools and parents in this magical revolution.
                        </p>
                        <Link to="/auth" className="hv3-cta-btn">
                            Join Kido Dev Now
                        </Link>
                    </div>
                </div>
            </section>
        </div>
    );
};

export default HowToUse;

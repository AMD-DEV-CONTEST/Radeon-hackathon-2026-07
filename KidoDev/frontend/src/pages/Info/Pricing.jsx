import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';

const Pricing = () => {
    useEffect(() => {
        window.scrollTo(0, 0);
    }, []);

    const plans = [
        {
            name: "Elite School Access",
            type: "Institutional Setup",
            price: "Rs. 5000",
            period: "One-Time Registration Fee",
            features: [
                "Full School Administration Console",
                "Teacher Training & Resources",
                "Advanced Curriculum Integration",
                "Custom School Branding",
                "Dedicated Account Manager",
                "Infrastructure Support"
            ],
            cta: "Register School",
            popular: false,
            color: "#8B5CF6"
        },
        {
            name: "Magical Student Pass",
            type: "Continuous Learning",
            price: "Rs. 500",
            period: "per Month / Student",
            features: [
                "Access to All 3D Gamified Projects",
                "Full Storyline Missions (1-10)",
                "AI Seekho Module Access",
                "Personal Creative Studio",
                "Progress Reports for Parents",
                "Achievement Certificates"
            ],
            cta: "Enroll Student",
            popular: true,
            color: "#F59E0B"
        }
    ];

    return (
        <div className="pricing-v3-container">
            {/* Ambient background */}
            <div className="pricing-v3-bg">
                <div className="pv3-blob pv3-blob-1"></div>
                <div className="pv3-blob pv3-blob-2"></div>
                <div className="pv3-blob pv3-blob-3"></div>
            </div>

            {/* HERO SECTION */}
            <section className="pricing-v3-hero">
                <div className="container">
                    <div className="pv3-hero-inner">
                        <div className="pv3-hero-badge">
                            <span className="pv3-badge-dot"></span>
                            Investment in Future
                        </div>
                        <h1 className="pv3-hero-title">
                            Simple and
                            <span className="pv3-title-highlight"> Transparent Pricing</span>
                        </h1>
                        <p className="pv3-hero-subtitle">
                            We empower schools to lead the digital revolution. Our straightforward
                            pricing ensures every student has access to the most advanced gamified
                            coding education in the world.
                        </p>
                    </div>
                </div>
                <div className="pv3-hero-wave">
                    <svg viewBox="0 0 1440 80" preserveAspectRatio="none" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M0,40 C360,80 1080,0 1440,40 L1440,80 L0,80 Z" fill="#ffffff" fillOpacity="0.06" />
                    </svg>
                </div>
            </section>

            <div className="container py-5">
                <div className="pv3-grid">
                    {plans.map((plan, index) => (
                        <div
                            key={index}
                            className={`pv3-card ${plan.popular ? 'popular' : ''}`}
                            style={{ '--plan-color': plan.color }}
                        >
                            {plan.popular && <div className="pv3-popular-label">Active Learning</div>}

                            <div className="pv3-card-header">
                                <h3 className="pv3-plan-name">{plan.name}</h3>
                                <p className="pv3-plan-type">{plan.type}</p>
                            </div>

                            <div className="pv3-price-section">
                                <div className="pv3-price">
                                    <span className="pv3-amount">{plan.price}</span>
                                    <span className="pv3-period">{plan.period}</span>
                                </div>
                            </div>

                            <ul className="pv3-features">
                                {plan.features.map((feature, fIndex) => (
                                    <li key={fIndex}>
                                        <span className="pv3-bullet" style={{ color: plan.color }}>•</span>
                                        <span>{feature}</span>
                                    </li>
                                ))}
                            </ul>

                            <Link
                                to="/auth"
                                className={`pv3-cta-btn ${plan.popular ? 'primary' : ''}`}
                                style={plan.popular ? {} : { borderColor: plan.color, color: plan.color }}
                            >
                                {plan.cta}
                            </Link>
                        </div>
                    ))}
                </div>
            </div>

            {/* FAQ SHORT SECTION */}
            <div className="pv3-bottom-info container text-center">
                <p>Ready to bring the magic of Kido Dev to your institution?</p>
                <Link to="/contact" className="pv3-contact-link">Contact Our Team</Link>
            </div>
        </div>
    );
};

export default Pricing;

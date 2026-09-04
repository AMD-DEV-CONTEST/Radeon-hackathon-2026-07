import React, { useEffect } from 'react';

const PrivacyPolicy = () => {
    useEffect(() => {
        window.scrollTo(0, 0);
    }, []);

    return (
        <div className="info-v3-container">
            {/* Ambient background */}
            <div className="info-v3-bg">
                <div className="iv3-blob iv3-blob-1"></div>
                <div className="iv3-blob iv3-blob-2"></div>
            </div>

            {/* HERO SECTION */}
            <section className="info-v3-hero">
                <div className="container">
                    <div className="iv3-hero-inner">
                        <div className="iv3-hero-badge">
                            <span className="iv3-badge-dot"></span>
                            Trust & Safety
                        </div>
                        <h1 className="iv3-hero-title">
                            Privacy
                            <span className="iv3-title-highlight"> Policy</span>
                        </h1>
                        <p className="iv3-hero-subtitle">
                            Your trust is our most valuable asset. We are committed to protecting the privacy of
                            our young creators and their families.
                        </p>
                    </div>
                </div>
            </section>

            <div className="container py-5">
                <div className="iv3-content-card">
                    <div className="iv3-card-body">
                        <h2 className="iv3-card-title">Standard <span>Terms</span></h2>

                        <div className="iv3-policy-item">
                            <h4 className="iv3-item-title">1. Information We Collect</h4>
                            <p>
                                At Kido Dev, we only collect information that is strictly necessary for providing our educational services.
                                This includes basic account details (username, encrypted password) and progress tracking to help
                                children resume their coding journey.
                            </p>
                        </div>

                        <div className="iv3-policy-item">
                            <h4 className="iv3-item-title">2. Commitment to Children's Safety</h4>
                            <p>
                                We strictly adhere to COPPA (Children's Online Privacy Protection Act) and global data protection standards.
                                We do not display targeted advertisements to children, and we do not sell or trade user data to third parties.
                            </p>
                        </div>

                        <div className="iv3-policy-item refund-highlight">
                            <h4 className="iv3-item-title text-danger">3. Non-Refundable Fee Policy</h4>
                            <div className="iv3-highlight-box">
                                Please note that all subscription fees, platform access charges, and registration fees are
                                <strong> strictly non-refundable</strong>.
                            </div>
                            <p>
                                Once a subscription is activated or a payment is processed, the digital assets and learning
                                materials are immediately unlocked for use. As these are digital goods, we cannot offer
                                refunds under any circumstances.
                            </p>
                        </div>

                        <div className="iv3-policy-item">
                            <h4 className="iv3-item-title">4. Data Usage</h4>
                            <p>Your data is used solely to:</p>
                            <ul className="iv3-list">
                                <li>Provide personalized learning paths.</li>
                                <li>Track student performance and logic development.</li>
                                <li>Communicate important platform updates to parents/schools.</li>
                            </ul>
                        </div>

                        <div className="iv3-policy-item">
                            <h4 className="iv3-item-title">5. Security Measures</h4>
                            <p>
                                We implement industry-standard encryption and security protocols to ensure your data remains
                                safe from unauthorized access. Our platform is regularly audited for security vulnerabilities.
                            </p>
                        </div>

                        <div className="iv3-footer">
                            Last Updated: April 2026. For any questions regarding this policy, please contact our support team.
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default PrivacyPolicy;

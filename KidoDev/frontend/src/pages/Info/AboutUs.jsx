import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';

const AboutUs = () => {
    useEffect(() => {
        window.scrollTo(0, 0);
    }, []);

    const missionPoints = [
        {
            title: "Playful Learning",
            desc: "We believe children learn best when they are fully immersed in play. Our platform transforms complex coding concepts into a magical, gamified experience that sparks natural curiosity.",
            color: "#0EA5E9",
            bg: "rgba(14, 165, 233, 0.07)"
        },
        {
            title: "Future Readiness",
            desc: "Equipping the next generation with the tools of tomorrow. Coding is the new literacy, and we make it accessible and exciting for every young mind.",
            color: "#8B5CF6",
            bg: "rgba(139, 92, 246, 0.07)"
        },
        {
            title: "AI Seekho Module",
            desc: "In advanced stages, students learn to master AI by crafting perfect prompts, preparing them for the future of human-AI collaboration through our exclusive AI Seekho module.",
            color: "#F59E0B",
            bg: "rgba(245, 158, 11, 0.07)"
        },
        {
            title: "Inclusive Design",
            desc: "Every level and interaction is designed with heart. We build confidence and creative problem-solving in an environment where every child feels empowered to excel.",
            color: "#22C55E",
            bg: "rgba(34, 197, 94, 0.07)"
        }
    ];

    const detailedSDGs = [
        {
            num: "04",
            title: "Quality Education",
            color: "#C31331",
            detail: "Kido Dev aligns with UN Target 4.4, aiming to increase youth with relevant technical and vocational skills for employment and entrepreneurship.",
            impacts: ["100,000+ interactive challenges", "98% proficiency in logic", "Teacher training modules"]
        },
        {
            num: "05",
            title: "Gender Equality",
            color: "#FF3A21",
            detail: "We bridge the gender gap in technology. Our inclusive gamified environment encourages girls to excel in STEM subjects, aligning with UN Target 5.b.",
            impacts: ["45% female enrollment", "Inclusive storytelling", "STEM empowerment workshops"]
        },
        {
            num: "09",
            title: "Industry & Innovation",
            color: "#F36D25",
            detail: "Fostering innovation from an early age. Kido Dev provides digital infrastructure for children to understand industrial logic and technological innovation.",
            impacts: ["Proprietary cognitive engine", "AI & ML logic introduction", "Infrastructure for schools"]
        },
        {
            num: "10",
            title: "Reduced Inequalities",
            color: "#E11484",
            detail: "Our mission is to democratize high-quality tech education, making advanced coding concepts accessible through play across all socioeconomic backgrounds.",
            impacts: ["Scholarship programs", "Low-bandwidth accessibility", "Multilingual learning support"]
        },
        {
            num: "17",
            title: "Global Partnerships",
            color: "#19486A",
            detail: "Success is a collective effort. We partner with elite educational institutions and global organizations to revitalize global partnerships for education.",
            impacts: ["Board collaborations", "Pedagogical resources", "Public-private synergy"]
        }
    ];

    return (
        <div className="about-v3-container">
            {/* Ambient background */}
            <div className="about-v3-bg">
                <div className="v3-blob v3-blob-1"></div>
                <div className="v3-blob v3-blob-2"></div>
                <div className="v3-blob v3-blob-3"></div>
            </div>

            {/* HERO SECTION */}
            <section className="about-v3-hero">
                <div className="container">
                    <div className="v3-hero-inner">
                        <div className="v3-hero-badge">
                            <span className="v3-badge-dot"></span>
                            Our Mission
                        </div>
                        <h1 className="v3-hero-title">
                            The Magical World of
                            <span className="v3-title-highlight"> Digital Creators</span>
                        </h1>
                        <p className="v3-hero-subtitle">
                            Kido Dev is where imagination meets logic. We are building a vibrant universe
                            where every child becomes a creator, an innovator, and a digital explorer.
                            No boring lessons, just pure magic and learning.
                        </p>
                        <div className="v3-hero-stats">
                            <div className="v3-stat-pill">
                                <strong>3</strong> Learning Levels
                            </div>
                            <div className="v3-stat-pill">
                                <strong>30+</strong> Projects
                            </div>
                            <div className="v3-stat-pill">
                                <strong>AI</strong> Powered
                            </div>
                        </div>
                    </div>
                </div>
                <div className="v3-hero-wave">
                    <svg viewBox="0 0 1440 80" preserveAspectRatio="none" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M0,40 C360,80 1080,0 1440,40 L1440,80 L0,80 Z" fill="#ffffff" fillOpacity="0.06" />
                    </svg>
                </div>
            </section>

            {/* OUR STORY SECTION */}
            <section className="v3-story-section">
                <div className="container">
                    <div className="v3-story-card">
                        <div className="v3-story-label">The Story So Far</div>
                        <h2 className="v3-section-title">
                            How the <span>Magic</span> Began
                        </h2>
                        <div className="v3-story-highlight">
                            Kido Dev wasn't born in a boardroom — it was born in the heart of a dream
                            to make the digital world accessible, colorful, and fun for every child.
                        </div>
                        <p className="v3-story-text">
                            We noticed that technology was becoming a barrier instead of a bridge. Dry manuals
                            and complex terminology were scaring away the most creative minds. We decided to
                            change that by combining the science of learning with the art of play.
                        </p>
                        <p className="v3-story-text">
                            What started as a small spark has grown into a massive movement of young creators.
                            We've stripped away complexity and replaced it with color, logic, and joy. Our journey
                            is fueled by the smiles of children who realize they can build anything they imagine.
                        </p>
                    </div>
                </div>
            </section>

            {/* MISSION STATEMENT SECTION */}
            <section className="v3-mission-statement-section">
                <div className="container">
                    <div className="v3-mission-statement-content">
                        <div className="v3-mission-label">Our Purpose</div>
                        <h2 className="v3-section-title">Mission <span>Statement</span></h2>
                        <p className="v3-mission-text">
                            Our mission is to empower the next generation of digital creators by democratizing
                            high-quality technology education through play. We are committed to building a
                            future where every child, regardless of background, has the logic, creativity,
                            and skills to thrive in an AI-driven world.
                        </p>

                        <div className="v3-sdg-intro">
                            <div className="v3-sdg-badge">Global Commitment</div>
                            <h3 className="v3-sdg-title">Aligning with UN Sustainable Development Goals</h3>
                            <p className="v3-sdg-desc">
                                We don't just teach code; we build a better world. Kido Dev is proudly
                                aligned with the United Nations SDGs to ensure inclusive and equitable
                                quality education for all.
                            </p>
                        </div>

                        <div className="v3-sdg-grid">
                            {detailedSDGs.map((sdg, index) => (
                                <div key={index} className="v3-sdg-card" style={{ '--sdg-color': sdg.color }}>
                                    <div className="v3-sdg-num">{sdg.num}</div>
                                    <h4 className="v3-sdg-card-title">{sdg.title}</h4>
                                    <p className="v3-sdg-card-detail">{sdg.detail}</p>
                                    <ul className="v3-sdg-impacts">
                                        {sdg.impacts.map((impact, i) => (
                                            <li key={i}>{impact}</li>
                                        ))}
                                    </ul>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </section>

            {/* MISSION SECTION */}
            <section className="v3-mission-section">
                <div className="container">
                    <div className="v3-section-header">
                        <div className="v3-section-label">What We Stand For</div>
                        <h2 className="v3-section-title">Our Core <span>Foundations</span></h2>
                        <p className="v3-section-sub">
                            Fostering logic, creativity, and global citizenship through intentional play.
                        </p>
                    </div>
                    <div className="v3-mission-grid">
                        {missionPoints.map((point, index) => (
                            <div
                                key={index}
                                className="v3-mission-card"
                                style={{ '--card-color': point.color, '--card-bg': point.bg }}
                            >
                                <h3 className="v3-mission-title" style={{ color: point.color }}>
                                    {point.title}
                                </h3>
                                <p className="v3-mission-desc">{point.desc}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </section>


            {/* CTA SECTION */}
            <section className="v3-cta-section">
                <div className="container">
                    <div className="v3-cta-card">
                        <div className="v3-cta-glow"></div>
                        <h2 className="v3-cta-title">
                            Join the <span>Magical</span> Revolution
                        </h2>
                        <p className="v3-cta-desc">
                            Let's build a brighter, more colorful, and more empowered future together.
                            Step into the world where every child is a digital creator.
                        </p>
                        <Link to="/auth" className="v3-cta-btn">
                            Get Started Today
                        </Link>
                    </div>
                </div>
            </section>
        </div>
    );
};

export default AboutUs;

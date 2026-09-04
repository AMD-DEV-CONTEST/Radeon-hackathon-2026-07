import React from 'react';

const mentors = [
    {
        name: "Dr.  Muhammad Zeeshan Asaf",
        role: "Lead Product Mentor",
        bio: "PhD NUST | Expert in Algorithmic Education & Child Psychology. Guiding the roadmap of Kido Dev.",
        color: "#1E293B",
        initials: "MZA"
    },
    {
        name: "M. Muteeb Ramzan",
        role: "Founder Code Nexus",
        bio: "Chief Architect & Visionary. Bridging the gap between elite technology and young minds.",
        color: "#2563EB",
        initials: "MR"
    }
];

const productTeam = [
    {
        name: "Laiba Sarwar",
        role: "Founder & CEO",
        bio: "Leading the vision of Kido Dev to empower the next generation of female innovators.",
        color: "#EC4899",
        initials: "LS",
        isLead: true
    },
    {
        name: "Maria Noor",
        role: "Technical Lead",
        bio: "Engineering high-performance interactive modules and magical coding experiences.",
        color: "#A855F7",
        initials: "MN",
        isLead: true
    },
    {
        name: "Laiba Noor",
        role: "Business Developer",
        bio: "Driving the growth and global partnerships of Kido Dev to reach every curious young mind.",
        color: "#0EA5E9",
        initials: "LN",
        isLead: true
    }
];

const Team = () => {
    return (
        <section className="team-section pt-4" id="team">
            <div className="container position-relative z-2">

                {/* SECTION 1: THE MENTORS */}
                <div className="section-label-pro text-center mb-4">THE MENTORS</div>
                <div className="row g-4 justify-content-center mb-5">
                    {mentors.map((member, index) => (
                        <div key={index} className="col-lg-6 col-md-6 mb-4">
                            <div className="wizard-pro-card mentor-card shadow-lg mx-auto" style={{ maxWidth: '600px' }}>
                                <div className="pro-card-avatar" style={{
                                    backgroundColor: member.color,
                                    width: '130px',
                                    height: '130px',
                                    fontSize: '3rem',
                                    border: '4px solid white'
                                }}>
                                    {member.initials}
                                </div>
                                <div className="pro-card-content">
                                    <h3 className="pro-name" style={{ fontSize: '2rem' }}>{member.name}</h3>
                                    <div className="pro-role">{member.role}</div>
                                    <p className="pro-bio">{member.bio}</p>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>

                <div className="pro-divider"></div>

                {/* SECTION 2: THE WOMEN-LED PRODUCT TEAM */}
                <div className="text-center mt-5 mb-5">
                    <span className="women-lead-badge">A WOMEN-LED INNOVATION</span>
                    <h2 className="display-4 fw-bold text-dark mt-3">The Product <span className="text-pink">Wizards</span></h2>
                    <p className="pro-subtitle-pink mx-auto mt-3" style={{ maxWidth: '700px' }}>
                        Empowering the next generation of female innovators. Our mission is to bridge the tech gap by creating an inclusive,
                        imaginative learning world led by a team of visionary women architects.
                    </p>
                </div>

                <div className="row g-4 justify-content-center">
                    {productTeam.map((member, index) => (
                        <div key={index} className="col-lg-6 col-md-12 mb-3">
                            <div className="wizard-pro-card team-card">
                                {member.isLead && <div className="women-tag">WOMEN LEAD</div>}
                                <div className="pro-card-avatar" style={{
                                    backgroundColor: member.color,
                                    width: '110px',
                                    height: '110px',
                                    fontSize: '2rem'
                                }}>
                                    {member.initials}
                                </div>
                                <div className="pro-card-content">
                                    <h3 className="pro-name">{member.name}</h3>
                                    <div className="pro-role">{member.role}</div>
                                    <p className="pro-bio">{member.bio}</p>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>

            </div>
        </section>
    );
};

export default Team;

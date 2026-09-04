import React from 'react';
import wizardSlate from '../assets/wizard_img.jpg';

const HowItWorks = () => {
    const steps = [
        {
            num: "1",
            title: "Pick a Mission",
            text: "Choose a game you want to build. From 'Flappy Bird' clones to 'Space Invaders'.",
            numColor: "#FF5F5F" // Coral Red
        },
        {
            num: "2",
            title: "Follow the Light",
            text: "Our magic overlay dims the screen and highlights exactly which block to grab.",
            numColor: "#4FB5FF" // Sky Blue
        },
        {
            num: "3",
            title: "Snap & Learn",
            text: "Drag the block. If it's right, it snaps with a satisfying click and you get XP!",
            numColor: "#67E032" // Lime Green
        },
        {
            num: "4",
            title: "Play Just Built",
            text: "Hit the Green Flag. You just built a real working game. Now share it with friends.",
            numColor: "#E0329E" // Magenta
        }
    ];

    return (
        <section id="how-it-works" className="how-it-works-section">
            <div className="container">
                {/* COLOURFUL HEADER - SENIOR UI PASS */}
                <div className="text-center mb-5 pb-lg-5">
                    <h2 className="how-title-big mb-3">
                        <span className="text-grad-multicolor">How to Become a</span> <br />
                        <span className="text-wizard-gradient">Coding Wizard</span>
                    </h2>
                    <p className="lead-ui text-muted mx-auto fw-600 mt-2" style={{ maxWidth: '700px' }}>
                        Forget boring lectures. In Kido Dev, you learn by doing.
                    </p>
                </div>

                {/* CONNECTED ROADMAP - HEAVY UI PASS */}
                <div className="roadmap-path-container">
                    {/* THE MAGICAL CONNECTING LINE */}
                    <div className="roadmap-magic-line"></div>

                    <div className="row g-4 position-relative z-2">
                        {steps.map((step, i) => (
                            <div className="col-lg-3 col-md-6" key={i}>
                                <div className="heavy-roadmap-card">
                                    <div className="heavy-card-node" style={{ backgroundColor: step.numColor }}>
                                        {step.num}
                                    </div>
                                    <div className="heavy-card-body">
                                        <h4 className="heavy-card-title">{step.title}</h4>
                                        <p className="heavy-card-text">{step.text}</p>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </section>
    );
};

export default HowItWorks;


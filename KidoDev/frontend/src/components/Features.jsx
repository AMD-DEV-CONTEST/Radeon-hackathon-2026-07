import React from 'react';
import { Link } from 'react-router-dom';
import video1 from '../assets/video1.mp4';
import video2 from '../assets/video2.mp4';
import video3 from '../assets/video3.mp4';
import { FaRocket, FaRobot, FaGamepad } from 'react-icons/fa';

const Features = () => {
    return (
        <section id="features" className="features-section">
            <div className="container">
                {/* Section Header */}
                <div className="features-header text-center mb-5">
                    <span className="badge-pill-shine">WHY Kido Dev?</span>
                    <h2 className="display-4 fw-bold mt-3 mb-4">
                        Learning <span className="text-grad-yellow">Reimagined</span> <br />
                        <span className="text-highlight">For Gen Alpha</span>
                    </h2>
                </div>

                {/* The Magic Bento Grid */}
                <div className="bento-grid mt-5">

                    {/* Block 1: The Hero Feature (Wide) - Video Background */}
                    <div className="magic-block block-wide magic-block--video">
                        <div className="magic-block-video-outer">
                            <video autoPlay muted loop playsInline className="magic-block-video">
                                <source src={video2} type="video/mp4" />
                            </video>
                            <div className="magic-block-overlay"></div>
                        </div>
                        <div className="block-content">
                            <div className="block-icon-circle bg-red-glass">
                                <FaRobot />
                            </div>
                            <h3 className="block-title">AI Agent <br /> Enabled Platform</h3>
                            <p className="block-desc">
                                Learn the base of coding from the ground up and master it perfectly with your personal AI mentor.
                            </p>
                        </div>
                    </div>

                    {/* Block 2: The Vertical Feature (Tall) - Video Background */}
                    <div className="magic-block block-tall magic-block--video">
                        <div className="magic-block-video-outer">
                            <video autoPlay muted loop playsInline className="magic-block-video">
                                <source src={video1} type="video/mp4" />
                            </video>
                            <div className="magic-block-overlay"></div>
                        </div>
                        <div className="block-content">
                            <div className="block-icon-circle bg-blue-glass">
                                <FaRocket />
                            </div>
                            <h3 className="block-title">Visual Block <br /> Masterclass</h3>
                            <p className="block-desc">
                                Snap together colorful blocks to create code. It's like building with LEGOs, but for computer programs!
                            </p>
                            <Link to="/levels" className="btn btn-sm btn-white-glass mt-auto text-decoration-none">Unlock Power</Link>
                        </div>
                    </div>

                    {/* Block 3: The Standard Feature - Video Background */}
                    <div className="magic-block block-standard magic-block--video">
                        <div className="magic-block-video-outer">
                            <video autoPlay muted loop playsInline className="magic-block-video">
                                <source src={video3} type="video/mp4" />
                            </video>
                            <div className="magic-block-overlay"></div>
                        </div>
                        <div className="block-content">
                            <div className="block-icon-circle bg-green-glass">
                                <FaGamepad />
                            </div>
                            <h3 className="block-title">Create Games <br /> & Local Stories</h3>
                            <p className="block-desc">
                                Design your own characters (Sprites), animate them, and share your adventures with the whole world.
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    );
};

export default Features;



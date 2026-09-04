import React, { useState, useEffect } from 'react';
import { supabase } from '../utils/supabaseClient';

const COLORS = [
    { bg: '#EFF6FF', border: '#BFDBFE', dot: '#3B82F6', tag: '#1D4ED8' },
    { bg: '#F0FDF4', border: '#BBF7D0', dot: '#22C55E', tag: '#15803D' },
    { bg: '#FFF7ED', border: '#FED7AA', dot: '#F97316', tag: '#C2410C' },
    { bg: '#FDF4FF', border: '#E9D5FF', dot: '#A855F7', tag: '#7E22CE' },
    { bg: '#FFF1F2', border: '#FECDD3', dot: '#EF4444', tag: '#B91C1C' },
    { bg: '#F0F9FF', border: '#BAE6FD', dot: '#0EA5E9', tag: '#0369A1' },
];

const Syllabus = () => {
    const curriculum = [
        {
            level: 1,
            title: "Basic Logic & Coding Foundation",
            description: "Master the fundamentals of computational thinking through interactive block coding and visual logic puzzles.",
            topics: ["Sequential Thinking", "Pattern Recognition", "Loops & Repetition", "Conditional Logic (If/Else)", "Simple Variable Logic"],
            projects: [
                { title: "Fruit Slasher Logic" },
                { title: "Robo-Maze Runner" },
                { title: "Magical Music Maker" },
                { title: "Color Match Master" }
            ]
        },
        {
            level: 2,
            title: "Game Development & Creativity",
            description: "Step into the world of game mechanics, physics engines, and creating interactive stories that come to life.",
            topics: ["Sprite Animation", "Physics & Gravity", "Coordinate Systems", "Event Handlers", "Score & Level Persistence"],
            projects: [
                { title: "Space Explorer 3000" },
                { title: "Ultimate Dino Jump" },
                { title: "Quest for the Crystal" },
                { title: "Neon Paddle Battle" }
            ]
        },
        {
            level: 3,
            title: "Web Engineering & Style",
            description: "Learn how the internet works by building your very own professional websites and interactive web applications.",
            topics: ["HTML5 Structure", "CSS3 Art & Layouts", "JavaScript Basics", "DOM Manipulation", "Responsive Design Mastery"],
            projects: [
                { title: "Hero Personal Web" },
                { title: "Magic Calculator 앱" },
                { title: "Weather Wizard Pro" },
                { title: "Dynamic Task Board" }
            ]
        },
        {
            level: 4,
            title: "Advanced AI & Software Engineering",
            description: "Deep dive into artificial intelligence, complex data structures, and advanced software architectural patterns.",
            topics: ["Machine Learning Basics", "Data Structures Fundamentals", "API Integration", "Functional Programming", "Ethical AI Design"],
            projects: [
                { title: "ChatBot Friend AI" },
                { title: "Smart Tic-Tac-Toe" },
                { title: "Facial Mood Reader" },
                { title: "Stock Market Tracker" }
            ]
        }
    ];

    return (
        <section id="syllabus" className="syllabus-section">
            <div className="syllabus-bg-glow"></div>
            
            <div className="container position-relative z-2">
                {/* SPECTACULAR COLOURFUL HEADER */}
                <div className="syllabus-header-zone text-center mb-5 pb-lg-5">
                    <span className="syllabus-tag">THE CHAMPIONS CURRICULUM</span>
                    <h2 className="syllabus-title-main">Structured Learning Path</h2>
                    <p className="syllabus-lead-pro mx-auto">
                        A step-by-step journey from basic logic to advanced coding — designed for young minds.
                    </p>
                </div>

                {/* 2 CARDS PER ROW ON BIG SCREEN | 1 PER ROW ON MOBILE */}
                <div className="row g-4 justify-content-center">
                    {curriculum.map((cls, index) => {
                        const c = COLORS[index % COLORS.length];
                        return (
                            <div className="col-lg-6 col-md-6 col-12" key={index}>
                                <div className="syllabus-card active" 
                                     style={{ backgroundColor: c.bg, borderColor: c.border }}>
                                    
                                    <div className="syllabus-card-header" style={{ borderColor: c.dot }}>
                                        <div className="level-badge" style={{ backgroundColor: c.dot }}>
                                            {cls.level}
                                        </div>
                                        <div className="flex-grow-1">
                                            <h3 className="level-name">Level {cls.level}</h3>
                                            <div className="level-count">{cls.projects?.length || 0} Lessons</div>
                                        </div>
                                    </div>
                                    
                                    <div className="syllabus-card-body p-4 pt-0">
                                        <div className="syllabus-group">
                                            <div className="group-label" style={{ color: c.tag }}>Topics Covered</div>
                                            <ul className="group-list">
                                                {(cls.topics || []).map((t, i) => (
                                                    <li key={i}>{t}</li>
                                                ))}
                                            </ul>
                                        </div>

                                        <div className="syllabus-group mt-3">
                                            <div className="group-label" style={{ color: c.tag }}>All Projects</div>
                                            <div className="project-tags">
                                                {(cls.projects || []).map((p, i) => (
                                                    <span key={i} className="mini-tag" style={{ background: '#fff', color: c.tag, borderColor: c.border }}>
                                                        {p.title}
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </section>
    );
};

export default Syllabus;

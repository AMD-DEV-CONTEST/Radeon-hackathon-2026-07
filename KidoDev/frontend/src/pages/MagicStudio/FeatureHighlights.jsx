import React from 'react';
import { FaRedo, FaCheckCircle, FaProjectDiagram, FaBrain } from 'react-icons/fa';

const HIGHLIGHTS = [
    {
        title: 'Loop Studio',
        description: 'Collection of repeat, forever, and wait blocks for motion loops, animation timing, and choreography.',
        icon: FaRedo,
    },
    {
        title: 'Conditional Logic',
        description: 'If / if-else and boolean operators help you build responsive games that react to choices.',
        icon: FaCheckCircle,
    },
    {
        title: 'Complete Scratch Toolbox',
        description: 'Motion, Looks, Sound, Pen, Sensing, Variables, Lists, and My Blocks are all accessible from the start.',
        icon: FaProjectDiagram,
    },
    {
        title: 'Studio Intelligence',
        description: 'AI tutor guidance, sprite controls, and rich asset libraries elevate every project, not just for kids.',
        icon: FaBrain,
    },
];

export function FeatureHighlights() {
    return (
        <div style={styles.container}>
            <div style={styles.grid}>
                {HIGHLIGHTS.map(item => {
                    const Icon = item.icon;
                    return (
                        <article key={item.title} style={styles.card}>
                            <div style={styles.icon}>
                                <Icon />
                            </div>
                            <div>
                                <h4 style={styles.title}>{item.title}</h4>
                                <p style={styles.description}>{item.description}</p>
                            </div>
                        </article>
                    );
                })}
            </div>
        </div>
    );
}

const styles = {
    container: {
        padding: '12px 24px 10px',
        background: '#eef2ff',
        borderBottom: '1px solid #dbeafe',
        boxShadow: '0 20px 50px rgba(79, 70, 229, 0.08)',
        zIndex: 2,
    },
    grid: {
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
        gap: 12,
    },
    card: {
        display: 'flex',
        gap: 12,
        alignItems: 'flex-start',
        padding: 10,
        borderRadius: 14,
        background: '#fff',
        border: '1px solid #e0e7ff',
        boxShadow: '0 10px 30px rgba(15, 23, 42, 0.08)',
    },
    icon: {
        width: 38,
        height: 38,
        borderRadius: 12,
        background: 'rgba(79, 70, 229, 0.12)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#4338ca',
        fontSize: 16,
    },
    title: {
        margin: 0,
        fontSize: 13,
        fontWeight: 700,
        color: '#1e1b4b',
    },
    description: {
        margin: '6px 0 0',
        fontSize: 11,
        color: '#475569',
        lineHeight: 1.4,
    },
};

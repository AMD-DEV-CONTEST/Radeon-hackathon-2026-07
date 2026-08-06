import React, { useEffect } from 'react';
import { useNavigate, useLocation, useParams } from 'react-router-dom';

export default function LevelCompletePage() {
    const navigate = useNavigate();
    const location = useLocation();
    const { lessonId } = useParams();

    // Get score/XP/badges from navigate state
    const data = location.state || {
        score: 0,
        feedback: 'No data available',
        xpEarned: 0,
        totalXp: 0,
        newLevel: 'Bronze',
        levelUp: false,
        newBadgeLabels: [],
        isFirstTime: false
    };

    // Auto redirect back to classes page after 5 seconds
    useEffect(() => {
        const timer = setTimeout(() => {
            navigate('/classes');
        }, 5000);
        return () => clearTimeout(timer);
    }, [navigate]);

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100vh',
            background: 'linear-gradient(135deg,#1E3A5F,#312E81)',
            color: 'white',
            textAlign: 'center',
            padding: 40,
        }}>
            <h1>🎉 Level Complete!</h1>
            <p>Score: {data.score}</p>
            <p>XP Earned: {data.xpEarned} / Total XP: {data.totalXp}</p>
            <p>Level: {data.newLevel} {data.levelUp && '🚀 Level Up!'}</p>
            {data.newBadgeLabels?.length > 0 && (
                <p>🏆 Badges: {data.newBadgeLabels.join(', ')}</p>
            )}
            <p style={{ fontStyle: 'italic', marginTop: 20 }}>"{data.feedback}"</p>
            <p style={{ marginTop: 30 }}>Returning to Classes...</p>
        </div>
    );
}
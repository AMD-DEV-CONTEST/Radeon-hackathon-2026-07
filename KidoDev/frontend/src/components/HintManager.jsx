import React, { useState, useEffect } from "react";

export default function HintManager({ events }) {
    const [hintLevel, setHintLevel] = useState(0);
    const [lastHint, setLastHint] = useState(0);

    useEffect(() => {
        if (!events.length) return;

        const now = Date.now();
        if (now - lastHint < 10000) return; // 10s cooldown

        // Example: simple logic based on blocks added
        const lastEvent = events[events.length - 1];
        if (lastEvent.event_type === "block_added") {
            const nextLevel = Math.min(hintLevel + 1, 4);
            setHintLevel(nextLevel);
            setLastHint(now);
        }
    }, [events]);

    const hintColors = ["green", "blue", "orange", "red"];
    const hintMessages = [
        "Try thinking about motion blocks",
        "Check the block category",
        "Use the specific block here",
        "Watch the solution animation"
    ];

    return (
        <div style={{ padding: "10px", marginTop: "10px" }}>
            {hintLevel > 0 && (
                <div style={{ background: hintColors[hintLevel - 1], padding: "8px", borderRadius: "6px", color: "white" }}>
                    {hintMessages[hintLevel - 1]}
                </div>
            )}
        </div>
    );
}
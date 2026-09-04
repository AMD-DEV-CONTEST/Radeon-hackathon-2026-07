// src/utils/ws.js

let ws;

export const connectWebSocket = (studentId) => {
    try {
        // Use a placeholder or environment variable for the backend URL
        const backendUrl = import.meta.env.VITE_BACKEND_WS_URL || "ws://localhost:8000";
        ws = new WebSocket(backendUrl);

        ws.onopen = () => console.log("Connected to AI feedback server");
        ws.onclose = () => console.log("WebSocket connection closed");
        ws.onerror = (err) => {
            console.warn("WebSocket could not connect. AI feedback features will be limited.");
        };

        return ws;
    } catch (e) {
        console.error("Failed to initialize WebSocket:", e);
    }
};

export const sendEvent = (event) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(event));
    }
};
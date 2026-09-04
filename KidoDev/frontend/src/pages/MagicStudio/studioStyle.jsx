// studioStyles.js

// ============================================================
// STYLE OBJECT (ALL INLINE STYLES USED IN STUDIO)
// ============================================================

export const S = {
    // ── Root ───────────────────────────────────────────────
    root: {
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        background: "#F0F4FF",
        fontFamily: "Inter, sans-serif",
        overflow: "hidden",
    },

    // ── Top Bar ───────────────────────────────────────────
    bar: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "8px 16px",
        background: "linear-gradient(90deg,#4F46E5,#7C3AED)",
        borderBottom: "3px solid #3730A3",
        flexShrink: 0,
        boxShadow: "0 4px 20px rgba(79,70,229,.4)",
    },
    logo: { color: "#fff", fontWeight: 900, fontSize: 17, letterSpacing: "-0.5px" },
    badge: {
        background: "rgba(255,255,255,.22)",
        color: "#fff",
        fontSize: 11,
        fontWeight: 700,
        borderRadius: 20,
        padding: "3px 12px",
        border: "1px solid rgba(255,255,255,.4)",
        maxWidth: 180,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
    },
    btn: {
        padding: "6px 14px",
        borderRadius: 20,
        fontWeight: 700,
        fontSize: 12,
        border: "none",
        cursor: "pointer",
        boxShadow: "0 2px 8px rgba(0,0,0,.15)",
        transition: "all 0.2s ease",
    },
    select: {
        padding: "5px 8px",
        borderRadius: 10,
        border: "1px solid rgba(255,255,255,.4)",
        background: "rgba(255,255,255,.15)",
        color: "#fff",
        fontSize: 12,
        fontWeight: 700,
        cursor: "pointer",
    },

    // ── Layout ────────────────────────────────────────────
    body: { display: "flex", flex: 1, overflow: "hidden", minHeight: 0 },

    sidebar: {
        width: 230,
        background: "#fff",
        borderRight: "2px solid #E0E7FF",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        minHeight: 0,
    },
    stagePanel: {
        width: 460,
        background: "#fff",
        borderLeft: "2px solid #E0E7FF",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        overflowY: "auto",
    },

    stageCanvas: {
        width: "100%",
        height: 360,
        background: "#000",
        borderRadius: 12,
        marginTop: 10,
        cursor: "grab",
    },

    console: {
        flex: 1,
        background: "#111827",
        color: "#10B981",
        fontFamily: "monospace",
        fontSize: 12,
        padding: 10,
        overflowY: "auto",
        borderRadius: 12,
        marginTop: 10,
    },

    // ── Modals ───────────────────────────────────────────
    modalOverlay: {
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
    },
    modal: {
        background: "#fff",
        padding: 24,
        borderRadius: 20,
        width: 400,
        maxWidth: "90%",
        boxShadow: "0 25px 60px rgba(0,0,0,.25)",
        animation: "slideUp .3s ease",
    },

    // ── Tutor Bubble ─────────────────────────────────────
    tutorBubble: {
        position: "absolute",
        bottom: 20,
        right: 20,
        background: "#fff",
        borderRadius: 20,
        padding: 16,
        width: 260,
        boxShadow: "0 10px 30px rgba(0,0,0,.2)",
        animation: "slideUp .4s ease",
    },
    tutorAvatar: {
        width: 60,
        height: 60,
        borderRadius: "50%",
        background: "linear-gradient(135deg,#4F46E5,#7C3AED)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#fff",
        fontWeight: 900,
        fontSize: 22,
        marginBottom: 8,
        animation: "tutorFloat 3s ease-in-out infinite",
    },
    guidePointer: {
        position: "absolute",
        width: 50,
        height: 50,
        pointerEvents: "none",
        animation: "handPoint .8s infinite alternate",
    },
};

// ============================================================
// STYLE INJECTION (ANIMATIONS + GLOBAL FIXES)
// ============================================================

export function injectStudioStyles() {
    if (document.getElementById("magic-studio-styles")) return;

    const styleTag = document.createElement("style");
    styleTag.id = "magic-studio-styles";

    styleTag.innerHTML = `
    @keyframes tutorFloat {
      0% { transform: translateY(0px) rotate(0deg); }
      50% { transform: translateY(-10px) rotate(2deg); }
      100% { transform: translateY(0px) rotate(0deg); }
    }

    @keyframes slideUp {
      0% { transform: translateY(20px); opacity: 0; }
      100% { transform: translateY(0); opacity: 1; }
    }

    @keyframes handPoint {
      0% { transform: scale(1) translate(0,0); }
      100% { transform: scale(1.1) translate(5px,5px); }
    }

    @keyframes ping {
      0% { transform: translateX(-50%) scale(0.2); opacity: 1; }
      100% { transform: translateX(-50%) scale(1.3); opacity: 0; }
    }

    /* Scrollbar Styling */
    ::-webkit-scrollbar { width: 8px; }
    ::-webkit-scrollbar-thumb { background: #6366F1; border-radius: 10px; }
    ::-webkit-scrollbar-track { background: transparent; }
  `;

    document.head.appendChild(styleTag);
}
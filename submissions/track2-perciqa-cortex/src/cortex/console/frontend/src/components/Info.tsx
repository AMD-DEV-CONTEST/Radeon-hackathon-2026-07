import { useState, useId, useRef, useLayoutEffect } from "react";
import { createPortal } from "react-dom";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { GLOSSARY, type GlossaryKey } from "../data/glossary";

export function Info({ k }: { k: GlossaryKey }) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0, ax: 12, flip: false, measured: false });
  const g = GLOSSARY[k];
  const id = useId();
  if (!g) return null;

  useLayoutEffect(() => {
    if (!open || !btn.current || !pop.current) return;
    const a = btn.current.getBoundingClientRect();
    const p = pop.current.getBoundingClientRect();
    const gap = 8, m = 12, vw = innerWidth, vh = innerHeight;
    const flip = a.bottom + gap + p.height + m > vh;
    const top = flip ? a.top - gap - p.height : a.bottom + gap;
    const want = a.left + a.width / 2 - p.width / 2;
    const left = Math.min(Math.max(m, want), vw - p.width - m);
    const ax = Math.min(p.width - 12, Math.max(12, (a.left + a.width / 2) - left));
    setPos({ top, left, ax, flip, measured: true });
  }, [open]);

  const node = open && createPortal(
    <Box
      ref={pop}
      role="tooltip"
      id={id}
      data-flip={pos.flip || undefined}
      sx={{
        position: "fixed",
        zIndex: 9999,
        top: pos.top,
        left: pos.left,
        width: 268,
        p: "11px 13px 12px",
        borderRadius: "var(--r-md, 10px)",
        bgcolor: "var(--bg-peak, #242c3a)",
        border: "1px solid rgba(150,170,200,.16)",
        boxShadow: "0 1px 0 rgba(255,255,255,.04), 0 8px 24px -8px rgba(0,0,0,.7)",
        display: "flex",
        flexDirection: "column",
        gap: "6px",
        visibility: pos.measured ? "visible" : "hidden",
        animation: pos.measured ? "pop-in 0.14s cubic-bezier(.16,1,.3,1)" : "none",
        "@keyframes pop-in": {
          from: { opacity: 0, transform: "translateY(4px)" },
          to: { opacity: 1, transform: "translateY(0)" },
        },
        "& .arrow": {
          position: "absolute",
          width: 9,
          height: 9,
          bgcolor: "var(--bg-peak, #242c3a)",
          borderLeft: "1px solid rgba(150,170,200,.16)",
          borderTop: "1px solid rgba(150,170,200,.16)",
          left: pos.ax,
          ...(pos.flip
            ? { bottom: -5, transform: "translateX(-50%) rotate(225deg)" }
            : { top: -5, transform: "translateX(-50%) rotate(45deg)" }),
        },
      }}
    >
      <Box className="arrow" component="i" aria-hidden />
      <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 600, fontSize: "0.6875rem", letterSpacing: "0.05em", color: "#34d6c8" }}>
        {g.term}
      </Typography>
      <Typography sx={{ fontFamily: '"IBM Plex Sans", sans-serif', fontWeight: 400, fontSize: "0.78125rem", lineHeight: 1.5, color: "#c2cbda" }}>
        {g.plain}
      </Typography>
      {'so' in g && g.so && (
        <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 400, fontSize: "0.71875rem", lineHeight: 1.45, color: "#8a94a8", fontStyle: "normal", borderTop: "1px dashed rgba(150,170,200,.1)", pt: "6px" }}>
          {g.so}
        </Typography>
      )}
    </Box>,
    document.body
  );

  return (
    <Box component="span" sx={{ position: "relative", display: "inline-flex", verticalAlign: "middle", lineHeight: 1 }}>
      <Box
        ref={btn}
        component="button"
        aria-label={`Explain: ${g.term}`}
        aria-describedby={open ? id : undefined}
        onPointerEnter={() => setOpen(true)}
        onPointerLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={(e) => { e.stopPropagation(); e.preventDefault(); setOpen(o => !o); }}
        sx={{
          display: "inline-grid", placeItems: "center", width: 16, height: 16,
          color: "#8a94a8", borderRadius: "50%", cursor: "help",
          bgcolor: "transparent", border: "none", p: 0,
          transition: "color 0.14s cubic-bezier(.22,.61,.36,1)",
          "&:hover, &:focus-visible": { color: "#34d6c8", outline: "none" },
        }}
      >
        <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden>
          <circle cx="8" cy="8" r="6.6" fill="none" stroke="currentColor" strokeWidth="1.2" />
          <path d="M8 7.1v3.6M8 4.7v.02" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </Box>
      {node}
    </Box>
  );
}

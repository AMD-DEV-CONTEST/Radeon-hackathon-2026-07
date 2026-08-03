import { motion, useReducedMotion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { Upload, Brain, Sparkles, FileDown } from 'lucide-react';

const STEPS = [
  {
    id: '01',
    code: 'Upload Reality',
    label: '上传真实素材',
    icon: Upload,
    angle: -90, // top
  },
  {
    id: '02',
    code: 'AI Understand',
    label: '理解人物 / 音乐 / 场景',
    icon: Brain,
    angle: 0, // right
  },
  {
    id: '03',
    code: 'Create Visual',
    label: '生成视觉作品',
    icon: Sparkles,
    angle: 90, // bottom
  },
  {
    id: '04',
    code: 'Export Poster',
    label: '输出可发布海报',
    icon: FileDown,
    angle: 180, // left
  },
] as const;

export default function CreativePortal() {
  const reduceMotion = useReducedMotion();
  const [activeStep, setActiveStep] = useState(0);

  useEffect(() => {
    if (reduceMotion) return;
    const timer = window.setInterval(() => setActiveStep(step => (step + 1) % STEPS.length), 1800);
    return () => window.clearInterval(timer);
  }, [reduceMotion]);

  return (
    <div className="portal" aria-hidden="true">
      {/* Outermost ambient glow */}
      <div className="portal-ambient" />

      {/* Orbiting ring 1 (slow, large) */}
      <motion.div
        className="portal-ring portal-ring--a"
        animate={reduceMotion ? undefined : { rotate: 360 }}
        transition={{ duration: 60, ease: 'linear', repeat: Infinity }}
      >
        <span className="portal-tick" style={{ top: '4%', left: '50%' }} />
        <span className="portal-tick" style={{ top: '50%', right: '4%' }} />
        <span className="portal-tick" style={{ bottom: '4%', left: '50%' }} />
        <span className="portal-tick" style={{ top: '50%', left: '4%' }} />
      </motion.div>

      {/* Orbiting ring 2 (counter direction) */}
      <motion.div
        className="portal-ring portal-ring--b"
        animate={reduceMotion ? undefined : { rotate: -360 }}
        transition={{ duration: 38, ease: 'linear', repeat: Infinity }}
      />

      {/* Orbiting ring 3 (dashed, fastest) */}
      <motion.div
        className="portal-ring portal-ring--c"
        animate={reduceMotion ? undefined : { rotate: 360 }}
        transition={{ duration: 22, ease: 'linear', repeat: Infinity }}
      >
        <span className="portal-runner" />
      </motion.div>

      {/* Crosshair / targeting lines */}
      <div className="portal-crosshair" />

      {/* Core: brand mark + label */}
      <div className="portal-core">
        <motion.div
          className="portal-core-pulse"
          animate={reduceMotion ? undefined : { scale: [1, 1.18, 1], opacity: [0.55, 0.18, 0.55] }}
          transition={{ duration: 3.2, ease: 'easeInOut', repeat: Infinity }}
        />
        <motion.div
          className="portal-core-glyph"
          animate={reduceMotion ? undefined : { rotate: [0, 90, 180, 270, 360] }}
          transition={{ duration: 18, ease: 'linear', repeat: Infinity }}
        >
          <svg viewBox="0 0 100 100" width="100%" height="100%">
            <defs>
              <linearGradient id="pg" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#C8603D" />
                <stop offset="100%" stopColor="#e0784f" />
              </linearGradient>
            </defs>
            <polygon
              points="22,4 96,4 78,96 4,96"
              fill="url(#pg)"
            />
            <text
              x="50"
              y="62"
              textAnchor="middle"
              fontFamily="Archivo Black, sans-serif"
              fontSize="34"
              fill="#0D0E13"
            >
              P
            </text>
          </svg>
        </motion.div>
        <div className="portal-core-meta">
          <span>POSTER · LAB 01</span>
          <b>AI CREATION STUDIO</b>
        </div>
      </div>

      {/* Orbiting process steps */}
      {STEPS.map((s, i) => {
        const rad = (s.angle * Math.PI) / 180;
        const r = 42; // % of container
        const x = 50 + Math.cos(rad) * r;
        const y = 50 + Math.sin(rad) * r;
        const Icon = s.icon;
        return (
          <motion.div
            key={s.id}
            className={`portal-step ${activeStep === i ? 'is-active' : ''}`}
            style={{ left: `${x}%`, top: `${y}%` }}
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.4 + i * 0.18, duration: 0.6, ease: 'easeOut' }}
          >
            <div className="portal-step-id">{s.id}</div>
            <div className="portal-step-icon">
              <Icon size={14} />
            </div>
            <div className="portal-step-text">
              <b>{s.code}</b>
              <span>{s.label}</span>
            </div>
          </motion.div>
        );
      })}

      {/* Status feed at the bottom */}
      <div className="portal-feed">
        <span className="portal-feed-dot" />
        <span className="portal-feed-line">
          reality <i>·</i> understanding <i>·</i> creation <i>·</i> poster
        </span>
        <span className="portal-feed-meta">0{activeStep + 1} / 04 · ROCm · Live</span>
      </div>
    </div>
  );
}

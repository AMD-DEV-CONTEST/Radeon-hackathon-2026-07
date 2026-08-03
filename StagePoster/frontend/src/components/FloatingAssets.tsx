import { motion, useMotionValue, useReducedMotion, useSpring, useTransform, type MotionValue } from 'framer-motion';
import { useRef, type ReactNode } from 'react';
import { Disc3, Music2, Camera, Triangle, Circle, Star, Aperture, Radio } from 'lucide-react';

type AssetKind = 'photo' | 'logo' | 'note' | 'poster' | 'light' | 'grain' | 'icon';

type Asset = {
  id: string;
  kind: AssetKind;
  top: string; // % of container
  left: string; // % of container
  size: number; // px
  rotate: number; // deg initial
  delay: number;
  duration: number;
  drift: number; // px
  depth: number; // 0..1 used for parallax
  content: ReactNode;
  className?: string;
};

const ASSETS: Asset[] = [
  // Band photo fragment (1) — duotone silhouette
  {
    id: 'photo-a',
    kind: 'photo',
    top: '6%',
    left: '12%',
    size: 130,
    rotate: -8,
    delay: 0,
    duration: 9,
    drift: 10,
    depth: 0.35,
    content: (
      <svg viewBox="0 0 100 130" width="100%" height="100%">
        <defs>
          <linearGradient id="phA" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#C8603D" stopOpacity="0.85" />
            <stop offset="100%" stopColor="#1a0d08" stopOpacity="0.95" />
          </linearGradient>
        </defs>
        <rect width="100" height="130" fill="url(#phA)" />
        <circle cx="50" cy="48" r="16" fill="#0D0E13" opacity="0.9" />
        <path
          d="M22 130 C22 90, 78 90, 78 130 Z"
          fill="#0D0E13"
          opacity="0.9"
        />
        <rect width="100" height="3" y="6" fill="#f0ebe0" opacity="0.4" />
        <text
          x="6"
          y="124"
          fontFamily="Archivo Black"
          fontSize="6"
          fill="#f0ebe0"
          opacity="0.75"
        >
          LIVE · 28.10
        </text>
      </svg>
    ),
  },
  // Band photo fragment (2) — guitarist silhouette
  {
    id: 'photo-b',
    kind: 'photo',
    top: '68%',
    left: '8%',
    size: 110,
    rotate: 6,
    delay: 0.4,
    duration: 11,
    drift: 12,
    depth: 0.5,
    content: (
      <svg viewBox="0 0 100 130" width="100%" height="100%">
        <defs>
          <linearGradient id="phB" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#7a3422" stopOpacity="0.95" />
            <stop offset="100%" stopColor="#0D0E13" stopOpacity="1" />
          </linearGradient>
        </defs>
        <rect width="100" height="130" fill="url(#phB)" />
        <rect width="100" height="1.5" y="0" fill="#C8603D" opacity="0.6" />
        <circle cx="50" cy="44" r="13" fill="#0D0E13" />
        <rect x="46" y="56" width="8" height="40" fill="#0D0E13" />
        <rect x="30" y="74" width="40" height="3" fill="#C8603D" />
      </svg>
    ),
  },
  // Logo plaque (1)
  {
    id: 'logo-a',
    kind: 'logo',
    top: '14%',
    left: '72%',
    size: 96,
    rotate: 9,
    delay: 0.2,
    duration: 8,
    drift: 8,
    depth: 0.4,
    content: (
      <div className="asset-logo">
        <span className="asset-logo-mark">
          <Triangle size={12} fill="#0D0E13" stroke="#0D0E13" />
        </span>
        <span className="asset-logo-text">MOONRUNNERS</span>
        <span className="asset-logo-sub">EST · 2024</span>
      </div>
    ),
  },
  // Logo plaque (2) — circular vinyl
  {
    id: 'logo-b',
    kind: 'logo',
    top: '70%',
    left: '76%',
    size: 104,
    rotate: -12,
    delay: 0.5,
    duration: 10,
    drift: 10,
    depth: 0.55,
    content: (
      <div className="asset-logo asset-logo--vinyl">
        <Disc3 size={78} stroke="#0D0E13" />
        <span>SIDE A · 33⅓ RPM</span>
      </div>
    ),
  },
  // Music note
  {
    id: 'note-a',
    kind: 'note',
    top: '30%',
    left: '82%',
    size: 32,
    rotate: 18,
    delay: 0.1,
    duration: 6,
    drift: 6,
    depth: 0.25,
    content: <Music2 size={32} stroke="#C8603D" />,
  },
  {
    id: 'note-b',
    kind: 'note',
    top: '78%',
    left: '38%',
    size: 26,
    rotate: -22,
    delay: 0.6,
    duration: 7,
    drift: 5,
    depth: 0.3,
    content: <Music2 size={26} stroke="#e0784f" />,
  },
  // Poster fragment
  {
    id: 'poster-a',
    kind: 'poster',
    top: '42%',
    left: '2%',
    size: 120,
    rotate: 14,
    delay: 0.3,
    duration: 12,
    drift: 14,
    depth: 0.6,
    content: (
      <svg viewBox="0 0 80 110" width="100%" height="100%">
        <rect width="80" height="110" fill="#0D0E13" />
        <rect x="6" y="6" width="68" height="98" fill="none" stroke="#C8603D" strokeWidth="0.6" />
        <text
          x="40"
          y="36"
          textAnchor="middle"
          fontFamily="Archivo Black"
          fontSize="9"
          fill="#f0ebe0"
          letterSpacing="0.5"
        >
          NEON
        </text>
        <text
          x="40"
          y="48"
          textAnchor="middle"
          fontFamily="Archivo Black"
          fontSize="9"
          fill="#C8603D"
          letterSpacing="0.5"
        >
          DRIFT
        </text>
        <line x1="10" y1="58" x2="70" y2="58" stroke="#C8603D" strokeWidth="0.3" />
        <text
          x="40"
          y="72"
          textAnchor="middle"
          fontFamily="Inter"
          fontSize="4"
          fill="#7a7567"
        >
          2026 · SHANGHAI
        </text>
        <circle cx="40" cy="90" r="6" fill="none" stroke="#C8603D" strokeWidth="0.4" />
        <circle cx="40" cy="90" r="2" fill="#C8603D" />
      </svg>
    ),
  },
  // Camera film
  {
    id: 'film-a',
    kind: 'icon',
    top: '4%',
    left: '46%',
    size: 30,
    rotate: 0,
    delay: 0.15,
    duration: 6,
    drift: 4,
    depth: 0.2,
    content: <Camera size={22} stroke="#f0ebe0" />,
  },
  // Aperture
  {
    id: 'ap-a',
    kind: 'icon',
    top: '88%',
    left: '52%',
    size: 32,
    rotate: 0,
    delay: 0.7,
    duration: 5,
    drift: 3,
    depth: 0.18,
    content: <Aperture size={26} stroke="#C8603D" />,
  },
  // Radio waves
  {
    id: 'radio-a',
    kind: 'icon',
    top: '46%',
    left: '90%',
    size: 30,
    rotate: 0,
    delay: 0.5,
    duration: 7,
    drift: 4,
    depth: 0.22,
    content: <Radio size={24} stroke="#e0784f" />,
  },
  // Star
  {
    id: 'star-a',
    kind: 'icon',
    top: '52%',
    left: '4%',
    size: 28,
    rotate: 0,
    delay: 0.25,
    duration: 8,
    drift: 5,
    depth: 0.26,
    content: <Star size={22} fill="#C8603D" stroke="#C8603D" />,
  },
  // Circle
  {
    id: 'circ-a',
    kind: 'icon',
    top: '24%',
    left: '40%',
    size: 18,
    rotate: 0,
    delay: 0.4,
    duration: 6,
    drift: 4,
    depth: 0.18,
    content: <Circle size={14} fill="#f0ebe0" stroke="#f0ebe0" />,
  },
  // Light flare (top right)
  {
    id: 'light-a',
    kind: 'light',
    top: '8%',
    left: '60%',
    size: 220,
    rotate: 0,
    delay: 0,
    duration: 0,
    drift: 0,
    depth: 0.1,
    content: <div className="asset-flare" />,
  },
  // Light flare (bottom left)
  {
    id: 'light-b',
    kind: 'light',
    top: '70%',
    left: '30%',
    size: 260,
    rotate: 0,
    delay: 0,
    duration: 0,
    drift: 0,
    depth: 0.1,
    content: <div className="asset-flare asset-flare--alt" />,
  },
  // Film grain strip
  {
    id: 'grain-a',
    kind: 'grain',
    top: '38%',
    left: '24%',
    size: 64,
    rotate: -22,
    delay: 0.6,
    duration: 9,
    drift: 6,
    depth: 0.3,
    content: (
      <div className="asset-grain">
        {Array.from({ length: 16 }).map((_, i) => (
          <span key={i} style={{ animationDelay: `${i * 0.08}s` }} />
        ))}
      </div>
    ),
  },
  {
    id: 'grain-b',
    kind: 'grain',
    top: '56%',
    left: '66%',
    size: 50,
    rotate: 30,
    delay: 0.8,
    duration: 8,
    drift: 5,
    depth: 0.25,
    content: (
      <div className="asset-grain">
        {Array.from({ length: 12 }).map((_, i) => (
          <span key={i} style={{ animationDelay: `${i * 0.1}s` }} />
        ))}
      </div>
    ),
  },
];

export default function FloatingAssets() {
  const containerRef = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();
  const mx = useMotionValue(0);
  const my = useMotionValue(0);
  const gather = useMotionValue(0);
  // smooth values
  const smx = useSpring(mx, { stiffness: 60, damping: 18 });
  const smy = useSpring(my, { stiffness: 60, damping: 18 });
  const gathered = useSpring(gather, {stiffness: 72, damping: 18});

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const cx = (e.clientX - rect.left) / rect.width - 0.5;
    const cy = (e.clientY - rect.top) / rect.height - 0.5;
    mx.set(cx * 2);
    my.set(cy * 2);
  }

  function onLeave() {
    mx.set(0);
    my.set(0);
    gather.set(0);
  }

  return (
    <div
      ref={containerRef}
      className="floating-assets"
      onMouseMove={onMove}
      onMouseEnter={() => gather.set(reduceMotion ? 0 : 1)}
      onMouseLeave={onLeave}
      aria-hidden="true"
    >
      <span className="floating-assets-hint">MOVE TO ASSEMBLE · REALITY → VISUAL</span>
      {ASSETS.map((a) => (
        <FloatingOne key={a.id} asset={a} smx={smx} smy={smy} gathered={gathered} reduceMotion={Boolean(reduceMotion)} />
      ))}
    </div>
  );
}

function FloatingOne({
  asset,
  smx,
  smy,
  gathered,
  reduceMotion,
}: {
  asset: Asset;
  smx: MotionValue<number>;
  smy: MotionValue<number>;
  gathered: MotionValue<number>;
  reduceMotion: boolean;
}) {
  const depth = asset.depth;
  // Parallax translation range in px
  const range = 60 * depth;
  const originX = Number.parseFloat(asset.left);
  const originY = Number.parseFloat(asset.top);
  const gatherX = (50 - originX) * 2.15;
  const gatherY = (50 - originY) * 2.15;
  const x = useTransform([smx, gathered], (values) => {
    const [mouse, focus] = values as number[];
    return mouse * range + gatherX * focus;
  });
  const y = useTransform([smy, gathered], (values) => {
    const [mouse, focus] = values as number[];
    return mouse * range + gatherY * focus;
  });
  const rotate = useTransform(smx, (v) => v * 6 * depth);
  const scale = useTransform(gathered, [0, 1], [1, asset.kind === 'light' ? 0.8 : 0.9]);

  // Float animation (gentle Y oscillation)
  return (
    <motion.div
      className={`floating-asset floating-asset--${asset.kind} ${asset.className ?? ''}`}
      style={{
        top: asset.top,
        left: asset.left,
        width: asset.size,
        height:
          asset.kind === 'photo' || asset.kind === 'poster' || asset.kind === 'logo'
            ? asset.size * 1.05
            : asset.size,
        x,
        y,
        rotate,
        scale,
        zIndex: Math.round(depth * 10),
      }}
    >
      <motion.div
        className="floating-asset-inner"
        animate={
          !reduceMotion && asset.drift > 0
            ? {
                y: [0, -asset.drift, 0, asset.drift, 0],
                rotate: [asset.rotate, asset.rotate + 2, asset.rotate, asset.rotate - 2, asset.rotate],
              }
            : { rotate: [0, 360] }
        }
        transition={
          asset.kind === 'light'
            ? { duration: 14, repeat: Infinity, ease: 'linear' }
            : {
                duration: asset.duration,
                repeat: Infinity,
                ease: 'easeInOut',
                delay: asset.delay,
              }
        }
        style={{ transformOrigin: 'center' }}
      >
        {asset.content}
      </motion.div>
    </motion.div>
  );
}

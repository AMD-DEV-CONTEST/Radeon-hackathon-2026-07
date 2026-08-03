import type { PosterCase } from '../data/posters';

// Inline SVG thumbnail generator. Each "motif" produces a distinct
// on-brand composition so cards look like real generated posters
// without needing network images.
export default function PosterThumb({ poster }: { poster: PosterCase }) {
  const [bg, mid, accent] = poster.palette;
  return (
    <svg
      className="poster-thumb-svg"
      viewBox="0 0 400 600"
      preserveAspectRatio="xMidYMid slice"
      role="img"
      aria-label={`${poster.title} — ${poster.style}`}
    >
      <defs>
        <radialGradient id={`bg-${poster.id}`} cx="50%" cy="40%" r="65%">
          <stop offset="0%" stopColor={mid} />
          <stop offset="55%" stopColor={bg} />
          <stop offset="100%" stopColor="#05050B" />
        </radialGradient>
        <linearGradient id={`acc-${poster.id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={accent} stopOpacity="0.95" />
          <stop offset="100%" stopColor={accent} stopOpacity="0.25" />
        </linearGradient>
      </defs>

      <rect width="400" height="600" fill={`url(#bg-${poster.id})`} />

      {/* Grid overlay */}
      <g opacity="0.08" stroke="#fff" strokeWidth="0.5">
        {Array.from({ length: 9 }).map((_, i) => (
          <line key={`v${i}`} x1={i * 50} y1="0" x2={i * 50} y2="600" />
        ))}
        {Array.from({ length: 13 }).map((_, i) => (
          <line key={`h${i}`} x1="0" y1={i * 50} x2="400" y2={i * 50} />
        ))}
      </g>

      {renderMotif(poster)}

      {/* Bottom info bar */}
      <g fontFamily="Inter, sans-serif">
        <rect x="20" y="520" width="360" height="1" fill="#ffffff22" />
        <text x="20" y="548" fontSize="11" fontWeight="700" letterSpacing="2" fill="#cdb892">
          REAL DATA / REAL LOGO
        </text>
        <text x="380" y="548" fontSize="10" textAnchor="end" fill="#7a7567">
          {poster.year} · {poster.location.toUpperCase()}
        </text>
      </g>
    </svg>
  );
}

function renderMotif(p: PosterCase) {
  const [, , accent] = p.palette;
  const id = p.id;
  switch (p.motif) {
    case 'duel':
      return (
        <g>
          {/* Two facing silhouettes */}
          <path d="M70 480 L60 300 L100 220 L150 200 L180 240 L175 380 L150 480 Z"
                fill={accent} opacity="0.85" />
          <path d="M330 480 L340 300 L300 220 L250 200 L220 240 L225 380 L250 480 Z"
                fill="#f0ebe0" opacity="0.7" />
          {/* Crossed light beam */}
          <line x1="80" y1="250" x2="320" y2="250" stroke={accent} strokeWidth="1.5" opacity="0.6" />
        </g>
      );
    case 'solo':
      return (
        <g>
          <circle cx="200" cy="320" r="120" fill={`url(#acc-${id})`} opacity="0.55" />
          <path d="M200 200 L240 280 L235 460 L165 460 L160 280 Z"
                fill={accent} opacity="0.9" />
          <circle cx="200" cy="180" r="35" fill={accent} opacity="0.9" />
          <line x1="200" y1="460" x2="200" y2="500" stroke="#cdb892" strokeWidth="1.5" />
        </g>
      );
    case 'crowd':
      return (
        <g>
          {Array.from({ length: 24 }).map((_, i) => {
            const x = 30 + (i % 8) * 45;
            const h = 40 + ((i * 17) % 40);
            return (
              <rect
                key={i}
                x={x}
                y={500 - h}
                width="14"
                height={h}
                fill={i % 5 === 0 ? accent : '#1c1d24'}
                opacity={i % 5 === 0 ? 0.85 : 0.7}
              />
            );
          })}
          <ellipse cx="200" cy="290" rx="180" ry="18" fill={accent} opacity="0.25" />
        </g>
      );
    case 'orbit':
      return (
        <g>
          <ellipse cx="200" cy="320" rx="160" ry="160" fill="none" stroke={accent} strokeWidth="1" opacity="0.4" />
          <ellipse cx="200" cy="320" rx="120" ry="120" fill="none" stroke={accent} strokeWidth="1" opacity="0.3" transform="rotate(20 200 320)" />
          <ellipse cx="200" cy="320" rx="90" ry="90" fill="none" stroke={accent} strokeWidth="1" opacity="0.5" transform="rotate(-25 200 320)" />
          <circle cx="200" cy="320" r="42" fill={accent} opacity="0.9" />
          <circle cx="320" cy="260" r="6" fill={accent} />
          <circle cx="80" cy="380" r="4" fill="#f0ebe0" />
        </g>
      );
    case 'grid':
      return (
        <g>
          {Array.from({ length: 6 }).map((_, r) =>
            Array.from({ length: 6 }).map((_, c) => (
              <rect
                key={`${r}-${c}`}
                x={40 + c * 55}
                y={140 + r * 55}
                width="40"
                height="40"
                fill={(r + c) % 3 === 0 ? accent : 'transparent'}
                stroke={accent}
                strokeWidth="0.5"
                opacity={0.3 + ((r * c) % 5) * 0.12}
              />
            ))
          )}
        </g>
      );
    case 'wave':
      return (
        <g>
          <path d="M0 380 Q100 320 200 380 T400 380 L400 600 L0 600 Z" fill={accent} opacity="0.7" />
          <path d="M0 420 Q100 380 200 420 T400 420 L400 600 L0 600 Z" fill={accent} opacity="0.4" />
          <path d="M0 460 Q100 430 200 460 T400 460 L400 600 L0 600 Z" fill={accent} opacity="0.25" />
          <circle cx="320" cy="160" r="40" fill="#f0ebe0" opacity="0.85" />
          <line x1="0" y1="280" x2="400" y2="280" stroke="#f0ebe0" strokeWidth="0.5" opacity="0.4" />
        </g>
      );
  }
}

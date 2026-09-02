import { motion } from 'framer-motion';
import { posters, type PosterCase } from '../data/posters';

function StoriesArchive() {
  return (
    <section id="stories" className="stories-archive">
      <header className="stories-archive-head">
        <div>
          <small>Generated Stories · 03</small>
          <h2>
            Made inside <span>Poster</span>
          </h2>
        </div>
        <p>
          一组来自不同乐队、活动与音乐人的真实生成结果。
          <br />
          原始素材保留，主视觉由 Poster 重新构成。
        </p>
      </header>

      <div className="stories-archive-grid">
        {posters.slice(0, 6).map((p, i) => (
          <motion.figure
            key={p.id}
            className="story-card"
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-60px' }}
            transition={{ duration: 0.6, delay: (i % 3) * 0.12 }}
          >
            <div className="story-card-frame">
              <StoryArt poster={p} />
              <div className="story-card-meta">
                <span className="story-card-cat">{p.categoryLabel}</span>
                <span className="story-card-loc">
                  {p.location} · {p.year}
                </span>
              </div>
            </div>
            <figcaption>
              <b>{p.title}</b>
              <i>{p.style}</i>
            </figcaption>
          </motion.figure>
        ))}
      </div>
    </section>
  );
}

function StoryArt({ poster }: { poster: PosterCase }) {
  const [bg, mid, accent] = poster.palette;
  return (
    <svg viewBox="0 0 100 150" preserveAspectRatio="xMidYMid slice" className="story-art">
      <defs>
        <radialGradient id={`bg-${poster.id}`} cx="50%" cy="35%" r="60%">
          <stop offset="0%" stopColor={mid} />
          <stop offset="100%" stopColor={bg} />
        </radialGradient>
        <linearGradient id={`stripe-${poster.id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={accent} stopOpacity="0.8" />
          <stop offset="100%" stopColor={accent} stopOpacity="0.1" />
        </linearGradient>
      </defs>
      <rect width="100" height="150" fill={`url(#bg-${poster.id})`} />
      {poster.motif === 'duel' && (
        <>
          <path d="M10 12 L48 4 L46 50 L8 60 Z" fill={`url(#stripe-${poster.id})`} opacity="0.8" />
          <path d="M52 50 L92 4 L90 60 L54 50 Z" fill="#f0ebe0" opacity="0.4" />
        </>
      )}
      {poster.motif === 'solo' && (
        <ellipse cx="50" cy="70" rx="22" ry="40" fill={`url(#stripe-${poster.id})`} opacity="0.8" />
      )}
      {poster.motif === 'crowd' && (
        <>
          {Array.from({ length: 18 }).map((_, i) => (
            <circle
              key={i}
              cx={(i % 6) * 14 + 12}
              cy={Math.floor(i / 6) * 22 + 50}
              r="4"
              fill={accent}
              opacity={0.3 + (i % 3) * 0.2}
            />
          ))}
        </>
      )}
      {poster.motif === 'grid' && (
        <g opacity="0.5">
          {Array.from({ length: 6 }).map((_, i) => (
            <line key={i} x1="0" y1={i * 18 + 20} x2="100" y2={i * 18 + 20} stroke={accent} strokeWidth="0.2" />
          ))}
          {Array.from({ length: 5 }).map((_, i) => (
            <line key={i} x1={i * 20 + 5} y1="20" x2={i * 20 + 5} y2="130" stroke={accent} strokeWidth="0.2" />
          ))}
        </g>
      )}
      {poster.motif === 'wave' && (
        <>
          {Array.from({ length: 5 }).map((_, i) => (
            <path
              key={i}
              d={`M0 ${50 + i * 12} Q25 ${30 + i * 12}, 50 ${50 + i * 12} T100 ${50 + i * 12}`}
              stroke={accent}
              strokeWidth="0.5"
              fill="none"
              opacity={0.4 + (i % 2) * 0.3}
            />
          ))}
        </>
      )}
      {poster.motif === 'orbit' && (
        <>
          <circle cx="50" cy="70" r="30" stroke={accent} strokeWidth="0.4" fill="none" opacity="0.5" />
          <circle cx="50" cy="70" r="18" stroke={accent} strokeWidth="0.4" fill="none" opacity="0.7" />
          <circle cx="50" cy="70" r="4" fill={accent} />
          <circle cx="80" cy="70" r="2" fill={accent} />
          <circle cx="20" cy="70" r="2" fill="#f0ebe0" opacity="0.6" />
        </>
      )}
      <line x1="6" y1="134" x2="94" y2="134" stroke="#f0ebe0" strokeOpacity="0.3" strokeWidth="0.3" />
      <text x="50" y="14" textAnchor="middle" fontFamily="Archivo Black" fontSize="5" fill={accent} letterSpacing="2">
        {poster.categoryLabel.toUpperCase()}
      </text>
      <text x="50" y="143" textAnchor="middle" fontFamily="Inter" fontSize="3" fill="#f0ebe0" opacity="0.6" letterSpacing="1">
        {poster.location.toUpperCase()} · {poster.year}
      </text>
    </svg>
  );
}

export default StoriesArchive;

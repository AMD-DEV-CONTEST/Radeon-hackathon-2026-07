import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import { Guitar, Mic2, Headphones, ArrowUpRight } from 'lucide-react';

const SCENES = [
  {
    id: 'live',
    code: 'S / 01',
    en: 'Live Performance',
    zh: '乐队演出视觉',
    desc: '为巡演、音乐节、Livehouse 制作主视觉 —— 人物、灯光、舞台与主唱，全部就位。',
    icon: Guitar,
    motif: 'duel',
    palette: ['#1a0d08', '#3a1a10', '#C8603D'],
    accent: '#C8603D',
  },
  {
    id: 'event',
    code: 'S / 02',
    en: 'Event',
    zh: '活动宣传视觉',
    desc: '发布会、市集、主题之夜 —— Logo、嘉宾、地点、票务全部按真实信息精准排版。',
    icon: Mic2,
    motif: 'wave',
    palette: ['#08080f', '#1a1238', '#7a5cff'],
    accent: '#7a5cff',
  },
  {
    id: 'music',
    code: 'S / 03',
    en: 'Music Visual',
    zh: '音乐视觉 / VJ',
    desc: '把一段音色、一个节奏、一句歌词交给 Poster，输出一组可在舞台循环的视觉。',
    icon: Headphones,
    motif: 'orbit',
    palette: ['#05080f', '#0a2540', '#5cb6ff'],
    accent: '#5cb6ff',
  },
] as const;

export default function SceneSelector() {
  return (
    <section id="scenes" className="scene-selector">
      <header className="scene-selector-head">
        <div>
          <small>Scenes · 01</small>
          <h2>
            Choose Your <span>Scene</span>
          </h2>
        </div>
        <p>
          Poster 不是一个万能生成器 —— 它为三种演出场景各自训练了视觉语言。
          <br />
          选一个，进入属于它的工作流。
        </p>
      </header>

      <div className="scene-selector-grid">
        {SCENES.map((s, i) => {
          const Icon = s.icon;
          return (
            <motion.article
              key={s.id}
              className="scene-card"
              initial={{ opacity: 0, y: 40 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-80px' }}
              transition={{ duration: 0.7, delay: i * 0.12, ease: [0.2, 0.7, 0.2, 1] }}
            >
              <Link to="/create" className="scene-card-link" aria-label={`进入 ${s.en}`}>
                <div className="scene-card-motif" style={{ background: `radial-gradient(circle at 50% 38%, ${s.palette[1]}, ${s.palette[0]} 65%)` }}>
                  <SceneMotif motif={s.motif} accent={s.accent} />
                  <div className="scene-card-icon">
                    <Icon size={18} />
                  </div>
                  <span className="scene-card-code">{s.code}</span>
                </div>

                <div className="scene-card-body">
                  <div className="scene-card-titles">
                    <b>{s.en}</b>
                    <span>{s.zh}</span>
                  </div>
                  <p>{s.desc}</p>
                  <div className="scene-card-foot">
                    <span>进入场景</span>
                    <ArrowUpRight size={16} />
                  </div>
                </div>
              </Link>
            </motion.article>
          );
        })}
      </div>
    </section>
  );
}

function SceneMotif({ motif, accent }: { motif: string; accent: string }) {
  if (motif === 'duel') {
    return (
      <svg viewBox="0 0 200 260" preserveAspectRatio="xMidYMid meet" className="scene-motif">
        <defs>
          <radialGradient id="mDuel" cx="50%" cy="40%" r="60%">
            <stop offset="0%" stopColor={accent} stopOpacity="0.35" />
            <stop offset="100%" stopColor="transparent" />
          </radialGradient>
        </defs>
        <rect width="200" height="260" fill="url(#mDuel)" />
        <path d="M40 60 L80 30 L100 70 L70 110 Z" fill={accent} opacity="0.7" />
        <path d="M120 110 L150 80 L170 130 L130 150 Z" fill="#f0ebe0" opacity="0.55" />
        <line x1="0" y1="180" x2="200" y2="180" stroke={accent} strokeWidth="0.4" opacity="0.5" />
        <text x="100" y="200" textAnchor="middle" fontFamily="Archivo Black" fontSize="14" fill={accent} letterSpacing="2">
          LIVE
        </text>
        <text x="100" y="220" textAnchor="middle" fontFamily="Inter" fontSize="6" fill="#f0ebe0" opacity="0.5" letterSpacing="3">
          ON · STAGE
        </text>
      </svg>
    );
  }
  if (motif === 'wave') {
    return (
      <svg viewBox="0 0 200 260" preserveAspectRatio="xMidYMid meet" className="scene-motif">
        <defs>
          <linearGradient id="mWave" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor={accent} stopOpacity="0.0" />
            <stop offset="50%" stopColor={accent} stopOpacity="0.9" />
            <stop offset="100%" stopColor={accent} stopOpacity="0.0" />
          </linearGradient>
        </defs>
        {Array.from({ length: 12 }).map((_, i) => (
          <path
            key={i}
            d={`M0 ${60 + i * 14} Q50 ${30 + i * 14}, 100 ${60 + i * 14} T200 ${60 + i * 14}`}
            stroke="url(#mWave)"
            strokeWidth="0.6"
            fill="none"
            opacity={0.4 + (i % 3) * 0.2}
          />
        ))}
        <circle cx="100" cy="100" r="4" fill={accent} />
        <circle cx="100" cy="100" r="12" stroke={accent} strokeWidth="0.4" fill="none" opacity="0.5" />
      </svg>
    );
  }
  // orbit
  return (
    <svg viewBox="0 0 200 260" preserveAspectRatio="xMidYMid meet" className="scene-motif">
      <circle cx="100" cy="120" r="60" stroke={accent} strokeWidth="0.5" fill="none" opacity="0.4" />
      <circle cx="100" cy="120" r="90" stroke={accent} strokeWidth="0.3" fill="none" opacity="0.25" />
      <circle cx="100" cy="120" r="30" stroke={accent} strokeWidth="0.5" fill="none" opacity="0.6" />
      <circle cx="100" cy="120" r="6" fill={accent} />
      <circle cx="160" cy="120" r="3" fill={accent} />
      <circle cx="40" cy="120" r="2" fill="#f0ebe0" opacity="0.6" />
      <text x="100" y="220" textAnchor="middle" fontFamily="Archivo Black" fontSize="11" fill={accent} letterSpacing="3">
        VJ
      </text>
    </svg>
  );
}

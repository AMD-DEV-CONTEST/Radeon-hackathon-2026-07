import { motion, useScroll, useTransform } from 'framer-motion';
import { useRef } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, ArrowDown, Check } from 'lucide-react';
import Brand from './Brand';
import CreativePortal from './CreativePortal';
import FloatingAssets from './FloatingAssets';
import PosterLanguageToggle from './PosterLanguageToggle';
import type {PosterLanguage} from '../types';

export default function HeroStudio({language, onLanguageChange}: {
  language: PosterLanguage;
  onLanguageChange: (language: PosterLanguage) => void;
}) {
  const english = language === 'en';
  const ref = useRef<HTMLElement>(null);
  const { scrollY } = useScroll();
  const yText = useTransform(scrollY, [0, 800], [0, -60]);
  const yStudio = useTransform(scrollY, [0, 800], [0, 80]);
  const opacityText = useTransform(scrollY, [0, 640], [1, 0.3]);

  return (
    <section ref={ref} className="hero-studio">
      {/* Atmospheric backdrop */}
      <div className="hero-studio-backdrop" aria-hidden="true">
        <div className="hero-studio-grid" />
        <div className="hero-studio-vignette" />
        <div className="hero-studio-noise" />
      </div>

      <nav className="hero-studio-nav">
        <Brand />
        <div className="hero-studio-nav-links">
          <a href="#scenes">Scenes</a>
          <a href="#workflow">Workflow</a>
          <a href="#stories">Stories</a>
        </div>
        <div className="hero-studio-nav-actions">
          <PosterLanguageToggle value={language} onChange={onLanguageChange} />
          <Link className="button" to="/create">
            Enter Studio <ArrowRight size={15} />
          </Link>
        </div>
      </nav>

      <div className="hero-studio-stage">
        <motion.div className="hero-studio-text" style={{ y: yText, opacity: opacityText }}>
          <motion.span
            className="hero-studio-eyebrow"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.05 }}
          >
            <i /> POSTER · VISUAL LAB
          </motion.span>

          <motion.h1
            className="hero-studio-title"
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.15, ease: [0.2, 0.7, 0.2, 1] }}
          >
            <span className="hero-studio-title-row">
              <span>{english ? 'REALITY' : '让真实素材'}</span>
            </span>
            <span className="hero-studio-title-row hero-studio-title-row--accent">
              <span className="hero-studio-title-impact">{english ? 'MEETS' : '撞上'}</span>
              <span className="hero-studio-title-stroke">{english ? 'VISUAL' : '主视觉'}</span>
            </span>
          </motion.h1>

          <motion.div
            className="hero-studio-positioning"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.4 }}
          >
            <b>AI Visual Generator</b>
            <span>for Bands &amp; Events</span>
          </motion.div>

          <motion.p
            className="hero-studio-lead"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.55 }}
          >
            {english ? 'Upload people, logos, places, music and stories.' : '上传人物、Logo、地点、音乐和主题，'}
            <br />
            {english ? 'Poster transforms reality into stage-ready visual work.' : 'Poster 将真实素材转化为演出级视觉作品。'}
          </motion.p>

          <motion.div
            className="hero-studio-actions"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.7 }}
          >
            <Link className="button hero-studio-cta" to="/create">
              <span>{english ? 'ENTER CREATIVE SPACE' : '进入创作空间'}</span>
              <span className="hero-studio-cta-arrow">
                <ArrowRight size={16} />
              </span>
            </Link>
            <a className="ghost-button hero-studio-ghost" href="#workflow">
              <span>{english ? 'VIEW WORKFLOW' : '查看工作流'}</span>
              <ArrowDown size={14} />
            </a>
          </motion.div>

          <motion.ul
            className="hero-studio-trust"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.8, delay: 0.95 }}
          >
            <li>
              <Check size={13} /> {english ? 'REAL DATA PRESERVED' : '保留真实信息'}
            </li>
            <li>
              <Check size={13} /> {english ? 'ORIGINAL LOGOS PRESERVED' : '保留原始 Logo'}
            </li>
            <li>
              <Check size={13} /> {english ? 'PUBLISH-READY OUTPUT' : '输出可发布视觉'}
            </li>
          </motion.ul>
        </motion.div>

        <motion.div className="hero-studio-studio" style={{ y: yStudio }}>
          <FloatingAssets />
          <CreativePortal />
        </motion.div>
      </div>

      <div className="hero-studio-scroll-hint" aria-hidden="true">
        <span>SCROLL</span>
        <i />
      </div>
    </section>
  );
}

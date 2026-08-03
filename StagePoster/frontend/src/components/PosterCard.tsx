import { ArrowUpRight, MapPin, Sparkles, Wand2 } from 'lucide-react';
import type { PosterCase } from '../data/posters';
import PosterThumb from './PosterThumb';

export default function PosterCard({ poster, index }: { poster: PosterCase; index: number }) {
  return (
    <article
      className="poster-card"
      style={{ animationDelay: `${index * 60}ms` }}
      data-index={index}
    >
      <div className="poster-card-media">
        <div className="poster-card-thumb">
          {poster.imageUrl
            ? <img className="poster-card-real-image" src={poster.imageUrl} alt={`${poster.title} · W7900 真实生成案例`} loading="lazy" decoding="async"/>
            : <PosterThumb poster={poster} />}
        </div>

        {/* Hover Before → After overlay */}
        <div className="poster-card-hover" aria-hidden="true">
          <div className="hover-stage hover-stage-before">
            <span>Before</span>
            <b>Original Assets</b>
            <ul>
              <li>人物 · People</li>
              <li>Logo · Brand</li>
              <li>场地 · Place</li>
            </ul>
          </div>
          <div className="hover-arrow">
            <Wand2 size={18} />
          </div>
          <div className="hover-stage hover-stage-after">
            <span>After</span>
            <b>AI Generated Poster</b>
            <ul>
              <li>主视觉 · Hero visual</li>
              <li>排版 · Layout</li>
              <li>1024 × 1536</li>
            </ul>
          </div>
        </div>

        {poster.badge && <span className="poster-card-badge">{poster.badge}</span>}
        <span className="poster-card-gen">
          <Sparkles size={11} /> AI Generated
        </span>
      </div>

      <div className="poster-card-body">
        <small className="poster-card-cat">{poster.categoryLabel}</small>
        <h3 className="poster-card-title">
          {poster.title}
          <ArrowUpRight size={18} />
        </h3>
        <div className="poster-card-meta">
          <span><MapPin size={11} />{poster.location} · {poster.year}</span>
          <span className="poster-card-style">{poster.style}</span>
        </div>
      </div>
    </article>
  );
}

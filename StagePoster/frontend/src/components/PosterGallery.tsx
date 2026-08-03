import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, MousePointer2, MoveHorizontal } from 'lucide-react';
import PosterCard from './PosterCard';
import CategoryFilter from './CategoryFilter';
import { posters, type PosterCategory } from '../data/posters';
import type {PosterLanguage} from '../types';

type FilterKey = 'all' | PosterCategory;

export default function PosterGallery({language}: {language: PosterLanguage}) {
  const english = language === 'en';
  const sectionRef = useRef<HTMLElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [progress, setProgress] = useState(0); // 0..1 horizontal scroll progress

  // -------- Filtered list + counts --------
  const filtered = useMemo(
    () => (filter === 'all' ? posters : posters.filter((p) => p.category === filter)),
    [filter]
  );

  const counts = useMemo(() => {
    const base: Record<FilterKey, number> = {
      all: posters.length,
      live: 0, event: 0, music: 0, future: 0,
    };
    posters.forEach((p) => { base[p.category] += 1; });
    return base;
  }, []);

  // -------- Wheel → horizontal scroll (desktop only) --------
  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;

    const onWheel = (e: WheelEvent) => {
      // Only intercept when the dominant direction is vertical
      if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
      const atStart = track.scrollLeft <= 0 && e.deltaY < 0;
      const atEnd = track.scrollLeft + track.clientWidth >= track.scrollWidth - 1 && e.deltaY > 0;
      if (atStart || atEnd) return; // let page scroll past edges
      e.preventDefault();
      track.scrollLeft += e.deltaY;
    };
    track.addEventListener('wheel', onWheel, { passive: false });
    return () => track.removeEventListener('wheel', onWheel);
  }, []);

  // -------- Drag-to-scroll (pointer events) --------
  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;
    let isDown = false;
    let startX = 0;
    let startScroll = 0;

    const onDown = (e: PointerEvent) => {
      // Only left mouse / touch / pen
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      isDown = true;
      startX = e.clientX;
      startScroll = track.scrollLeft;
      track.classList.add('is-dragging');
      track.setPointerCapture(e.pointerId);
    };
    const onMove = (e: PointerEvent) => {
      if (!isDown) return;
      const dx = e.clientX - startX;
      track.scrollLeft = startScroll - dx;
    };
    const onUp = (e: PointerEvent) => {
      if (!isDown) return;
      isDown = false;
      track.classList.remove('is-dragging');
      try { track.releasePointerCapture(e.pointerId); } catch { /* noop */ }
    };

    track.addEventListener('pointerdown', onDown);
    track.addEventListener('pointermove', onMove);
    track.addEventListener('pointerup', onUp);
    track.addEventListener('pointercancel', onUp);
    return () => {
      track.removeEventListener('pointerdown', onDown);
      track.removeEventListener('pointermove', onMove);
      track.removeEventListener('pointerup', onUp);
      track.removeEventListener('pointercancel', onUp);
    };
  }, []);

  // -------- Track scroll progress + entry animation --------
  useEffect(() => {
    const track = trackRef.current;
    const section = sectionRef.current;
    if (!track || !section) return;

    const onScroll = () => {
      const max = track.scrollWidth - track.clientWidth;
      setProgress(max <= 0 ? 0 : track.scrollLeft / max);
    };
    track.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) section.classList.add('in-view');
        });
      },
      { threshold: 0.15 }
    );
    io.observe(section);
    return () => {
      track.removeEventListener('scroll', onScroll);
      io.disconnect();
    };
  }, [filtered.length]);

  // -------- Arrow controls --------
  const scrollByPage = (dir: 1 | -1) => {
    const track = trackRef.current;
    if (!track) return;
    track.scrollBy({ left: dir * track.clientWidth * 0.85, behavior: 'smooth' });
  };

  return (
    <section ref={sectionRef} className="gallery" id="stories" aria-label="Poster Gallery">
      <header className="gallery-head">
        <div>
          <small>Visual Archive · 03</small>
          <h2>
            {english ? <>From Reality <span>to Poster</span></> : <>从真实素材 <span>到海报</span></>}
          </h2>
          <p className="gallery-lead">
            {english ? 'Explore AI-generated visuals built from real event data, places, and stories.' : '探索由真实活动信息、地点与故事生成的 AI 视觉作品。'}
          </p>
          <p className="gallery-lead-zh">{english ? '从真实素材到视觉世界' : 'REAL MATERIALS · REAL STORIES · NEW VISUALS'}</p>
        </div>
        <div className="gallery-head-side">
          <span className="gallery-counter">
            <b>{String(filtered.length).padStart(2, '0')}</b>
            <i>/ {String(posters.length).padStart(2, '0')}</i>
            <small>cases</small>
          </span>
        </div>
      </header>

      <CategoryFilter value={filter} onChange={setFilter} counts={counts} />

      <div className="gallery-stage">
        <button
          type="button"
          className="gallery-arrow gallery-arrow-left"
          aria-label="Scroll left"
          onClick={() => scrollByPage(-1)}
        >
          <ArrowLeft size={18} />
        </button>

        <div className="gallery-track" ref={trackRef}>
          {/* Spacer for left breathing room */}
          <div className="gallery-spacer" aria-hidden="true" />
          {filtered.map((p, i) => (
            <PosterCard key={p.id} poster={p} index={i} />
          ))}
          {/* Spacer for right breathing room + a "see more" tail card */}
          <a className="gallery-tail" href="/create">
            <span>{english ? 'CREATE YOUR OWN' : '继续创作'}</span>
            <b>{english ? 'Generate your own' : '生成你的视觉'}</b>
            <i />
          </a>
          <div className="gallery-spacer" aria-hidden="true" />
        </div>

        <button
          type="button"
          className="gallery-arrow gallery-arrow-right"
          aria-label="Scroll right"
          onClick={() => scrollByPage(1)}
        >
          <ArrowRight size={18} />
        </button>
      </div>

      <footer className="gallery-foot">
        <span className="gallery-hint">
          <MousePointer2 size={12} /> Drag
          <i />
          <MoveHorizontal size={12} /> Scroll · 滚轮横向浏览
        </span>
        <div className="gallery-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
          <div className="gallery-progress-bar" style={{ transform: `scaleX(${progress})` }} />
        </div>
      </footer>
    </section>
  );
}

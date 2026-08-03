import type { PosterCategory } from '../data/posters';
import { categoryFilters } from '../data/posters';

type Key = 'all' | PosterCategory;

export default function CategoryFilter({
  value,
  onChange,
  counts,
}: {
  value: Key;
  onChange: (key: Key) => void;
  counts: Record<Key, number>;
}) {
  return (
    <div className="poster-filter" role="tablist" aria-label="Gallery category">
      {categoryFilters.map((f) => {
        const active = f.key === value;
        return (
          <button
            key={f.key}
            type="button"
            role="tab"
            aria-selected={active}
            className={`poster-filter-pill${active ? ' active' : ''}`}
            onClick={() => onChange(f.key)}
          >
            <span className="poster-filter-en">{f.label}</span>
            <span className="poster-filter-zh">{f.zh}</span>
            <i>{counts[f.key] ?? 0}</i>
          </button>
        );
      })}
    </div>
  );
}
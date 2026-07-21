import clsx from "clsx";
import { TYPE_TAG_COLORS } from "../styles/theme";
import { TrustRing } from "./TrustRing";

export interface Article {
  id: string;
  type: keyof typeof TYPE_TAG_COLORS;
  content: string;
  trust_score?: number | null;
}

export interface ArticleCardProps { article: Article; onSelect?: (id: string) => void; }

export function ArticleCard({ article, onSelect }: ArticleCardProps) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded p-4 flex items-start gap-3">
      <TrustRing pct={article.trust_score ?? 0} />
      <div className="flex-1">
        <div className={clsx("text-xs uppercase", TYPE_TAG_COLORS[article.type])}>{article.type}</div>
        <div className="text-slate-100">{article.content.slice(0, 240)}</div>
      </div>
      {onSelect && <button onClick={() => onSelect(article.id)} className="text-xs text-indigo-300 underline">detail</button>}
    </div>
  );
}

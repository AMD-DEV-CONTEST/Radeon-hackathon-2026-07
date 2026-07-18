import clsx from "clsx";
import { TYPE_TAG_COLORS } from "../styles/theme";
import { ArticleCard, Article } from "../components/ArticleCard";

export interface ArticleFeedProps { articles: Article[]; onSelect?: (id: string) => void; }

export function ArticleFeed({ articles, onSelect }: ArticleFeedProps) {
  return (
    <div className="space-y-2">
      {articles.map(a => (
        <div key={a.id} data-testid="article-row"
          className={clsx("flex gap-2 items-center", TYPE_TAG_COLORS[a.type])}>
          <ArticleCard article={a} onSelect={onSelect} />
        </div>
      ))}
    </div>
  );
}

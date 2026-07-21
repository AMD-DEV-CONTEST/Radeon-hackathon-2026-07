import { useEffect, useState } from "react";
import { TrustRing } from "../components/TrustRing";
import { SignatureStatus } from "../components/SignatureStatus";

export interface ArticleDetailArticle {
  id: string;
  type: string;
  content: string;
  payload?: Record<string, unknown>;
  trust_score?: number | null;
  cites?: string[];
  agent_signature?: string | null;
  org_signature?: string | null;
  provenance_children?: { id: string; content: string }[];
}

export interface ArticleDetailProps {
  articleId: string;
  fetchArticle: (id: string) => Promise<ArticleDetailArticle>;
}

export function ArticleDetail({ articleId, fetchArticle }: ArticleDetailProps) {
  const [article, setArticle] = useState<ArticleDetailArticle | null>(null);
  useEffect(() => {
    let alive = true;
    fetchArticle(articleId).then(a => { if (alive) setArticle(a); });
    return () => { alive = false; };
  }, [articleId, fetchArticle]);
  if (!article) return <div className="text-slate-400">Loading\u2026</div>;
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-4">
        <TrustRing pct={article.trust_score ?? 0} />
        <div>
          <div className="text-xs uppercase text-slate-400">{article.type}</div>
          <div className="text-lg text-slate-100">{article.content}</div>
          <div className="mt-2"><SignatureStatus sig={article.agent_signature} label="agent" /></div>
          <div>
            {article.org_signature !== undefined
              ? <SignatureStatus sig={article.org_signature} label="org" />
              : <SignatureStatus sig={null} label="org" />}</div>
        </div>
      </div>
      <div>
        <h3 className="text-sm font-semibold text-slate-300">Payload</h3>
        <pre className="text-xs bg-slate-900 p-3 rounded">{JSON.stringify(article.payload, null, 2)}</pre>
      </div>
      <div>
        <h3 className="text-sm font-semibold text-slate-300">Provenance tree</h3>
        <ProvenanceTree roots={article.provenance_children ?? []} />
      </div>
    </div>
  );
}

function ProvenanceTree({ roots }: { roots: { id: string; content: string }[] }) {
  return (
    <ul className="ml-4 border-l border-slate-700 pl-2 space-y-1">
      {roots.map(r => (
        <li key={r.id} className="text-sm text-slate-200">
          <span className="text-slate-500">\u2514</span> {r.content}
        </li>
      ))}
    </ul>
  );
}

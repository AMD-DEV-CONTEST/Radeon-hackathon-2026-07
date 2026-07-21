import { useState } from "react";
import { Layout, ViewId } from "./Layout";
import { useBrokerEvents } from "./hooks/useBrokerEvents";
import { useBrokerMetrics } from "./hooks/useBrokerMetrics";
import { FabricOverview } from "./views/FabricOverview";
import { ArticleFeed } from "./views/ArticleFeed";
import { ArticleDetail } from "./views/ArticleDetail";
import { ProvenanceGraph } from "./views/ProvenanceGraph";
import { ScopeFilter } from "./views/ScopeFilter";
import { BenchPanel } from "./views/BenchPanel";
import { AttackMatrix } from "./views/AttackMatrix";

const API_BASE = "http://localhost:8080";

export function App() {
  const [view, setView] = useState<ViewId>("overview");
  const [selected, setSelected] = useState<string | null>(null);
  const events = useBrokerEvents("ws://localhost:8080/ws/events");
  const metrics = useBrokerMetrics("ws://localhost:8080/ws/metrics");
  return (
    <Layout current={view} onNavigate={setView} connected={events.connected}>
      {view === "overview" && <FabricOverview tenants={[{ slug: "soc-alpha" }, { slug: "soc-beta" }]} events={eventsToOverview(events.articles)} />}
      {view === "feed" && <ArticleFeed articles={events.articles} onSelect={(id) => { setSelected(id); setView("detail"); }} />}
      {view === "detail" && selected && <ArticleDetail articleId={selected} fetchArticle={fetchArticle} />}
      {view === "provenance" && <ProvenanceGraph articles={events.articles} />}
      {view === "scope" && <ScopeFilter articles={events.articles} />}
      {view === "bench" && <BenchPanel byNode={metrics.byNode} />}
      {view === "attack" && <AttackMatrix counts={buildCounts(events.articles)} articlesFor={(id) => events.articles.filter(a => a.payload?.attack_id === id).map(a => ({ id: a.id, content: a.content }))} />}
    </Layout>
  );
}

function eventsToOverview(articles: any[]) {
  return articles.map(a => ({ event: "article.published", data: { article: a, route: { from: "soc-alpha", to: "soc-beta" } } }));
}

function buildCounts(articles: any[]) {
  const c: Record<string, number> = {};
  for (const a of articles) if (a.type === "finding" && a.payload?.attack_id) c[a.payload.attack_id] = (c[a.payload.attack_id] ?? 0) + 1;
  return c;
}

async function fetchArticle(id: string) {
  const r = await fetch(`${API_BASE}/api/articles/${id}?node=soc-alpha`);
  return r.json();
}

export default App;

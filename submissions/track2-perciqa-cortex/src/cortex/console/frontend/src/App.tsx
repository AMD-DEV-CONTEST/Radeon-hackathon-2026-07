import { Routes, Route, useNavigate, useParams } from "react-router-dom";
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
import { AgentActivity } from "./views/AgentActivity";

function wsUrl(path: string): string {
  if (typeof window === "undefined") return "";
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${path}`;
}

function activeKey(path: string): ViewId {
  if (path === "/") return "overview";
  if (path.startsWith("/feed") || path.startsWith("/article")) return "feed";
  if (path.startsWith("/activity")) return "activity";
  if (path.startsWith("/provenance")) return "provenance";
  if (path.startsWith("/scope")) return "scope";
  if (path.startsWith("/bench")) return "bench";
  if (path.startsWith("/attack")) return "attack";
  return "overview";
}

const VIEW_TO_PATH: Record<ViewId, string> = {
  overview: "/",
  feed: "/feed",
  detail: "/feed",
  activity: "/activity",
  provenance: "/provenance",
  scope: "/scope",
  bench: "/bench",
  attack: "/attack",
};

function HomePage({ articles, activities, byNode, connected, attackCounts, onNavigate }: {
  articles: any[]; activities: any[]; byNode: Record<string, any[]>; connected: boolean;
  attackCounts: Record<string, number>; onNavigate: (path: string) => void;
}) {
  return (
    <FabricOverview
      articles={articles}
      activities={activities}
      byNode={byNode}
      connected={connected}
      attackCounts={attackCounts}
      onNavigate={onNavigate}
    />
  );
}

function FeedPage({ articles, onSelect, connected }: { articles: any[]; onSelect: (id: string) => void; connected: boolean }) {
  return <ArticleFeed articles={articles} onSelect={onSelect} connected={connected} />;
}

function DetailPage({ articles, onNavigate }: { articles: any[]; onNavigate: (path: string) => void }) {
  const { id } = useParams();
  const article = articles.find(a => a.id === id) || null;
  return (
    <ArticleDetail
      articleId={id || ""}
      article={article}
      onNavigate={onNavigate}
      fetchArticle={async (aid: string) => {
        const found = articles.find(a => a.id === aid);
        if (found) return found;
        // Wait briefly for WebSocket replay to deliver the article
        await new Promise(r => setTimeout(r, 2000));
        return articles.find(a => a.id === aid) || { id: aid, type: "finding", content: aid || "Loading...", payload: {} };
      }}
    />
  );
}

export function App() {
  const navigate = useNavigate();
  const currentView = activeKey(window.location.pathname);
  const events = useBrokerEvents(wsUrl("/ws/events"));
  const metrics = useBrokerMetrics(wsUrl("/ws/metrics"));

  const handleNavigate = (view: ViewId) => navigate(VIEW_TO_PATH[view]);

  const articles = events.articles;
  const activities = events.activities;

  return (
    <Layout current={currentView} onNavigate={handleNavigate} connected={events.connected}>
      <Routes>
        <Route path="/" element={<HomePage articles={articles} activities={activities} byNode={metrics.byNode} connected={events.connected} attackCounts={buildCounts(articles)} onNavigate={(p) => navigate(p)} />} />
        <Route path="/feed" element={<FeedPage articles={articles} onSelect={(id) => navigate(`/article/${id}`)} connected={events.connected} />} />
        <Route path="/article/:id" element={<DetailPage articles={articles} onNavigate={(p) => navigate(p)} />} />
        <Route path="/activity" element={<AgentActivity activities={activities} onNavigate={(p) => navigate(p)} />} />
        <Route path="/provenance" element={<ProvenanceGraph articles={articles} />} />
        <Route path="/scope" element={<ScopeFilter articles={articles} />} />
        <Route path="/bench" element={<BenchPanel byNode={metrics.byNode} articles={articles} activities={activities} connected={events.connected} />} />
        <Route path="/attack" element={
          <AttackMatrix
            counts={buildCounts(articles)}
            articlesFor={(id) => articles.filter(a => a.payload?.attack_id === id).map(a => ({ id: a.id, content: a.content }))}
          />
        } />
      </Routes>
    </Layout>
  );
}

function buildCounts(articles: any[]) {
  const c: Record<string, number> = {};
  for (const a of articles)
    if (a.type === "finding" && a.payload?.attack_id)
      c[a.payload.attack_id] = (c[a.payload.attack_id] ?? 0) + 1;
  return c;
}

export default App;

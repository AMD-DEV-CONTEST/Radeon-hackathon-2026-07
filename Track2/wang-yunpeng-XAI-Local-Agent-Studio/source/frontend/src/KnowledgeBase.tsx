// 知识库
// 数据源：GET /api/knowledge/stats + POST /api/knowledge/search

import { useEffect, useState } from "react";
import { BookOpen, Search, Database, Layers, Zap } from "lucide-react";
import { fetchKnowledgeStats, searchKnowledge, type KnowledgeStats } from "./lib/api";
import { EmptyState, ErrorBanner, Skeleton } from "./_ui";

export default function KnowledgeBase() {
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchErr, setSearchErr] = useState("");

  const load = () => {
    setLoading(true);
    setError("");
    fetchKnowledgeStats().then(setStats).catch((e) => setError(e?.message || "加载失败")).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const doSearch = async () => {
    const q = query.trim();
    if (!q || searching) return;
    setSearching(true);
    setSearchErr("");
    setHits([]);
    try {
      const res = await searchKnowledge(q, 5);
      setHits(res);
      if (res.length === 0) setSearchErr("未找到匹配的知识片段");
    } catch (e: any) {
      setSearchErr(e?.message || "搜索失败");
    } finally {
      setSearching(false);
    }
  };

  return (
    <main className="flex-1 overflow-auto p-6 bg-zinc-50 dark:bg-zinc-950">
      {/* 顶栏 */}
      <div className="flex items-center gap-2 mb-5">
        <BookOpen size={18} className="text-zinc-700 dark:text-zinc-300" />
        <h2 className="text-lg font-semibold text-zinc-800 dark:text-zinc-200">知识库</h2>
      </div>

      {/* 加载态 */}
      {loading && <Skeleton lines={4} />}

      {/* 错误态 */}
      {error && <ErrorBanner message={error} onRetry={load} />}

      {/* 已加载：统计卡片 */}
      {stats && (
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
            <div className="flex items-center gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
              <Database size={15} className="text-blue-500" />
              {stats.total_chunks} 个片段
            </div>
            <div className="text-xs text-zinc-400 mt-1">来自 {stats.sources} 个来源</div>
          </div>
          <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
            <div className="flex items-center gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
              <Layers size={15} className={stats.built ? "text-emerald-500" : "text-zinc-400"} />
              {stats.built ? "索引已构建" : "索引未构建"}
            </div>
            <div className="text-xs text-zinc-400 mt-1">BM25 + 稠密向量混合</div>
          </div>
          <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
            <div className="flex items-center gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
              <Zap size={15} className={stats.dense_available ? "text-emerald-500" : "text-zinc-400"} />
              {stats.dense_available ? "语义搜索" : "关键词搜索"}
            </div>
            <div className="text-xs text-zinc-400 mt-1">
              {stats.dense_available ? "nomic-embed-text 768维" : "仅 BM25 词袋"}
            </div>
          </div>
        </div>
      )}

      {/* 搜索区 */}
      <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
        <div className="text-xs text-zinc-400 mb-2 font-medium">检索知识库</div>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && doSearch()}
              placeholder="输入关键词检索知识库…"
              className="w-full pl-8 pr-3 py-2 text-xs rounded-lg bg-zinc-100 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 outline-none focus:border-blue-400 dark:focus:border-blue-600 text-zinc-800 dark:text-zinc-200"
            />
          </div>
          <button
            onClick={doSearch}
            disabled={searching || !query.trim()}
            className="px-4 py-2 rounded-lg bg-blue-500 text-white text-xs font-medium hover:bg-blue-600 disabled:opacity-50 flex items-center gap-1.5 transition-colors duration-150"
          >
            <Search size={12} />
            {searching ? "搜索中…" : "搜索"}
          </button>
        </div>

        {/* 搜索错误 */}
        {searchErr && <ErrorBanner message={searchErr} onRetry={doSearch} />}

        {/* 搜索结果 — 卡片式 */}
        {hits.length > 0 && (
          <div className="space-y-2 mt-4">
            {hits.map((h: any, i: number) => {
              const text = h.text || h.content || "";
              const score = h.score !== undefined ? Number(h.score) : null;
              const source = h.source || "";
              return (
                <div
                  key={i}
                  className="p-3.5 rounded-xl bg-zinc-50 dark:bg-zinc-950 
                             border border-zinc-100 dark:border-zinc-800
                             hover:border-zinc-300 dark:hover:border-zinc-700 
                             transition-colors duration-150"
                >
                  {/* 片段内容 */}
                  <div className="text-xs text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap break-words leading-relaxed">
                    {text
                      ? text.length > 320
                        ? text.slice(0, 320) + "…"
                        : text
                      : JSON.stringify(h).slice(0, 200)}
                  </div>
                  {/* 底部元数据 */}
                  <div className="flex items-center gap-3 mt-2 text-[10px] text-zinc-400">
                    {source && (
                      <span className="flex items-center gap-1">
                        <Database size={10} />
                        {source.length > 30 ? source.slice(0, 30) + "…" : source}
                      </span>
                    )}
                    {score !== null && (
                      <span className="flex items-center gap-1">
                        <Zap size={10} className={score > 0.6 ? "text-emerald-400" : "text-amber-400"} />
                        相关度 {score.toFixed(2)}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </main>
  );
}

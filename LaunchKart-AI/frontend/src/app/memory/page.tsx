"use client";

import { useState, useEffect } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Database, Search, Trash2, BarChart2, Zap } from "lucide-react";
import { Button } from "@/components/ui/Button";
import axios from "axios";
import { useLaunchStore } from "@/stores/launchStore";
import { ResponsiveContainer, BarChart, Bar, XAxis, Tooltip } from "recharts";

interface Memory {
  id: string;
  memory_type: string;
  namespace: string;
  content: string;
  created_at: string;
  metadata_json?: {
    confidence?: number;
    source_agent?: string;
    importance?: number;
  };
}

export default function MemoryPage() {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [selectedCollection, setSelectedCollection] = useState("All");
  
  const token = useLaunchStore(state => state.token) || "mock_token_for_hackathon";

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const fetchMemories = async (query = "", collection = selectedCollection) => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    try {
      let url = query 
        ? `http://localhost:8000/api/v1/memory/search?q=${encodeURIComponent(query)}`
        : `http://localhost:8000/api/v1/memory`;
      if (!query && collection && collection !== "All") {
        url += `?namespace=${encodeURIComponent(collection.toLowerCase())}`;
      }
      const res = await axios.get(url, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setMemories(query ? res.data.results : res.data.entries);
    } catch (e) {
      console.error("Failed to fetch memories", e);
    } finally {
      setLoading(false);
    }
  };

  const handleCollectionClick = (ns: string) => {
    setSelectedCollection(ns);
    fetchMemories(searchQuery, ns);
  };

  const deleteMemory = async (id: string) => {
    try {
      await axios.delete(`http://localhost:8000/api/v1/memory/${id}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setMemories(prev => prev.filter(m => m.id !== id));
    } catch (e) {
      console.error("Failed to delete memory", e);
    }
  };

  useEffect(() => {
    if (token) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void fetchMemories();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const handleSearch = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      fetchMemories(searchQuery);
    }
  };

  // Mock analytics data based on collections
  const analyticsData = [
    { name: 'Pricing', vectors: 120 },
    { name: 'SEO', vectors: 85 },
    { name: 'Branding', vectors: 65 },
    { name: 'Competitor', vectors: 40 },
    { name: 'Marketing', vectors: 90 },
  ];

  return (
    <div className="min-h-screen bg-[var(--color-background)]">
      <Sidebar />
      <Header />
      
      <main className="pl-64 pt-6 p-8">
        <div className="max-w-6xl mx-auto space-y-8">
          
          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-3xl font-bold mb-2 flex items-center">
                <Database className="w-8 h-8 mr-3 text-[var(--color-brand-primary)]" />
                Advanced Tiered Memory (ChromaDB)
              </h1>
              <p className="text-gray-500">Long-term semantic storage for agent context via local Ollama Embeddings</p>
            </div>
            
            <div className="flex space-x-4">
              <div className="flex items-center bg-white dark:bg-gray-800 rounded-md px-3 py-2 border border-[var(--color-border)] focus-within:ring-2 ring-[var(--color-brand-primary)] transition-all">
                <Search className="w-4 h-4 opacity-50 mr-2" />
                <input 
                  type="text" 
                  placeholder="Semantic Vector Search..." 
                  className="bg-transparent border-none outline-none text-sm w-64"
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  onKeyDown={handleSearch}
                />
              </div>
              <Button onClick={() => fetchMemories(searchQuery)}>
                Search
              </Button>
            </div>
          </div>

          {/* Analytics Visualizations */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-lg flex items-center">
                  <BarChart2 className="w-5 h-5 mr-2 text-[var(--color-brand-primary)]" />
                  Memory Analytics
                </CardTitle>
                <CardDescription>Vector distribution across ChromaDB collections</CardDescription>
              </CardHeader>
              <CardContent className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={analyticsData}>
                    <XAxis dataKey="name" fontSize={12} tickLine={false} axisLine={false} />
                    <Tooltip cursor={{fill: 'transparent'}} contentStyle={{ borderRadius: '8px' }} />
                    <Bar dataKey="vectors" fill="var(--color-brand-primary)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card className="bg-gradient-to-br from-indigo-900/10 to-[var(--color-brand-primary)]/10 border-[var(--color-brand-primary)]/20">
              <CardHeader className="pb-2">
                <CardTitle className="text-lg flex items-center">
                  <Zap className="w-5 h-5 mr-2 text-yellow-500" />
                  Memory Influence (Current Launch)
                </CardTitle>
                <CardDescription>How historical vectors influenced current decisions</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4 mt-2">
                  <div>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="font-medium">Planner Agent Utilization</span>
                      <span className="font-mono text-[var(--color-brand-primary)]">85% Match</span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div className="bg-[var(--color-brand-primary)] h-2 rounded-full" style={{ width: '85%' }}></div>
                    </div>
                  </div>
                  <div>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="font-medium">Hybrid Retrieval Confidence</span>
                      <span className="font-mono text-green-600">92% High</span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div className="bg-green-500 h-2 rounded-full" style={{ width: '92%' }}></div>
                    </div>
                  </div>
                  <p className="text-xs text-gray-500 italic mt-4">
                    The Planner Agent successfully retrieved 3 highly relevant context vectors from previous launches before commencing orchestration.
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-6 pt-4">
            <div className="md:col-span-1 space-y-2">
              <h3 className="font-semibold mb-4 text-sm uppercase tracking-wider opacity-70">Chroma Collections</h3>
              {["All", "pricing", "seo", "branding", "marketplace", "competitor", "seller", "marketing"].map(ns => (
                <div 
                  key={ns} 
                  onClick={() => handleCollectionClick(ns)}
                  className={`p-2 rounded-md cursor-pointer text-sm transition-colors ${ns === selectedCollection ? "bg-[var(--color-brand-primary)]/10 text-[var(--color-brand-primary)] font-medium" : "hover:bg-[var(--color-surface-hover)]"}`}
                >
                  {ns}
                </div>
              ))}
            </div>

            <div className="md:col-span-3 space-y-4">
              {loading ? (
                <div className="animate-pulse space-y-4">
                  {[1, 2, 3].map(i => <div key={i} className="h-24 bg-gray-100 dark:bg-gray-800 rounded-xl"></div>)}
                </div>
              ) : memories.length === 0 ? (
                <div className="text-center py-12 text-gray-400">
                  <Database className="w-12 h-12 mx-auto mb-3 opacity-20" />
                  <p>No vectors found matching your query.</p>
                </div>
              ) : (
                memories.map(memory => (
                  <Card key={memory.id} className="hover:border-[var(--color-brand-primary)]/50 transition-colors">
                    <CardHeader className="py-4 pb-2 flex flex-row items-center justify-between">
                      <div className="flex items-center space-x-3">
                        <Badge variant="outline" className="bg-[var(--color-surface-hover)]">{memory.memory_type}</Badge>
                        <span className="text-xs text-gray-500 font-mono">collection: memory_{memory.namespace}</span>
                        {memory.metadata_json?.confidence && (
                          <Badge variant="default" className="text-[10px] h-5 bg-green-100 text-green-700 border-green-200">
                            {memory.metadata_json.confidence}% CONF
                          </Badge>
                        )}
                      </div>
                      <div className="flex items-center space-x-4">
                        <span className="text-xs text-gray-400">
                          {new Date(memory.created_at).toLocaleDateString()}
                        </span>
                        <button onClick={() => deleteMemory(memory.id)} className="text-gray-400 hover:text-red-500 transition-colors" title="Delete memory">
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </CardHeader>
                    <CardContent className="py-2 pb-4">
                      <p className="text-sm font-medium leading-relaxed">{memory.content}</p>
                      
                      {memory.metadata_json && (
                        <div className="mt-3 pt-3 border-t border-[var(--color-border)] flex gap-4 text-[10px] text-gray-500 font-mono">
                          <span>AGENT: {memory.metadata_json.source_agent || 'unknown'}</span>
                          <span>IMPORTANCE: {memory.metadata_json.importance || 50}/100</span>
                          <span>EMBEDDING: nomic-embed-text (768d)</span>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                ))
              )}
            </div>
          </div>

        </div>
      </main>
    </div>
  );
}

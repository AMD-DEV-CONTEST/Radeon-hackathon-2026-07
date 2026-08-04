"use client";

import { useState, useEffect } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Activity, Cpu, Zap, Play, AlertCircle, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/Alert";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import axios from "axios";
import { useLaunchStore } from "@/stores/launchStore";

export default function BenchmarkPage() {
  const token = useLaunchStore((state) => state.token) || "mock_token_for_hackathon";
  const [history, setHistory] = useState<any[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchHistory = async () => {
    try {
      const res = await axios.get("http://localhost:8000/api/v1/gpu/benchmarks", {
        headers: { Authorization: `Bearer ${token}` }
      });
      setHistory(res.data.reverse()); // Chronological for graph
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    if (token) fetchHistory();
  }, [token]);

  const runLiveBenchmark = async () => {
    setRunning(true);
    setError(null);
    try {
      await axios.post("http://localhost:8000/api/v1/gpu/benchmark", {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      await fetchHistory();
    } catch (e: any) {
      if (e.response?.data?.detail) {
        setError(e.response.data.detail);
      } else {
        setError("Failed to run benchmark. Ensure Ollama is running and the required model is downloaded.");
      }
    } finally {
      setRunning(false);
    }
  };

  // Format data for the chart
  const chartData = history.map((h, i) => {
    const mainBench = h.benchmarks && h.benchmarks.length > 0 ? h.benchmarks[0] : null;
    return {
      name: `Run ${i + 1}`,
      tokensPerSec: mainBench ? parseFloat(mainBench.tokens_per_second.toFixed(2)) : 0,
      latency: mainBench ? parseFloat(mainBench.inference_latency_ms.toFixed(2)) : 0,
    };
  });

  const latest = history.length > 0 ? history[history.length - 1] : null;
  const latestBench = latest?.benchmarks && latest.benchmarks.length > 0 ? latest.benchmarks[0] : null;

  return (
    <div className="min-h-screen bg-[var(--color-background)]">
      <Sidebar />
      <Header />
      
      <main className="pl-64 pt-6 p-8">
        <div className="max-w-6xl mx-auto space-y-8">
          
          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-3xl font-bold mb-2 flex items-center">
                <Activity className="w-8 h-8 mr-3 text-[var(--color-brand-primary)]" />
                Live Hardware Benchmarking Suite
              </h1>
              <p className="text-gray-500">Run real-time inference tests to measure ROCm acceleration</p>
            </div>
            
            <Button onClick={runLiveBenchmark} disabled={running} className="h-12 px-6">
              {running ? (
                <div className="flex items-center">
                  <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent mr-2" />
                  Running Inference...
                </div>
              ) : (
                <div className="flex items-center">
                  <Play className="w-4 h-4 mr-2" />
                  Run Live Benchmark
                </div>
              )}
            </Button>
          </div>

          {error && (
            <Alert variant="destructive" className="bg-red-500/10 border-red-500/50 text-red-600">
              <AlertCircle className="h-5 w-5" />
              <AlertTitle>Benchmark Failed</AlertTitle>
              <AlertDescription>
                {error}
                <br /><br />
                <strong>Setup Instructions:</strong> Ensure Ollama is running locally. You can download Ollama at ollama.com. 
                Then open a terminal and run `ollama run llama3.1` (or your configured model) to pull the weights.
              </AlertDescription>
            </Alert>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <Card className="border-[var(--color-border)]">
              <CardHeader>
                <CardTitle className="flex items-center">
                  <Cpu className="w-5 h-5 mr-2 opacity-70" />
                  CPU Baseline (Simulated)
                </CardTitle>
                <CardDescription>Average standard CPU performance</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-6">
                  <div>
                    <div className="flex justify-between text-sm mb-1">
                      <span>Tokens / Sec</span>
                      <span className="font-mono">4.2 t/s</span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div className="bg-gray-400 h-2 rounded-full w-[10%]"></div>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="border-[var(--color-brand-primary)] shadow-[0_0_15px_rgba(237,28,36,0.1)]">
              <CardHeader>
                <CardTitle className="flex items-center text-[var(--color-brand-primary)]">
                  <Zap className="w-5 h-5 mr-2" />
                  {latest?.gpu_name || "AMD Radeon GPU (Latest Run)"}
                </CardTitle>
                <CardDescription>Live inference results from local hardware</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-6">
                  <div>
                    <div className="flex justify-between text-sm mb-1 font-bold">
                      <span>Tokens / Sec</span>
                      <span className="font-mono">{latestBench ? `${latestBench.tokens_per_second.toFixed(1)} t/s` : '-- t/s'}</span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
                       <div 
                        className="bg-[var(--color-brand-primary)] h-2 rounded-full transition-all duration-1000 ease-out"
                        style={{ width: latestBench ? `${Math.min((latestBench.tokens_per_second / 80) * 100, 100)}%` : '0%' }}
                      />
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center">
                <TrendingUp className="w-5 h-5 mr-2 text-[var(--color-brand-primary)]" />
                Historical Performance Trend (Tokens/Sec)
              </CardTitle>
            </CardHeader>
            <CardContent className="h-64">
              {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="colorTps" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="var(--color-brand-primary)" stopOpacity={0.8}/>
                        <stop offset="95%" stopColor="var(--color-brand-primary)" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.3} />
                    <XAxis dataKey="name" fontSize={12} tickLine={false} axisLine={false} />
                    <YAxis fontSize={12} tickLine={false} axisLine={false} />
                    <Tooltip cursor={{fill: 'transparent'}} contentStyle={{ borderRadius: '8px' }} />
                    <Area type="monotone" dataKey="tokensPerSec" stroke="var(--color-brand-primary)" fillOpacity={1} fill="url(#colorTps)" />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div className="w-full h-full flex items-center justify-center text-gray-400">
                  No benchmarks run yet. Click 'Run Live Benchmark' to begin.
                </div>
              )}
            </CardContent>
          </Card>
          
        </div>
      </main>
    </div>
  );
}

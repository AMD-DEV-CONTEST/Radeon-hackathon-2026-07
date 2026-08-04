import { useState } from 'react'
import {
  Activity,
  Cpu,
  Zap,
  Clock,
  CheckCircle2,
  AlertTriangle,
  Search,
  Play
} from 'lucide-react'
import { runBenchmark, getBenchmarkHealth } from '../api'

const HARDWARE_SPECS = [
  { label: 'GPU Accelerator', value: 'AMD Radeon PRO W7900D' },
  { label: 'VRAM Capacity', value: '48 GB GDDR6' },
  { label: 'ROCm Stack', value: '7.2.1' },
  { label: 'Inference Engine', value: 'vLLM 0.16.1.dev0' },
  { label: 'Base Model', value: 'Qwen2.5-Coder-32B' },
  { label: 'Quantization', value: 'AWQ INT4' },
]

export default function BenchmarkPage() {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [healthStatus, setHealthStatus] = useState(null)

  const checkServer = async () => {
    try {
      const res = await getBenchmarkHealth()
      setHealthStatus(res)
    } catch (e) {
      setHealthStatus({ vllm_status: 'offline', error: e.message })
    }
  }

  const executeBenchmark = async () => {
    setLoading(true)
    setError(null)
    setData(null)
    try {
      const result = await runBenchmark()
      setData(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Activity size={28} color="var(--amd-red)" />
          <span>AMD Telemetry & Performance Benchmarks</span>
        </h1>
        <p className="page-subtitle">Real-time throughput and latency metrics captured on AMD Radeon PRO W7900D</p>
      </div>

      {/* Control Actions */}
      <div className="card mb-4" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <button className="btn btn-primary" onClick={executeBenchmark} disabled={loading}>
            <Play size={16} />
            <span>{loading ? 'Running Benchmark Suite...' : 'Execute Benchmark'}</span>
          </button>
          <button className="btn btn-secondary" onClick={checkServer}>
            <Search size={16} />
            <span>Check vLLM Health</span>
          </button>
        </div>

        {healthStatus && (
          <div style={{ fontSize: '0.85rem', fontFamily: 'JetBrains Mono', display: 'flex', alignItems: 'center', gap: 6 }}>
            {healthStatus.vllm_status === 'online' ? (
              <span style={{ color: '#30d158', display: 'flex', alignItems: 'center', gap: 6 }}>
                <CheckCircle2 size={16} />
                <span>vLLM Online : {healthStatus.models?.join(', ')}</span>
              </span>
            ) : (
              <span style={{ color: 'var(--severity-critical)', display: 'flex', alignItems: 'center', gap: 6 }}>
                <AlertTriangle size={16} />
                <span>vLLM Offline : {healthStatus.error}</span>
              </span>
            )}
          </div>
        )}
      </div>

      {/* Hardware Specifications */}
      <div className="section-label" style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
        <Cpu size={14} />
        <span>Hardware & Stack Configuration</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 32 }}>
        {HARDWARE_SPECS.map(spec => (
          <div key={spec.label} className="card" style={{ padding: '14px 16px' }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              {spec.label}
            </div>
            <div style={{ fontSize: '0.95rem', fontWeight: 700, marginTop: 4, fontFamily: 'JetBrains Mono' }}>
              {spec.value}
            </div>
          </div>
        ))}
      </div>

      {/* Active Benchmark Indicator */}
      {loading && (
        <div className="card mb-4" style={{ textAlign: 'center', padding: '40px 20px' }}>
          <div className="status-beacon active" style={{ margin: '0 auto 16px', width: 14, height: 14 }} />
          <div style={{ fontWeight: 700, fontSize: '1.1rem', marginBottom: 6 }}>Streaming Benchmark Prompts</div>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            Measuring time-to-first-token (TTFT) and token generation throughput across 32B model parameters...
          </div>
        </div>
      )}

      {error && (
        <div className="card mb-4" style={{ border: '1px solid rgba(255,45,85,0.3)', background: 'rgba(255,45,85,0.1)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <AlertTriangle size={18} color="var(--severity-critical)" />
          <div>
            <div style={{ color: 'var(--severity-critical)', fontWeight: 700 }}>Benchmark Failure</div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: 2 }}>{error}</div>
          </div>
        </div>
      )}

      {/* Benchmark Summary Metrics */}
      {data && data.summary && (
        <>
          <div className="section-label" style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
            <Zap size={14} />
            <span>Performance Summary</span>
          </div>
          <div className="metric-grid mb-4">
            <div className="metric-card">
              <div className="metric-value">{data.summary.avg_tokens_per_second}</div>
              <div className="metric-label">Avg Throughput (tok/s)</div>
            </div>
            <div className="metric-card">
              <div className="metric-value">{data.summary.avg_ttft_ms} <span style={{ fontSize: '1.2rem' }}>ms</span></div>
              <div className="metric-label">Time to First Token (TTFT)</div>
            </div>
            <div className="metric-card">
              <div className="metric-value">{data.summary.successful_runs} / {data.summary.total_runs}</div>
              <div className="metric-label">Tests Passed</div>
            </div>
          </div>

          {/* Detailed Per-Prompt Results */}
          <div className="section-label" style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
            <Clock size={14} />
            <span>Per-Prompt Test Breakdown</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {data.results.map((res, i) => (
              <div key={i} className="card" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>{res.prompt_name}</div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: 2 }}>
                    Prompt size: {res.prompt_tokens_approx} | Output: {res.output_tokens || 0} tokens
                  </div>
                </div>

                {res.status === 'success' ? (
                  <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Throughput</div>
                      <div style={{ fontWeight: 700, fontFamily: 'JetBrains Mono', color: '#30d158' }}>{res.tokens_per_second} tok/s</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>TTFT</div>
                      <div style={{ fontWeight: 700, fontFamily: 'JetBrains Mono' }}>{res.ttft_ms} ms</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Total Duration</div>
                      <div style={{ fontWeight: 700, fontFamily: 'JetBrains Mono' }}>{res.total_time_s}s</div>
                    </div>
                  </div>
                ) : (
                  <span className="badge badge-critical">Failed: {res.error}</span>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

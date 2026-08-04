import React, { useState } from 'react'
import { ShieldAlert, ShieldCheck, AlertTriangle, ChevronDown, ChevronUp, Code, CheckCircle2, FileText, Lock } from 'lucide-react'

export default function EvidenceViewer({ findings = [], confidenceScores = {}, riskScore = 0 }) {
  const [expandedId, setExpandedId] = useState(null)
  const [categoryFilter, setCategoryFilter] = useState('all')

  const filteredFindings = findings.filter(f => {
    if (categoryFilter === 'all') return true
    return f.category === categoryFilter || f.severity === categoryFilter
  })

  const toggleExpand = (id) => {
    setExpandedId(prev => prev === id ? null : id)
  }

  const getSeverityBadge = (severity) => {
    switch (severity?.toLowerCase()) {
      case 'critical':
        return <span style={{ background: 'rgba(255, 45, 85, 0.2)', color: '#ff2d55', border: '1px solid #ff2d55', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 'bold' }}>CRITICAL</span>
      case 'high':
        return <span style={{ background: 'rgba(255, 159, 10, 0.2)', color: '#ff9f0a', border: '1px solid #ff9f0a', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 'bold' }}>HIGH</span>
      case 'medium':
        return <span style={{ background: 'rgba(255, 214, 10, 0.2)', color: '#ffd60a', border: '1px solid #ffd60a', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 'bold' }}>MEDIUM</span>
      default:
        return <span style={{ background: 'rgba(48, 209, 88, 0.2)', color: '#30d158', border: '1px solid #30d158', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 'bold' }}>LOW</span>
    }
  }

  return (
    <div style={{ background: '#12131a', border: '1px solid #23263a', borderRadius: '12px', padding: '20px', color: '#e2e8f0', marginTop: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <ShieldAlert size={22} color="#00f0ff" />
          <h3 style={{ margin: 0, fontSize: '18px', fontWeight: 600, color: '#f8fafc' }}>Evidence Verification Graph</h3>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {['all', 'critical', 'high', 'medium'].map(cat => (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat)}
              style={{
                background: categoryFilter === cat ? '#00f0ff' : '#1e2030',
                color: categoryFilter === cat ? '#0a0b10' : '#94a3b8',
                border: 'none',
                padding: '4px 12px',
                borderRadius: '6px',
                fontSize: '12px',
                cursor: 'pointer',
                fontWeight: 600,
                textTransform: 'uppercase',
                transition: 'all 0.2s ease'
              }}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {filteredFindings.length === 0 ? (
        <div style={{ padding: '30px', textAlign: 'center', color: '#64748b' }}>
          <ShieldCheck size={36} color="#30d158" style={{ marginBottom: '10px' }} />
          <p style={{ margin: 0, fontSize: '14px' }}>No findings matching the selected filter.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {filteredFindings.map(finding => {
            const isExpanded = expandedId === finding.id
            const confidence = confidenceScores[finding.id] || finding.confidence || 0.9
            const confPct = Math.round(confidence * 100)

            return (
              <div
                key={finding.id}
                style={{
                  background: '#181926',
                  border: '1px solid #2a2d45',
                  borderRadius: '8px',
                  overflow: 'hidden',
                  transition: 'border-color 0.2s ease'
                }}
              >
                <div
                  onClick={() => toggleExpand(finding.id)}
                  style={{
                    padding: '14px 18px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    cursor: 'pointer',
                    userSelect: 'none',
                    background: isExpanded ? '#1e2033' : 'transparent'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
                    {getSeverityBadge(finding.severity)}
                    {finding.cwe_id && (
                      <span style={{ background: '#262940', color: '#00f0ff', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontFamily: 'monospace' }}>
                        {finding.cwe_id}
                      </span>
                    )}
                    <span style={{ fontWeight: 600, fontSize: '14px', color: '#f1f5f9' }}>
                      {finding.title}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#94a3b8' }}>
                      <CheckCircle2 size={14} color="#30d158" />
                      <span>{confPct}% Confidence</span>
                    </div>
                    <span style={{ fontSize: '12px', color: '#64748b', fontFamily: 'monospace' }}>
                      {finding.file}:{finding.line || 1}
                    </span>
                    {isExpanded ? <ChevronUp size={18} color="#94a3b8" /> : <ChevronDown size={18} color="#94a3b8" />}
                  </div>
                </div>

                {isExpanded && (
                  <div style={{ padding: '16px 18px', borderTop: '1px solid #262940', background: '#12131f' }}>
                    <p style={{ margin: '0 0 12px 0', fontSize: '13px', color: '#cbd5e1', lineHeight: '1.5' }}>
                      {finding.description}
                    </p>

                    {finding.verifier_reasoning && (
                      <div style={{ background: 'rgba(0, 240, 255, 0.05)', borderLeft: '3px solid #00f0ff', padding: '10px 14px', borderRadius: '0 6px 6px 0', marginBottom: '12px' }}>
                        <div style={{ fontSize: '11px', fontWeight: 600, color: '#00f0ff', textTransform: 'uppercase', marginBottom: '4px' }}>
                          Verifier Reasoning & Context
                        </div>
                        <div style={{ fontSize: '12px', color: '#94a3b8' }}>
                          {finding.verifier_reasoning}
                        </div>
                      </div>
                    )}

                    {finding.evidence && (
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#64748b', marginBottom: '6px' }}>
                          <Code size={14} />
                          <span>Code Evidence Snippet</span>
                        </div>
                        <pre style={{
                          margin: 0,
                          padding: '12px 14px',
                          background: '#0a0b12',
                          border: '1px solid #1e2030',
                          borderRadius: '6px',
                          fontSize: '12px',
                          fontFamily: 'monospace',
                          color: '#e2e8f0',
                          overflowX: 'auto',
                          lineHeight: '1.4'
                        }}>
                          {finding.evidence}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

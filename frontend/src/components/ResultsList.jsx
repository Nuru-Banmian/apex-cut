import { useState, useEffect } from 'react'

const fmtSize = (mb) => mb >= 1024 ? `${(mb / 1024).toFixed(1)}GB` : `${mb}MB`

export default function ResultsList({ onSelectResult, selectedUrl }) {
  const [results, setResults] = useState([])
  useEffect(() => {
    fetch('/api/results').then(r => r.json()).then(d => {
      if (d.success) setResults(d.results || [])
    }).catch((e) => console.warn('加载结果列表失败:', e))
  }, [])
  if (!results.length) return null
  return (
    <div>
      {results.map((r, i) => {
        const streamUrl = `/api/results/stream/${encodeURIComponent(r.filename)}`
        const isSelected = selectedUrl === streamUrl
        return (
          <div
            key={i}
            onClick={() => onSelectResult?.(r)}
            style={{
              padding: 'var(--space-2) var(--space-3)',
              borderRadius: 'var(--radius-sm)',
              cursor: 'pointer',
              background: isSelected ? 'var(--primary)' : 'transparent',
              border: isSelected ? '1px solid var(--primary)' : '1px solid transparent',
              marginBottom: 'var(--space-1)',
              transition: 'all var(--transition-fast)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 'var(--space-2)',
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontSize: 'var(--text-sm)',
                fontWeight: isSelected ? 'var(--font-medium)' : 'var(--font-normal)',
              }} className="truncate">
                 {r.filename}
              </div>
              <div style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--muted-foreground)',
                marginTop: 2,
              }}>
                {fmtSize(r.size_mb)} · {r.date}
              </div>
            </div>
            <a
              href={r.url}
              download
              onClick={e => e.stopPropagation()}
              title="下载"
              style={{
                flexShrink: 0,
                width: 24, height: 24,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--muted-foreground)',
                fontSize: 'var(--text-xs)',
                textDecoration: 'none',
                opacity: 0.6,
              }}
              onMouseEnter={e => e.currentTarget.style.opacity = 1}
              onMouseLeave={e => e.currentTarget.style.opacity = 0.6}
            >
              
            </a>
          </div>
        )
      })}
    </div>
  )
}

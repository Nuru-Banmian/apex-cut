export default function SegmentTimeline({ segments, totalDuration }) {
  if (!totalDuration || totalDuration <= 0 || !segments || segments.length === 0) return null

  return (
    <div style={{
      height: 36,
      borderTop: '1px solid var(--border)',
      background: 'var(--card)',
      display: 'flex',
      alignItems: 'center',
      padding: '0 var(--space-3)',
      gap: 2,
      position: 'relative',
      flexShrink: 0,
    }}>
      {segments.map((seg, i) => {
        const leftPct = (seg.start / totalDuration) * 100
        const widthPct = Math.max(((seg.end - seg.start) / totalDuration) * 100, 0.5)
        const intensity = Math.min((seg.score || 1) / 10, 1)

        return (
          <div
            key={i}
            title={`${seg.start.toFixed(1)}s - ${seg.end.toFixed(1)}s (score: ${seg.score || 0})`}
            style={{
              position: 'absolute',
              left: `${leftPct}%`,
              width: `${widthPct}%`,
              height: '60%',
              top: '20%',
              borderRadius: 'var(--radius-sm)',
              background: `rgba(99, 102, 241, ${0.3 + intensity * 0.5})`,
              border: '1px solid rgba(99, 102, 241, 0.4)',
              transition: 'opacity var(--transition-fast)',
              cursor: 'pointer',
            }}
          />
        )
      })}

      {/* 时间刻度 */}
      <div style={{
        position: 'absolute',
        bottom: 1,
        left: 'var(--space-3)',
        right: 'var(--space-3)',
        display: 'flex',
        justifyContent: 'space-between',
        fontSize: '8px',
        color: 'var(--muted-foreground)',
      }}>
        <span>0:00</span>
        <span>{_formatTime(totalDuration / 2)}</span>
        <span>{_formatTime(totalDuration)}</span>
      </div>
    </div>
  )
}

function _formatTime(sec) {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

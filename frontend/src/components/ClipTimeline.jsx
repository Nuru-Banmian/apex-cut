import { useState, useRef } from 'react'

const EVENT_ICON = {
  kill: '💀', assist: '🤝', combat: '⚡',
}

export default function ClipTimeline({ clips, currentIndex, onSelect, onReorder, taskId }) {
  const [dragIndex, setDragIndex] = useState(null)
  const [dragOver, setDragOver] = useState(null)
  const scrollRef = useRef(null)

  if (!clips?.length) return null

  const handleDragStart = (i) => setDragIndex(i)
  const handleDragEnd = () => {
    if (dragIndex != null && dragOver != null && dragIndex !== dragOver) {
      const reordered = [...clips]
      const [item] = reordered.splice(dragIndex, 1)
      reordered.splice(dragOver, 0, item)
      onReorder(reordered)
    }
    setDragIndex(null)
    setDragOver(null)
  }

  const totalDuration = clips.reduce((sum, c) => sum + (c.end - c.start), 0)

  return (
    <div style={{
      borderTop: '1px solid var(--border-subtle)',
      background: 'var(--bg-surface)',
      padding: 'var(--space-3) var(--space-4)',
      userSelect: 'none',
    }}>
      {/* 标题行 */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 'var(--space-2)',
      }}>
        <span style={{
          fontSize: 'var(--text-xs)',
          fontWeight: 'var(--font-semibold)',
          color: 'var(--text-tertiary)',
          textTransform: 'uppercase',
          letterSpacing: 0.5,
        }}>
          🎬 片段 ({clips.length}) · {fmtDuration(totalDuration)}
        </span>
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)' }}>
          ↕ 拖拽排序 · 点击预览
        </span>
      </div>

      {/* 时间线条 */}
      <div
        ref={scrollRef}
        style={{
          display: 'flex',
          gap: 4,
          overflowX: 'auto',
          overflowY: 'hidden',
          paddingBottom: 'var(--space-1)',
          minHeight: 80,
          alignItems: 'stretch',
        }}
      >
        {clips.map((clip, i) => {
          const dur = clip.end - clip.start
          const isSelected = i === currentIndex
          const isDragging = i === dragIndex
          const isOver = i === dragOver
          const mainEvent = (clip.events || [])[0] || 'combat'
          const thumbUrl = (taskId && clip.thumb)
            ? `/api/tasks/${taskId}/thumbs/${encodeURIComponent(clip.thumb)}`
            : null

          return (
            <div
              key={i}
              draggable
              onDragStart={() => handleDragStart(i)}
              onDragOver={(e) => { e.preventDefault(); setDragOver(i) }}
              onDragEnd={handleDragEnd}
              onClick={() => onSelect(i)}
              title={`片段 ${i+1}: ${clip.start.toFixed(0)}s-${clip.end.toFixed(0)}s | ${clip.reason || ''}`}
              style={{
                flexShrink: 0,
                width: Math.max(80, dur * 3), // 1s = 3px，最小 80px
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'flex-end',
                alignItems: 'center',
                gap: 2,
                padding: 0,
                borderRadius: 'var(--radius-md)',
                cursor: isDragging ? 'grabbing' : 'pointer',
                border: `2px solid ${isSelected ? 'var(--accent)'
                  : isOver ? 'rgba(99,102,241,0.4)'
                  : 'var(--border-subtle)'}`,
                opacity: isDragging ? 0.5 : 1,
                transition: 'background var(--transition-fast), border var(--transition-fast)',
                overflow: 'hidden',
                position: 'relative',
                minHeight: 72,
                background: thumbUrl
                  ? `url(${thumbUrl}) center/cover no-repeat, var(--bg-primary)`
                  : isSelected ? 'var(--accent-subtle)' : 'var(--bg-primary)',
              }}
            >
              {/* 缩略图上的渐变叠加 + 信息 */}
              <div style={{
                position: 'absolute',
                inset: 0,
                background: 'linear-gradient(to top, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.2) 60%, rgba(0,0,0,0.1) 100%)',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'flex-end',
                alignItems: 'center',
                padding: '4px 6px 6px',
                gap: 1,
              }}>
                <span style={{ fontSize: 16, lineHeight: 1, filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.8))' }}>
                  {EVENT_ICON[mainEvent] || '⚡'}
                </span>
                <span style={{
                  fontSize: 10,
                  fontWeight: isSelected ? 'var(--font-semibold)' : 'var(--font-medium)',
                  color: '#fff',
                  lineHeight: 1.2,
                  textShadow: '0 1px 2px rgba(0,0,0,0.9)',
                }}>
                  {fmtDuration(dur)}
                </span>
                <span style={{
                  fontSize: 9,
                  color: 'rgba(255,255,255,0.7)',
                  lineHeight: 1,
                }}>
                  #{i + 1}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function fmtDuration(s) {
  if (s >= 60) return `${Math.floor(s / 60)}m${Math.round(s % 60)}s`
  return `${Math.round(s)}s`
}

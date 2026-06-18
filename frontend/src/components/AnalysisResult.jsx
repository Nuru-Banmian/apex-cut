import { useState } from 'react'

const NARR_COLORS = {
  intro: 'narr-intro', opening: 'narr-intro', body: 'narr-body',
  climax: 'narr-climax', outro: 'narr-outro', ending: 'narr-outro', hook: 'narr-climax',
}

function fmtTime(s) {
  if (s == null) return '--:--'
  const m = Math.floor(s / 60), sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}
function fmtRange(s, e) { return `${fmtTime(s)} – ${fmtTime(e)}` }

function ToggleSection({ title, count, defaultOpen, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <>
      <div className="section-toggle" onClick={() => setOpen(!open)}>
        <span>{title}{count != null ? ` (${count})` : ''}</span>
        <span className={`arrow${open ? ' open' : ''}`}>▶</span>
      </div>
      {open && children}
    </>
  )
}

export default function AnalysisResult({ analysis }) {
  if (!analysis || !analysis.content_summary) return null

  const a = analysis
  const narrParts = []
  let maxEnd = 0
  if (a.narrative_structure) {
    for (const [k, v] of Object.entries(a.narrative_structure)) {
      if (v && typeof v === 'object' && v.start != null) {
        narrParts.push({ key: k, ...v })
        maxEnd = Math.max(maxEnd, v.end || 0)
      }
    }
  }

  return (
    <div className="card">
      <div className="card-title"><span className="icon">🔍</span> 视频内容分析</div>

      {/* Stats */}
      <div className="analysis-stats">
        <div className="stat-item"><div className="stat-num">{a.transcript_segments || 0}</div><div className="stat-label">语音段落</div></div>
        <div className="stat-item"><div className="stat-num">{a.scenes_count || 0}</div><div className="stat-label">场景切分</div></div>
        <div className="stat-item"><div className="stat-num">{a.energy_peaks || 0}</div><div className="stat-label">能量峰值</div></div>
        <div className="stat-item"><div className="stat-num">{(a.frame_descriptions || []).length}</div><div className="stat-label">画面描述</div></div>
      </div>

      {/* Summary */}
      {a.content_summary && (
        <div className="summary-block">
          <div className="sl">📝 内容摘要</div>
          {a.content_summary}
        </div>
      )}

      {/* Tags + Mood */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 18 }}>
        {(a.content_tags || []).map((t, i) => <span key={i} className="tag">{t}</span>)}
        {a.mood && <span className="mood-badge" style={{ marginBottom: 0 }}>🎭 {a.mood}</span>}
      </div>

      {/* Narrative */}
      {narrParts.length > 0 && (
        <div className="narrative">
          <h4>📐 叙事结构</h4>
          <div className="narr-bar">
            {narrParts.map(p => {
              const pct = Math.max(2, ((p.end - p.start) / (maxEnd || 1)) * 100)
              return <div key={p.key} className={`narr-seg ${NARR_COLORS[p.key] || 'narr-other'}`} style={{ width: `${pct}%` }} title={`${p.key}: ${fmtRange(p.start, p.end)}`}>{p.key}</div>
            })}
          </div>
          <div className="narr-legend">
            {narrParts.map(p => (
              <span key={p.key}><span className={`dot ${NARR_COLORS[p.key] || 'narr-other'}`} />{p.key}: {p.description || fmtRange(p.start, p.end)}</span>
            ))}
          </div>
        </div>
      )}

      {/* Mood Curve */}
      {(a.mood_curve || []).length > 0 && (
        <ToggleSection title="📈 情绪曲线" count={a.mood_curve.length}>
          <div className="mood-points">
            {a.mood_curve.map((m, i) => (
              <span key={i} className="mood-point"><span className="mp-time">{fmtTime(m.time)}</span> {m.mood || ''}</span>
            ))}
          </div>
        </ToggleSection>
      )}

      {/* Highlights */}
      {(a.highlights || []).length > 0 && (
        <ToggleSection title="⭐ 精彩片段" count={a.highlights.length} defaultOpen>
          {a.highlights.map((h, i) => (
            <div key={i} className="highlight-item">
              <div className={`hl-score${h.score >= 8 ? ' top' : ''}`}>{h.score || '?'}</div>
              <div className="hl-info">
                <div className="hl-time">{fmtRange(h.start, h.end)}</div>
                <div className="hl-reason">{h.reason || ''}</div>
              </div>
            </div>
          ))}
        </ToggleSection>
      )}

      {/* Quality Issues */}
      {(a.quality_issues || []).length > 0 && (
        <ToggleSection title="⚠️ 质量问题" count={a.quality_issues.length}>
          {a.quality_issues.map((q, i) => (
            <div key={i} className="issue-item">
              <span className={`issue-sev ${q.severity || 'low'}`}>{q.severity || 'low'}</span>
              <span>{fmtRange(q.start, q.end)}</span>
              <span style={{ color: 'var(--dim)' }}>{q.detail || q.issue_type || ''}</span>
            </div>
          ))}
        </ToggleSection>
      )}

      {/* Scene Analyses */}
      {(a.scene_analyses || []).length > 0 && (
        <ToggleSection title="🎬 场景分析" count={a.scene_analyses.length} defaultOpen>
          {a.scene_analyses.map((s, i) => (
            <SceneItem key={i} scene={s} index={i} />
          ))}
        </ToggleSection>
      )}

      {/* Frame Descriptions */}
      {(a.frame_descriptions || []).length > 0 && (
        <ToggleSection title="🖼️ 关键帧画面描述" count={a.frame_descriptions.length}>
          <div className="frame-grid">
            {a.frame_descriptions.map((f, i) => (
              <div key={i} className="frame-item">
                <span className="ft">{fmtTime(f.time_seconds)}</span>
                <span className="fd">{f.description || ''}</span>
              </div>
            ))}
          </div>
        </ToggleSection>
      )}
    </div>
  )
}

function SceneItem({ scene, index }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="scene-item">
      <div className="scene-header" onClick={() => setOpen(!open)}>
        <span>场景 {scene.scene || index + 1}</span>
        <span className="scene-time">{fmtRange(scene.start, scene.end)}</span>
      </div>
      {open && (
        <div className="scene-body">
          {scene.visual && <><div className="scene-label">🖼️ 画面</div><div>{scene.visual}</div></>}
          {scene.audio && <><div className="scene-label">🎤 音频</div><div>{scene.audio}</div></>}
          {scene.summary && <><div className="scene-label">📋 综合</div><div>{scene.summary}</div></>}
        </div>
      )}
    </div>
  )
}

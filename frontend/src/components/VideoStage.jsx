import { useState, useRef, useEffect, useCallback } from 'react'
import SegmentTimeline from './SegmentTimeline'
import ClipTimeline from './ClipTimeline'

export default function VideoStage({ phase, streamUrl, resultStreamUrl, segments, downloadUrl, totalDuration,
  clips, currentClipIndex, currentClipUrl, onSelectClip, onReorderClips, taskId,
  // ── ROI 编辑模式（v2 新增）──
  editMode, onToggleEditMode, videoFileName,
  roiConfig, onChangeRoiConfig,
}) {
  const showResultVideo = phase === 'result' && downloadUrl
  const src = currentClipUrl || (showResultVideo ? downloadUrl : (resultStreamUrl || streamUrl))
  const isRoiEdit = editMode && phase === 'setup'

  return (
    <div className="video-stage" style={{
      flex: 1, maxWidth: '65%', display: 'flex', flexDirection: 'column',
      background: '#000', borderRadius: 'var(--radius-lg)',
      margin: 'var(--space-4)', overflow: 'hidden', position: 'relative', minWidth: 0,
    }}>
      {/* ROI 编辑切换按钮 */}
      {phase === 'setup' && streamUrl && (
        <div style={{ position: 'absolute', top: 'var(--space-3)', right: 'var(--space-3)', zIndex: 10, display: 'flex', gap: 'var(--space-2)' }}>
          <button onClick={onToggleEditMode} style={{
            padding: '4px 12px', borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)',
            background: editMode ? 'var(--primary)' : 'rgba(0,0,0,0.6)',
            color: '#fff', fontSize: 'var(--text-xs)', cursor: 'pointer',
            fontFamily: 'inherit', backdropFilter: 'blur(4px)',
          }}>
            {editMode ? '✓ 完成框选' : '✂️ 配置检测区域'}
          </button>
        </div>
      )}

      {/* 视频 / ROI编辑 */}
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
        {isRoiEdit ? (
          <RoiEditView streamUrl={streamUrl} roiConfig={roiConfig} onChangeRoiConfig={onChangeRoiConfig} />
        ) : src ? (
          <video key={src} src={src} controls preload="metadata"
            style={{ maxWidth: '100%', maxHeight: '100%', borderRadius: 'var(--radius-md)' }} />
        ) : (
          <EmptyState />
        )}
      </div>

      {phase === 'result' && clips?.length > 0 && (
        <ClipTimeline clips={clips} currentIndex={currentClipIndex} onSelect={onSelectClip} onReorder={onReorderClips} taskId={taskId} />
      )}
      {phase !== 'result' && !isRoiEdit && (
        <SegmentTimeline segments={segments} totalDuration={totalDuration} />
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════
// ROI 编辑视图 — Canvas + 拖拽画矩形 + 调整 + 显示已有ROI
// ═══════════════════════════════════════════════════════

const ROI_COLORS = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']
const HANDLE_R = 6

function RoiEditView({ streamUrl, roiConfig, onChangeRoiConfig }) {
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const containerRef = useRef(null)
  const [loaded, setLoaded] = useState(false)
  const [seekTime, setSeekTime] = useState(60)
  const [duration, setDuration] = useState(0)

  // ROI 类型列表
  const [roiTypes, setRoiTypes] = useState([])
  useEffect(() => { fetch('/api/roi-types').then(r => r.json()).then(d => { if (d.success) setRoiTypes(d.types) }).catch((e) => console.warn('获取 ROI 类型列表失败:', e)) }, [])

  // 绘图状态
  const [drawing, setDrawing] = useState(false)
  const [drawStart, setDrawStart] = useState(null)
  const [drawRect, setDrawRect] = useState(null)
  const [selectedIdx, setSelectedIdx] = useState(-1)
  const [dragMode, setDragMode] = useState(null)
  const [dragStart, setDragStart] = useState(null)
  const [dragOrigRect, setDragOrigRect] = useState(null)

  // 浮窗状态
  const [popupIdx, setPopupIdx] = useState(-1)  // 当前编辑的 ROI 索引
  const [popupPos, setPopupPos] = useState(null) // 浮窗位置

  // 加载视频
  useEffect(() => {
    const vid = videoRef.current
    if (!vid) return
    const onMeta = () => { setDuration(vid.duration); vid.currentTime = Math.min(seekTime, vid.duration - 1) }
    const onSeeked = () => { drawAll(); setLoaded(true) }
    vid.addEventListener('loadedmetadata', onMeta)
    vid.addEventListener('seeked', onSeeked)
    return () => { vid.removeEventListener('loadedmetadata', onMeta); vid.removeEventListener('seeked', onSeeked) }
  }, [streamUrl])

  const getCanvasCtx = () => canvasRef.current?.getContext('2d')
  const getContainerSize = () => containerRef.current ? { w: containerRef.current.clientWidth, h: containerRef.current.clientHeight } : { w: 0, h: 0 }

  // 绘制全部
  const drawAll = useCallback(() => {
    const vid = videoRef.current; const cvs = canvasRef.current; const sz = getContainerSize()
    if (!vid || !cvs || !sz.w) return
    const vw = vid.videoWidth; const vh = vid.videoHeight
    if (!vw || !vh) return
    const scale = Math.min(sz.w / vw, sz.h / vh)
    const dw = vw * scale; const dh = vh * scale
    const ox = (sz.w - dw) / 2; const oy = (sz.h - dh) / 2

    cvs.width = sz.w; cvs.height = sz.h
    const ctx = cvs.getContext('2d')
    ctx.drawImage(vid, ox, oy, dw, dh)

    // 绘制已有 ROI
    roiConfig.forEach((roi, i) => {
      const r = roi.rect; const rx = ox + r.x * dw; const ry = oy + r.y * dh
      const rw = r.w * dw; const rh = r.h * dh
      const color = ROI_COLORS[i % ROI_COLORS.length]
      ctx.strokeStyle = color; ctx.lineWidth = 2
      ctx.strokeRect(rx, ry, rw, rh)
      ctx.fillStyle = color + '20'; ctx.fillRect(rx, ry, rw, rh)
      // 标签
      ctx.fillStyle = color; ctx.font = '11px Inter, sans-serif'
      const label = roi.label || `ROI ${i + 1}`; const tw = ctx.measureText(label).width
      ctx.fillRect(rx, ry - 18, tw + 8, 18)
      ctx.fillStyle = '#fff'; ctx.fillText(label, rx + 4, ry - 5)
      // 选中态 + 手柄
      if (i === selectedIdx) {
        ctx.strokeStyle = '#fff'; ctx.lineWidth = 1; ctx.setLineDash([4, 4])
        ctx.strokeRect(rx - 2, ry - 2, rw + 4, rh + 4); ctx.setLineDash([])
        drawHandles(ctx, rx, ry, rw, rh, HANDLE_R)
      }
    })

    // 正在画的矩形
    if (drawRect) {
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.setLineDash([6, 3])
      ctx.strokeRect(drawRect.x, drawRect.y, drawRect.w, drawRect.h); ctx.setLineDash([])
    }
  }, [roiConfig, selectedIdx, drawRect])

  useEffect(() => { if (loaded) drawAll() }, [loaded, roiConfig, selectedIdx, drawRect])

  // px → 百分比坐标
  const pxToPct = useCallback((px, py) => {
    const sz = getContainerSize(); const vid = videoRef.current
    const vw = vid?.videoWidth || 1920; const vh = vid?.videoHeight || 1080
    const scale = Math.min(sz.w / vw, sz.h / vh)
    const ox = (sz.w - vw * scale) / 2; const oy = (sz.h - vh * scale) / 2
    return {
      x: Math.max(0, Math.min(1, (px - ox) / (vw * scale))),
      y: Math.max(0, Math.min(1, (py - oy) / (vh * scale))),
    }
  }, [])

  // ── 鼠标事件 ──
  const getPos = (e) => { const r = canvasRef.current?.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top } }

  const hitHandle = (px, py) => {
    const sz = getContainerSize(); const vid = videoRef.current
    const vw = vid?.videoWidth || 1920; const vh = vid?.videoHeight || 1080
    const scale = Math.min(sz.w / vw, sz.h / vh)
    const ox = (sz.w - vw * scale) / 2; const oy = (sz.h - vh * scale) / 2
    for (let i = roiConfig.length - 1; i >= 0; i--) {
      const r = roiConfig[i].rect; const rx = ox + r.x * vw * scale; const ry = oy + r.y * vh * scale
      const rw = r.w * vw * scale; const rh = r.h * vh * scale
      const handles = { nw: [rx, ry], ne: [rx + rw, ry], sw: [rx, ry + rh], se: [rx + rw, ry + rh] }
      for (const [k, [hx, hy]] of Object.entries(handles)) {
        if (Math.abs(px - hx) < HANDLE_R + 4 && Math.abs(py - hy) < HANDLE_R + 4) return { idx: i, mode: 'resize-' + k }
      }
      if (px >= rx && px <= rx + rw && py >= ry && py <= ry + rh) return { idx: i, mode: 'move' }
    }
    return null
  }

  const onMouseDown = (e) => {
    const p = getPos(e); const hit = hitHandle(p.x, p.y)
    if (hit) {
      setSelectedIdx(hit.idx); setDragMode(hit.mode); setDragStart(p)
      const sz = getContainerSize(); const vid = videoRef.current
      const vw = vid?.videoWidth || 1920; const vh = vid?.videoHeight || 1080
      const scale = Math.min(sz.w / vw, sz.h / vh)
      const ox = (sz.w - vw * scale) / 2; const oy = (sz.h - vh * scale) / 2
      const r = roiConfig[hit.idx].rect
      setDragOrigRect({ x: ox + r.x * vw * scale, y: oy + r.y * vh * scale, w: r.w * vw * scale, h: r.h * vh * scale })
    } else {
      setSelectedIdx(-1); setDrawing(true); setDrawStart(p); setDrawRect({ x: p.x, y: p.y, w: 0, h: 0 })
    }
  }

  const onMouseMove = (e) => {
    const p = getPos(e)
    if (drawing && drawStart) {
      setDrawRect({ x: Math.min(p.x, drawStart.x), y: Math.min(p.y, drawStart.y), w: Math.abs(p.x - drawStart.x), h: Math.abs(p.y - drawStart.y) })
    } else if (dragMode && dragOrigRect && dragStart) {
      const dx = p.x - dragStart.x; const dy = p.y - dragStart.y
      let nr = { ...dragOrigRect }
      if (dragMode === 'move') { nr.x += dx; nr.y += dy }
      else if (dragMode === 'resize-nw') { nr.x += dx; nr.y += dy; nr.w -= dx; nr.h -= dy }
      else if (dragMode === 'resize-ne') { nr.y += dy; nr.w += dx; nr.h -= dy }
      else if (dragMode === 'resize-sw') { nr.x += dx; nr.w -= dx; nr.h += dy }
      else if (dragMode === 'resize-se') { nr.w += dx; nr.h += dy }
      if (nr.w < 10) nr.w = 10; if (nr.h < 10) nr.h = 10
      // 更新当前 ROI
      const pct = pxToPct(nr.x, nr.y); const pct2 = pxToPct(nr.x + nr.w, nr.y + nr.h)
      const updated = [...roiConfig]
      updated[selectedIdx] = { ...updated[selectedIdx], rect: { x: pct.x, y: pct.y, w: Math.max(0.01, pct2.x - pct.x), h: Math.max(0.01, pct2.y - pct.y) } }
      onChangeRoiConfig(updated)
    } else {
      const hit = hitHandle(p.x, p.y)
      canvasRef.current.style.cursor = hit ? (hit.mode === 'move' ? 'move' : hit.mode.includes('nw') || hit.mode.includes('se') ? 'nwse-resize' : 'nesw-resize') : 'crosshair'
    }
  }

  const onMouseUp = (e) => {
    if (drawing && drawRect && drawRect.w > 5 && drawRect.h > 5) {
      const p1 = pxToPct(drawRect.x, drawRect.y); const p2 = pxToPct(drawRect.x + drawRect.w, drawRect.y + drawRect.h)
      const newRoi = {
        type_id: 'kills_assists',
        rect: { x: p1.x, y: p1.y, w: Math.max(0.01, p2.x - p1.x), h: Math.max(0.01, p2.y - p1.y) },
        label: '', custom_instruction: '',
      }
      const updated = [...roiConfig, newRoi]
      onChangeRoiConfig(updated)
      // 弹出浮窗编辑
      const idx = updated.length - 1
      setSelectedIdx(idx)
      const p = getPos(e)
      setPopupPos({ x: Math.min(p.x + 10, (containerRef.current?.clientWidth || 400) - 240), y: Math.min(p.y - 10, (containerRef.current?.clientHeight || 300) - 300) })
      setPopupIdx(idx)
    }
    setDrawing(false); setDrawStart(null); setDrawRect(null)
    setDragMode(null); setDragStart(null); setDragOrigRect(null)
  }

  // 双击已有 ROI → 编辑
  const onDoubleClick = (e) => {
    const p = getPos(e); const hit = hitHandle(p.x, p.y)
    if (hit) {
      setPopupIdx(hit.idx); setSelectedIdx(hit.idx)
      setPopupPos({ x: Math.min(p.x + 10, (containerRef.current?.clientWidth || 400) - 240), y: Math.min(p.y - 10, (containerRef.current?.clientHeight || 300) - 300) })
    }
  }

  const handleSeek = (t) => { setSeekTime(t); setLoaded(false); if (videoRef.current) videoRef.current.currentTime = t }

  // 删除 ROI
  const deleteRoi = (idx) => {
    onChangeRoiConfig(roiConfig.filter((_, i) => i !== idx))
    setPopupIdx(-1); setSelectedIdx(-1)
  }

  // 更新当前编辑 ROI 的字段
  const updateRoi = (idx, patch) => {
    const updated = [...roiConfig]
    updated[idx] = { ...updated[idx], ...patch }
    onChangeRoiConfig(updated)
  }

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', position: 'relative' }}>
      <video ref={videoRef} src={streamUrl} crossOrigin="anonymous" preload="metadata" style={{ display: 'none' }} />
      <canvas ref={canvasRef} onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={onMouseUp} onMouseLeave={onMouseUp} onDoubleClick={onDoubleClick}
        style={{ width: '100%', height: '100%', display: loaded ? 'block' : 'none', cursor: 'crosshair' }} />
      {!loaded && <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--muted-foreground)' }}><span>⏳ 加载视频帧...</span></div>}
      {loaded && duration > 0 && (
        <div style={{ position: 'absolute', bottom: 'var(--space-4)', left: '50%', transform: 'translateX(-50%)', width: '80%', maxWidth: 400, display: 'flex', alignItems: 'center', gap: 'var(--space-3)', background: 'rgba(0,0,0,0.7)', borderRadius: 'var(--radius-md)', padding: 'var(--space-2) var(--space-4)', backdropFilter: 'blur(8px)' }}>
          <span style={{ color: 'var(--muted-foreground)', fontSize: 'var(--text-xs)', minWidth: 48 }}>{fmtTime(seekTime)}</span>
          <input type="range" min={0} max={Math.floor(duration)} value={seekTime} onChange={e => handleSeek(Number(e.target.value))} style={{ flex: 1, accentColor: 'var(--primary)' }} />
          <span style={{ color: 'var(--muted-foreground)', fontSize: 'var(--text-xs)', minWidth: 48, textAlign: 'right' }}>{fmtTime(duration)}</span>
        </div>
      )}
      {loaded && roiConfig.length === 0 && (
        <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', color: 'rgba(255,255,255,0.15)', fontSize: 'var(--text-2xl)', fontWeight: 'var(--font-semibold)', pointerEvents: 'none', userSelect: 'none' }}>拖拽框选检测区域</div>
      )}

      {/* ═══ ROI 编辑浮窗 ═══ */}
      {popupIdx >= 0 && popupIdx < roiConfig.length && popupPos && (
        <RoiPopup
          roi={roiConfig[popupIdx]}
          types={roiTypes}
          pos={popupPos}
          onChange={(patch) => updateRoi(popupIdx, patch)}
          onDelete={() => deleteRoi(popupIdx)}
          onClose={() => { setPopupIdx(-1); setPopupPos(null) }}
        />
      )}
    </div>
  )
}

function drawHandles(ctx, x, y, w, h, r) {
  const handles = [[x, y], [x + w, y], [x, y + h], [x + w, y + h],
  [x + w / 2, y], [x + w / 2, y + h], [x, y + h / 2], [x + w, y + h / 2]]
  handles.forEach(([hx, hy]) => { ctx.fillStyle = '#fff'; ctx.fillRect(hx - r / 2, hy - r / 2, r, r); ctx.strokeStyle = '#6366f1'; ctx.lineWidth = 1; ctx.strokeRect(hx - r / 2, hy - r / 2, r, r) })
}

// ═══════════════════════════════════════════════════════
// ROI 编辑浮窗
// ═══════════════════════════════════════════════════════

function RoiPopup({ roi, types, pos, onChange, onDelete, onClose }) {
  const [typeId, setTypeId] = useState(roi.type_id || 'kills_assists')
  const [label, setLabel] = useState(roi.label || '')
  const [customInst, setCustomInst] = useState(roi.custom_instruction || '')

  const selectedType = types.find(t => t.id === typeId)
  const instruction = (typeId === 'custom') ? customInst : (selectedType?.instruction || '')

  const handleTypeChange = (tid) => {
    setTypeId(tid)
    onChange({ type_id: tid, custom_instruction: tid === 'custom' ? customInst : '' })
  }

  const handleLabelBlur = () => { onChange({ label }) }
  const handleInstBlur = () => { onChange({ custom_instruction: customInst }) }

  return (
    <div onClick={e => e.stopPropagation()} style={{
      position: 'absolute', left: pos.x, top: pos.y, zIndex: 20,
      width: 230, background: 'var(--popover)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius-md)', padding: 'var(--space-3)', boxShadow: 'var(--shadow-lg)',
      display: 'flex', flexDirection: 'column', gap: 'var(--space-2)',
    }}>
      {/* 标题栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)', color: 'var(--foreground)' }}>
          {selectedType?.icon} {selectedType?.name || '选择类型'}
        </span>
        <div style={{ display: 'flex', gap: 4 }}>
          <button onClick={onDelete} title="删除" style={{ background: 'none', border: 'none', color: 'var(--destructive)', cursor: 'pointer', fontSize: 14, padding: '0 2px' }}>✕</button>
          <button onClick={onClose} title="关闭" style={{ background: 'none', border: 'none', color: 'var(--muted-foreground)', cursor: 'pointer', fontSize: 14, padding: '0 2px' }}>×</button>
        </div>
      </div>

      {/* 类型选择 */}
      <select value={typeId} onChange={e => handleTypeChange(e.target.value)} style={{
        width: '100%', padding: 'var(--space-1) var(--space-2)',
        background: 'var(--background)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius-sm)', color: 'var(--foreground)', fontSize: 'var(--text-xs)', fontFamily: 'inherit',
      }}>
        {types.map(t => <option key={t.id} value={t.id}>{t.icon} {t.name}</option>)}
      </select>

      {/* 名称 */}
      <input value={label} onChange={e => setLabel(e.target.value)} onBlur={handleLabelBlur}
        placeholder="名称（可选）" style={{
          width: '100%', padding: 'var(--space-1) var(--space-2)',
          background: 'var(--background)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', color: 'var(--foreground)', fontSize: 'var(--text-xs)', fontFamily: 'inherit',
        }} />

      {/* 指令预览/编辑 */}
      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)', lineHeight: 1.4, maxHeight: 48, overflow: 'hidden' }}>
        {instruction || '（无指令）'}
      </div>

      {/* 自定义指令（仅 custom 类型显示） */}
      {typeId === 'custom' && (
        <textarea value={customInst} onChange={e => setCustomInst(e.target.value)} onBlur={handleInstBlur}
          placeholder="写一句简短指令，告诉 AI 这个区域要看什么..."
          rows={2} style={{
            width: '100%', padding: 'var(--space-1) var(--space-2)',
            background: 'var(--background)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)', color: 'var(--foreground)', fontSize: 'var(--text-xs)', fontFamily: 'inherit',
            resize: 'vertical',
          }} />
      )}
    </div>
  )
}

function EmptyState() {
  return (
    <div style={{ textAlign: 'center', color: 'var(--muted-foreground)', userSelect: 'none' }}>
      <div style={{ fontSize: 48, marginBottom: 'var(--space-4)' }}></div>
      <div style={{ fontSize: 'var(--text-lg)', fontWeight: 'var(--font-medium)', color: 'var(--muted-foreground)' }}>拖拽视频或从素材库选择</div>
      <div style={{ fontSize: 'var(--text-sm)', marginTop: 'var(--space-2)' }}>支持 MP4 / MOV / AVI / MKV / FLV</div>
    </div>
  )
}
function fmtTime(s) { const m = Math.floor(s / 60); const sec = Math.floor(s % 60); return `${m}:${String(sec).padStart(2, '0')}` }

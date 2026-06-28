import { useState, useRef, useEffect } from 'react'

const fmtSize = (mb) => mb >= 1024 ? `${(mb / 1024).toFixed(1)}GB` : `${mb}MB`

const inputStyle = {
  width: '100%',
  padding: 'var(--space-2) var(--space-3)',
  background: 'var(--background)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-sm)',
  color: 'var(--foreground)',
  fontSize: 'var(--text-sm)',
  transition: 'border-color var(--transition-fast)',
}

export default function SetupPanel({
  materials, loadingLib, loadMaterials,
  videoPath, setVideoPath, fileName, setFileName,
  requirement, setRequirement,
  keyVerified, uploadError, setUploadError,
  downloadUrl,
  outputName, setOutputName,
  onDirectStart,
  resultStreamUrl, setResultStreamUrl,
  // ── ROI 配置（v2）──
  roiConfig, editMode, onToggleEditMode, onChangeRoiConfig,
}) {
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef(null)
  const renameInputRef = useRef(null)

  // ── 重命名 ──
  const [renamingPath, setRenamingPath] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [renamingBusy, setRenamingBusy] = useState(false)

  const startRename = (mat) => {
    setRenamingPath(mat.path)
    setRenameValue(mat.filename)
    setTimeout(() => renameInputRef.current?.focus(), 0)
  }

  const cancelRename = () => {
    setRenamingPath(null)
    setRenameValue('')
  }

  const submitRename = async () => {
    if (!renamingPath || !renameValue.trim() || renamingBusy) return
    const oldFilename = renamingPath.replace(/\\/g, '/').split('/').pop()
    if (renameValue.trim() === oldFilename) { cancelRename(); return }
    setRenamingBusy(true)
    try {
      const resp = await fetch(`/api/materials/${encodeURIComponent(oldFilename)}/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: renameValue.trim() }),
      })
      if (resp.ok) {
        if (loadMaterials) await loadMaterials()
      }
    } catch (e) { console.warn('重命名素材失败:', e) }
    setRenamingBusy(false)
    cancelRename()
  }

  const handleRenameKey = (e) => {
    if (e.key === 'Enter') submitRename()
    if (e.key === 'Escape') cancelRename()
  }

  // ── 上传 ──
  const handleFile = async (file) => {
    setUploading(true)
    setUploadError('')
    const form = new FormData()
    form.append('file', file)
    try {
      const resp = await fetch('/api/upload', { method: 'POST', body: form })
      if (!resp.ok) {
        let err = `HTTP ${resp.status}`
        try { const d = await resp.json(); err = d.detail || err } catch (e) { console.warn('解析上传错误响应失败:', e) }
        setUploadError(err)
        setUploading(false)
        return
      }
      const data = await resp.json()
      if (data.success) {
        setVideoPath(data.video_path)
        setFileName(file.name)
        if (loadMaterials) await loadMaterials()
      } else {
        setUploadError(data.error || '上传失败')
      }
    } catch (e) {
      setUploadError(`网络错误: ${e.message}`)
    }
    setUploading(false)
  }

  // ── 本地路径输入 ──
  const [pathInput, setPathInput] = useState('')
  const handlePathSubmit = async () => {
    const p = pathInput.trim()
    if (!p) return
    setUploadError('')
    try {
      const resp = await fetch('/api/validate-path', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: p }),
      })
      if (!resp.ok) {
        const d = await resp.json().catch(() => ({}))
        setUploadError(d.detail || '路径无效')
        return
      }
      const data = await resp.json()
      if (data.success) {
        setVideoPath(data.video_path)
        setFileName(data.filename)
      }
    } catch (e) {
      setUploadError(`网络错误: ${e.message}`)
    }
  }

  const handleDeleteMaterial = async (mat) => {
    if (!confirm(`删除「${mat.filename}」？`)) return
    try {
      await fetch(`/api/materials/${encodeURIComponent(mat.filename)}`, { method: 'DELETE' })
      if (videoPath === mat.path) { setVideoPath(''); setFileName('') }
      if (loadMaterials) await loadMaterials()
    } catch (e) { console.warn('删除素材失败:', e) }
  }

  // ── 素材库选择 ──
  const selectMaterial = (mat) => {
    setVideoPath(mat.path)
    setFileName(mat.filename)
  }

  const handleDragOver = (e) => { e.preventDefault(); setDragOver(true) }
  const handleDragLeave = () => setDragOver(false)
  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
      {/* ═══════════════ 上传区（始终可见）═══════════════ */}
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        style={{
          border: `2px dashed ${dragOver ? 'var(--primary)' : 'var(--border)'}`,
          borderRadius: 'var(--radius-md)', padding: 'var(--space-4)', textAlign: 'center',
          cursor: 'pointer', background: dragOver ? 'var(--primary)' : 'var(--background)',
          transition: 'all var(--transition-fast)',
        }}
      >
        <div style={{ fontSize: 24, marginBottom: 'var(--space-1)' }}>{uploading ? '⏳' : '📁'}</div>
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)' }}>
          {uploading ? '上传中...' : '拖拽或点击上传视频'}
        </div>
        <div style={{ fontSize: 10, color: 'var(--muted-foreground)', marginTop: 2 }}>MP4 / MOV / AVI / MKV / FLV</div>
      </div>
      <input ref={inputRef} type="file" accept="video/*" style={{ display: 'none' }}
        onChange={e => { const f = e.target.files[0]; if (f) handleFile(f) }} />
      {uploadError && (
        <div style={{ padding: 'var(--space-2) var(--space-3)', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 'var(--radius-sm)', fontSize: 'var(--text-xs)', color: 'var(--destructive)' }}>{uploadError}</div>
      )}

      {/* 本地路径快捷输入 */}
      <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
        <input value={pathInput} onChange={e => setPathInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handlePathSubmit()}
          placeholder="或输入视频路径，如 D:\video\game.mp4"
          style={{
            flex: 1, padding: 'var(--space-1) var(--space-2)',
            background: 'var(--background)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)', color: 'var(--foreground)',
            fontSize: 10, fontFamily: 'inherit',
          }} />
        <button onClick={handlePathSubmit} style={{
          padding: 'var(--space-1) var(--space-2)', background: 'var(--card)',
          color: 'var(--muted-foreground)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', fontSize: 10, cursor: 'pointer', fontFamily: 'inherit',
        }}>确认</button>
      </div>

      {/* ═══════════════ 最新结果卡片 ═══════════════ */}
      {downloadUrl && (
        <div style={{ padding: 'var(--space-3)', background: 'var(--background)', border: '1px solid var(--success)', borderRadius: 'var(--radius-md)' }}>
          <div style={{ fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)', color: 'var(--success)', marginBottom: 'var(--space-2)' }}>✅ 处理完成</div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--foreground)', marginBottom: 'var(--space-2)' }} className="truncate">{fileName || '视频'} 已处理完成</div>
          <button onClick={() => window.open(downloadUrl)} style={{
            padding: 'var(--space-1) var(--space-3)', background: 'var(--success)', color: '#fff',
            border: 'none', borderRadius: 'var(--radius-sm)', fontSize: 'var(--text-xs)', cursor: 'pointer', fontFamily: 'inherit',
          }}>▶ 播放成品</button>
        </div>
      )}

      {/* ═══════════════ 素材库 ═══════════════ */}
      <div>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-semibold)', marginBottom: 'var(--space-2)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span> 素材库</span>
          <button onClick={() => {
            fetch('/api/tasks/open-material-folder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: (materials[0] || {}).path || '' }) }).catch((e) => console.warn('打开素材文件夹失败:', e))
          }} title="打开素材文件夹" style={{
            fontSize: 10, color: 'var(--muted-foreground)', cursor: 'pointer',
            border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
            padding: '2px 6px', background: 'var(--background)', fontFamily: 'inherit',
          }}>📂 打开文件夹</button>
        </div>
        <div style={{ maxHeight: 200, overflowY: 'auto' }}>
          {loadingLib ? (
            <div style={{ textAlign: 'center', padding: 'var(--space-4)', color: 'var(--muted-foreground)', fontSize: 'var(--text-sm)' }}>加载中...</div>
          ) : !materials || materials.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 'var(--space-6) var(--space-4)', color: 'var(--muted-foreground)', fontSize: 'var(--text-sm)' }}>
              <div style={{ fontSize: 36, marginBottom: 'var(--space-3)', opacity: 0.3 }}>📂</div>
              <div style={{ marginBottom: 'var(--space-1)', fontWeight: 'var(--font-medium)' }}>暂无素材</div>
              <div style={{ fontSize: 10, lineHeight: 1.6 }}>
                拖拽视频文件到上方虚线框<br />或点击选择文件上传
              </div>
            </div>
          ) : (
            materials.map(mat => {
              const isRenaming = renamingPath === mat.path
              const isSelected = videoPath === mat.path
              return (
              <div key={mat.path} onClick={() => { if (!isRenaming) selectMaterial(mat) }}
                style={{
                  padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-sm)',
                  cursor: isRenaming ? 'default' : 'pointer',
                  background: isSelected ? 'var(--primary)' : 'transparent',
                  border: isSelected ? '1px solid var(--primary)' : '1px solid transparent',
                  borderLeft: isSelected ? '3px solid var(--primary)' : '3px solid transparent',
                  marginBottom: 2, transition: 'all var(--transition-fast)',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-2)',
                }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {isRenaming ? (
                    <input ref={renameInputRef} value={renameValue} onChange={e => setRenameValue(e.target.value)}
                      onKeyDown={handleRenameKey} onBlur={submitRename} disabled={renamingBusy}
                      onClick={e => e.stopPropagation()}
                      style={{ ...inputStyle, fontSize: 'var(--text-sm)', padding: 'var(--space-1) var(--space-2)' }} />
                  ) : (
                    <>
                      <div style={{ fontSize: 'var(--text-sm)', fontWeight: isSelected ? 'var(--font-medium)' : 'var(--font-normal)' }} className="truncate">{mat.filename}</div>
                      <div style={{ fontSize: 10, color: 'var(--muted-foreground)', marginTop: 2 }}>{fmtSize(mat.size_mb)} · {mat.date}</div>
                    </>
                  )}
                </div>
                {!isRenaming && (
                  <div style={{ display: 'flex', gap: 2, flexShrink: 0 }}>
                    <button onClick={e => { e.stopPropagation(); startRename(mat) }} title="重命名"
                      style={{ width: 24, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 4, cursor: 'pointer', color: 'var(--muted-foreground)', fontSize: 12 }}>✏️</button>
                    <button onClick={e => { e.stopPropagation(); handleDeleteMaterial(mat) }} title="删除"
                      style={{ width: 24, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 4, cursor: 'pointer', color: 'var(--destructive)', fontSize: 12 }}>🗑️</button>
                  </div>
                )}
              </div>
            )})
          )}
        </div>
      </div>

      <div style={{ borderTop: '1px solid var(--border)' }} />

      {/* ═══════════════ ROI 检测区域（v2）═══════════════ */}
      {videoPath && (
        <div>
          <div style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-semibold)', marginBottom: 'var(--space-3)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <span>🔍 ROI 检测区域</span>
            {roiConfig.length > 0 && <span style={{ fontSize: 10, color: 'var(--primary)', background: 'var(--accent)', padding: '1px 6px', borderRadius: 10 }}>{roiConfig.length}</span>}
          </div>

          {/* ROI 列表 */}
          {roiConfig.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 'var(--space-3)' }}>
              {roiConfig.map((roi, i) => {
                const typeIcon = { kills_assists: '💀', total_damage: '📊', kill_feed: '☠️' }[roi.type_id] || '❓'
                const label = roi.label || `ROI ${i + 1}`
                return (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                    padding: 'var(--space-1) var(--space-2)',
                    background: 'var(--background)', borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border)', fontSize: 'var(--text-xs)',
                  }}>
                    <span>{typeIcon}</span>
                    <span style={{ flex: 1, color: 'var(--foreground)' }}>{label}</span>
                    <span style={{ color: 'var(--muted-foreground)', fontSize: 10 }}>
                      {(roi.rect.w * 100).toFixed(0)}% × {(roi.rect.h * 100).toFixed(0)}%
                    </span>
                  </div>
                )
              })}
            </div>
          ) : (
            <div style={{ marginBottom: 'var(--space-3)', padding: 'var(--space-3)', background: 'var(--background)', border: '1px dashed var(--border)', borderRadius: 'var(--radius-md)', textAlign: 'center' }}>
              <div style={{ fontSize: 'var(--text-sm)', color: 'var(--muted-foreground)', marginBottom: 'var(--space-2)' }}>
                尚未配置检测区域
              </div>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)', marginBottom: 'var(--space-2)' }}>
                点击右上角 [✂️ 配置检测区域] 在视频上框选
              </div>
              <div style={{ fontSize: 10, color: 'var(--warning)', background: 'rgba(245,158,11,0.1)', padding: 'var(--space-1) var(--space-2)', borderRadius: 'var(--radius-sm)', display: 'inline-block' }}>
                💡 配置检测区域可大幅提高战斗识别准确率，无 ROI 时使用默认统计面板识别精度较低
              </div>
            </div>
          )}

          {/* 编辑按钮 */}
          <div style={{ display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-3)' }}>
            <button onClick={onToggleEditMode} style={{
              flex: 1, padding: 'var(--space-2)',
              background: editMode ? 'var(--primary)' : 'var(--background)',
              color: editMode ? '#fff' : 'var(--muted-foreground)',
              border: '1px solid ' + (editMode ? 'var(--primary)' : 'var(--border)'),
              borderRadius: 'var(--radius-sm)', fontSize: 'var(--text-xs)',
              cursor: 'pointer', fontFamily: 'inherit',
            }}>
              {editMode ? '✓ 完成框选' : '✂️ 编辑区域'}
            </button>
            {roiConfig.length > 0 && (
              <button onClick={() => {
                const name = prompt('模板名称（如：Apex 标准、Valorant）')
                if (!name) return
                const templates = JSON.parse(localStorage.getItem('apexcut_roi_templates') || '{}')
                templates[name] = { name, date: new Date().toISOString(), rois: roiConfig }
                localStorage.setItem('apexcut_roi_templates', JSON.stringify(templates))
                alert(`已保存模板「${name}」`)
              }} style={{
                padding: 'var(--space-2) var(--space-3)',
                background: 'var(--background)', color: 'var(--success)',
                border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                fontSize: 'var(--text-xs)', cursor: 'pointer', fontFamily: 'inherit',
              }}>
                💾 保存
              </button>
            )}
            <LoadTemplateButton onLoad={(rois) => onChangeRoiConfig(rois)} />
          </div>
        </div>
      )}
      {videoPath && <div style={{ borderTop: '1px solid var(--border)', marginBottom: 0 }} />}

      {/* ═══════════════ 剪辑需求（v2）═══════════════ */}
      <div>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-semibold)', marginBottom: 'var(--space-3)' }}>
          ✍️ 剪辑需求
        </div>
        <textarea
          value={requirement}
          onChange={e => {
            setRequirement(e.target.value)
            // 关键词联动策略预设
            const v = e.target.value
            if (/快节奏|短视频|60秒|抖音|shorts/i.test(v)) { setPaddingBefore(5); setPaddingAfter(3); setMergeGap(3); setMinSegment(2); setMinDamage(80) }
            else if (/残血|反杀|高光|精华/i.test(v)) { setPaddingBefore(15); setPaddingAfter(10); setMergeGap(8); setMinSegment(3); setMinDamage(30) }
            else if (/完整|全部|整局|全片/i.test(v)) { setPaddingBefore(25); setPaddingAfter(20); setMergeGap(12); setMinSegment(5); setMinDamage(30) }
            else if (/击杀|集锦/i.test(v)) { setPaddingBefore(12); setPaddingAfter(8); setMergeGap(6); setMinSegment(3); setMinDamage(50) }
            else if (/教学|复盘/i.test(v)) { setPaddingBefore(40); setPaddingAfter(30); setMergeGap(20); setMinSegment(5); setMinDamage(10) }
          }}
          placeholder="例如：保留所有击杀，快节奏2分钟"
          rows={2}
          style={{
            width: '100%', padding: 'var(--space-2) var(--space-3)',
            background: 'var(--background)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)', color: 'var(--foreground)',
            fontSize: 'var(--text-sm)', fontFamily: 'inherit', resize: 'vertical',
            lineHeight: 1.5,
          }}
        />
        {/* 快捷标签 */}
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 'var(--space-2)' }}>
          {[
            { label: '🎯 击杀集锦', text: '保留所有击杀，快节奏' },
            { label: '💀 残血反杀', text: '只要残血反杀高光时刻' },
            { label: '⚔️ 完整对局', text: '保留完整对局，按时间顺序' },
            { label: '⚡ 60秒快剪', text: '剪成60秒短视频，快节奏' },
          ].map(tag => (
            <button key={tag.label} onClick={() => setRequirement(tag.text)} style={{
              padding: '2px 8px', fontSize: 10, borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border)', cursor: 'pointer',
              background: requirement === tag.text ? 'var(--primary)' : 'var(--card)',
              color: 'var(--muted-foreground)', fontFamily: 'inherit',
            }}>{tag.label}</button>
          ))}
        </div>
      </div>

      {/* ═══════════════ 启动 ═══════════════ */}
      {/* 输出命名 */}
      <div style={{ marginBottom: 'var(--space-3)' }}>
        <label style={{ fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>
           输出文件名（可选）
        </label>
        <input
          value={outputName}
          onChange={e => setOutputName(e.target.value)}
          placeholder={fileName ? fileName.replace(/\.[^.]+$/, '') + '_高光' : '自动命名'}
          style={{
            ...inputStyle,
            fontSize: 'var(--text-sm)',
          }}
        />
      </div>

      {onDirectStart && (
        <button
          onClick={() => onDirectStart()}
          disabled={!keyVerified || !videoPath}
          style={{
            width: '100%',
            padding: 'var(--space-3) var(--space-4)',
            background: (!keyVerified || !videoPath) ? 'var(--border)' : 'var(--primary)',
            color: '#fff',
            border: 'none',
            borderRadius: 'var(--radius-md)',
            fontSize: 'var(--text-base)',
            fontWeight: 'var(--font-semibold)',
            cursor: (!keyVerified || !videoPath) ? 'not-allowed' : 'pointer',
            transition: 'all var(--transition-fast)',
            opacity: (!keyVerified || !videoPath) ? 0.5 : 1,
          }}
        >
           开始剪辑
        </button>
      )}

    </div>
  )
}

function LoadTemplateButton({ onLoad }) {
  const [templates, setTemplates] = useState({})
  const [open, setOpen] = useState(false)

  useEffect(() => {
    try { setTemplates(JSON.parse(localStorage.getItem('apexcut_roi_templates') || '{}')) } catch {}
  }, [open])

  const names = Object.keys(templates)
  if (names.length === 0) return null

  return (
    <div style={{ position: 'relative' }}>
      <button onClick={() => setOpen(!open)} style={{
        padding: 'var(--space-2) var(--space-3)',
        background: 'var(--background)', color: 'var(--muted-foreground)',
        border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
        fontSize: 'var(--text-xs)', cursor: 'pointer', fontFamily: 'inherit',
        whiteSpace: 'nowrap',
      }}>
        📂 加载
      </button>
      {open && (
        <div onClick={e => e.stopPropagation()} style={{
          position: 'absolute', bottom: '100%', right: 0, marginBottom: 4, zIndex: 30,
          width: 200, background: 'var(--popover)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-lg)', overflow: 'hidden',
        }}>
          {names.map(name => (
            <div key={name} onClick={() => {
              if (confirm(`加载模板「${name}」？当前 ROI 将被替换`)) {
                onLoad(templates[name].rois)
              }
              setOpen(false)
            }} style={{
              padding: 'var(--space-2) var(--space-3)', cursor: 'pointer',
              fontSize: 'var(--text-xs)', color: 'var(--foreground)',
              borderBottom: '1px solid var(--border)',
            }} onMouseEnter={e => e.target.style.background = 'var(--primary)'}
               onMouseLeave={e => e.target.style.background = 'transparent'}>
              {name}
            </div>
          ))}
          <div onClick={() => {
            if (confirm('删除所有模板？')) {
              localStorage.removeItem('apexcut_roi_templates')
              setTemplates({})
            }
            setOpen(false)
          }} style={{
            padding: 'var(--space-2) var(--space-3)', cursor: 'pointer',
            fontSize: 'var(--text-xs)', color: 'var(--destructive)', textAlign: 'center',
          }}>
            清除全部模板
          </div>
        </div>
      )}
    </div>
  )
}
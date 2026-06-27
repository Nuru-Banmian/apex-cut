import { useState, useRef } from 'react'
import ResultsList from '../ResultsList'

const fmtSize = (mb) => mb >= 1024 ? `${(mb / 1024).toFixed(1)}GB` : `${mb}MB`

const inputStyle = {
  width: '100%',
  padding: 'var(--space-2) var(--space-3)',
  background: 'var(--bg-primary)',
  border: '1px solid var(--border-default)',
  borderRadius: 'var(--radius-sm)',
  color: 'var(--text-primary)',
  fontSize: 'var(--text-sm)',
  transition: 'border-color var(--transition-fast)',
}

export default function SetupPanel({
  materials, loadingLib, loadMaterials,
  videoPath, setVideoPath, fileName, setFileName,
  keyVerified, uploadError, setUploadError,
  outputName, setOutputName,
  onDirectStart,
  resultStreamUrl, setResultStreamUrl,
}) {
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [activeTab, setActiveTab] = useState('upload')
  const inputRef = useRef(null)
  const renameInputRef = useRef(null)

  // ── 融合策略参数 ──
  const [paddingBefore, setPaddingBefore] = useState(20)
  const [paddingAfter, setPaddingAfter] = useState(20)
  const [mergeGap, setMergeGap] = useState(8)
  const [minSegment, setMinSegment] = useState(3)
  const [minDamage, setMinDamage] = useState(30)

  const buildStrategy = () => ({
    triggers: ['kill_occurred', 'assist_occurred', 'damage_dealt'],
    min_damage: minDamage,
    padding_before: paddingBefore,
    padding_after: paddingAfter,
    merge_gap: mergeGap,
    min_segment: minSegment,
    order: 'chronological',
    trim_strategy: 'cut_lowest_priority',
    priority_weights: {
      damage_dealt: 5,
      kill_occurred: 5,
      assist_occurred: 2,
    },
  })

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
    } catch (_) { }
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
        try { const d = await resp.json(); err = d.detail || err } catch (_) { }
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
      {/* ═══════════════ Tab: 上传 / 素材库 ═══════════════ */}
      <div>
        <div style={{
          display: 'flex',
          borderBottom: '1px solid var(--border-subtle)',
          marginBottom: 'var(--space-4)',
        }}>
          {['upload', 'library', 'results'].map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                flex: 1,
                padding: 'var(--space-2) 4px',
                fontSize: 'var(--text-xs)',
                fontWeight: activeTab === tab ? 'var(--font-semibold)' : 'var(--font-normal)',
                color: activeTab === tab ? 'var(--accent)' : 'var(--text-tertiary)',
                borderBottom: activeTab === tab ? '2px solid var(--accent)' : '2px solid transparent',
                cursor: 'pointer',
                transition: 'all var(--transition-fast)',
              }}
            >
              {tab === 'upload' ? ' 上传' : tab === 'library' ? ' 素材库' : ' 结果'}
            </button>
          ))}
        </div>

        {activeTab === 'upload' ? (
          <>
            <div
              onClick={() => inputRef.current?.click()}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              style={{
                border: `2px dashed ${dragOver ? 'var(--accent)' : 'var(--border-default)'}`,
                borderRadius: 'var(--radius-md)',
                padding: 'var(--space-8) var(--space-4)',
                textAlign: 'center',
                cursor: 'pointer',
                background: dragOver ? 'var(--accent-subtle)' : 'var(--bg-primary)',
                transition: 'all var(--transition-fast)',
              }}
            >
              <div style={{ fontSize: 32, marginBottom: 'var(--space-2)' }}>
                {uploading ? '' : ''}
              </div>
              <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
                {uploading ? '上传中...' : '点击或拖拽上传视频'}
              </div>
              <div style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--text-tertiary)',
                marginTop: 'var(--space-1)',
              }}>
                MP4 / MOV / AVI / MKV / FLV
              </div>
            </div>
            <input
              ref={inputRef}
              type="file"
              accept="video/*"
              style={{ display: 'none' }}
              onChange={e => { const f = e.target.files[0]; if (f) handleFile(f) }}
            />
            {uploadError && (
              <div style={{
                marginTop: 'var(--space-2)',
                padding: 'var(--space-2) var(--space-3)',
                background: 'rgba(239,68,68,0.1)',
                border: '1px solid rgba(239,68,68,0.3)',
                borderRadius: 'var(--radius-sm)',
                fontSize: 'var(--text-xs)',
                color: 'var(--danger)',
              }}>
                {uploadError}
              </div>
            )}
          </>
        ) : activeTab === 'library' ? (
          <div style={{ maxHeight: 240, overflowY: 'auto' }}>
            {loadingLib ? (
              <div style={{
                textAlign: 'center',
                padding: 'var(--space-4)',
                color: 'var(--text-tertiary)',
                fontSize: 'var(--text-sm)',
              }}>
                加载中...
              </div>
            ) : !materials || materials.length === 0 ? (
              <div style={{
                textAlign: 'center',
                padding: 'var(--space-4)',
                color: 'var(--text-tertiary)',
                fontSize: 'var(--text-sm)',
              }}>
                 暂无素材
              </div>
            ) : (
              materials.map(mat => {
                const isRenaming = renamingPath === mat.path
                return (
                <div
                  key={mat.path}
                  onClick={() => { if (!isRenaming) selectMaterial(mat) }}
                  style={{
                    padding: 'var(--space-2) var(--space-3)',
                    borderRadius: 'var(--radius-sm)',
                    cursor: isRenaming ? 'default' : 'pointer',
                    background: videoPath === mat.path ? 'var(--accent-subtle)' : 'transparent',
                    border: videoPath === mat.path ? '1px solid var(--accent)' : '1px solid transparent',
                    marginBottom: 'var(--space-1)',
                    transition: 'all var(--transition-fast)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 'var(--space-2)',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {isRenaming ? (
                      <input
                        ref={renameInputRef}
                        value={renameValue}
                        onChange={e => setRenameValue(e.target.value)}
                        onKeyDown={handleRenameKey}
                        onBlur={submitRename}
                        disabled={renamingBusy}
                        onClick={e => e.stopPropagation()}
                        style={{
                          ...inputStyle,
                          fontSize: 'var(--text-sm)',
                          padding: 'var(--space-1) var(--space-2)',
                        }}
                      />
                    ) : (
                      <>
                        <div style={{
                          fontSize: 'var(--text-sm)',
                          fontWeight: videoPath === mat.path ? 'var(--font-medium)' : 'var(--font-normal)',
                        }} className="truncate">
                          {mat.filename}
                        </div>
                        <div style={{
                          fontSize: 'var(--text-xs)',
                          color: 'var(--text-tertiary)',
                          marginTop: 2,
                        }}>
                          {fmtSize(mat.size_mb)} · {mat.date}
                        </div>
                      </>
                    )}
                  </div>
                  {!isRenaming && (
                    <button
                      onClick={e => { e.stopPropagation(); startRename(mat) }}
                      title="重命名"
                      style={{
                        flexShrink: 0,
                        width: 24,
                        height: 24,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        borderRadius: 'var(--radius-sm)',
                        cursor: 'pointer',
                        color: 'var(--text-tertiary)',
                        fontSize: 'var(--text-xs)',
                        border: 'none',
                        background: 'transparent',
                        opacity: 0.6,
                      }}
                      onMouseEnter={e => e.currentTarget.style.opacity = 1}
                      onMouseLeave={e => e.currentTarget.style.opacity = 0.6}
                    >
                      ️
                    </button>
                  )}
                </div>
              )})
            )}
          </div>
        ) : (
          <ResultsList
            onSelectResult={(r) => {
              setResultStreamUrl?.(`/api/results/stream/${encodeURIComponent(r.filename)}`)
              setFileName(r.filename)
            }}
            selectedUrl={resultStreamUrl}
          />
        )}

        {fileName && (
          <div style={{
            marginTop: 'var(--space-2)',
            padding: 'var(--space-2) var(--space-3)',
            background: 'rgba(34,197,94,0.1)',
            borderRadius: 'var(--radius-sm)',
            fontSize: 'var(--text-xs)',
            color: 'var(--success)',
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-1)',
          }}>
            <span></span> 已选择: {fileName}
          </div>
        )}
      </div>

      {/* ═══════════════ 分隔线 ═══════════════ */}
      <div style={{ borderTop: '1px solid var(--border-subtle)' }} />

      {/* ═══════════════ 融合策略 ═══════════════ */}
      <div>
        <div style={{
          fontSize: 'var(--text-sm)',
          fontWeight: 'var(--font-semibold)',
          marginBottom: 'var(--space-3)',
        }}>
          ️ 融合策略
        </div>
        <div style={{
          padding: 'var(--space-3)',
          background: 'var(--bg-primary)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-md)',
          display: 'flex', flexDirection: 'column', gap: 'var(--space-3)',
        }}>
          {/* 快速预设 */}
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {[
              { label: '紧凑高光', pb: 10, pa: 8, gap: 5, min: 3, dmg: 50 },
              { label: '标准', pb: 20, pa: 20, gap: 8, min: 3, dmg: 30 },
              { label: '完整战斗', pb: 30, pa: 25, gap: 15, min: 5, dmg: 20 },
            ].map(p => (
              <button key={p.label} onClick={() => {
                setPaddingBefore(p.pb); setPaddingAfter(p.pa)
                setMergeGap(p.gap); setMinSegment(p.min); setMinDamage(p.dmg)
              }} style={{
                padding: '2px 8px', fontSize: 10, borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)', cursor: 'pointer',
                background: paddingBefore === p.pb && paddingAfter === p.pa ? 'var(--accent-subtle)' : 'var(--bg-surface)',
                color: 'var(--text-secondary)', fontFamily: 'inherit',
              }}>{p.label}</button>
            ))}
          </div>

          <SliderRow label="前摇" value={paddingBefore} onChange={setPaddingBefore} min={5} max={45} unit="s" />
          <SliderRow label="后摇" value={paddingAfter} onChange={setPaddingAfter} min={5} max={45} unit="s" />
          <SliderRow label="合并" value={mergeGap} onChange={setMergeGap} min={2} max={30} unit="s" />
          <SliderRow label="最短" value={minSegment} onChange={setMinSegment} min={2} max={15} unit="s" />
          <SliderRow label="伤害" value={minDamage} onChange={setMinDamage} min={10} max={200} unit="" step={10} />
        </div>
      </div>

      {/* ═══════════════ 启动 ═══════════════ */}
      {/* 输出命名 */}
      <div style={{ marginBottom: 'var(--space-3)' }}>
        <label style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)', display: 'block', marginBottom: 4 }}>
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
          onClick={() => onDirectStart(buildStrategy())}
          disabled={!keyVerified || !videoPath}
          style={{
            width: '100%',
            padding: 'var(--space-3) var(--space-4)',
            background: (!keyVerified || !videoPath) ? 'var(--border-default)' : 'var(--accent)',
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

function SliderRow({ label, value, onChange, min, max, unit, step = 1 }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)', minWidth: 36 }}>{label}</span>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))}
        style={{ flex: 1, accentColor: 'var(--accent)' }}
      />
      <span style={{
        fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)',
        color: 'var(--text-primary)', minWidth: 32, textAlign: 'right',
      }}>
        {value}{unit}
      </span>
    </div>
  )
}

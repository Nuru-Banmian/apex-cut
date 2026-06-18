import { useRef, useState } from 'react'

export default function VideoUpload({ onUpload, fileName }) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef(null)

  const handleFile = async (file) => {
    setUploading(true)
    setError('')

    const form = new FormData()
    form.append('file', file)

    try {
      const resp = await fetch('/api/upload', { method: 'POST', body: form })
      if (!resp.ok) {
        let err = `HTTP ${resp.status}`
        try { const d = await resp.json(); err = d.detail || err } catch (_) {}
        setError(err)
        setUploading(false)
        return
      }
      const data = await resp.json()
      if (data.success) {
        onUpload(data.video_path, file.name)
      } else {
        setError(data.error || '上传失败')
      }
    } catch (e) {
      setError(`网络错误: ${e.message}`)
    }
    setUploading(false)
  }

  return (
    <div className="card">
      <div className="card-title"><span className="icon">📹</span> 上传视频</div>
      <div
        className={`upload-zone${dragOver ? ' dragover' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) handleFile(f) }}
      >
        <div className="up-icon">📁</div>
        <p>点击选择视频文件，或拖拽到此处</p>
        <p style={{ fontSize: 11, marginTop: 4 }}>支持 MP4 / MOV / AVI / MKV，长视频处理时间较长</p>
        {uploading && <p style={{ color: 'var(--warn)', marginTop: 6 }}>⏳ 上传中...</p>}
        {fileName && <div className="file-name">{uploading ? '⏳' : '✅'} {fileName}</div>}
        {error && <div className="file-name" style={{ color: 'var(--danger)' }}>❌ {error}</div>}
      </div>
      <input ref={inputRef} type="file" accept="video/*" style={{ display: 'none' }}
        onChange={e => { const f = e.target.files[0]; if (f) handleFile(f) }} />
    </div>
  )
}

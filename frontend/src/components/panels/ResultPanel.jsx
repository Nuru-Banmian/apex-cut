import ResultsList from '../ResultsList'

export default function ResultPanel({ streamUrl, onReset }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
      {/* ── 视频播放器 ── */}
      {streamUrl && (
        <div style={{
          background: '#000',
          borderRadius: 'var(--radius-md)',
          overflow: 'hidden',
          aspectRatio: '16 / 9',
        }}>
          <video
            controls
            autoPlay
            src={streamUrl}
            style={{ width: '100%', height: '100%', display: 'block' }}
          >
            你的浏览器不支持视频播放
          </video>
        </div>
      )}

      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 48, marginBottom: 'var(--space-2)' }}></div>
        <div style={{
          fontSize: 'var(--text-xl)',
          fontWeight: 'var(--font-semibold)',
          color: 'var(--success)',
        }}>
          剪辑成功
        </div>
      </div>

      <button onClick={onReset}
        style={{
          width: '100%', padding: 'var(--space-3)',
          background: 'var(--background)', color: 'var(--muted-foreground)',
          border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
          fontSize: 'var(--text-base)', fontWeight: 'var(--font-medium)', cursor: 'pointer',
        }}
      >
         重新剪辑
      </button>

      <ResultsList />
    </div>
  )
}

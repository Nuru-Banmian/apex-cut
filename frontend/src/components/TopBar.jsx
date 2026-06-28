export default function TopBar({ gpuStatus, onSettings }) {
  const gpuOk = gpuStatus && gpuStatus.summary !== 'CPU 模式'

  return (
    <header className="top-bar" style={{
      height: 'var(--topbar-h)', display: 'flex', alignItems: 'center',
      justifyContent: 'space-between', padding: '0 var(--space-5)',
      borderBottom: '1px solid var(--border)', background: 'var(--card)',
      flexShrink: 0, zIndex: 10,
    }}>
      <span style={{ fontSize: 'var(--text-lg)', fontWeight: 'var(--font-semibold)' }}>AutoCut</span>

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
        {gpuStatus && (
          <span style={{ fontSize: 'var(--text-xs)', color: gpuOk ? 'var(--success)' : 'var(--muted-foreground)' }}>
            {gpuOk ? `GPU ${gpuStatus.ffmpeg_encode?.toUpperCase() || ''}` : 'CPU'}
          </span>
        )}
        <button onClick={onSettings} style={{
          padding: '4px 12px', borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border)', cursor: 'pointer',
          color: 'var(--muted-foreground)', fontSize: 'var(--text-xs)',
          fontFamily: 'inherit', background: 'var(--background)',
        }}>设置</button>
      </div>
    </header>
  )
}

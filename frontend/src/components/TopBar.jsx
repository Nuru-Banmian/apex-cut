export default function TopBar({ gpuStatus, onSettings }) {
  const gpuOk = gpuStatus && gpuStatus.summary !== 'CPU 模式'

  return (
    <header style={{
      height: 'var(--topbar-h)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 var(--space-5)',
      borderBottom: '1px solid var(--border-subtle)',
      background: 'var(--bg-surface)',
      flexShrink: 0,
      zIndex: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
        <span style={{
          fontSize: 'var(--text-lg)',
          fontWeight: 'var(--font-semibold)',
          letterSpacing: '-0.3px',
        }}>
           AutoCut
        </span>
        <span style={{
          fontSize: 'var(--text-xs)',
          color: 'var(--text-tertiary)',
          background: 'var(--accent-subtle)',
          padding: '2px 8px',
          borderRadius: 'var(--radius-sm)',
          fontWeight: 'var(--font-medium)',
        }}>
          Apex
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}>
        {gpuStatus && (
          <span style={{
            fontSize: 'var(--text-xs)',
            color: gpuOk ? 'var(--success)' : 'var(--warning)',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}>
            <span style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: gpuOk ? 'var(--success)' : 'var(--warning)',
            }} />
            {gpuOk ? 'GPU' : 'CPU'}
          </span>
        )}
        <button
          onClick={onSettings}
          style={{
            width: 32,
            height: 32,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: 'var(--radius-sm)',
            cursor: 'pointer',
            color: 'var(--text-secondary)',
            transition: 'all var(--transition-fast)',
            fontSize: 'var(--text-lg)',
          }}
          title="设置"
        >
          
        </button>
      </div>
    </header>
  )
}

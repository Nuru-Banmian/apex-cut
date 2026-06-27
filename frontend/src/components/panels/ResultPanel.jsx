import ResultsList from '../ResultsList'

export default function ResultPanel({ downloadUrl, onReset }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
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

      {downloadUrl && (
        <a href={downloadUrl} download
          style={{
            width: '100%', padding: 'var(--space-3)', textAlign: 'center',
            background: 'var(--accent)', color: '#fff', border: 'none',
            borderRadius: 'var(--radius-md)', fontSize: 'var(--text-base)',
            fontWeight: 'var(--font-semibold)', cursor: 'pointer',
            textDecoration: 'none', display: 'block',
          }}
        >
           下载成品
        </a>
      )}

      <button onClick={onReset}
        style={{
          width: '100%', padding: 'var(--space-3)',
          background: 'var(--bg-primary)', color: 'var(--text-secondary)',
          border: '1px solid var(--border-default)', borderRadius: 'var(--radius-md)',
          fontSize: 'var(--text-base)', fontWeight: 'var(--font-medium)', cursor: 'pointer',
        }}
      >
         重新剪辑
      </button>

      <ResultsList />
    </div>
  )
}

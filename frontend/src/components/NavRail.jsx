const PHASES = [
  { key: 'setup',      label: '准备', icon: '' },
  { key: 'processing', label: '进度', icon: '' },
  { key: 'result',     label: '结果', icon: '' },
]

export default function NavRail({ phase }) {
  const currentIdx = PHASES.findIndex(p => p.key === phase)

  return (
    <nav className="nav-rail" style={{
      width: 'var(--nav-rail-w)',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      padding: 'var(--space-4) 0',
      gap: 'var(--space-1)',
      borderRight: '1px solid var(--border)',
      background: 'var(--card)',
      flexShrink: 0,
    }}>
      {PHASES.map((p, i) => {
        const isActive = i === currentIdx
        const isPast = i < currentIdx
        return (
          <div key={p.key} style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 2,
            padding: 'var(--space-2) var(--space-1)',
            borderRadius: 'var(--radius-sm)',
            opacity: isActive || isPast ? 1 : 0.35,
            transition: 'opacity var(--transition-normal)',
            cursor: 'default',
          }} title={p.label}>
            <span style={{ fontSize: 'var(--text-lg)' }}>{p.icon}</span>
            <span style={{
              fontSize: '9px',
              fontWeight: isActive ? 'var(--font-semibold)' : 'var(--font-normal)',
              color: isActive ? 'var(--primary)' : 'var(--muted-foreground)',
            }}>
              {p.label}
            </span>
            {isPast && (
              <span style={{
                width: 4,
                height: 4,
                borderRadius: '50%',
                background: 'var(--success)',
              }} />
            )}
          </div>
        )
      })}
    </nav>
  )
}

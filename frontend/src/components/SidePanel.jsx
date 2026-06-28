import SetupPanel from './panels/SetupPanel'
import ProgressPanel from './panels/ProgressPanel'
import ResultPanel from './panels/ResultPanel'

const PHASE_META = {
  setup:      { icon: '', title: '准备素材' },
  processing: { icon: '', title: '处理中' },
  result:     { icon: '', title: '剪辑结果' },
}

export default function SidePanel({ phase, ...panelProps }) {
  const meta = PHASE_META[phase] || PHASE_META.setup

  return (
    <aside className="side-panel" style={{
      width: 'var(--panel-w)',
      minWidth: 'var(--panel-w)',
      borderLeft: '1px solid var(--border)',
      background: 'var(--card)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {/* 阶段标题 */}
      <div style={{
        padding: 'var(--space-4) var(--space-5)',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <span style={{ fontSize: 'var(--text-lg)' }}>{meta.icon}</span>
          <span style={{ fontWeight: 'var(--font-semibold)', fontSize: 'var(--text-base)' }}>
            {meta.title}
          </span>
        </div>
      </div>

      {/* 阶段内容（可滚动） */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: 'var(--space-5)',
      }}>
        {phase === 'setup'      && <SetupPanel {...panelProps} />}
        {phase === 'processing' && <ProgressPanel {...panelProps} />}
        {phase === 'result'     && <ResultPanel {...panelProps} />}
      </div>
    </aside>
  )
}

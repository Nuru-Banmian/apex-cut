import { useEffect, useRef } from 'react'

const STEPS = [
  { key: 'director', icon: '', label: '导演' },
  { key: 'analyzer', icon: '', label: '分析' },
  { key: 'editor',   icon: '️', label: '剪辑' },
  { key: 'reviewer', icon: '', label: '审核' },
]

function detectStep(progress) {
  if (!progress) return -1
  if (progress.includes('完成')) return STEPS.length
  if (progress.includes('审核') || progress.includes('审查')) return 3
  if (progress.includes('裁剪') || progress.includes('剪辑') || progress.includes('编辑')) return 2
  if (progress.includes('分析') || progress.includes('采集') || progress.includes('提取')) return 1
  if (progress.includes('策略') || progress.includes('翻译') || progress.includes('导演')) return 0
  return -1
}

export default function ProgressPanel({ progress, reviewRound, error, logLines }) {
  const logEndRef = useRef(null)
  const currentStep = detectStep(progress)

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logLines])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
      {/* 步骤指示器 */}
      <div>
        <div style={{
          fontSize: 'var(--text-xs)',
          fontWeight: 'var(--font-semibold)',
          color: 'var(--text-tertiary)',
          marginBottom: 'var(--space-2)',
        }}>
          处理流程
        </div>
        <div style={{ display: 'flex', gap: 2, marginBottom: 'var(--space-2)' }}>
          {STEPS.map((s, i) => (
            <div key={s.key} style={{
              flex: 1,
              height: 4,
              borderRadius: 2,
              background: i < currentStep ? 'var(--success)'
                : i === currentStep ? 'var(--accent)'
                : 'var(--border-default)',
              transition: 'background var(--transition-normal)',
            }} />
          ))}
        </div>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 'var(--text-xs)',
          color: 'var(--text-tertiary)',
        }}>
          {STEPS.map((s, i) => (
            <span key={s.key} style={{
              color: i <= currentStep ? 'var(--text-primary)' : 'var(--text-tertiary)',
              fontWeight: i === currentStep ? 'var(--font-semibold)' : 'var(--font-normal)',
            }}>
              {s.icon} {s.label}
            </span>
          ))}
        </div>
      </div>

      {/* 当前状态 */}
      <div style={{
        padding: 'var(--space-3)',
        background: 'var(--accent-subtle)',
        border: '1px solid rgba(99,102,241,0.15)',
        borderRadius: 'var(--radius-md)',
        fontSize: 'var(--text-sm)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}>
        <span style={{ color: 'var(--accent)', fontWeight: 'var(--font-medium)' }}>
          {progress || '初始化...'}
        </span>
        {reviewRound > 0 && (
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)' }}>
            审查第 {reviewRound} 轮
          </span>
        )}
      </div>

      {error && (
        <div style={{
          padding: 'var(--space-3)',
          background: 'rgba(239,68,68,0.1)',
          border: '1px solid rgba(239,68,68,0.3)',
          borderRadius: 'var(--radius-md)',
          fontSize: 'var(--text-sm)',
          color: 'var(--danger)',
        }}>
          {error}
        </div>
      )}

      {/* 实时日志 */}
      {(logLines || []).length > 0 && (
        <div>
          <div style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--text-tertiary)',
            marginBottom: 'var(--space-2)',
          }}>
             实时日志
          </div>
          <div style={{
            background: 'var(--bg-primary)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: 'var(--space-3)',
            maxHeight: 300,
            overflowY: 'auto',
            fontFamily: 'var(--font-mono)',
            fontSize: 'var(--text-xs)',
            lineHeight: 1.7,
          }}>
            {(logLines || []).map((line, i) => (
              <div key={i} style={{
                color: i === 0 ? 'var(--accent)' : 'var(--text-tertiary)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}>
                {line}
              </div>
            ))}
            <div ref={logEndRef} />
          </div>
        </div>
      )}
    </div>
  )
}

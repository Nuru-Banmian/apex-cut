import { useState } from 'react'

/** FastAPI validation errors come as array of {type, loc, msg, input} — flatten to string */
function formatDetail(detail) {
  if (detail === undefined || detail === null) return ''
  if (Array.isArray(detail)) {
    return detail.map(d => {
      const loc = (d.loc || []).join('.')
      return `${d.msg}${loc ? ` (${loc})` : ''}`
    }).join('; ')
  }
  if (typeof detail === 'string') return detail
  if (typeof detail === 'object') return detail.msg || detail.message || JSON.stringify(detail)
  return String(detail)
}

const PROVIDERS = [
  { value: 'qwen', label: '阿里千问 Qwen3.7-Plus', desc: '多模态 · 1M上下文 · 推荐' },
  { value: 'deepseek', label: 'DeepSeek', desc: '性价比高，中文友好' },
  { value: 'openai', label: 'OpenAI', desc: 'GPT-4o，综合能力强' },
  { value: 'anthropic', label: 'Anthropic Claude', desc: '逻辑严谨，长文理解强' },
]

const VISION_PROVIDERS = [
  { value: 'qwen', label: '千问 Qwen3.7-Plus（推荐）', desc: '文本+视觉统一模型，一个 Key 搞定' },
  { value: 'zhipu', label: '智谱 GLM-4V', desc: '国产视觉模型' },
  { value: 'openai', label: 'OpenAI GPT-4o', desc: '综合能力最强' },
]

export default function ApiConfig({
  llmProvider, setLlmProvider, apiKey, setApiKey,
  visionProvider, setVisionProvider, visionKey, setVisionKey,
  savedConfig, keyVerified, setKeyVerified, hasSavedKey, setHasSavedKey,
}) {
  const [status, setStatus] = useState({ type: '', msg: '' })
  const [busy, setBusy] = useState(false)
  const [showPw, setShowPw] = useState(false)
  const [showVisPw, setShowVisPw] = useState(false)

  const cfg = savedConfig || {}

  // 检查各 provider 是否有已保存的 key
  const keyMap = { deepseek: cfg.deepseek_api_key, openai: cfg.openai_api_key, qwen: cfg.qwen_api_key, anthropic: cfg.anthropic_api_key }
  const savedKey = keyMap[llmProvider] || ''
  const hasMainSaved = !!(savedKey && savedKey.includes('*'))

  const visKeyMap = { zhipu: cfg.zhipu_api_key, qwen: cfg.qwen_api_key, openai: cfg.openai_api_key }
  const visSavedKey = visKeyMap[visionProvider] || ''
  const hasVisSaved = !!(visSavedKey && visSavedKey.includes('*'))

  const handleTestAndSave = async () => {
    const hasNewMainKey = apiKey && !apiKey.includes('*')
    const hasNewVisKey = visionKey && !visionKey.includes('*')

    if (!hasNewMainKey && !hasMainSaved && !hasNewVisKey && !hasVisSaved) {
      setStatus({ type: 'error', msg: '请填写 API Key' })
      return
    }

    setBusy(true)
    setStatus({ type: 'testing', msg: '⏳ 测试连接中...' })

    // ── Step 1: 测试主 LLM 连接 ──
    if (hasNewMainKey) {
      const testPayload = { llm_provider: llmProvider }
      if (llmProvider === 'deepseek') testPayload.deepseek_api_key = apiKey
      else if (llmProvider === 'openai') testPayload.openai_api_key = apiKey
      else if (llmProvider === 'qwen') testPayload.qwen_api_key = apiKey
      else if (llmProvider === 'anthropic') testPayload.anthropic_api_key = apiKey

      try {
        const resp = await fetch('/api/config/test', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(testPayload),
        })
        const data = await resp.json()
        if (!resp.ok || !data.success) {
          setKeyVerified(false)
          setStatus({ type: 'error', msg: data.error || formatDetail(data.detail) || '连接失败' })
          setBusy(false)
          return
        }
      } catch (e) {
        setKeyVerified(false)
        setStatus({ type: 'error', msg: `网络错误: ${e.message}` })
        setBusy(false)
        return
      }
    }

    // ── Step 2: 保存配置到 .env ──
    setStatus({ type: 'testing', msg: hasNewMainKey ? '✅ 连接成功，保存中...' : '💾 保存配置中...' })

    const savePayload = { llm_provider: llmProvider, vision_provider: visionProvider }
    if (hasNewMainKey) {
      if (llmProvider === 'deepseek') savePayload.deepseek_api_key = apiKey
      else if (llmProvider === 'openai') savePayload.openai_api_key = apiKey
      else if (llmProvider === 'qwen') savePayload.qwen_api_key = apiKey
      else if (llmProvider === 'anthropic') savePayload.anthropic_api_key = apiKey
    }
    if (hasNewVisKey) {
      if (visionProvider === 'zhipu') savePayload.zhipu_api_key = visionKey
      else if (visionProvider === 'qwen') savePayload.qwen_api_key = visionKey
      else savePayload.openai_api_key = visionKey
    }

    try {
      const resp = await fetch('/api/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(savePayload),
      })
      if (!resp.ok) {
        let err = `HTTP ${resp.status}`
        try { const e = await resp.json(); err = formatDetail(e.detail) || err } catch (_) {}
        setStatus({ type: 'error', msg: `保存失败: ${err}` })
        setBusy(false)
        return
      }
      const data = await resp.json()
      if (data.success) {
        setKeyVerified(true)
        setHasSavedKey(true)
        setStatus({ type: 'success', msg: '✅ 配置已保存' })
        if (hasNewMainKey) setApiKey('')
        if (hasNewVisKey) setVisionKey('')
      }
    } catch (e) {
      setStatus({ type: 'error', msg: `保存失败: ${e.message}` })
    }
    setBusy(false)
  }

  const statusColor = { success: 'var(--success)', error: 'var(--danger)', testing: 'var(--warn)' }[status.type] || 'var(--dim)'

  return (
    <div className="sidebar-card">
      <div className="sidebar-card-title">
        <span>🔑</span> API 配置
        {hasSavedKey && <span className="badge">已保存</span>}
      </div>

      {/* ── 文本 LLM ── */}
      <div className="side-section-label">📝 文本理解 & 剪辑决策</div>

      <div className="side-field">
        <select className="side-select" value={llmProvider} onChange={e => setLlmProvider(e.target.value)}>
          {PROVIDERS.map(p => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
      </div>

      <div className="side-field">
        <div className="pw-wrap">
          <input
            type={showPw ? 'text' : 'password'}
            value={apiKey}
            placeholder={hasMainSaved ? `已保存 (${savedKey})` : `${llmProvider.toUpperCase()} API Key`}
            onChange={e => setApiKey(e.target.value)}
            autoComplete="off"
          />
          <button className="toggle" onClick={() => setShowPw(!showPw)}>{showPw ? '🙈' : '👁'}</button>
        </div>
        {hasMainSaved && <div className="side-hint success">✅ 已保存</div>}
      </div>

      {/* ── 视觉 LLM ── */}
      <div className="side-section-label">👁️ 画面理解（可选）</div>

      <div className="side-field">
        <select className="side-select" value={visionProvider} onChange={e => setVisionProvider(e.target.value)}>
          {VISION_PROVIDERS.map(p => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
      </div>

      <div className="side-field">
        <div className="pw-wrap">
          <input
            type={showVisPw ? 'text' : 'password'}
            value={visionKey}
            placeholder={hasVisSaved ? `已保存 (${visSavedKey})` : '视觉 Key（可选）'}
            onChange={e => setVisionKey(e.target.value)}
            autoComplete="off"
          />
          <button className="toggle" onClick={() => setShowVisPw(!showVisPw)}>{showVisPw ? '🙈' : '👁'}</button>
        </div>
        {hasVisSaved && <div className="side-hint success">✅ 已保存</div>}
        {!hasVisSaved && !visionKey && <div className="side-hint">留空则使用文本 Key</div>}
      </div>

      {/* ── 操作按钮 ── */}
      <button className="side-btn" onClick={handleTestAndSave} disabled={busy}>
        {busy ? '⏳ 处理中...' : keyVerified ? '✅ 已就绪 — 点击重新验证' : '🔍 测试并保存'}
      </button>

      {status.msg && (
        <div className="side-status" style={{ color: statusColor }}>{status.msg}</div>
      )}

      <div className="side-footer-text">
        🔒 Key 仅保存在本地 .env 文件，不会上传到任何第三方
      </div>
    </div>
  )
}

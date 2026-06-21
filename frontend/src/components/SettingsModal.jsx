import { useState } from 'react'

const KEY_FIELD = {
  deepseek: 'deepseek_api_key',
  openai: 'openai_api_key',
  qwen: 'qwen_api_key',
  anthropic: 'anthropic_api_key',
  zhipu: 'zhipu_api_key',
}

const renderModelSelect = (models, value, onChange) => {
  if (!models || models.length === 0) {
    return (
      <div className="text-xs" style={{ color: 'var(--danger)' }}>
        该平台不支持此类型模型
      </div>
    )
  }
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      style={{
        width: '100%',
        padding: 'var(--space-2) var(--space-3)',
        background: 'var(--bg-primary)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-sm)',
        color: 'var(--text-primary)',
        fontSize: 'var(--text-sm)',
        fontFamily: 'inherit',
        cursor: 'pointer',
      }}
    >
      {models.map(m => (
        <option key={m.id} value={m.id}>{m.name}</option>
      ))}
    </select>
  )
}

export default function SettingsModal({
  open, onClose,
  textProvider, setTextProvider, textApiKey, setTextApiKey, textModel, setTextModel,
  visionProvider, setVisionProvider, visionApiKey, setVisionApiKey, visionModel, setVisionModel,
  savedConfig, keyVerified, setKeyVerified, hasSavedKey, setHasSavedKey,
  providers,
  advancedSettings, setAdvancedSettings,
}) {
  const [showPw, setShowPw] = useState(false)
  const [status, setStatus] = useState({ type: '', msg: '' })
  const [busy, setBusy] = useState(false)
  const [activeTab, setActiveTab] = useState('api')

  if (!open) return null

  const cfg = savedConfig || {}
  const textProv = providers.find(p => p.id === textProvider) || {}
  const visProv = providers.find(p => p.id === visionProvider) || {}
  const textModels = textProv.text_models || []
  const visModels = visProv.vision_models || []
  const visionProviders = providers.filter(p => p.has_vision)

  const keyMap = {
    deepseek: cfg.deepseek_api_key,
    openai: cfg.openai_api_key,
    qwen: cfg.qwen_api_key,
    anthropic: cfg.anthropic_api_key,
    zhipu: cfg.zhipu_api_key,
  }
  const textSavedKey = keyMap[textProvider] || ''
  const visSavedKey = keyMap[visionProvider] || ''
  const hasTextSaved = !!(textSavedKey && textSavedKey.includes('*'))
  const hasVisSaved = !!(visSavedKey && visSavedKey.includes('*'))

  const textProviders = providers.map(p => ({
    ...p,
    label: p.has_vision ? p.name : `${p.name} (仅文本)`,
  }))

  // ── 保存逻辑（从旧 ApiConfig 迁移）──
  const handleSave = async () => {
    const hasNewTextKey = textApiKey && !textApiKey.includes('*')
    const hasNewVisKey = visionApiKey && visionProvider !== textProvider && !visionApiKey.includes('*')

    if (!hasNewTextKey && !hasTextSaved && !hasNewVisKey && !hasVisSaved) {
      setStatus({ type: 'error', msg: '请填写至少一个 API Key' })
      return
    }

    setBusy(true)
    setStatus({ type: 'testing', msg: '⏳ 测试连接中...' })

    // Step 1: 测试文本模型
    if (hasNewTextKey) {
      const testPayload = { llm_provider: textProvider, [KEY_FIELD[textProvider]]: textApiKey }
      try {
        const resp = await fetch('/api/config/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(testPayload),
        })
        const data = await resp.json()
        if (!resp.ok || !data.success) {
          setKeyVerified(false)
          setStatus({ type: 'error', msg: data.error || data.detail || '连接失败' })
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

    // Step 2: 测试视觉模型（与文本不同提供商时）
    if (hasNewVisKey) {
      setStatus({ type: 'testing', msg: '👁️ 测试视觉模型连接...' })
      const visTestPayload = { llm_provider: visionProvider, [KEY_FIELD[visionProvider]]: visionApiKey }
      try {
        const resp = await fetch('/api/config/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(visTestPayload),
        })
        const data = await resp.json()
        if (!resp.ok || !data.success) {
          setKeyVerified(false)
          setStatus({ type: 'error', msg: `视觉 Key 测试失败: ${data.error || data.detail || '连接失败'}` })
          setBusy(false)
          return
        }
      } catch (e) {
        setKeyVerified(false)
        setStatus({ type: 'error', msg: `视觉 Key 网络错误: ${e.message}` })
        setBusy(false)
        return
      }
    }

    // Step 3: 保存
    setStatus({ type: 'testing', msg: '💾 保存配置中...' })
    const savePayload = { llm_provider: textProvider, vision_provider: visionProvider }
    if (hasNewTextKey) savePayload[KEY_FIELD[textProvider]] = textApiKey
    if (hasNewVisKey) savePayload[KEY_FIELD[visionProvider]] = visionApiKey
    if (textProvider === 'qwen') savePayload.qwen_text_model = textModel
    if (textProvider === 'deepseek') savePayload.deepseek_model = textModel
    if (textProvider === 'openai') savePayload.openai_model = textModel
    if (visionProvider === 'qwen') savePayload.qwen_vision_model = visionModel
    if (visionProvider === 'zhipu') savePayload.zhipu_model = visionModel

    try {
      const resp = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(savePayload),
      })
      if (!resp.ok) {
        let err = `HTTP ${resp.status}`
        try { const e = await resp.json(); err = e.detail || err } catch (_) { }
        setStatus({ type: 'error', msg: `保存失败: ${err}` })
        setBusy(false)
        return
      }
      const data = await resp.json()
      if (data.success) {
        if (hasNewTextKey || hasTextSaved) setKeyVerified(true)
        setHasSavedKey(true)
        setStatus({ type: 'success', msg: '✅ 配置已保存，即刻生效' })
        if (hasNewTextKey) setTextApiKey('')
        if (hasNewVisKey) setVisionApiKey('')
      }
    } catch (e) {
      setStatus({ type: 'error', msg: `保存失败: ${e.message}` })
    }
    setBusy(false)
  }

  const statusColor = {
    success: 'var(--success)',
    error: 'var(--danger)',
    testing: 'var(--warning)',
  }[status.type] || 'var(--dim)'

  const fieldStyle = {
    width: '100%',
    padding: 'var(--space-2) var(--space-3)',
    background: 'var(--bg-primary)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)',
    color: 'var(--text-primary)',
    fontSize: 'var(--text-sm)',
    fontFamily: 'inherit',
  }

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      background: 'rgba(0,0,0,0.6)',
      backdropFilter: 'blur(4px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 100,
    }} onClick={onClose}>
      <div style={{
        width: 480,
        maxHeight: '80vh',
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-xl)',
        boxShadow: 'var(--shadow-lg)',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: 'var(--space-5) var(--space-6)',
          borderBottom: '1px solid var(--border-subtle)',
        }}>
          <span style={{ fontSize: 'var(--text-lg)', fontWeight: 'var(--font-semibold)' }}>
            ⚙ 设置
          </span>
          <button onClick={onClose} style={{
            width: 28,
            height: 28,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: 'var(--radius-sm)',
            cursor: 'pointer',
            color: 'var(--text-tertiary)',
            fontSize: 'var(--text-lg)',
          }}>
            ✕
          </button>
        </div>

        {/* Tabs */}
        <div style={{
          display: 'flex',
          borderBottom: '1px solid var(--border-subtle)',
          padding: '0 var(--space-6)',
        }}>
          {['api', 'advanced'].map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                padding: 'var(--space-2) var(--space-4)',
                borderBottom: activeTab === tab ? '2px solid var(--accent)' : '2px solid transparent',
                color: activeTab === tab ? 'var(--accent)' : 'var(--text-tertiary)',
                fontWeight: activeTab === tab ? 'var(--font-semibold)' : 'var(--font-normal)',
                fontSize: 'var(--text-sm)',
                cursor: 'pointer',
                background: 'none',
              }}
            >
              {tab === 'api' ? '🔑 API 配置' : '🔧 高级'}
            </button>
          ))}
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 'var(--space-6)' }}>
          {activeTab === 'api' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
              {/* ── 文本模型 ── */}
              <div style={{
                fontSize: 'var(--text-xs)',
                fontWeight: 'var(--font-semibold)',
                color: 'var(--text-primary)',
                textTransform: 'uppercase',
              }}>
                📝 文本模型
              </div>

              <div>
                <label style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)', display: 'block', marginBottom: 'var(--space-1)' }}>
                  提供商
                </label>
                <select
                  value={textProvider}
                  onChange={e => {
                    const newProv = e.target.value
                    setTextProvider(newProv)
                    const prov = providers.find(p => p.id === newProv)
                    if (prov && prov.text_models.length > 0) {
                      setTextModel(prov.default_text_model || prov.text_models[0].id)
                    }
                  }}
                  style={{ ...fieldStyle, cursor: 'pointer' }}
                >
                  {textProviders.map(p => (
                    <option key={p.id} value={p.id}>{p.label}</option>
                  ))}
                </select>
              </div>

              {textModels.length > 0 && (
                <div>
                  <label style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)', display: 'block', marginBottom: 'var(--space-1)' }}>
                    模型
                  </label>
                  {renderModelSelect(textModels, textModel, setTextModel)}
                  {textModels.find(m => m.id === textModel)?.desc && (
                    <div className="text-xs text-tertiary" style={{ marginTop: 'var(--space-1)' }}>
                      {textModels.find(m => m.id === textModel).desc}
                    </div>
                  )}
                </div>
              )}

              <div>
                <label style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)', display: 'block', marginBottom: 'var(--space-1)' }}>
                  API Key
                </label>
                <div style={{ position: 'relative' }}>
                  <input
                    type={showPw ? 'text' : 'password'}
                    value={textApiKey}
                    placeholder={hasTextSaved ? `已保存 (${textSavedKey})` : `${textProv.name || '文本模型'} API Key`}
                    onChange={e => setTextApiKey(e.target.value)}
                    autoComplete="off"
                    style={{ ...fieldStyle, paddingRight: 32 }}
                  />
                  <button
                    onClick={() => setShowPw(!showPw)}
                    style={{
                      position: 'absolute',
                      right: 8,
                      top: '50%',
                      transform: 'translateY(-50%)',
                      cursor: 'pointer',
                      color: 'var(--text-tertiary)',
                      fontSize: 'var(--text-sm)',
                    }}
                  >
                    {showPw ? '🙈' : '👁'}
                  </button>
                </div>
                {hasTextSaved && (
                  <div className="text-xs" style={{ marginTop: 'var(--space-1)', color: 'var(--success)' }}>
                    ✅ 已保存
                  </div>
                )}
              </div>

              {/* ── 视觉模型 ── */}
              <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 'var(--space-4)' }}>
                <div style={{
                  fontSize: 'var(--text-xs)',
                  fontWeight: 'var(--font-semibold)',
                  color: 'var(--text-primary)',
                  textTransform: 'uppercase',
                  marginBottom: 'var(--space-3)',
                }}>
                  👁️ 视觉模型
                </div>

                <div style={{ marginBottom: 'var(--space-3)' }}>
                  <label style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)', display: 'block', marginBottom: 'var(--space-1)' }}>
                    提供商
                  </label>
                  <select
                    value={visionProvider}
                    onChange={e => {
                      const newProv = e.target.value
                      setVisionProvider(newProv)
                      if (newProv === textProvider) setVisionApiKey('')
                      const prov = providers.find(p => p.id === newProv)
                      if (prov && prov.vision_models.length > 0) {
                        setVisionModel(prov.default_vision_model || prov.vision_models[0].id)
                      }
                    }}
                    style={{ ...fieldStyle, cursor: 'pointer' }}
                  >
                    {visionProviders.map(p => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>

                {visModels.length > 0 && (
                  <div style={{ marginBottom: 'var(--space-3)' }}>
                    <label style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)', display: 'block', marginBottom: 'var(--space-1)' }}>
                      模型
                    </label>
                    {renderModelSelect(visModels, visionModel, setVisionModel)}
                    {visModels.find(m => m.id === visionModel)?.desc && (
                      <div className="text-xs text-tertiary" style={{ marginTop: 'var(--space-1)' }}>
                        {visModels.find(m => m.id === visionModel).desc}
                      </div>
                    )}
                  </div>
                )}

                {visionProvider !== textProvider ? (
                  <div>
                    <label style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)', display: 'block', marginBottom: 'var(--space-1)' }}>
                      API Key
                    </label>
                    <div style={{ position: 'relative' }}>
                      <input
                        type={showPw ? 'text' : 'password'}
                        value={visionApiKey}
                        placeholder={hasVisSaved ? `已保存 (${visSavedKey})` : `${visProv.name || '视觉模型'} API Key`}
                        onChange={e => setVisionApiKey(e.target.value)}
                        autoComplete="off"
                        style={{ ...fieldStyle, paddingRight: 32 }}
                      />
                      <button
                        onClick={() => setShowPw(!showPw)}
                        style={{
                          position: 'absolute',
                          right: 8,
                          top: '50%',
                          transform: 'translateY(-50%)',
                          cursor: 'pointer',
                          color: 'var(--text-tertiary)',
                          fontSize: 'var(--text-sm)',
                        }}
                      >
                        {showPw ? '🙈' : '👁'}
                      </button>
                    </div>
                    {hasVisSaved && (
                      <div className="text-xs" style={{ marginTop: 'var(--space-1)', color: 'var(--success)' }}>
                        ✅ 已保存
                      </div>
                    )}
                    <div className="text-xs" style={{ marginTop: 'var(--space-1)', color: 'var(--warning)' }}>
                      ⚠️ 视觉与文本使用不同平台，需独立 Key
                    </div>
                  </div>
                ) : (
                  <div className="text-xs" style={{ color: 'var(--success)' }}>
                    ✅ 视觉与文本共用 {textProv.name} API Key
                  </div>
                )}
              </div>
            </div>
          ) : (
            /* 高级设置 */
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
              <div>
                <label style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)', display: 'block', marginBottom: 'var(--space-1)' }}>
                  抽帧间隔 (秒, 0=自动)
                </label>
                <input type="number" value={advancedSettings.frameInterval}
                  onChange={e => setAdvancedSettings({ ...advancedSettings, frameInterval: parseFloat(e.target.value) || 0 })}
                  min={0} step={0.5} style={fieldStyle} />
              </div>
              <div>
                <label style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)', display: 'block', marginBottom: 'var(--space-1)' }}>
                  视觉分析帧数上限 (0=不限制)
                </label>
                <input type="number" value={advancedSettings.maxVisionFrames}
                  onChange={e => setAdvancedSettings({ ...advancedSettings, maxVisionFrames: parseInt(e.target.value) || 0 })}
                  min={0} style={fieldStyle} />
              </div>
              <div>
                <label style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)', display: 'block', marginBottom: 'var(--space-1)' }}>
                  审核最大轮数 (默认6)
                </label>
                <input type="number" value={advancedSettings.maxReviewRounds}
                  onChange={e => setAdvancedSettings({ ...advancedSettings, maxReviewRounds: parseInt(e.target.value) || 6 })}
                  min={1} max={20} style={fieldStyle} />
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        {activeTab === 'api' && (
          <div style={{ padding: 'var(--space-4) var(--space-6)', borderTop: '1px solid var(--border-subtle)' }}>
            <button
              onClick={handleSave}
              disabled={busy}
              style={{
                width: '100%',
                padding: 'var(--space-2) var(--space-4)',
                background: 'var(--accent)',
                color: '#fff',
                border: 'none',
                borderRadius: 'var(--radius-md)',
                fontSize: 'var(--text-sm)',
                fontWeight: 'var(--font-semibold)',
                cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              {busy ? '⏳ 验证中...' : keyVerified ? '✅ 已就绪 — 重新验证' : '🔍 测试并保存'}
            </button>
            {status.msg && (
              <div style={{
                marginTop: 'var(--space-2)',
                fontSize: 'var(--text-xs)',
                textAlign: 'center',
                color: statusColor,
              }}>
                {status.msg}
              </div>
            )}
          </div>
        )}
        <div style={{
          padding: '0 var(--space-6) var(--space-4)',
          fontSize: 'var(--text-xs)',
          color: 'var(--text-tertiary)',
          textAlign: 'center',
        }}>
          🔒 Key 仅保存在本地 .env，不上传第三方
        </div>
      </div>
    </div>
  )
}

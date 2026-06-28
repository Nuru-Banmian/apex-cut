import { useState } from 'react'

const KEY_FIELD = {
  deepseek: 'deepseek_api_key', openai: 'openai_api_key',
  qwen: 'qwen_api_key', anthropic: 'anthropic_api_key', zhipu: 'zhipu_api_key',
}

const TIER = {
  'deepseek-v4-pro': '🔥 旗舰', 'deepseek-chat': '💰 实惠',
  'qwen3.7-plus': '⭐ 推荐', 'qwen3.5-plus': '💰 高性价比', 'qwen3.5-flash': '⚡ 极速',
  'qwen3-vl-flash': '💰 最省', 'GLM-4.7-Flash': '🆓 免费', 'GLM-4.6V-Flash': '🆓 免费',
  'gpt-4o': '⭐ 推荐', 'gpt-4o-mini': '💰 实惠',
  'claude-sonnet-4-6': '⭐ 推荐', 'claude-haiku-4-5-20251001': '💰 实惠',
}

const PRESETS = [
  { name: '💰 省钱', desc: '~¥1/视频', text: { provider: 'deepseek', model: 'deepseek-chat' }, vision: { provider: 'qwen', model: 'qwen3-vl-flash' } },
  { name: '⭐ 推荐', desc: '~¥3/视频', text: { provider: 'deepseek', model: 'deepseek-v4-pro' }, vision: { provider: 'qwen', model: 'qwen3.7-plus' } },
  { name: '🔥 最强', desc: '~¥8/视频', text: { provider: 'deepseek', model: 'deepseek-v4-pro' }, vision: { provider: 'qwen', model: 'qwen3.7-plus' } },
]

export default function SettingsModal({
  open, onClose,
  textProvider, setTextProvider, textApiKey, setTextApiKey, textModel, setTextModel,
  visionProvider, setVisionProvider, visionApiKey, setVisionApiKey, visionModel, setVisionModel,
  savedConfig, keyVerified, setKeyVerified, hasSavedKey, setHasSavedKey,
  providers, advancedSettings, setAdvancedSettings,
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
  const textProviders = providers.map(p => ({ ...p, label: p.has_vision ? p.name : `${p.name} (仅文本)` }))
  const keyMap = { deepseek: cfg.deepseek_api_key, openai: cfg.openai_api_key, qwen: cfg.qwen_api_key, anthropic: cfg.anthropic_api_key, zhipu: cfg.zhipu_api_key }
  const textSavedKey = keyMap[textProvider] || ''; const visSavedKey = keyMap[visionProvider] || ''
  const hasTextSaved = !!(textSavedKey && textSavedKey.includes('*'))
  const hasVisSaved = !!(visSavedKey && visSavedKey.includes('*'))

  const applyPreset = (p) => {
    setTextProvider(p.text.provider); setTextModel(p.text.model)
    setVisionProvider(p.vision.provider); setVisionModel(p.vision.model)
  }

  const handleSave = async () => {
    const hasNewTextKey = textApiKey && !textApiKey.includes('*')
    const hasNewVisKey = visionApiKey && visionProvider !== textProvider && !visionApiKey.includes('*')
    if (!hasNewTextKey && !hasTextSaved && !hasNewVisKey && !hasVisSaved) { setStatus({ type: 'error', msg: '请填写至少一个 API Key' }); return }
    setBusy(true); setStatus({ type: 'testing', msg: ' 测试连接中...' })
    if (hasNewTextKey) {
      try {
        const resp = await fetch('/api/config/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ llm_provider: textProvider, [KEY_FIELD[textProvider]]: textApiKey }) })
        const data = await resp.json()
        if (!resp.ok || !data.success) { setKeyVerified(false); setStatus({ type: 'error', msg: data.error || '连接失败' }); setBusy(false); return }
      } catch (e) { setKeyVerified(false); setStatus({ type: 'error', msg: `网络错误: ${e.message}` }); setBusy(false); return }
    }
    if (hasNewVisKey) {
      setStatus({ type: 'testing', msg: '️ 测试视觉连接...' })
      try {
        const resp = await fetch('/api/config/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ llm_provider: visionProvider, [KEY_FIELD[visionProvider]]: visionApiKey }) })
        const data = await resp.json()
        if (!resp.ok || !data.success) { setKeyVerified(false); setStatus({ type: 'error', msg: `视觉: ${data.error}` }); setBusy(false); return }
      } catch (e) { setKeyVerified(false); setStatus({ type: 'error', msg: `视觉网络: ${e.message}` }); setBusy(false); return }
    }
    setStatus({ type: 'testing', msg: ' 保存中...' })
    const sp = { llm_provider: textProvider, vision_provider: visionProvider }
    if (hasNewTextKey) sp[KEY_FIELD[textProvider]] = textApiKey
    if (hasNewVisKey) sp[KEY_FIELD[visionProvider]] = visionApiKey
    if (textProvider === 'qwen') sp.qwen_text_model = textModel
    if (textProvider === 'deepseek') sp.deepseek_model = textModel
    if (textProvider === 'openai') sp.openai_model = textModel
    if (visionProvider === 'qwen') sp.qwen_vision_model = visionModel
    if (visionProvider === 'zhipu') sp.zhipu_model = visionModel
    try {
      const resp = await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sp) })
      if (!resp.ok) { const e = await resp.json().catch(() => ({})); setStatus({ type: 'error', msg: `保存失败: ${e.detail || resp.status}` }); setBusy(false); return }
      const data = await resp.json()
      if (data.success) { if (hasNewTextKey || hasTextSaved) setKeyVerified(true); setHasSavedKey(true); setStatus({ type: 'success', msg: ' 配置已保存' }); if (hasNewTextKey) setTextApiKey(''); if (hasNewVisKey) setVisionApiKey('') }
    } catch (e) { setStatus({ type: 'error', msg: `保存失败: ${e.message}` }) }
    setBusy(false)
  }

  const statusColor = { success: 'var(--success)', error: 'var(--destructive)', testing: 'var(--warning)' }[status.type] || 'var(--muted-foreground)'
  const fieldStyle = { width: '100%', padding: 'var(--space-2) var(--space-3)', background: 'var(--background)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--foreground)', fontSize: 'var(--text-sm)', fontFamily: 'inherit' }
  const renderSelect = (models, value, onChange) => models?.length ? (
    <select value={value} onChange={e => onChange(e.target.value)} style={{ ...fieldStyle, cursor: 'pointer' }}>
      {models.map(m => <option key={m.id} value={m.id}>{m.name} {TIER[m.id] || ''}</option>)}
    </select>
  ) : <div style={{ fontSize: 'var(--text-xs)', color: 'var(--destructive)' }}>不支持此类型</div>

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }} onClick={onClose}>
      <div style={{ width: 500, maxHeight: '85vh', background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-xl)', boxShadow: 'var(--shadow-lg)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: 'var(--space-5) var(--space-6)', borderBottom: '1px solid var(--border)' }}>
          <span style={{ fontSize: 'var(--text-lg)', fontWeight: 'var(--font-semibold)' }}> 设置</span>
          <button onClick={onClose} style={{ width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 'var(--radius-sm)', cursor: 'pointer', color: 'var(--muted-foreground)', fontSize: 'var(--text-lg)' }}>×</button>
        </div>
        {/* Tabs */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', padding: '0 var(--space-6)' }}>
          {['api', 'advanced'].map(tab => (
            <button key={tab} onClick={() => setActiveTab(tab)} style={{
              padding: 'var(--space-2) var(--space-4)', borderBottom: activeTab === tab ? '2px solid var(--primary)' : '2px solid transparent',
              color: activeTab === tab ? 'var(--primary)' : 'var(--muted-foreground)', fontWeight: activeTab === tab ? 'var(--font-semibold)' : 'var(--font-normal)', fontSize: 'var(--text-sm)', cursor: 'pointer', background: 'none',
            }}>{tab === 'api' ? ' API 配置' : ' 高级'}</button>
          ))}
        </div>
        {/* Content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 'var(--space-6)' }}>
          {activeTab === 'api' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
              {/* 快捷方案 */}
              <div>
                <div style={{ fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)', color: 'var(--foreground)', marginBottom: 'var(--space-2)' }}>⚡ 快捷方案</div>
                <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                  {PRESETS.map(p => (
                    <button key={p.name} onClick={() => applyPreset(p)} style={{ flex: 1, padding: 'var(--space-2)', background: 'var(--background)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontFamily: 'inherit' }}>
                      <div style={{ fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)', color: 'var(--foreground)' }}>{p.name}</div>
                      <div style={{ fontSize: 10, color: 'var(--muted-foreground)', marginTop: 2 }}>{p.desc}</div>
                    </button>
                  ))}
                </div>
              </div>
              <div style={{ borderTop: '1px solid var(--border)' }} />
              {/* 文本模型 */}
              <div style={{ fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)', color: 'var(--foreground)' }}> 文本模型</div>
              <div><label style={{ fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>提供商</label>
                <select value={textProvider} onChange={e => { const np = e.target.value; setTextProvider(np); const p = providers.find(x => x.id === np); if (p?.text_models.length > 0) setTextModel(p.default_text_model || p.text_models[0].id) }} style={{ ...fieldStyle, cursor: 'pointer' }}>
                  {textProviders.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select></div>
              {textModels.length > 0 && <div><label style={{ fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>模型</label>{renderSelect(textModels, textModel, setTextModel)}{TIER[textModel] && <div style={{ fontSize: 10, color: 'var(--primary)', marginTop: 4 }}>{TIER[textModel]}</div>}</div>}
              <div><label style={{ fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>API Key</label>
                <div style={{ position: 'relative' }}>
                  <input type={showPw ? 'text' : 'password'} value={textApiKey} placeholder={hasTextSaved ? `已保存 (${textSavedKey})` : `${textProv.name || '文本模型'} API Key`} onChange={e => setTextApiKey(e.target.value)} autoComplete="off" style={{ ...fieldStyle, paddingRight: 32 }} />
                  <button onClick={() => setShowPw(!showPw)} title={showPw ? '隐藏' : '显示'} style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--muted-foreground)', fontSize: 'var(--text-sm)', padding: 2, lineHeight: 1 }}>{showPw ? '🙈' : '👁️'}</button>
                </div>
                {hasTextSaved && <div style={{ fontSize: 'var(--text-xs)', marginTop: 4, color: 'var(--success)' }}> 已保存</div>}</div>
              {/* 视觉模型 */}
              <div style={{ borderTop: '1px solid var(--border)', paddingTop: 'var(--space-4)' }}>
                <div style={{ fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)', color: 'var(--foreground)', marginBottom: 'var(--space-3)' }}>️ 视觉模型</div>
                {!textProv.has_vision && (
                  <div style={{ padding: 'var(--space-3)', background: 'var(--background)', border: '1px solid var(--warning)', borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-3)' }}>
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--warning)', fontWeight: 'var(--font-semibold)', marginBottom: 4 }}>⚠️ {textProv.name} 不支持视觉分析</div>
                    <div style={{ fontSize: 10, color: 'var(--muted-foreground)' }}>需要单独配置视觉模型（如千问、智谱）的 API Key</div>
                  </div>)}
                <div style={{ marginBottom: 'var(--space-3)' }}><label style={{ fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>提供商</label>
                  <select value={visionProvider} onChange={e => { const np = e.target.value; setVisionProvider(np); if (np === textProvider) setVisionApiKey(''); const p = providers.find(x => x.id === np); if (p?.vision_models.length > 0) setVisionModel(p.default_vision_model || p.vision_models[0].id) }} style={{ ...fieldStyle, cursor: 'pointer' }}>
                    {visionProviders.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select></div>
                {visModels.length > 0 && <div style={{ marginBottom: 'var(--space-3)' }}><label style={{ fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>模型</label>{renderSelect(visModels, visionModel, setVisionModel)}{TIER[visionModel] && <div style={{ fontSize: 10, color: 'var(--primary)', marginTop: 4 }}>{TIER[visionModel]}</div>}</div>}
                {visionProvider !== textProvider ? (
                  <div><label style={{ fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>API Key</label>
                    <div style={{ position: 'relative' }}>
                      <input type={showPw ? 'text' : 'password'} value={visionApiKey} placeholder={hasVisSaved ? `已保存 (${visSavedKey})` : `${visProv.name || '视觉模型'} API Key`} onChange={e => setVisionApiKey(e.target.value)} autoComplete="off" style={{ ...fieldStyle, paddingRight: 32 }} />
                      <button onClick={() => setShowPw(!showPw)} title={showPw ? '隐藏' : '显示'} style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--muted-foreground)', fontSize: 'var(--text-sm)', padding: 2, lineHeight: 1 }}>{showPw ? '🙈' : '👁️'}</button>
                    </div>
                    {hasVisSaved && <div style={{ fontSize: 'var(--text-xs)', marginTop: 4, color: 'var(--success)' }}> 已保存</div>}</div>
                ) : <div style={{ fontSize: 'var(--text-xs)', color: 'var(--success)' }}> 视觉与文本共用 {textProv.name} API Key</div>}
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
              <div><label style={{ fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>抽帧间隔 (秒, 0=自动)</label><input type="number" value={advancedSettings.frameInterval} onChange={e => setAdvancedSettings({ ...advancedSettings, frameInterval: parseFloat(e.target.value) || 0 })} min={0} step={0.5} style={fieldStyle} /></div>
              <div><label style={{ fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>视觉分析帧数上限 (0=不限制)</label><input type="number" value={advancedSettings.maxVisionFrames} onChange={e => setAdvancedSettings({ ...advancedSettings, maxVisionFrames: parseInt(e.target.value) || 0 })} min={0} style={fieldStyle} /></div>
              <div><label style={{ fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>审核最大轮数 (默认6)</label><input type="number" value={advancedSettings.maxReviewRounds} onChange={e => setAdvancedSettings({ ...advancedSettings, maxReviewRounds: parseInt(e.target.value) || 6 })} min={1} max={20} style={fieldStyle} /></div>
            </div>
          )}
        </div>
        {activeTab === 'api' && (
          <div style={{ padding: 'var(--space-4) var(--space-6)', borderTop: '1px solid var(--border)' }}>
            <button onClick={handleSave} disabled={busy} style={{ width: '100%', padding: 'var(--space-2) var(--space-4)', background: 'var(--primary)', color: 'var(--primary-foreground)', border: 'none', borderRadius: 'var(--radius-md)', fontSize: 'var(--text-sm)', fontWeight: 'var(--font-semibold)', cursor: 'pointer', fontFamily: 'inherit' }}>
              {busy ? ' 验证中...' : keyVerified ? ' 已就绪 — 重新验证' : ' 测试并保存'}
            </button>
            {status.msg && <div style={{ marginTop: 'var(--space-2)', fontSize: 'var(--text-xs)', textAlign: 'center', color: statusColor }}>{status.msg}</div>}
          </div>
        )}
        <div style={{ padding: '0 var(--space-6) var(--space-4)', fontSize: 'var(--text-xs)', color: 'var(--muted-foreground)', textAlign: 'center' }}> Key 仅保存在本地 .env，不上传第三方</div>
      </div>
    </div>
  )
}

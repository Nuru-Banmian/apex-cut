import { useState, useEffect, useRef, useCallback, Component } from 'react'
import AppShell from './components/AppShell'
import VideoStage from './components/VideoStage'
import SidePanel from './components/SidePanel'
import SettingsModal from './components/SettingsModal'
// 错误边界
class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100vh',
          background: 'var(--bg-primary)',
          color: 'var(--text-primary)',
        }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 48, marginBottom: 'var(--space-4)' }}>💥</div>
            <div style={{ fontSize: 'var(--text-xl)', fontWeight: 'var(--font-semibold)', marginBottom: 'var(--space-2)' }}>
              页面出错了
            </div>
            <div className="text-sm text-secondary" style={{ marginBottom: 'var(--space-4)' }}>
              {this.state.error?.message || '未知错误'}
            </div>
            <button
              onClick={() => { this.setState({ hasError: false }); window.location.reload() }}
              style={{
                padding: 'var(--space-2) var(--space-4)',
                background: 'var(--accent)',
                color: '#fff',
                border: 'none',
                borderRadius: 'var(--radius-md)',
                fontSize: 'var(--text-base)',
                cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              🔄 刷新页面
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

function determinePhase(taskStatus) {
  if (taskStatus === 'running') return 'processing'
  if (taskStatus === 'done' || taskStatus === 'failed') return 'result'
  return 'setup'
}

export default function App() {
  // ── 文本模型配置 ──
  const [textProvider, setTextProvider] = useState('deepseek')
  const [textApiKey, setTextApiKey] = useState('')
  const [textModel, setTextModel] = useState('deepseek-v4-pro')

  // ── 视觉模型配置 ──
  const [visionProvider, setVisionProvider] = useState('zhipu')
  const [visionApiKey, setVisionApiKey] = useState('')
  const [visionModel, setVisionModel] = useState('GLM-4.6V')

  // ── 通用 ──
  const [savedConfig, setSavedConfig] = useState({})
  const [keyVerified, setKeyVerified] = useState(false)
  const [hasSavedKey, setHasSavedKey] = useState(false)
  const [gpuStatus, setGpuStatus] = useState(null)
  const [providers, setProviders] = useState([])
  const [showSettings, setShowSettings] = useState(false)

  // ── Upload state ──
  const [videoPath, setVideoPath] = useState('')
  const [fileName, setFileName] = useState('')
  const [materials, setMaterials] = useState([])
  const [loadingLib, setLoadingLib] = useState(true)
  const [uploadError, setUploadError] = useState('')

  // ── Task state ──
  const [requirement, setRequirement] = useState('')
  const [contentType, setContentType] = useState('')
  const [targetDuration, setTargetDuration] = useState('')
  const [targetAspect, setTargetAspect] = useState('')
  const [taskId, setTaskId] = useState('')
  const [taskStatus, setTaskStatus] = useState('idle')
  const [progress, setProgress] = useState('')
  const [reviewRound, setReviewRound] = useState(0)
  const [error, setError] = useState('')

  // ── Director 策略预览 ──
  const [previewing, setPreviewing] = useState(false)
  const [directorResult, setDirectorResult] = useState(null)
  const [strategyLocked, setStrategyLocked] = useState(false)

  // ── Results ──
  const [analysis, setAnalysis] = useState(null)
  const [reviewScore, setReviewScore] = useState(null)
  const [reviewIssues, setReviewIssues] = useState([])
  const [downloadUrl, setDownloadUrl] = useState('')
  const [logLines, setLogLines] = useState([])

  // ── 高级设置 ──
  const [advancedSettings, setAdvancedSettings] = useState({
    frameInterval: 0,
    maxVisionFrames: 0,
    maxReviewRounds: 6,
  })

  // ── VideoStage 数据 ──
  const [editPlanForTimeline, setEditPlanForTimeline] = useState([])
  const [probeDuration, setProbeDuration] = useState(0)

  // ── 片段编辑器 ──
  const [clips, setClips] = useState([])
  const [currentClipIndex, setCurrentClipIndex] = useState(0)
  const [outputName, setOutputName] = useState('')
  const [manifest, setManifest] = useState(null)
  const [merging, setMerging] = useState(false)
  const [resultStreamUrl, setResultStreamUrl] = useState('')

  const sseRef = useRef(null)
  const pollTimerRef = useRef(null)
  const taskIdRef = useRef('')

  // ── 素材库 ──
  const loadMaterials = useCallback(async () => {
    setLoadingLib(true)
    try {
      const resp = await fetch('/api/materials')
      if (resp.ok) {
        const data = await resp.json()
        if (data.success) setMaterials(data.materials || [])
      }
    } catch (_) { }
    setLoadingLib(false)
  }, [])

  // ── 初始化 ──
  useEffect(() => {
    Promise.all([
      fetch('/api/config').then(r => r.json()),
      fetch('/api/providers').then(r => r.json()),
    ]).then(([cfgData, provData]) => {
      if (cfgData?.success && cfgData?.config) {
        const cfg = cfgData.config
        setSavedConfig(cfg)
        const tp = cfg.llm_provider || 'deepseek'
        setTextProvider(tp)
        const vp = cfg.vision_provider || 'zhipu'
        setVisionProvider(vp)

        const keyMap = {
          deepseek: cfg.deepseek_api_key,
          openai: cfg.openai_api_key,
          qwen: cfg.qwen_api_key,
          anthropic: cfg.anthropic_api_key,
          zhipu: cfg.zhipu_api_key,
        }
        const visMap = {
          zhipu: cfg.zhipu_api_key,
          qwen: cfg.qwen_api_key,
          openai: cfg.openai_api_key,
          anthropic: cfg.anthropic_api_key,
        }
        const hasAnySaved = (keyMap[tp] && keyMap[tp].includes('*')) ||
          (visMap[vp] && visMap[vp].includes('*'))
        if (hasAnySaved) {
          setHasSavedKey(true)
          setKeyVerified(true)
        }
        if (cfgData?.gpu) setGpuStatus(cfgData.gpu)
      }

      if (provData?.success && provData?.providers) {
        setProviders(provData.providers)
        const provs = provData.providers
        const tp2 = cfgData?.config?.llm_provider || 'deepseek'
        const vp2 = cfgData?.config?.vision_provider || 'zhipu'
        const textProv = provs.find(p => p.id === tp2)
        const visProv = provs.find(p => p.id === vp2)
        const config = cfgData?.config || {}

        const savedTextModel =
          (tp2 === 'qwen' && config.qwen_text_model) ||
          (tp2 === 'deepseek' && config.deepseek_model) ||
          (tp2 === 'openai' && config.openai_model) ||
          ''
        if (savedTextModel) {
          setTextModel(savedTextModel)
        } else if (textProv?.default_text_model) {
          setTextModel(textProv.default_text_model)
        }

        const savedVisModel =
          (vp2 === 'qwen' && config.qwen_vision_model) ||
          (vp2 === 'zhipu' && config.zhipu_model) ||
          ''
        if (savedVisModel) {
          setVisionModel(savedVisModel)
        } else if (visProv?.default_vision_model) {
          setVisionModel(visProv.default_vision_model)
        }
      }
    }).catch((e) => { console.error('加载配置失败:', e) })
    loadMaterials()
  }, [loadMaterials])

  // ── SSE ──
  const startStreaming = useCallback(() => {
    const tid = taskIdRef.current
    if (!tid) return

    const es = new EventSource(`/api/tasks/${tid}/stream`)
    sseRef.current = es

    es.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)
        if (data.log) {
          if (data.overwrite) {
            setLogLines(prev => [...prev.slice(0, -1), data.log])
          } else {
            setLogLines(prev => [...prev, data.log])
          }
        }
        if (data.progress) setProgress(data.progress)
        if (data.review_round != null) setReviewRound(data.review_round)
        if (data.review_score != null) setReviewScore(data.review_score)

        if (data.status === 'done') {
          es.close()
          sseRef.current = null
          setTaskStatus('done')
          fetchResult()
        } else if (data.status === 'failed') {
          es.close()
          sseRef.current = null
          setTaskStatus('failed')
          setError(data.error || '未知错误')
        }
      } catch (e) { console.error('SSE 消息解析失败:', e) }
    }

    es.onerror = () => {
      es.close()
      sseRef.current = null
      pollTimerRef.current = setInterval(async () => {
        const tid2 = taskIdRef.current
        if (!tid2) return
        try {
          const resp = await fetch(`/api/tasks/${tid2}`)
          if (!resp.ok) return
          const data = await resp.json()
          if (data.progress) setProgress(data.progress)
          setReviewRound(data.review_round)
          if (data.review_score != null) setReviewScore(data.review_score)
          if (data.status === 'done') {
            clearInterval(pollTimerRef.current); pollTimerRef.current = null
            setTaskStatus('done'); fetchResult()
          } else if (data.status === 'failed') {
            clearInterval(pollTimerRef.current); pollTimerRef.current = null
            setTaskStatus('failed'); setError(data.error || '未知错误')
          }
        } catch (e) { console.error('轮询失败:', e) }
      }, 3000)
    }
  }, [])

  const fetchResult = async () => {
    const tid = taskIdRef.current
    if (!tid) return
    try {
      const resp = await fetch(`/api/tasks/${tid}/result`)
      const data = await resp.json()
      setReviewScore(data.review_score)
      setReviewIssues(data.review_issues || [])
      setAnalysis(data.analysis || null)
      setDownloadUrl(`/api/tasks/${tid}/download`)
    } catch (e) {
      console.error('获取结果失败:', e)
    }
    // 同时拉取 manifest
    fetchManifest()
  }

  const fetchManifest = async () => {
    const tid = taskIdRef.current
    if (!tid) return
    try {
      const resp = await fetch(`/api/tasks/${tid}/manifest`)
      const data = await resp.json()
      setManifest(data)
      const clipList = data.clips || []
      setClips(clipList)
      if (clipList.length > 0) setCurrentClipIndex(0)
    } catch (e) {
      console.error('获取 manifest 失败:', e)
    }
  }

  const handleSelectClip = (i) => setCurrentClipIndex(i)

  const handleReorderClips = (reordered) => {
    setClips(reordered)
  }

  const handleMerge = async (customOrder) => {
    const tid = taskIdRef.current
    if (!tid || !clips.length) return
    setMerging(true)
    try {
      // 使用 clip 的原始 index（从 manifest 中）构建剪辑顺序
      const order = (customOrder || clips).map(c => (c.index || 1) - 1)
      const resp = await fetch(`/api/tasks/${tid}/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clip_order: order }),
      })
      const data = await resp.json()
      if (data.success) {
        setDownloadUrl(`/api/tasks/${tid}/download?t=${Date.now()}`)
      }
    } catch (e) {
      console.error('合并失败:', e)
    }
    setMerging(false)
  }

  // ── 预览策略 ──
  const handlePreview = async () => {
    if (!keyVerified || !videoPath) return
    setPreviewing(true)
    setDirectorResult(null)
    setError('')
    try {
      const resp = await fetch('/api/director/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_path: videoPath,
          user_requirement: requirement,
          content_type: contentType || null,
          target_duration: targetDuration ? parseFloat(targetDuration) : null,
          target_aspect_ratio: targetAspect || null,
          text_provider: textProvider,
          text_api_key: textApiKey,
          text_model: textModel,
        }),
      })
      const data = await resp.json()
      if (data.success) {
        setDirectorResult(data)
      } else {
        setError(data.error || '预览失败')
      }
    } catch (e) {
      setError(e.message)
    }
    setPreviewing(false)
  }

  // ── 直接启动（跳过 Director）──
  const handleDirectStart = async (presetStrategy) => {
    if (!keyVerified || !videoPath) return
    setTaskStatus('running')
    setError('')
    setStrategyLocked(true)
    try {
      const resp = await fetch('/api/tasks/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_path: videoPath,
          user_requirement: requirement || 'Apex 击杀集锦',
          output_name: outputName,
          content_type: 'apex',
          target_duration: targetDuration ? parseFloat(targetDuration) : null,
          target_aspect_ratio: targetAspect || null,
          text_provider: textProvider,
          text_api_key: textApiKey,
          text_model: textModel,
          vision_provider: visionProvider,
          vision_api_key: visionApiKey,
          vision_model: visionModel,
          frame_interval: advancedSettings.frameInterval,
          max_vision_frames: advancedSettings.maxVisionFrames,
          max_review_rounds: advancedSettings.maxReviewRounds,
          director_confirmed: true,
          confirmed_content_type: 'apex',
          confirmed_segment_strategy: presetStrategy,
          confirmed_review_criteria: [],
          confirmed_edit_style: '击杀集锦',
          confirmed_editing_notes: '跳过Director，固定策略',
        }),
      })
      const data = await resp.json()
      if (!resp.ok || data.status === 'failed') {
        setTaskStatus('failed')
        setError(data.error || data.detail || '创建任务失败')
        return
      }
      taskIdRef.current = data.task_id
      setTaskId(data.task_id)
      startStreaming()
    } catch (e) {
      setTaskStatus('failed')
      setError(e.message)
    }
  }

  // ── 策略实时编辑回调 ──
  const handleUpdateStrategy = (partial) => {
    if (!directorResult) return
    const updated = {
      ...directorResult,
      segment_strategy: { ...directorResult.segment_strategy, ...partial },
    }
    setDirectorResult(updated)
  }

  // ── 确认策略并开始剪辑 ──
  const handleConfirmAndStart = async (editedStrategy) => {
    if (!keyVerified || !videoPath) return

    setTaskStatus('running')
    setError('')
    setStrategyLocked(true)

    try {
      const resp = await fetch('/api/tasks/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_path: videoPath,
          user_requirement: requirement,
          content_type: contentType || null,
          target_duration: targetDuration ? parseFloat(targetDuration) : null,
          target_aspect_ratio: targetAspect || null,
          text_provider: textProvider,
          text_api_key: textApiKey,
          text_model: textModel,
          vision_provider: visionProvider,
          vision_api_key: visionApiKey,
          vision_model: visionModel,
          frame_interval: advancedSettings.frameInterval,
          max_vision_frames: advancedSettings.maxVisionFrames,
          max_review_rounds: advancedSettings.maxReviewRounds,
          director_confirmed: true,
          confirmed_content_type: contentType || 'apex',
          confirmed_segment_strategy: editedStrategy,
          confirmed_review_criteria: directorResult?.review_criteria || [],
          confirmed_edit_style: directorResult?.edit_style || '',
          confirmed_editing_notes: directorResult?.editing_notes || '',
        }),
      })
      const data = await resp.json()
      if (!resp.ok || data.status === 'failed') {
        setTaskStatus('failed')
        setError(data.error || data.detail || '创建任务失败')
        return
      }
      taskIdRef.current = data.task_id
      setTaskId(data.task_id)
      startStreaming()
    } catch (e) {
      setTaskStatus('failed')
      setError(e.message)
    }
  }

  // ── Reset ──
  const handleReset = () => {
    if (sseRef.current) { sseRef.current.close(); sseRef.current = null }
    if (pollTimerRef.current) { clearInterval(pollTimerRef.current); pollTimerRef.current = null }
    taskIdRef.current = ''
    setTaskStatus('idle'); setTaskId('')
    setProgress(''); setReviewRound(0); setError('')
    setAnalysis(null); setReviewScore(null); setReviewIssues([])
    setDownloadUrl(''); setLogLines([]); setEditPlanForTimeline([])
    setDirectorResult(null); setStrategyLocked(false)
  }

  // ── 阶段判定 ──
  const phase = determinePhase(taskStatus)

  // ── 视频流 URL（浏览器不能直接读本地路径，需要走后端）──
  const getFilenameFromPath = (p) => {
    if (!p) return ''
    return p.replace(/\\/g, '/').split('/').pop()
  }
  const videoStreamUrl = videoPath
    ? `/api/materials/stream/${encodeURIComponent(getFilenameFromPath(videoPath))}`
    : ''

  // 当前选中片段的播放 URL
  const currentClipUrl = (phase === 'result' && clips.length > 0 && currentClipIndex < clips.length)
    ? `/api/tasks/${taskId}/clips/${encodeURIComponent(clips[currentClipIndex].file)}`
    : null

  // ── 渲染 ──
  return (
    <ErrorBoundary>
      <AppShell
        phase={phase}
        gpuStatus={gpuStatus}
        onSettings={() => setShowSettings(true)}
      >
        <VideoStage
              phase={phase}
              streamUrl={videoStreamUrl}
              resultStreamUrl={resultStreamUrl}
              segments={editPlanForTimeline}
              downloadUrl={phase === 'result' ? downloadUrl : null}
              totalDuration={probeDuration}
              clips={clips}
              currentClipIndex={currentClipIndex}
              currentClipUrl={currentClipUrl}
              onSelectClip={handleSelectClip}
              onReorderClips={handleReorderClips}
              taskId={taskId}
            />
            <SidePanel
              phase={phase}
              /* ── SetupPanel props ── */
              materials={materials} loadingLib={loadingLib} loadMaterials={loadMaterials}
              videoPath={videoPath} setVideoPath={setVideoPath}
              fileName={fileName} setFileName={setFileName}
              keyVerified={keyVerified} uploadError={uploadError} setUploadError={setUploadError}
              outputName={outputName} setOutputName={setOutputName}
              onDirectStart={handleDirectStart}
              resultStreamUrl={resultStreamUrl} setResultStreamUrl={setResultStreamUrl}
              /* ── ProgressPanel props ── */
              progress={progress}
              reviewRound={reviewRound}
              error={error}
              logLines={logLines}
              /* ── ResultPanel props ── */
              score={reviewScore}
              issues={reviewIssues}
              downloadUrl={downloadUrl}
              taskId={taskId}
              onReset={handleReset}
              clips={clips}
              merging={merging}
              onMerge={handleMerge}
            />
      </AppShell>

      <SettingsModal
        open={showSettings}
        onClose={() => setShowSettings(false)}
        textProvider={textProvider} setTextProvider={setTextProvider}
        textApiKey={textApiKey} setTextApiKey={setTextApiKey}
        textModel={textModel} setTextModel={setTextModel}
        visionProvider={visionProvider} setVisionProvider={setVisionProvider}
        visionApiKey={visionApiKey} setVisionApiKey={setVisionApiKey}
        visionModel={visionModel} setVisionModel={setVisionModel}
        savedConfig={savedConfig}
        keyVerified={keyVerified} setKeyVerified={setKeyVerified}
        hasSavedKey={hasSavedKey} setHasSavedKey={setHasSavedKey}
        providers={providers}
        advancedSettings={advancedSettings} setAdvancedSettings={setAdvancedSettings}
      />
    </ErrorBoundary>
  )
}

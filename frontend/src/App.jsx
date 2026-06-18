import { useState, useEffect, useRef, useCallback, Component } from 'react'
import ApiConfig from './components/ApiConfig'
import VideoUpload from './components/VideoUpload'
import EditRequirements from './components/EditRequirements'
import ProgressCard from './components/ProgressCard'
import AnalysisResult from './components/AnalysisResult'
import EditResult from './components/EditResult'

// 错误边界 — 防止未捕获异常导致全屏白/黑
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
        <div className="card" style={{ marginTop: 40, textAlign: 'center' }}>
          <div className="card-title"><span className="icon">💥</span> 页面出错了</div>
          <p style={{ color: 'var(--dim)', fontSize: 13, marginBottom: 12 }}>
            {this.state.error?.message || '未知错误'}
          </p>
          <button className="btn" onClick={() => { this.setState({ hasError: false }); window.location.reload() }}>
            🔄 刷新页面
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

const STEPS = ['director', 'analyzer', 'editor', 'reviewer']

export default function App() {
  // ── Config state ──
  const [llmProvider, setLlmProvider] = useState('deepseek')
  const [apiKey, setApiKey] = useState('')
  const [visionProvider, setVisionProvider] = useState('zhipu')
  const [visionKey, setVisionKey] = useState('')
  const [savedConfig, setSavedConfig] = useState({})
  const [keyVerified, setKeyVerified] = useState(false)
  const [hasSavedKey, setHasSavedKey] = useState(false)

  // ── Upload state ──
  const [videoPath, setVideoPath] = useState('')
  const [fileName, setFileName] = useState('')

  // ── Task state ──
  const [requirement, setRequirement] = useState('')
  const [targetDuration, setTargetDuration] = useState('')
  const [targetAspect, setTargetAspect] = useState('')
  const [taskId, setTaskId] = useState('')
  const [taskStatus, setTaskStatus] = useState('idle') // idle | running | done | failed
  const [progress, setProgress] = useState('')
  const [reviewRound, setReviewRound] = useState(0)
  const [error, setError] = useState('')
  const [currentStep, setCurrentStep] = useState(-1)

  // ── Results ──
  const [analysis, setAnalysis] = useState(null)
  const [reviewScore, setReviewScore] = useState(null)
  const [reviewIssues, setReviewIssues] = useState([])
  const [downloadUrl, setDownloadUrl] = useState('')

  const pollRef = useRef(null)
  const taskIdRef = useRef('')  // 避免闭包过期，始终持有最新 taskId

  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => {
        if (data?.success && data?.config) {
          const cfg = data.config
          setSavedConfig(cfg)
          const p = cfg.llm_provider || 'deepseek'
          setLlmProvider(p)
          setVisionProvider(cfg.vision_provider || 'zhipu')

          // check if any keys are saved (masked)
          const keyMap = { deepseek: cfg.deepseek_api_key, openai: cfg.openai_api_key, qwen: cfg.qwen_api_key, anthropic: cfg.anthropic_api_key }
          const visMap = { zhipu: cfg.zhipu_api_key, qwen: cfg.qwen_api_key, openai: cfg.openai_api_key }
          const hasAnySaved = (keyMap[p] && keyMap[p].includes('*')) ||
                              (visMap[cfg.vision_provider] && visMap[cfg.vision_provider].includes('*'))
          if (hasAnySaved) {
            setHasSavedKey(true)
            setKeyVerified(true)
          }
        }
      })
      .catch(() => {})
  }, [])

  // 选千问时自动切换视觉提供商（qwen3.7-plus 原生多模态，一个 Key 搞定图文）
  useEffect(() => {
    if (llmProvider === 'qwen') {
      setVisionProvider('qwen')
    }
  }, [llmProvider])

  // ── Poll task status ──
  // 使用 ref 读取最新 taskId，避免 setState 异步导致的闭包过期问题
  const startPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      const tid = taskIdRef.current
      if (!tid) return  // taskId 尚未就绪，跳过
      try {
        const resp = await fetch(`/api/tasks/${tid}`)
        if (!resp.ok) return
        const data = await resp.json()
        setProgress(data.progress)
        setReviewRound(data.review_round)

        // detect current step
        const stepMap = { director: 0, analyzer: 1, editor: 2, reviewer: 3 }
        for (const [k, v] of Object.entries(stepMap)) {
          if (data.progress.includes(k)) { setCurrentStep(v); break }
        }

        if (data.status === 'done') {
          clearInterval(pollRef.current)
          pollRef.current = null
          setTaskStatus('done')
          fetchResult()
        } else if (data.status === 'failed') {
          clearInterval(pollRef.current)
          pollRef.current = null
          setTaskStatus('failed')
          setError(data.error || '未知错误')
        }
      } catch (_) {}
    }, 2000)
  }, [])

  const fetchResult = async () => {
    try {
      const resp = await fetch(`/api/tasks/${taskIdRef.current}/result`)
      const data = await resp.json()
      setReviewScore(data.review_score)
      setReviewIssues(data.review_issues || [])
      setAnalysis(data.analysis || null)
      setDownloadUrl(`/api/tasks/${taskId}/download`)
    } catch (e) {
      console.error('获取结果失败:', e)
    }
  }

  // ── Submit task ──
  const handleStart = async () => {
    if (!keyVerified) return
    if (!videoPath) return

    setTaskStatus('running')
    setError('')
    setCurrentStep(0)

    try {
      const resp = await fetch('/api/tasks/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_path: videoPath,
          user_requirement: requirement,
          target_duration: targetDuration ? parseFloat(targetDuration) : null,
          target_aspect_ratio: targetAspect || null,
          llm_provider: llmProvider,
          api_key: apiKey,
          vision_key: visionKey,
          vision_provider: visionProvider,
        }),
      })
      const data = await resp.json()
      if (resp.ok) {
        taskIdRef.current = data.task_id  // ref 立即生效，避免闭包过期
        setTaskId(data.task_id)
        startPolling()
      } else {
        setTaskStatus('failed')
        setError(data.detail || '创建任务失败')
      }
    } catch (e) {
      setTaskStatus('failed')
      setError(e.message)
    }
  }

  // ── Reset ──
  const handleReset = () => {
    taskIdRef.current = ''
    setTaskStatus('idle')
    setTaskId('')
    setProgress('')
    setReviewRound(0)
    setError('')
    setCurrentStep(-1)
    setAnalysis(null)
    setReviewScore(null)
    setReviewIssues([])
    setDownloadUrl('')
  }

  const isRunning = taskStatus === 'running'

  return (
    <ErrorBoundary>
    <div className="app-layout">
      {/* ═══════════════ 左侧边栏 — API 配置 ═══════════════ */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <h1>🎬 <span>AutoCut</span></h1>
          <p>智能视频剪辑 Agent</p>
        </div>

        <ApiConfig
          llmProvider={llmProvider} setLlmProvider={setLlmProvider}
          apiKey={apiKey} setApiKey={setApiKey}
          visionProvider={visionProvider} setVisionProvider={setVisionProvider}
          visionKey={visionKey} setVisionKey={setVisionKey}
          savedConfig={savedConfig}
          keyVerified={keyVerified} setKeyVerified={setKeyVerified}
          hasSavedKey={hasSavedKey} setHasSavedKey={setHasSavedKey}
        />
      </aside>

      {/* ═══════════════ 右侧主内容 ═══════════════ */}
      <main className="main-content">

        {!isRunning && taskStatus !== 'done' && (
          <>
            <VideoUpload
              onUpload={(path, name) => { setVideoPath(path); setFileName(name) }}
              fileName={fileName}
            />

            <EditRequirements
              requirement={requirement} setRequirement={setRequirement}
              targetDuration={targetDuration} setTargetDuration={setTargetDuration}
              targetAspect={targetAspect} setTargetAspect={setTargetAspect}
            />

            <button className="btn" onClick={handleStart} disabled={!keyVerified || !videoPath}>
              🚀 开始分析 & 剪辑
            </button>
          </>
        )}

        {isRunning && (
          <ProgressCard
            progress={progress}
            reviewRound={reviewRound}
            currentStep={currentStep}
            steps={STEPS}
            error={error}
          />
        )}

        {taskStatus === 'done' && analysis && (
          <AnalysisResult analysis={analysis} />
        )}

        {taskStatus === 'done' && (
          <EditResult
            score={reviewScore}
            issues={reviewIssues}
            downloadUrl={downloadUrl}
            taskId={taskId}
            onReset={handleReset}
          />
        )}

        {taskStatus === 'failed' && (
          <div className="card">
            <div className="card-title"><span className="icon">❌</span> 任务失败</div>
            <div className="error-msg">{error}</div>
            <button className="btn" onClick={handleReset} style={{ marginTop: 12 }}>🔄 重试</button>
          </div>
        )}
      </main>
    </div>
    </ErrorBoundary>
  )
}

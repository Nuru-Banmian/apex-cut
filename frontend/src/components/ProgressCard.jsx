export default function ProgressCard({ progress, reviewRound, currentStep, steps, error }) {
  return (
    <div className="card">
      <div className="card-title"><span className="icon">⏳</span> 处理进度</div>
      <div className="progress-steps">
        {steps.map((s, i) => (
          <div key={s} className={`step-bar${i < currentStep ? ' done' : i === currentStep ? ' active' : ''}${error ? ' error' : ''}`} />
        ))}
      </div>
      <div className="status-line">
        <span className="st">{progress || '初始化...'}</span>
        <span className="rd">{reviewRound > 0 ? `审核第 ${reviewRound} 轮` : ''}</span>
      </div>
      {error && <div className="error-msg">{error}</div>}
    </div>
  )
}

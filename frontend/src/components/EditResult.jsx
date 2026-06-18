export default function EditResult({ score, issues, downloadUrl, taskId, onReset }) {
  return (
    <div className="card">
      <div className="card-title"><span className="icon">📊</span> 剪辑结果</div>
      <div className={`result-score${score != null && score < 70 ? ' fail' : ''}`}>
        {score != null ? `${score}/100` : '--'}
      </div>
      <ul className="issues">
        {(issues || []).map((s, i) => <li key={i}>{s}</li>)}
      </ul>
      {downloadUrl && (
        <a className="download-link" href={downloadUrl} target="_blank" rel="noreferrer">
          ⬇ 下载成品视频
        </a>
      )}
      <button className="btn" onClick={onReset} style={{ marginTop: 12, background: '#2a2a3a' }}>
        🚀 再来一次
      </button>
    </div>
  )
}

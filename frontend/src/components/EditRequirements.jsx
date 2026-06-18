const PRESETS = [
  '剪成3分钟精华版，去掉所有静音段和口误，加中文字幕',
  '剪成1分钟快节奏短视频，竖屏9:16，保留最精彩的画面',
  '剪成5分钟教程版，保留完整的技术内容，去掉废话和停顿',
  '只去掉静音和口误，保留全部有效内容，不做精简',
  '分析这个视频的内容，告诉我里面讲了什么',
]

export default function EditRequirements({
  requirement, setRequirement, targetDuration, setTargetDuration, targetAspect, setTargetAspect,
}) {
  return (
    <div className="card">
      <div className="card-title"><span className="icon">✏️</span> 剪辑需求</div>
      <div className="field">
        <textarea value={requirement} onChange={e => setRequirement(e.target.value)}
          placeholder="例如：把这段30分钟的采访剪成3分钟的精华版，竖屏9:16，加中文字幕，去掉所有的静音和口误片段" />
      </div>
      <div className="presets">
        {PRESETS.map((p, i) => (
          <span key={i} className="preset" onClick={() => setRequirement(p)}>{p.length > 20 ? p.slice(0, 20) + '...' : p}</span>
        ))}
      </div>
      <div className="row" style={{ marginTop: 12 }}>
        <div className="field">
          <label>目标时长（秒，可选）</label>
          <input type="number" value={targetDuration} onChange={e => setTargetDuration(e.target.value)} placeholder="如 180" />
        </div>
        <div className="field">
          <label>目标画幅（可选）</label>
          <select value={targetAspect} onChange={e => setTargetAspect(e.target.value)}>
            <option value="">保持原画幅</option>
            <option value="16:9">横屏 16:9</option>
            <option value="9:16">竖屏 9:16</option>
            <option value="1:1">方形 1:1</option>
            <option value="4:3">4:3</option>
          </select>
        </div>
      </div>
    </div>
  )
}

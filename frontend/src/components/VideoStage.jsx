import SegmentTimeline from './SegmentTimeline'
import ClipTimeline from './ClipTimeline'

export default function VideoStage({ phase, streamUrl, resultStreamUrl, segments, downloadUrl, totalDuration,
  clips, currentClipIndex, currentClipUrl, onSelectClip, onReorderClips, taskId,
}) {
  const showResultVideo = phase === 'result' && downloadUrl
  // 选中片段 → 播放片段；否则 → 合并成品 → 结果库选中 → 素材库源视频
  const src = currentClipUrl || (showResultVideo ? downloadUrl : (resultStreamUrl || streamUrl))

  return (
    <div style={{
      flex: 1,
      maxWidth: '65%',
      display: 'flex',
      flexDirection: 'column',
      background: '#000',
      borderRadius: 'var(--radius-lg)',
      margin: 'var(--space-4)',
      overflow: 'hidden',
      position: 'relative',
      minWidth: 0,
    }}>
      {/* 视频播放区 */}
      <div style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
      }}>
        {(src) ? (
          <video
            key={src}
            src={src}
            controls
            preload="metadata"
            style={{
              maxWidth: '100%',
              maxHeight: '100%',
              borderRadius: 'var(--radius-md)',
            }}
          />
        ) : (
          <EmptyState />
        )}
      </div>

      {/* 结果阶段：片段编辑器时间线 */}
      {phase === 'result' && clips?.length > 0 && (
        <ClipTimeline
          clips={clips}
          currentIndex={currentClipIndex}
          onSelect={onSelectClip}
          onReorder={onReorderClips}
          taskId={taskId}
        />
      )}

      {/* 非结果阶段：片段时间线预览 */}
      {phase !== 'result' && (
        <SegmentTimeline segments={segments} totalDuration={totalDuration} />
      )}
    </div>
  )
}

function EmptyState() {
  return (
    <div style={{
      textAlign: 'center',
      color: 'var(--text-tertiary)',
      userSelect: 'none',
    }}>
      <div style={{ fontSize: 48, marginBottom: 'var(--space-4)' }}>🎬</div>
      <div style={{
        fontSize: 'var(--text-lg)',
        fontWeight: 'var(--font-medium)',
        color: 'var(--text-secondary)',
      }}>
        拖拽视频或从素材库选择
      </div>
      <div style={{
        fontSize: 'var(--text-sm)',
        marginTop: 'var(--space-2)',
      }}>
        支持 MP4 / MOV / AVI / MKV / FLV
      </div>
    </div>
  )
}

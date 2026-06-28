import TopBar from './TopBar'
import NavRail from './NavRail'

export default function AppShell({ phase, gpuStatus, onSettings, children }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      overflow: 'hidden',
    }}>
      <TopBar gpuStatus={gpuStatus} onSettings={onSettings} />
      <div className="app-main" style={{
        flex: 1,
        display: 'flex',
        overflow: 'hidden',
      }}>
        <NavRail phase={phase} />
        {children}
      </div>
    </div>
  )
}

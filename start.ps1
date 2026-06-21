# AutoCut Agent — 一键启动 (Backend + Frontend)
Set-Location $PSScriptRoot

# ═══════════════════════════════════
# 查找 Python
# ═══════════════════════════════════
$Python = $null
@(
    "D:\study_tool\anaconda\envs\agent\python.exe",
    "$env:USERPROFILE\anaconda3\envs\agent\python.exe",
    "$env:USERPROFILE\miniconda3\envs\agent\python.exe",
    "C:\Users\1\anaconda3\envs\agent\python.exe"
) | ForEach-Object { if (-not $Python -and (Test-Path $_)) { $Python = $_ } }

if (-not $Python) {
    try { $Python = (Get-Command python -ErrorAction Stop).Source } catch {}
    if (-not $Python) {
        try { $Python = (Get-Command python3 -ErrorAction Stop).Source } catch {}
    }
}

# ═══════════════════════════════════
# 查找 Node
# ═══════════════════════════════════
$Node = $null
try { $Node = (Get-Command node -ErrorAction Stop).Source } catch {}

$FrontendPort = 3000
$BackendPort  = 8000

# ═══════════════════════════════════
# 打印并暂停 (避免闪退)
# ═══════════════════════════════════
function Wait-Exit {
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  AutoCut Agent — Apex 智能剪辑系统" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

if (-not $Python) {
    Write-Host "  [ERROR] Python 未找到" -ForegroundColor Red
    Write-Host "  请安装 Python 或修改脚本 knownPaths" -ForegroundColor Yellow
    Wait-Exit
}
if (-not $Node) {
    Write-Host "  [ERROR] Node.js 未找到" -ForegroundColor Red
    Write-Host "  请安装 Node.js: https://nodejs.org" -ForegroundColor Yellow
    Wait-Exit
}

Write-Host "  Python : $Python" -ForegroundColor DarkGray
Write-Host "  Node   : $Node" -ForegroundColor DarkGray
Write-Host ""

# ── 检查 Python ──
Write-Host "[1/4] 检查 Python 环境..." -ForegroundColor Gray
try {
    $check = & $Python -c "from apex_cut.config import settings; print(settings.llm_provider)" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] autocut 模块导入失败" -ForegroundColor Red
        Write-Host "  $check" -ForegroundColor Red
        Write-Host "  请运行: pip install -r requirements.txt" -ForegroundColor Yellow
        Wait-Exit
    }
    Write-Host "  OK — Provider: $check" -ForegroundColor DarkGray
} catch {
    Write-Host "  [ERROR] Python 执行异常: $_" -ForegroundColor Red
    Wait-Exit
}

# ── 检查前端 ──
Write-Host "[2/4] 检查前端依赖..." -ForegroundColor Gray
$frontendDir = "$PSScriptRoot\frontend"
if (-not (Test-Path "$frontendDir\node_modules")) {
    Write-Host "  首次运行，安装前端依赖..." -ForegroundColor Yellow
    $oldLoc = Get-Location
    try {
        Set-Location $frontendDir
        $npmCmd = $null
        try { $npmCmd = (Get-Command npm -ErrorAction Stop).Source } catch {}
        if (-not $npmCmd) {
            # npm 不在 PATH 中，尝试同目录下的 npm.cmd
            $npmDir = Split-Path $Node -Parent
            $npmTry = "$npmDir\npm.cmd"
            if (Test-Path $npmTry) { $npmCmd = $npmTry }
            else {
                # 最后试 npx.cmd
                $npxTry = "$npmDir\npx.cmd"
                if (Test-Path $npxTry) { $npmCmd = $npxTry }
            }
        }
        if (-not $npmCmd) {
            Write-Host "  [ERROR] npm 未找到，请手动安装 Node.js" -ForegroundColor Red
            Set-Location $oldLoc
            Wait-Exit
        }
        Write-Host "  使用: $npmCmd install" -ForegroundColor DarkGray
        cmd /c "`"$npmCmd`" install"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [ERROR] npm install 失败" -ForegroundColor Red
            Set-Location $oldLoc
            Wait-Exit
        }
        Set-Location $oldLoc
        Write-Host "  依赖安装完成" -ForegroundColor Green
    } catch {
        Set-Location $oldLoc
        Write-Host "  [ERROR] npm install 异常: $_" -ForegroundColor Red
        Write-Host "  请手动: cd frontend && npm install" -ForegroundColor Yellow
        Wait-Exit
    }
} else {
    Write-Host "  OK — node_modules 已存在" -ForegroundColor DarkGray
}

# ═══════════════════════════════════
# 启动后端
# ═══════════════════════════════════
Write-Host "[3/4] 启动后端..." -ForegroundColor Gray

$backendProc = Start-Process `
    -FilePath $Python `
    -ArgumentList "main.py serve --port $BackendPort" `
    -WorkingDirectory $PSScriptRoot `
    -PassThru

# 等待后端就绪
Write-Host "  等待后端 (port $BackendPort) ..." -ForegroundColor DarkGray -NoNewline

$backendReady = $false
1..40 | ForEach-Object {
    if (-not $backendReady) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/api/providers" -TimeoutSec 1 -UseBasicParsing
            if ($resp.StatusCode -eq 200) { $backendReady = $true }
        } catch {}
        if (-not $backendReady) { Start-Sleep -Milliseconds 500; Write-Host "." -NoNewline -ForegroundColor DarkGray }
    }
}
Write-Host ""

if (-not $backendReady) {
    Write-Host "  [WARN] 后端响应超时，继续..." -ForegroundColor Yellow
} else {
    Write-Host "  后端已就绪" -ForegroundColor Green
}

# ═══════════════════════════════════
# 启动前端
# ═══════════════════════════════════
Write-Host "[4/4] 启动前端..." -ForegroundColor Gray

# vite.cmd 是独立的批处理脚本，直接执行（不传给 node）
$viteCmd = "$frontendDir\node_modules\.bin\vite.cmd"
if (-not (Test-Path $viteCmd)) {
    Write-Host "  [ERROR] vite.cmd 未找到: $viteCmd" -ForegroundColor Red
    Write-Host "  请手动: cd frontend && npm install && npm run dev" -ForegroundColor Yellow
    Wait-Exit
}

$frontendProc = Start-Process `
    -FilePath "$frontendDir\node_modules\.bin\vite.cmd" `
    -ArgumentList "--port $FrontendPort" `
    -WorkingDirectory $frontendDir `
    -PassThru

Write-Host "  等待前端 (port $FrontendPort) ..." -ForegroundColor DarkGray -NoNewline
$frontendReady = $false
1..30 | ForEach-Object {
    if (-not $frontendReady) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$FrontendPort" -TimeoutSec 1 -UseBasicParsing
            if ($resp.StatusCode -eq 200) { $frontendReady = $true }
        } catch {}
        if (-not $frontendReady) { Start-Sleep -Milliseconds 500; Write-Host "." -NoNewline -ForegroundColor DarkGray }
    }
}
Write-Host ""

if (-not $frontendReady) {
    Write-Host "  [WARN] 前端未能在 15s 内就绪，可能端口被占或启动失败" -ForegroundColor Yellow
} else {
    Write-Host "  前端已就绪" -ForegroundColor Green
}

# ═══════════════════════════════════
# 完成
# ═══════════════════════════════════
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  🎬 AutoCut Agent 已启动!" -ForegroundColor White
Write-Host ""
Write-Host "  前端页面 : http://localhost:$FrontendPort" -ForegroundColor Cyan
Write-Host "  API 文档 : http://localhost:$BackendPort/docs"   -ForegroundColor Cyan
Write-Host ""
Write-Host "  后端/前端分别在 2 个独立最小化窗口中运行" -ForegroundColor Gray
Write-Host "============================================" -ForegroundColor Green
Write-Host ""

# 打开浏览器
Start-Process "http://localhost:$FrontendPort"

# 等待 Ctrl+C → 杀掉子进程
Write-Host "按 Ctrl+C 停止所有服务..." -ForegroundColor Yellow
try {
    while ($true) { Start-Sleep -Seconds 1 }
} finally {
    Write-Host ""
    Write-Host "正在关闭..." -ForegroundColor Yellow
    if ($frontendProc -and -not $frontendProc.HasExited) {
        Stop-Process -Id $frontendProc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($backendProc -and -not $backendProc.HasExited) {
        Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "已停止" -ForegroundColor Gray
}

Read-Host "Press Enter to exit"

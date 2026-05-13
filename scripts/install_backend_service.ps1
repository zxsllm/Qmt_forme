# 把 AI Trade 后端注册为 Windows 服务 (NSSM)
# 用法: 普通 PowerShell 里跑 .\scripts\install_backend_service.ps1
#       脚本会自动请求 UAC 提升

param(
    [string]$ServiceName = "QmtBackend",
    [int]$Port = 8000,
    [string]$ProjectRoot = "E:\Project\Qmt_forme"
)

$ErrorActionPreference = 'Stop'

# ---------- 自我提权 ----------
$current = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $current.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "需要管理员权限,正在请求提升..." -ForegroundColor Yellow
    $args = @('-NoExit', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"",
              '-ServiceName', $ServiceName, '-Port', $Port, '-ProjectRoot', "`"$ProjectRoot`"")
    Start-Process powershell -Verb RunAs -ArgumentList $args
    exit
}

function Invoke-Nssm {
    param([Parameter(ValueFromRemainingArguments=$true)] $NssmArgs)
    $output = & nssm @NssmArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "nssm $($NssmArgs -join ' ') 失败 (exit=$LASTEXITCODE):`n$output"
    }
    return $output
}

# ---------- 路径检查 ----------
$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$backendDir = Join-Path $ProjectRoot "backend"
$logsDir    = Join-Path $backendDir "logs"
$stdoutLog  = Join-Path $logsDir "uvicorn.stdout.log"
$stderrLog  = Join-Path $logsDir "uvicorn.stderr.log"

if (-not (Test-Path $venvPython)) { throw "找不到 venv python: $venvPython" }
if (-not (Test-Path $backendDir)) { throw "找不到 backend 目录: $backendDir" }
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

# ---------- 读用户级 TUSHARE_TOKEN ----------
$tushareToken = [Environment]::GetEnvironmentVariable('TUSHARE_TOKEN','User')
if (-not $tushareToken) {
    throw "用户级环境变量 TUSHARE_TOKEN 未设置,无法注入到服务"
}
Write-Host "TUSHARE_TOKEN 已读取 (前8位: $($tushareToken.Substring(0,8))...)" -ForegroundColor Green

# ---------- 安装 NSSM ----------
$nssm = Get-Command nssm -ErrorAction SilentlyContinue
if (-not $nssm) {
    Write-Host "正在通过 winget 安装 NSSM..." -ForegroundColor Cyan
    winget install --id NSSM.NSSM --silent --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget 安装 NSSM 失败 (exit=$LASTEXITCODE)" }
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ";" + [Environment]::GetEnvironmentVariable('Path','User')
    $nssm = Get-Command nssm -ErrorAction SilentlyContinue
    if (-not $nssm) { throw "winget 装完后仍找不到 nssm,请重开 PowerShell 后再试" }
}
Write-Host "NSSM 路径: $($nssm.Source)" -ForegroundColor Green

# ---------- 停掉 8000 端口的临时进程 ----------
$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    foreach ($conn in $existing) {
        Write-Host "停止占用 $Port 端口的旧进程 PID=$($conn.OwningProcess)" -ForegroundColor Yellow
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

# ---------- 移除同名旧服务 ----------
$svc = Get-Service $ServiceName -ErrorAction SilentlyContinue
if ($svc) {
    Write-Host "服务 $ServiceName 已存在,先移除..." -ForegroundColor Yellow
    & nssm stop $ServiceName confirm 2>&1 | Out-Null
    & nssm remove $ServiceName confirm 2>&1 | Out-Null
    Start-Sleep -Seconds 2
}

# ---------- 注册服务 ----------
Write-Host "注册服务 $ServiceName..." -ForegroundColor Cyan
Invoke-Nssm install $ServiceName $venvPython | Out-Null
Invoke-Nssm set $ServiceName AppParameters "-m uvicorn app.main:app --host 127.0.0.1 --port $Port" | Out-Null
Invoke-Nssm set $ServiceName AppDirectory $backendDir | Out-Null
Invoke-Nssm set $ServiceName DisplayName "Qmt_forme Backend (FastAPI)" | Out-Null
Invoke-Nssm set $ServiceName Description "AI Trade 后端服务 (uvicorn + scheduler)" | Out-Null
Invoke-Nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null

# 环境变量注入 (TUSHARE_TOKEN + UTF-8 + 实时输出)
Invoke-Nssm set $ServiceName AppEnvironmentExtra "TUSHARE_TOKEN=$tushareToken" "PYTHONIOENCODING=utf-8" "PYTHONUNBUFFERED=1" | Out-Null

# 日志重定向 + 在线轮转 (10 MB 一切)
Invoke-Nssm set $ServiceName AppStdout $stdoutLog | Out-Null
Invoke-Nssm set $ServiceName AppStderr $stderrLog | Out-Null
Invoke-Nssm set $ServiceName AppRotateFiles 1 | Out-Null
Invoke-Nssm set $ServiceName AppRotateOnline 1 | Out-Null
Invoke-Nssm set $ServiceName AppRotateBytes 10485760 | Out-Null
Invoke-Nssm set $ServiceName AppRotateSeconds 0 | Out-Null

# 异常退出 3 秒后自动拉起
Invoke-Nssm set $ServiceName AppExit Default Restart | Out-Null
Invoke-Nssm set $ServiceName AppRestartDelay 3000 | Out-Null

# ---------- 启动 ----------
Write-Host "启动服务..." -ForegroundColor Cyan
Invoke-Nssm start $ServiceName | Out-Null
Start-Sleep -Seconds 6

# ---------- 验证 ----------
$svc = Get-Service $ServiceName
Write-Host ""
Write-Host "=== 验证 ===" -ForegroundColor Cyan
Write-Host "服务状态 : $($svc.Status) (启动模式: $($svc.StartType))" -ForegroundColor Green

$listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listen) {
    Write-Host "端口 $Port  : 监听中 (PID=$($listen[0].OwningProcess))" -ForegroundColor Green
} else {
    Write-Host "端口 $Port  : 未监听 - 请查看 $stderrLog" -ForegroundColor Red
}

try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/feed/status" -TimeoutSec 5
    Write-Host "API 探活  : scheduler.running=$($resp.running), is_trade_date=$($resp.is_trade_date)" -ForegroundColor Green
} catch {
    Write-Host "API 探活  : 失败 ($($_.Exception.Message))" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== 完成 ===" -ForegroundColor Cyan
Write-Host "日志文件 : $stdoutLog"
Write-Host "          $stderrLog (10MB 自动轮转)"
Write-Host ""
Write-Host "常用管理命令:"
Write-Host "  Restart-Service $ServiceName        # 重启"
Write-Host "  Stop-Service $ServiceName           # 停止"
Write-Host "  nssm edit $ServiceName              # 图形化改配置"
Write-Host "  nssm remove $ServiceName confirm    # 卸载"

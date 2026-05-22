param(
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"

# Solve Chinese garbled characters by setting console to UTF-8
$OutputEncoding = [Console]::OutputEncoding = [Console]::InputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AiServiceRoot = Join-Path $ProjectRoot "ai-service"
$LogRoot = Join-Path $ProjectRoot "logs"
$PythonCommand = if ($env:INTERNPATH_PYTHON) {
    $env:INTERNPATH_PYTHON
} elseif (Test-Path (Join-Path $ProjectRoot ".venv\Scripts\python.exe")) {
    Join-Path $ProjectRoot ".venv\Scripts\python.exe"
} else {
    "python"
}
$AiPort = if ($env:INTERNPATH_AI_PORT) { [int]$env:INTERNPATH_AI_PORT } else { 8000 }
$BackendPort = if ($env:INTERNPATH_BACKEND_PORT) { [int]$env:INTERNPATH_BACKEND_PORT } else { 8787 }
$WebPort = if ($env:INTERNPATH_WEB_PORT) { [int]$env:INTERNPATH_WEB_PORT } elseif ($env:LOCAL_PORT) { [int]$env:LOCAL_PORT } else { 5173 }

function Get-PythonInvocation {
    if ($PythonCommand -match "[\\/]") {
        return '"' + $PythonCommand.Replace('"', '""') + '"'
    }
    return $PythonCommand
}

function Get-ListeningProcessIds {
    param([int]$Port)

    try {
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    } catch {
        @()
    }
}

function Test-PortBusy {
    param([int]$Port)

    $ids = @(Get-ListeningProcessIds -Port $Port)
    return $ids.Count -gt 0
}

function Stop-PortProcess {
    param(
        [int]$Port,
        [string]$Name
    )

    $ids = @(Get-ListeningProcessIds -Port $Port)
    if ($ids.Count -eq 0) {
        Write-Host "$Name is not running on port $Port."
        return
    }

    foreach ($processId in $ids) {
        try {
            $process = Get-Process -Id $processId -ErrorAction Stop
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host "Stopped $Name process $processId ($($process.ProcessName)) on port $Port."
        } catch {
            Write-Warning "Failed to stop $Name process $processId on port ${Port}: $($_.Exception.Message)"
        }
    }
}

function Start-DetachedCommand {
    param(
        [string]$Title,
        [string]$WorkingDirectory,
        [string]$Command
    )

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $env:ComSpec
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.Arguments = "/k chcp 65001 >nul && title $Title && $Command"
    $psi.UseShellExecute = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Minimized
    [System.Diagnostics.Process]::Start($psi) | Out-Null
}

function Start-InternPath {
    New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

    $aiLog = Join-Path $LogRoot "ai-service.log"
    $backendLog = Join-Path $LogRoot "backend.log"
    $webLog = Join-Path $LogRoot "frontend.log"
    $pythonInvocation = Get-PythonInvocation

    if (Test-PortBusy -Port $AiPort) {
        Write-Host "AI service already appears to be running on http://127.0.0.1:$AiPort."
    } else {
        $aiCommand = "$pythonInvocation -m uvicorn app.main:app --host 127.0.0.1 --port $AiPort >> `"$aiLog`" 2>>&1"
        Start-DetachedCommand -Title "InternPath AI Service" -WorkingDirectory $AiServiceRoot -Command $aiCommand
        Write-Host "Started AI service window on http://127.0.0.1:$AiPort."
    }

    if (Test-PortBusy -Port $BackendPort) {
        Write-Host "Backend API already appears to be running on http://127.0.0.1:$BackendPort."
    } else {
        $backendCommand = "$pythonInvocation -m uvicorn backend.main:app --host 127.0.0.1 --port $BackendPort >> `"$backendLog`" 2>>&1"
        Start-DetachedCommand -Title "InternPath Backend API" -WorkingDirectory $ProjectRoot -Command $backendCommand
        Write-Host "Started backend API window on http://127.0.0.1:$BackendPort."
    }

    $FrontendRoot = Join-Path $ProjectRoot "frontend"
    $NodeModules = Join-Path $FrontendRoot "node_modules"
    if (-not (Test-Path $NodeModules)) {
        Write-Warning "frontend\node_modules not found. Run 'npm install' inside frontend before starting the React UI."
    } elseif (Test-PortBusy -Port $WebPort) {
        Write-Host "React workbench already appears to be running on http://127.0.0.1:$WebPort."
    } else {
        $webCommand = "npm run dev -- --port $WebPort >> `"$webLog`" 2>>&1"
        Start-DetachedCommand -Title "InternPath React Workbench" -WorkingDirectory $FrontendRoot -Command $webCommand
        Write-Host "Started React workbench window on http://127.0.0.1:$WebPort."
    }

    Write-Host "Open http://127.0.0.1:$WebPort in your browser."
    Write-Host "Logs: $LogRoot"
}

function Stop-InternPath {
    Stop-PortProcess -Port $WebPort -Name "Web app"
    Stop-PortProcess -Port $BackendPort -Name "Backend API"
    Stop-PortProcess -Port $AiPort -Name "AI service"
}

function Show-InternPathStatus {
    if (Test-PortBusy -Port $AiPort) {
        Write-Host "AI service: running on http://127.0.0.1:$AiPort"
    } else {
        Write-Host "AI service: stopped on port $AiPort"
    }

    if (Test-PortBusy -Port $WebPort) {
        Write-Host "Web app: running on http://127.0.0.1:$WebPort"
    } else {
        Write-Host "Web app: stopped on port $WebPort"
    }

    if (Test-PortBusy -Port $BackendPort) {
        Write-Host "Backend API: running on http://127.0.0.1:$BackendPort"
    } else {
        Write-Host "Backend API: stopped on port $BackendPort"
    }
}

switch ($Action) {
    "start" { Start-InternPath }
    "stop" { Stop-InternPath }
    "restart" {
        Stop-InternPath
        Start-Sleep -Seconds 1
        Start-InternPath
    }
    "status" { Show-InternPathStatus }
}

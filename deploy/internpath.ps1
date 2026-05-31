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

# PostgreSQL configuration and fallback to workspace scratch path
$PgBin = if ($env:INTERNPATH_PG_BIN) {
    $env:INTERNPATH_PG_BIN
} else {
    Join-Path $ProjectRoot "scratch\pgsql\bin"
}
$PgData = if ($env:INTERNPATH_PG_DATA) {
    $env:INTERNPATH_PG_DATA
} else {
    Join-Path $ProjectRoot "scratch\pgdata"
}
$PgLog = if ($env:INTERNPATH_PG_LOG) {
    $env:INTERNPATH_PG_LOG
} else {
    Join-Path $ProjectRoot "scratch\pg_log.txt"
}
$PgPort = if ($env:INTERNPATH_PG_PORT) { [int]$env:INTERNPATH_PG_PORT } else { 54321 }

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

    # 1. Handle PostgreSQL Startup
    $pgCtlExe = Join-Path $PgBin "pg_ctl.exe"
    $isPgConfigured = $false
    if (Test-Path $pgCtlExe) {
        $isPgConfigured = $true
        
        # Check and automatically install pgvector if missing
        $PgsqlLib = Join-Path $ProjectRoot "scratch\pgsql\lib"
        $VectorDll = Join-Path $PgsqlLib "vector.dll"
        if (-not (Test-Path $VectorDll)) {
            Write-Host "Local pgvector extension is missing. Automatically installing pgvector..." -ForegroundColor Yellow
            $InstallerScript = Join-Path $ProjectRoot "deploy\install_pgvector_windows.ps1"
            if (Test-Path $InstallerScript) {
                try {
                    & powershell -NoProfile -ExecutionPolicy Bypass -File $InstallerScript
                } catch {
                    Write-Warning "Failed to install pgvector automatically: $_"
                }
            } else {
                Write-Warning "pgvector installer script not found at: $InstallerScript"
            }
        }

        if (Test-PortBusy -Port $PgPort) {
            Write-Host "PostgreSQL already appears to be running on port $PgPort."
        } else {
            Write-Host "Starting local PostgreSQL on port $PgPort..."
            try {
                # Start PostgreSQL
                & $pgCtlExe -D $PgData -l $PgLog -o "-p $PgPort" start
                Start-Sleep -Seconds 3
                Write-Host "PostgreSQL started successfully."
            } catch {
                Write-Warning "Failed to start PostgreSQL: $_"
            }
        }

        # 2. Check and Create Database
        $psqlExe = Join-Path $PgBin "psql.exe"
        $createdbExe = Join-Path $PgBin "createdb.exe"
        $dbExists = $false
        try {
            $dbList = & $psqlExe -U postgres -p $PgPort -lqt
            if ($dbList -match "job_dashboard") {
                $dbExists = $true
            }
        } catch {
            # Ignore list failure
        }

        if (-not $dbExists) {
            Write-Host "Creating PostgreSQL database 'job_dashboard'..."
            try {
                & $createdbExe -U postgres -p $PgPort job_dashboard
                Write-Host "Database 'job_dashboard' created successfully."
            } catch {
                Write-Warning "Failed to create database 'job_dashboard': $_"
            }
        }

        # 3. Export DATABASE_URL env variable for child processes to inherit
        $env:DATABASE_URL = "postgresql://postgres@localhost:$PgPort/job_dashboard"
        Write-Host "DATABASE_URL set to postgresql://postgres@localhost:$PgPort/job_dashboard"
    } else {
        Write-Warning "PostgreSQL binaries not found at: $pgCtlExe"
        Write-Warning "Skipping local PostgreSQL startup. The application will fall back to SQLite."
    }

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

    # Stop PostgreSQL
    $pgCtlExe = Join-Path $PgBin "pg_ctl.exe"
    if (Test-Path $pgCtlExe) {
        if (Test-PortBusy -Port $PgPort) {
            Write-Host "Stopping local PostgreSQL on port $PgPort..."
            try {
                & $pgCtlExe -D $PgData stop
                Write-Host "PostgreSQL stopped successfully."
            } catch {
                Write-Warning "Failed to stop PostgreSQL: $_"
            }
        } else {
            Write-Host "PostgreSQL is not running on port $PgPort."
        }
    }
}

function Show-InternPathStatus {
    $pgCtlExe = Join-Path $PgBin "pg_ctl.exe"
    if (Test-Path $pgCtlExe) {
        if (Test-PortBusy -Port $PgPort) {
            Write-Host "PostgreSQL: running on port $PgPort"
        } else {
            Write-Host "PostgreSQL: stopped on port $PgPort"
        }
    } else {
        Write-Host "PostgreSQL: binaries not found (using SQLite fallback)"
    }

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

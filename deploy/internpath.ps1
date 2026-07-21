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

if (-not $env:RQ_QUEUE_NAME) {
    $env:RQ_QUEUE_NAME = "internpath-default"
}

# Load .env file variables if present
$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line -match "=") {
            $key, $value = $line -split "=", 2
            [System.Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim())
        }
    }
}
if (-not $env:RQ_ADVISOR_QUEUE_NAME) {
    $env:RQ_ADVISOR_QUEUE_NAME = "internpath-advisor"
}

# PostgreSQL configuration. Runtime requires PostgreSQL + pgvector; no SQLite runtime mode is supported.
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
        # Get-NetTCPConnection has intermittently blocked for 20+ seconds on this
        # host. netstat is sufficient for the narrow port-to-PID lookup needed by
        # start, stop and status, and keeps service management responsive.
        $pattern = "^\s*TCP\s+.*(?:\]:|:)$Port\s+.*(?:LISTENING|侦听)\s+(\d+)\s*$"
        @(
            & "$env:SystemRoot\System32\netstat.exe" -ano -p tcp 2>$null |
                ForEach-Object {
                    if ($_ -match $pattern) { [int]$Matches[1] }
                } |
                Select-Object -Unique
        )
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
    return [System.Diagnostics.Process]::Start($psi)
}

function Test-PidFileProcess {
    param([string]$PidFile)

    if (-not (Test-Path $PidFile)) {
        return $false
    }
    try {
        $processId = [int](Get-Content $PidFile -ErrorAction Stop | Select-Object -First 1)
        Get-Process -Id $processId -ErrorAction Stop | Out-Null
        return $true
    } catch {
        Remove-Item -Force -ErrorAction SilentlyContinue $PidFile
        return $false
    }
}

function Stop-PidFileProcess {
    param(
        [string]$PidFile,
        [string]$Name
    )

    if (-not (Test-Path $PidFile)) {
        Write-Host "$Name is not running."
        return
    }
    try {
        $processId = [int](Get-Content $PidFile -ErrorAction Stop | Select-Object -First 1)
        Stop-ProcessTree -ProcessId $processId
        Remove-Item -Force -ErrorAction SilentlyContinue $PidFile
        Write-Host "Stopped $Name process $processId."
    } catch {
        Remove-Item -Force -ErrorAction SilentlyContinue $PidFile
        Write-Warning "Failed to stop $Name from PID file: $($_.Exception.Message)"
    }
}

function Stop-ProcessTree {
    param(
        [int]$ProcessId
    )

    # Recursive WMI enumeration and taskkill /T can both hang on this Windows host.
    # PID files only track the direct Python service processes, so terminate that
    # process promptly and let the port-specific cleanup handle any listener left
    # behind. This keeps restart bounded instead of stalling before startup.
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Start-BackgroundPythonModule {
    param(
        [string]$Module,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$LogFile,
        [string]$ErrorLogFile
    )

    $argumentList = @("-m", $Module) + $Arguments
    return Start-Process `
        -FilePath $PythonCommand `
        -ArgumentList $argumentList `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $ErrorLogFile `
        -WindowStyle Hidden `
        -PassThru
}

function Assert-PostgresDatabaseUrl {
    if (-not $env:DATABASE_URL) {
        throw "DATABASE_URL is required. InternPath runs on PostgreSQL + pgvector only."
    }
    if ($env:DATABASE_URL -notmatch "^postgres(ql)?://") {
        throw "DATABASE_URL must be a PostgreSQL connection string."
    }
}

function Test-TcpEndpoint {
    param(
        [string]$HostName,
        [int]$Port
    )

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(2000, $false)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Assert-RedisEndpoint {
    if (-not $env:REDIS_URL) {
        throw "REDIS_URL is required for Redis/RQ background jobs."
    }
    try {
        $redisUri = [System.Uri]$env:REDIS_URL
        $redisPort = if ($redisUri.Port -gt 0) { $redisUri.Port } else { 6379 }
        $redisHost = $redisUri.DnsSafeHost
        if (-not (Test-TcpEndpoint -HostName $redisHost -Port $redisPort)) {
            throw "Redis endpoint is not reachable at ${redisHost}:${redisPort}."
        }
        Write-Host "Redis is reachable at ${redisHost}:${redisPort}." -ForegroundColor Green
    } catch {
        throw "REDIS_URL is invalid or unreachable: $($_.Exception.Message)"
    }
}

function Start-InternPath {
    New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

    $aiLog = Join-Path $LogRoot "ai-service.log"
    $backendLog = Join-Path $LogRoot "backend.log"
    $workerLog = Join-Path $LogRoot "rq-worker.log"
    $workerErrorLog = Join-Path $LogRoot "rq-worker.error.log"
    $workerPidFile = Join-Path $LogRoot "rq-worker.pid"
    $advisorWorkerLog = Join-Path $LogRoot "rq-advisor-worker.log"
    $advisorWorkerErrorLog = Join-Path $LogRoot "rq-advisor-worker.error.log"
    $advisorWorkerPidFile = Join-Path $LogRoot "rq-advisor-worker.pid"
    $webLog = Join-Path $LogRoot "frontend.log"
    $pythonInvocation = Get-PythonInvocation

    # 1. Handle PostgreSQL Startup
    $pgCtlExe = Join-Path $PgBin "pg_ctl.exe"
    if ($env:DATABASE_URL) {
        Assert-PostgresDatabaseUrl
        Write-Host "PostgreSQL is configured via DATABASE_URL: $env:DATABASE_URL" -ForegroundColor Green
    } elseif (Test-Path $pgCtlExe) {
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
            $conn = Get-NetTCPConnection -LocalPort $PgPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($conn) {
                $pid = $conn.OwningProcess
                $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
                $procPath = if ($proc) { $proc.Path } else { "" }
                $procName = if ($proc) { $proc.Name } else { "Unknown" }
                if ($procPath -and $procPath.ToLower().Contains("scratch\pgsql")) {
                    Write-Host "PostgreSQL is already running on port $PgPort (PID: $pid, Project Instance)." -ForegroundColor Green
                } else {
                    throw "Port $PgPort is occupied by an external process (PID: $pid, Name: $procName, Path: $procPath). Set DATABASE_URL explicitly or release the port."
                }
            } else {
                Write-Host "PostgreSQL already appears to be running on port $PgPort."
            }
        } else {
            Write-Host "Starting local PostgreSQL on port $PgPort..."
            try {
                # 浣跨敤鐩稿璺緞鑴辩涓枃缁濆璺緞缂栫爜瑙ｆ瀽骞叉壈锛屽湪鐙珛绐楀彛涓洿鎺ユ媺璧峰苟淇濇椿杩愯 postgres.exe
                $pgCommand = "scratch\pgsql\bin\postgres.exe -D scratch\pgdata -p $PgPort >> scratch\pg_log.txt 2>>&1"
                $null = Start-DetachedCommand -Title "PostgreSQL-54321" -WorkingDirectory $ProjectRoot -Command $pgCommand
                Start-Sleep -Seconds 4

                # 鍙岄噸鍋ュ悍搴︽牎楠岋細妫€鏌ョ鍙ｆ槸鍚︾湡鐨勫凡缁忚 PostgreSQL 鐩戝惉
                if (Test-PortBusy -Port $PgPort) {
                    Write-Host "PostgreSQL started successfully and is listening on port $PgPort." -ForegroundColor Green
                } else {
                    Write-Warning "PostgreSQL failed to start. Port $PgPort is not active."
                    # 璇诲彇骞惰緭鍑烘棩蹇椾腑鏈€鍚?10 琛屼互鎻愮ず鐢ㄦ埛鍏蜂綋閿欒
                    if (Test-Path $PgLog) {
                        Write-Host "--- Recent PostgreSQL Logs ($PgLog) ---" -ForegroundColor Red
                        Get-Content $PgLog -Tail 10 | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
                    }
                    throw "PostgreSQL failed to start. InternPath cannot run without PostgreSQL + pgvector."
                }
            } catch {
                throw "Failed to start PostgreSQL: $_"
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
                throw "Failed to create database 'job_dashboard': $_"
            }
        }

        # 3. Export DATABASE_URL env variable for child processes to inherit
        $env:DATABASE_URL = "postgresql://postgres@localhost:$PgPort/job_dashboard"
        Write-Host "DATABASE_URL set to $env:DATABASE_URL"
    } else {
        throw "DATABASE_URL is required and local PostgreSQL binaries were not found at: $pgCtlExe"
    }

    Assert-PostgresDatabaseUrl
    Assert-RedisEndpoint

    if (Test-PortBusy -Port $AiPort) {
        Write-Host "AI service already appears to be running on http://127.0.0.1:$AiPort."
    } else {
        $aiCommand = "$pythonInvocation -m uvicorn app.main:app --host 127.0.0.1 --port $AiPort >> `"$aiLog`" 2>>&1"
        $null = Start-DetachedCommand -Title "InternPath AI Service" -WorkingDirectory $AiServiceRoot -Command $aiCommand
        Write-Host "Started AI service window on http://127.0.0.1:$AiPort."
    }

    if (Test-PidFileProcess -PidFile $workerPidFile) {
        $workerPid = Get-Content $workerPidFile | Select-Object -First 1
        Write-Host "RQ worker already appears to be running (PID: $workerPid, queue: $env:RQ_QUEUE_NAME)."
    } else {
        $workerProcess = Start-BackgroundPythonModule `
            -Module "backend.rq_worker" `
            -Arguments @("--queues", $env:RQ_QUEUE_NAME) `
            -WorkingDirectory $ProjectRoot `
            -LogFile $workerLog `
            -ErrorLogFile $workerErrorLog
        Set-Content -Path $workerPidFile -Value $workerProcess.Id
        Write-Host "Started RQ worker for queue '$($env:RQ_QUEUE_NAME)' (PID: $($workerProcess.Id))."
    }

    if (Test-PidFileProcess -PidFile $advisorWorkerPidFile) {
        $advisorWorkerPid = Get-Content $advisorWorkerPidFile | Select-Object -First 1
        Write-Host "Advisor RQ worker already appears to be running (PID: $advisorWorkerPid, queue: $env:RQ_ADVISOR_QUEUE_NAME)."
    } else {
        $advisorWorkerProcess = Start-BackgroundPythonModule `
            -Module "backend.advisor_autoscaler" `
            -Arguments @("--queue", $env:RQ_ADVISOR_QUEUE_NAME) `
            -WorkingDirectory $ProjectRoot `
            -LogFile $advisorWorkerLog `
            -ErrorLogFile $advisorWorkerErrorLog
        Set-Content -Path $advisorWorkerPidFile -Value $advisorWorkerProcess.Id
        Write-Host "Started elastic Advisor worker supervisor for queue '$($env:RQ_ADVISOR_QUEUE_NAME)' (PID: $($advisorWorkerProcess.Id))."
    }

    if (Test-PortBusy -Port $BackendPort) {
        Write-Host "Backend API already appears to be running on http://127.0.0.1:$BackendPort."
    } else {
        $backendCommand = "$pythonInvocation -m uvicorn backend.main:app --host 127.0.0.1 --port $BackendPort >> `"$backendLog`" 2>>&1"
        $null = Start-DetachedCommand -Title "InternPath Backend API" -WorkingDirectory $ProjectRoot -Command $backendCommand
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
        $null = Start-DetachedCommand -Title "InternPath React Workbench" -WorkingDirectory $FrontendRoot -Command $webCommand
        Write-Host "Started React workbench window on http://127.0.0.1:$WebPort."
    }

    Write-Host "Open http://127.0.0.1:$WebPort in your browser."
    Write-Host "Logs: $LogRoot"
}

function Stop-InternPath {
    $workerPidFile = Join-Path $LogRoot "rq-worker.pid"
    $advisorWorkerPidFile = Join-Path $LogRoot "rq-advisor-worker.pid"
    Stop-PidFileProcess -PidFile $advisorWorkerPidFile -Name "Advisor RQ worker"
    Stop-PidFileProcess -PidFile $workerPidFile -Name "RQ worker"
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
    if ($env:DATABASE_URL) {
        Write-Host "PostgreSQL: configured via DATABASE_URL"
    } elseif (Test-Path $pgCtlExe) {
        if (Test-PortBusy -Port $PgPort) {
            Write-Host "PostgreSQL: running on port $PgPort"
        } else {
            Write-Host "PostgreSQL: stopped on port $PgPort"
        }
    } else {
        Write-Host "PostgreSQL: not configured. DATABASE_URL is required."
    }

    if ($env:REDIS_URL) {
        try {
            $redisUri = [System.Uri]$env:REDIS_URL
            $redisPort = if ($redisUri.Port -gt 0) { $redisUri.Port } else { 6379 }
            $redisHost = $redisUri.DnsSafeHost
            if (Test-TcpEndpoint -HostName $redisHost -Port $redisPort) {
                Write-Host "Redis: reachable at ${redisHost}:${redisPort}"
            } else {
                Write-Host "Redis: configured but unreachable at ${redisHost}:${redisPort}"
            }
        } catch {
            Write-Host "Redis: invalid REDIS_URL"
        }
    } else {
        Write-Host "Redis: not configured. REDIS_URL is required."
    }

    $workerPidFile = Join-Path $LogRoot "rq-worker.pid"
    if (Test-PidFileProcess -PidFile $workerPidFile) {
        $workerPid = Get-Content $workerPidFile | Select-Object -First 1
        Write-Host "RQ worker: running (PID: $workerPid)"
    } else {
        Write-Host "RQ worker: stopped"
    }

    $advisorWorkerPidFile = Join-Path $LogRoot "rq-advisor-worker.pid"
    if (Test-PidFileProcess -PidFile $advisorWorkerPidFile) {
        $advisorWorkerPid = Get-Content $advisorWorkerPidFile | Select-Object -First 1
        Write-Host "Advisor RQ worker: running (PID: $advisorWorkerPid)"
    } else {
        Write-Host "Advisor RQ worker: stopped"
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

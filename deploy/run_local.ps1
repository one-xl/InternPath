$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\\python.exe"
$StreamlitExe = Join-Path $VenvPath "Scripts\\streamlit.exe"
$Port = if ($env:LOCAL_PORT) { $env:LOCAL_PORT } else { "8501" }

if (-not (Test-Path $VenvPath)) {
    python -m venv $VenvPath
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r (Join-Path $ProjectRoot "requirements.local.txt")
& $StreamlitExe run (Join-Path $ProjectRoot "app.py") --server.address 127.0.0.1 --server.port $Port --browser.gatherUsageStats false

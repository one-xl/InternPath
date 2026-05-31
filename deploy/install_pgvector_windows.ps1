# Install pgvector Extension for PostgreSQL 15 on Windows (Local Workbench)
$ErrorActionPreference = "Stop"

# Set encoding to UTF-8
$OutputEncoding = [Console]::OutputEncoding = [Console]::InputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PgsqlHome = Join-Path $ProjectRoot "scratch\pgsql"
$PgsqlLib = Join-Path $PgsqlHome "lib"
$PgsqlExtension = Join-Path $PgsqlHome "share\extension"

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "   InternPath: Local Windows pgvector Installer" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

if (-not (Test-Path $PgsqlHome)) {
    Write-Error "Could not find local PostgreSQL installation at $PgsqlHome. Please verify your workspace folder structure."
}

# 1. Download precompiled pgvector zip for PG15 on Windows
$Tag = "0.8.2_15.14"
$ZipName = "vector.v0.8.2-pg15.zip"
$Url = "https://github.com/andreiramani/pgvector_pgsql_windows/releases/download/$Tag/$ZipName"
$TempDir = Join-Path $env:TEMP "internpath-pgvector-tmp"
$ZipPath = Join-Path $TempDir $ZipName

Write-Host "Creating temporary directory: $TempDir" -ForegroundColor Gray
if (Test-Path $TempDir) {
    Remove-Item -Recurse -Force $TempDir
}
New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

Write-Host "Downloading precompiled pgvector binary from: $Url" -ForegroundColor Yellow
try {
    # Set SecurityProtocol to TLS1.2 to avoid download failures
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile $ZipPath -UseBasicParsing
    Write-Host "Download completed successfully." -ForegroundColor Green
} catch {
    Write-Error "Failed to download pgvector from GitHub. Please check your internet connection or URL: $_"
}

# 2. Extract ZIP Archive
Write-Host "Extracting zip archive..." -ForegroundColor Yellow
$ExtractDir = Join-Path $TempDir "extracted"
Expand-Archive -Path $ZipPath -DestinationPath $ExtractDir -Force

# 3. Find and copy files to local PostgreSQL directory
Write-Host "Locating compiled extension files..." -ForegroundColor Gray
$DllFiles = Get-ChildItem -Path $ExtractDir -Filter "vector.dll" -Recurse
$SqlFiles = Get-ChildItem -Path $ExtractDir -Filter "vector*.sql" -Recurse
$ControlFiles = Get-ChildItem -Path $ExtractDir -Filter "vector.control" -Recurse

if ($DllFiles.Count -eq 0 -or $SqlFiles.Count -eq 0 -or $ControlFiles.Count -eq 0) {
    Write-Error "Extracted zip structure is unexpected. Could not locate vector.dll or SQL control files."
}

$DllSource = $DllFiles[0].FullName
Write-Host "Copying vector.dll to $PgsqlLib..." -ForegroundColor Green
Copy-Item -Path $DllSource -Destination $PgsqlLib -Force

foreach ($sql in $SqlFiles) {
    Write-Host "Copying extension SQL file: $($sql.Name) to $PgsqlExtension..." -ForegroundColor Green
    Copy-Item -Path $sql.FullName -Destination $PgsqlExtension -Force
}

foreach ($ctrl in $ControlFiles) {
    Write-Host "Copying extension control file: $($ctrl.Name) to $PgsqlExtension..." -ForegroundColor Green
    Copy-Item -Path $ctrl.FullName -Destination $PgsqlExtension -Force
}

# 4. Clean up temp folder
Write-Host "Cleaning up temporary files..." -ForegroundColor Gray
Remove-Item -Recurse -Force $TempDir

Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host "  pgvector Extension installed successfully!" -ForegroundColor Green
Write-Host "  Please run 'restart_internpath.cmd' to reload." -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green

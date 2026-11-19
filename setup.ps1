# Prepares a clone for `docker compose up`. Safe to run again. Same behavior as setup.sh.
$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Stop-Setup([string]$Problem, [string]$Action) {
    Write-Host ''
    Write-Host "SETUP STOPPED: $Problem"
    Write-Host "Action: $Action"
    exit 1
}

function Get-EnvValue([string]$Name) {
    # Reads NAME from .env without executing the file.
    if (-not (Test-Path .env)) { return '' }
    $line = Get-Content .env | Where-Object { $_ -match "^$Name=" } | Select-Object -Last 1
    if ($null -eq $line) { return '' }
    return $line.Substring($Name.Length + 1).Trim()
}

function Test-Native([scriptblock]$Command) {
    try { & $Command *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}

# 1. Docker and Docker Compose
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Stop-Setup 'Docker is not installed.' 'Install Docker Desktop: https://docs.docker.com/get-docker/'
}
if (-not (Test-Native { docker compose version })) {
    Stop-Setup 'Docker Compose v2 is not available.' "Install or update Docker so that 'docker compose version' works."
}
if (-not (Test-Native { docker info })) {
    Stop-Setup 'Docker is installed but not running.' 'Start Docker Desktop, then run .\setup.ps1 again.'
}
Write-Host 'OK  Docker and Docker Compose are running.'

# 2. .env
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host ''
    Write-Host 'Created .env from .env.example. Fill in these values:'
    Write-Host '  Required: OPENROUTER_API_KEY, LLM_REWRITE_MODEL, LLM_GRADE_MODEL, LLM_GENERATE_MODEL,'
    Write-Host '            EMBEDDING_MODEL, EMBEDDING_DIMENSIONS'
    Write-Host '  Optional: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST (tracing is off when empty)'
    Stop-Setup 'Values in .env are not filled in yet.' 'Edit .env, then run .\setup.ps1 again.'
}
$required = 'OPENROUTER_API_KEY', 'OPENROUTER_BASE_URL', 'LLM_REWRITE_MODEL', 'LLM_GRADE_MODEL', 'LLM_GENERATE_MODEL',
    'EMBEDDING_MODEL', 'EMBEDDING_DIMENSIONS', 'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB',
    'STORAGE_BACKEND', 'S3_BUCKET', 'S3_REGION', 'S3_ACCESS_KEY', 'S3_SECRET_KEY',
    'FRONTEND_PORT', 'BACKEND_PORT', 'DB_PORT', 'STORAGE_PORT'
$missing = @($required | Where-Object { -not (Get-EnvValue $_) })
if ($missing.Count -gt 0) {
    Stop-Setup "Required values in .env are empty: $($missing -join ' ')" 'Edit .env, then run .\setup.ps1 again.'
}
Write-Host 'OK  .env has all required values.'

# 3. Ports (skipped while this stack runs, because its own containers hold the ports)
# Continue: in PowerShell 5.1, redirected stderr from a native command is an error record.
$running = & { $ErrorActionPreference = 'Continue'; docker compose ps -q 2>$null }
if ($running) {
    Write-Host 'OK  The stack is already running. Port check skipped.'
} else {
    foreach ($var in 'FRONTEND_PORT', 'BACKEND_PORT', 'DB_PORT', 'STORAGE_PORT') {
        $port = [int](Get-EnvValue $var)
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $inUse = $client.ConnectAsync('127.0.0.1', $port).Wait(500)
        } catch { $inUse = $false } finally { $client.Dispose() }
        if ($inUse) {
            Stop-Setup "Port $port is in use." "Stop the program that uses port $port, or set $var to a free port in .env."
        }
    }
    Write-Host 'OK  Ports are free.'
}

# 4. Next step
$frontendPort = Get-EnvValue FRONTEND_PORT
$backendPort = Get-EnvValue BACKEND_PORT
Write-Host ''
Write-Host 'Ready. Run: docker compose up'
Write-Host "  App:      http://localhost:$frontendPort"
Write-Host "  API docs: http://localhost:$backendPort/api/v1/docs"

# Prepares a clone for the stack. Safe to run again. Same behavior as setup.sh.
# It creates backend\.env, infra\.env and frontend\.env from their .env.example files.
$ErrorActionPreference = 'Stop'
Set-Location -Path (Split-Path -Parent $PSScriptRoot)

$compose = 'docker compose -f infra/docker-compose.yml'

function Stop-Setup([string]$Problem, [string]$Action) {
    Write-Host ''
    Write-Host "SETUP STOPPED: $Problem"
    Write-Host "Action: $Action"
    exit 1
}

function Get-EnvValue([string]$File, [string]$Name) {
    # Reads NAME from the file without executing the file.
    if (-not (Test-Path $File)) { return '' }
    $line = Get-Content $File | Where-Object { $_ -match "^$Name=" } | Select-Object -Last 1
    if ($null -eq $line) { return '' }
    return $line.Substring($Name.Length + 1).Trim()
}

function Test-Empty([string]$File, [string[]]$Names) {
    # Stops with the empty names and the file that holds them.
    $missing = @($Names | Where-Object { -not (Get-EnvValue $File $_) })
    if ($missing.Count -gt 0) {
        Stop-Setup "Required values in $File are empty: $($missing -join ' ')" "Edit $File, then run infra\setup.ps1 again."
    }
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
    Stop-Setup 'Docker is installed but not running.' 'Start Docker Desktop, then run infra\setup.ps1 again.'
}
Write-Host 'OK  Docker and Docker Compose are running.'

# 2. The .env files. infra and frontend have working defaults; backend needs the OpenRouter key.
foreach ($project in 'infra', 'frontend', 'backend') {
    if (-not (Test-Path "$project/.env")) {
        Copy-Item "$project/.env.example" "$project/.env"
        Write-Host "OK  Created $project/.env from $project/.env.example."
    }
}
if (-not (Get-EnvValue 'backend/.env' 'OPENROUTER_API_KEY')) {
    Write-Host ''
    Write-Host 'Fill in backend/.env:'
    Write-Host '  Required: OPENROUTER_API_KEY (the models have working defaults)'
    Write-Host '  Optional: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST (tracing is off when empty)'
    Stop-Setup 'OPENROUTER_API_KEY in backend/.env is empty.' 'Edit backend/.env, then run infra\setup.ps1 again.'
}
Test-Empty 'backend/.env' @('OPENROUTER_API_KEY', 'OPENROUTER_BASE_URL', 'LLM_CHAT_MODEL', 'LLM_REWRITE_MODEL',
    'LLM_GRADE_MODEL', 'LLM_GENERATE_MODEL', 'EMBEDDING_MODEL', 'EMBEDDING_DIMENSIONS', 'STORAGE_BACKEND', 'S3_BUCKET', 'S3_REGION')
Test-Empty 'infra/.env' @('POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB', 'S3_ACCESS_KEY', 'S3_SECRET_KEY',
    'FRONTEND_PORT', 'BACKEND_PORT', 'DB_PORT', 'STORAGE_PORT')
Write-Host 'OK  backend/.env and infra/.env have all required values.'

# 3. Ports (skipped while this stack runs, because its own containers hold the ports)
# Continue: in PowerShell 5.1, redirected stderr from a native command is an error record.
$running = & { $ErrorActionPreference = 'Continue'; docker compose -f infra/docker-compose.yml ps -q 2>$null }
if ($running) {
    Write-Host 'OK  The stack is already running. Port check skipped.'
} else {
    foreach ($var in 'FRONTEND_PORT', 'BACKEND_PORT', 'DB_PORT', 'STORAGE_PORT') {
        $port = [int](Get-EnvValue 'infra/.env' $var)
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $inUse = $client.ConnectAsync('127.0.0.1', $port).Wait(500)
        } catch { $inUse = $false } finally { $client.Dispose() }
        if ($inUse) {
            Stop-Setup "Port $port is in use." "Stop the program that uses port $port, or set $var to a free port in infra/.env."
        }
    }
    Write-Host 'OK  Ports are free.'
}

# 4. Next step
Write-Host ''
Write-Host "Ready. From the repository root, run: $compose up"
Write-Host "  App:      http://localhost:$(Get-EnvValue 'infra/.env' 'FRONTEND_PORT')"
Write-Host "  API docs: http://localhost:$(Get-EnvValue 'infra/.env' 'BACKEND_PORT')/api/v1/docs"

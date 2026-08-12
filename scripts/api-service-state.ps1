[CmdletBinding()]
param(
    [ValidateSet("check", "stop-stale")]
    [string]$Mode = "check",
    [string]$HealthUrl = "http://127.0.0.1:8000/health",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$apiSourceRoot = Join-Path $projectRoot "services\api\src"
$schemaPath = Join-Path $apiSourceRoot "viral_dna_api\schema.py"
$pyprojectPath = Join-Path $projectRoot "services\api\pyproject.toml"
$localEnvPath = Join-Path $projectRoot ".env.local"

function Get-ExpectedSchemaVersion {
    if (-not (Test-Path -LiteralPath $schemaPath -PathType Leaf)) {
        throw "Workspace schema source is missing: $schemaPath"
    }
    $schemaSource = Get-Content -LiteralPath $schemaPath -Raw
    $match = [regex]::Match($schemaSource, "(?m)^WORKSPACE_SCHEMA_VERSION\s*=\s*(\d+)\s*$")
    if (-not $match.Success) {
        throw "WORKSPACE_SCHEMA_VERSION was not found in $schemaPath"
    }
    return [int]$match.Groups[1].Value
}

function Get-LatestApiSourceWriteTimeUtc {
    $sourceFiles = @(
        Get-ChildItem -LiteralPath $apiSourceRoot -Recurse -File |
            Where-Object {
                $_.FullName -notmatch "[\\/]__pycache__[\\/]" -and
                $_.Extension -ne ".pyc"
            }
    )
    if (Test-Path -LiteralPath $pyprojectPath -PathType Leaf) {
        $sourceFiles += Get-Item -LiteralPath $pyprojectPath
    }
    if (Test-Path -LiteralPath $localEnvPath -PathType Leaf) {
        $sourceFiles += Get-Item -LiteralPath $localEnvPath
    }
    if ($sourceFiles.Count -eq 0) {
        throw "No API source files were found under $apiSourceRoot"
    }
    return ($sourceFiles | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).LastWriteTimeUtc
}

function Get-ListenerProcessId {
    try {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -First 1
        if ($null -ne $connection) {
            return [int]$connection.OwningProcess
        }
    }
    catch {
        $portPattern = [regex]::Escape(":$Port")
        $line = netstat -ano -p TCP |
            Select-String -Pattern "^\s*TCP\s+\S+$portPattern\s+\S+\s+LISTENING\s+(\d+)\s*$" |
            Select-Object -First 1
        if ($null -ne $line -and $line.Matches.Count -gt 0) {
            return [int]$line.Matches[0].Groups[1].Value
        }
    }
    return $null
}

try {
    $expectedSchemaVersion = Get-ExpectedSchemaVersion
    $latestSourceWriteTimeUtc = Get-LatestApiSourceWriteTimeUtc
}
catch {
    Write-Error $_.Exception.Message
    exit 4
}

try {
    $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
}
catch {
    if ($null -ne (Get-ListenerProcessId)) {
        Write-Output "Port $Port is occupied by a service that does not expose the ViralDNA health contract."
        exit 3
    }
    exit 1
}

if ($health.service -ne "viral-dna-api") {
    Write-Output "Port $Port is occupied by a non-ViralDNA service."
    exit 3
}

$staleReasons = [System.Collections.Generic.List[string]]::new()
if ($null -eq $health.workspace_schema_version) {
    $staleReasons.Add("health response has no workspace schema version")
}
elseif ([int]$health.workspace_schema_version -ne $expectedSchemaVersion) {
    $staleReasons.Add(
        "workspace schema $($health.workspace_schema_version) does not match source schema $expectedSchemaVersion"
    )
}

if ($null -eq $health.process_started_at) {
    $staleReasons.Add("health response has no process start time")
}
else {
    try {
        $processStartedAt = [DateTimeOffset]::Parse([string]$health.process_started_at)
        if ($latestSourceWriteTimeUtc -gt $processStartedAt.UtcDateTime.AddSeconds(2)) {
            $staleReasons.Add("API source or local configuration changed after the process started")
        }
    }
    catch {
        $staleReasons.Add("health response contains an invalid process start time")
    }
}

if ($staleReasons.Count -eq 0) {
    exit 0
}

Write-Output ("Stale ViralDNA API detected: " + ($staleReasons -join "; "))
if ($Mode -eq "check") {
    exit 2
}

$listenerProcessId = Get-ListenerProcessId
if ($null -eq $listenerProcessId) {
    exit 0
}

try {
    $listenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$listenerProcessId"
    $commandLine = [string]$listenerProcess.CommandLine
    if ($commandLine -notmatch "uvicorn" -or $commandLine -notmatch "viral_dna_api\.main:app") {
        Write-Output "Refusing to stop PID $listenerProcessId because it is not the ViralDNA Uvicorn process."
        exit 3
    }
    Stop-Process -Id $listenerProcessId -Force -ErrorAction Stop
}
catch {
    Write-Error "Failed to stop stale ViralDNA API process $listenerProcessId`: $($_.Exception.Message)"
    exit 4
}

$deadline = [DateTime]::UtcNow.AddSeconds(5)
while ([DateTime]::UtcNow -lt $deadline) {
    if ($null -eq (Get-ListenerProcessId)) {
        Write-Output "Stopped stale ViralDNA API process $listenerProcessId."
        exit 0
    }
    Start-Sleep -Milliseconds 100
}

Write-Error "Timed out while waiting for stale ViralDNA API process $listenerProcessId to stop."
exit 4

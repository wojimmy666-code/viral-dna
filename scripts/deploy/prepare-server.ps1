[CmdletBinding()]
param(
    [string]$RepositoryRoot = 'C:\Projects\ViralDNA',
    [string]$RuntimeRoot,
    [string]$ConfigPath,
    [switch]$Preview
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $RepositoryRoot '.server' }
if (-not $ConfigPath) { $ConfigPath = Join-Path $RuntimeRoot 'config\deploy.json' }
Import-Module (Join-Path $PSScriptRoot 'Server.Prepare.psm1') -Force -DisableNameChecking
if ($Preview) {
    # Use a non-secret sample identity; never put the preparation computer's
    # username into a distributable server configuration.
    New-ServerConfig $RepositoryRoot $RuntimeRoot '.\Administrator' | ConvertTo-Json -Depth 8
    return
}
try {
    $null = Initialize-CurrentUserServer $RepositoryRoot $RuntimeRoot $ConfigPath
    Write-Host ''
    Write-Host "Next: update Git using .server\setup\sync-code.ps1, then configure IIS, then build/start."
} catch {
    Write-Error $_
    exit 1
}

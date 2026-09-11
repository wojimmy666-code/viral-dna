[CmdletBinding()]
param([string]$Config = 'C:\Projects\ViralDNA\.server\config\deploy.json', [switch]$InstallComponents)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Deploy.Core.psm1') -DisableNameChecking
Assert-Administrator
$settings = Read-DeployConfig $Config
Assert-AutomaticIis $settings
Write-Warning 'ARR proxy enablement, timeout and streaming buffer settings affect IIS at server scope. Only the ViralDNA site/pool is configured; no other site is stopped.'
if ($InstallComponents) {
    & (Join-Path $PSScriptRoot 'install-prerequisites.ps1') -RepositoryRoot $settings.RepositoryRoot -Iis
}
Initialize-DeployRuntime $settings
$lock = Open-DeployLock $settings
try { Initialize-ManagedIis $settings } finally { $lock.Dispose() }

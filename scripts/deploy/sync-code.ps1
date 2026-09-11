[CmdletBinding()]
param([string]$Config = 'C:\Projects\ViralDNA\.server\config\deploy.json')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Deploy.Core.psm1') -DisableNameChecking
Assert-Administrator
$settings = Read-DeployConfig $Config
if (-not (Get-PrivateRuntimeRoot $settings)) { throw 'This copy-first bootstrap entry requires single-root .server configuration.' }
if (Test-Path -LiteralPath (Join-Path $settings.RepositoryRoot '.git')) { Add-PrivateGitExclude $settings }
Assert-Repository $settings -Clean -AllowMissing
# Check SSH without downtime or a partial checkout.
$null = Invoke-DeployGit $settings @('ls-remote', '--exit-code', 'git@github.com:wojimmy666-code/viral-dna.git', 'refs/heads/main')
Initialize-DeployRuntime $settings
$lock = Open-DeployLock $settings
try {
    Update-DeployRepository $settings
    Write-Host 'main updated over SSH. No build, service restart, Git push or data migration was performed.'
} finally { $lock.Dispose() }

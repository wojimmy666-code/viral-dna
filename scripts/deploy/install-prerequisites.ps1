[CmdletBinding()]
param([string]$RepositoryRoot = 'C:\Projects\ViralDNA', [switch]$Iis)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Deploy.Core.psm1') -DisableNameChecking
Assert-Administrator
$runtime = Join-Path (Get-FullPath $RepositoryRoot) '.server'
Assert-NoReparsePoint $runtime

function Install-SignedPrerequisite([string]$Path, [string]$Publisher, [string[]]$Arguments, [switch]$Msi) {
    Assert-NoReparsePoint $Path
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or
        $signature.SignerCertificate.Subject -notmatch ('CN=' + [regex]::Escape($Publisher) + ',')) {
        throw "Installer signature is invalid or has an unexpected publisher: $Path"
    }
    $executable = $Path
    if ($Msi) { $executable = Join-Path $env:WINDIR 'System32\msiexec.exe'; $Arguments = @('/i', $Path, '/qn', '/norestart') }
    $result = Invoke-DeployProcess $executable $Arguments $runtime -AllowFailure
    if ($result.Code -eq 3010) { throw 'Installation succeeded but Windows requires a restart. Restart the server, then repeat this step.' }
    if ($result.Code -ne 0) { throw "Installer failed (exit $($result.Code)): $Path" }
}

if ($Iis) {
    Write-Warning 'This installs IIS Windows roles and enables ARR prerequisites at SERVER scope. Use a maintenance window if this server hosts other sites. No iisreset is performed.'
    Import-Module ServerManager -ErrorAction Stop
    $features = @('Web-Server', 'Web-Static-Content', 'Web-Default-Doc', 'Web-Http-Errors', 'Web-Http-Logging',
        'Web-Request-Monitor', 'Web-Filtering', 'Web-Mgmt-Console', 'Web-Scripting-Tools')
    $missing = @(Get-WindowsFeature -Name $features | Where-Object Installed -ne $true | ForEach-Object Name)
    if ($missing.Count) {
        $result = Install-WindowsFeature -Name $missing -IncludeManagementTools
        if (-not $result.Success) { throw 'IIS role installation failed; Windows may need its installation media/update source.' }
        if ($result.RestartNeeded.ToString() -eq 'Yes') { throw 'IIS roles installed. Restart Windows and repeat this step.' }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $env:WINDIR 'System32\inetsrv\rewrite.dll'))) {
        Install-SignedPrerequisite (Join-Path $runtime 'tools\installers\rewrite_amd64_en-US.msi') 'Microsoft Corporation' @() -Msi
    }
    if (-not (Test-Path -LiteralPath (Join-Path $env:WINDIR 'System32\inetsrv\requestRouter.dll'))) {
        Install-SignedPrerequisite (Join-Path $runtime 'tools\installers\requestRouter_amd64.msi') 'Microsoft Corporation' @() -Msi
    }
} else {
    $pythonRoot = Join-Path $runtime 'tools\python'
    $python = Join-Path $pythonRoot 'python.exe'
    Assert-NoReparsePoint $python
    if (-not (Test-Path -LiteralPath $python)) {
        if ((Test-Path -LiteralPath $pythonRoot) -and @(Get-ChildItem -LiteralPath $pythonRoot -Force).Count) {
            throw 'Python target is nonempty but incomplete. Inspect it before retrying; nothing was overwritten.'
        }
        # Avoid silently moving/repairing a pre-existing same-version system install.
        foreach ($registry in @('HKLM:\SOFTWARE\Python\PythonCore\3.13\InstallPath', 'HKCU:\SOFTWARE\Python\PythonCore\3.13\InstallPath')) {
            if (Test-Path -LiteralPath $registry) {
                $existing = (Get-Item -LiteralPath $registry).GetValue('')
                if ($existing -and (Get-FullPath $existing) -ne $pythonRoot) {
                    throw 'Python 3.13 already exists elsewhere. Resolve that installation explicitly before installing this project-local Python.'
                }
            }
        }
        Install-SignedPrerequisite (Join-Path $runtime 'tools\installers\python-3.13.15-amd64.exe') 'Python Software Foundation' @(
            '/quiet', 'InstallAllUsers=0', ('TargetDir=' + $pythonRoot), 'Include_pip=1', 'Include_launcher=0',
            'InstallLauncherAllUsers=0', 'Include_test=0', 'PrependPath=0', 'Shortcuts=0', 'AssociateFiles=0')
    }
    $null = Invoke-DeployProcess $python @('-c', 'import sys,venv,ensurepip; assert sys.version_info >= (3,11)') $runtime -Quiet
    & (Join-Path $PSScriptRoot 'prepare-server.ps1') -RepositoryRoot $RepositoryRoot
}
Write-Host 'Requested prerequisites are ready. No ViralDNA services were started.'

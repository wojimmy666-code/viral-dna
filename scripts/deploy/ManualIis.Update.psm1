# Installation only changes the enumerated setup files and three IIS config
# fields. It never imports IIS, manages services, touches api.env or uses Git.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Deploy.Core.psm1') -DisableNameChecking

function Get-ManualIisPayloadNames {
    return @('Deploy.Core.psm1', 'Iis.Proxy.ps1', 'deploy-server.ps1', 'configure-iis.ps1',
        'api-host.py', '05-run.bat', '06-check-https.bat',
        'templates\api-service.xml.template', 'templates\web-service.xml.template',
        'templates\Caddyfile.template', 'templates\Caddyfile.iis.template',
        'templates\iis-web.config.template')
}

function Get-VerifiedManualIisPayload([string]$UpdateRoot) {
    $root = Get-FullPath $UpdateRoot
    Assert-NoReparsePoint $root
    $manifest = Read-JsonFile (Join-Path $root 'update-manifest.json')
    if ($manifest.SchemaVersion -ne 1 -or $manifest.Kind -cne 'ViralDNA manual IIS controller update') {
        throw 'Not a supported manual IIS controller update.'
    }
    $required = @(Get-ManualIisPayloadNames)
    $seen = @{}
    foreach ($entry in $manifest.Files) {
        if ($entry.Path -cnotin $required -or $seen.ContainsKey($entry.Path) -or
            $entry.Sha256 -notmatch '^[a-fA-F0-9]{64}$') { throw 'Unexpected/duplicate payload path or invalid checksum.' }
        $file = Get-FullPath (Join-Path (Join-Path $root 'payload') $entry.Path)
        Assert-NoReparsePoint $file
        if (-not (Test-Path -LiteralPath $file -PathType Leaf) -or (Get-Item -LiteralPath $file).Length -ne $entry.Bytes -or
            (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ine $entry.Sha256) {
            throw "Update payload integrity check failed: $($entry.Path)"
        }
        $seen[$entry.Path] = $true
    }
    if ($seen.Count -ne $required.Count) { throw 'Update payload is incomplete.' }
    return @($manifest.Files)
}

function ConvertTo-ManualIisConfig($Config, [string]$PublicSiteUrl) {
    # Clone so callers can compare against or keep the original parsed config.
    $copy = $Config | ConvertTo-Json -Depth 30 | ConvertFrom-Json
    if (-not (Test-IisEnabled $copy)) { throw 'This update requires an existing single-root IIS deployment prepared by 02-prepare.' }
    $copy.Iis | Add-Member -MemberType NoteProperty -Name ManagementMode -Value 'Manual' -Force
    $copy.Iis.SiteUrl = $PublicSiteUrl.TrimEnd('/')
    $copy.Iis.AllowPublicAccess = $true
    return Resolve-DeployConfig $copy
}

function Install-ManualIisControllerUpdate {
    param([string]$UpdateRoot, [string]$RepositoryRoot = 'C:\Projects\ViralDNA',
        [string]$PublicSiteUrl = 'https://viraldnastudio.com', [switch]$Preview)
    $root = Get-FullPath $RepositoryRoot
    $private = Join-Path $root '.server'
    $setupRoot = Join-Path $private 'setup'
    $configPath = Join-Path $private 'config\deploy.json'
    foreach ($path in @($root, $private, $setupRoot, $configPath)) { Assert-NoReparsePoint $path }
    if (-not (Test-Path -LiteralPath $setupRoot -PathType Container)) { throw 'Existing .server\setup folder is missing; run the original preparation step first.' }
    $entries = @(Get-VerifiedManualIisPayload $UpdateRoot)
    $originalConfigHash = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash
    $settings = ConvertTo-ManualIisConfig (Read-JsonFile $configPath) $PublicSiteUrl
    if ($settings.RepositoryRoot -ne $root -or $settings.PrivateRuntimeRoot -ne $private) { throw 'Repository path differs from the existing server config.' }
    $null = Read-ProductionEnv $settings
    foreach ($entry in $entries) {
        $target = Get-FullPath (Join-Path $setupRoot $entry.Path)
        if (-not (Test-PathWithin $target $setupRoot)) { throw 'Update target escaped .server\setup.' }
        Assert-NoReparsePoint $target
        if ((Test-Path -LiteralPath $target) -and -not (Test-Path -LiteralPath $target -PathType Leaf)) { throw 'A setup file path is occupied by a directory.' }
    }
    if ($Preview) {
        return [pscustomobject]@{ Preview = $true; RepositoryRoot = $root; PayloadFiles = $entries.Count; PublicSiteUrl = $settings.Iis.SiteUrl }
    }
    Assert-Administrator
    $updateLock = $null
    $deploymentLock = $null
    $journal = New-Object 'Collections.Generic.List[object]'
    $configChanged = $false
    $backup = $null
    try {
        $updateLockPath = Join-Path $private 'config\controller-update.lock'
        Assert-NoReparsePoint $updateLockPath
        $updateLock = [IO.File]::Open($updateLockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        # Do not create a deploy.lock inside an as-yet unowned runtime folder.
        if (Test-Path -LiteralPath (Join-Path $settings.DeploymentRoot 'owner.json')) {
            $deploymentLock = Open-DeployLock $settings
        }
        if ((Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -ne $originalConfigHash) { throw 'deploy.json changed during validation; close other configuration tools and retry.' }
        $backup = Join-Path $private ('backups\manual-iis-update-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N'))
        Assert-NoReparsePoint $backup
        $null = New-Item -ItemType Directory -Path $backup
        Copy-Item -LiteralPath $configPath -Destination (Join-Path $backup 'deploy.json')
        foreach ($entry in $entries) {
            $source = Join-Path (Join-Path $UpdateRoot 'payload') $entry.Path
            $target = Join-Path $setupRoot $entry.Path
            Assert-NoReparsePoint $source
            Assert-NoReparsePoint $target
            $existed = Test-Path -LiteralPath $target -PathType Leaf
            if ($existed -and (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ieq $entry.Sha256) { continue }
            $saved = Join-Path (Join-Path $backup 'setup') $entry.Path
            if ($existed) {
                $null = New-Item -ItemType Directory -Path (Split-Path -Parent $saved) -Force
                Copy-Item -LiteralPath $target -Destination $saved
            }
            $null = New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force
            $journal.Add([pscustomobject]@{ Target = $target; Existed = $existed; Saved = $saved })
            Copy-Item -LiteralPath $source -Destination $target -Force
            if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ine $entry.Sha256) { throw "Installed file verification failed: $($entry.Path)" }
        }
        # Config is committed last: never enable manual mode on an old controller.
        if ((Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -ne $originalConfigHash) { throw 'deploy.json changed during file installation; controller update is being rolled back.' }
        $configChanged = $true
        Write-AtomicText $configPath ($settings | ConvertTo-Json -Depth 30)
        Write-Host 'Manual IIS controller installed. No services or IIS settings were changed.'
        Write-Host "Backup: $backup"
        return [pscustomobject]@{ Preview = $false; RepositoryRoot = $root; BackupRoot = $backup; PublicSiteUrl = $settings.Iis.SiteUrl }
    } catch {
        $failure = $_
        $rollbackErrors = New-Object 'Collections.Generic.List[string]'
        if ($configChanged) {
            try { Copy-Item -LiteralPath (Join-Path $backup 'deploy.json') -Destination $configPath -Force } catch { $rollbackErrors.Add($_.Exception.Message) }
        }
        for ($index = $journal.Count - 1; $index -ge 0; $index--) {
            $change = $journal[$index]
            try {
                Assert-NoReparsePoint $change.Target
                if ($change.Existed) { Copy-Item -LiteralPath $change.Saved -Destination $change.Target -Force }
                elseif ((Test-PathWithin $change.Target $setupRoot) -and (Test-Path -LiteralPath $change.Target -PathType Leaf)) {
                    # Only this exact newly copied update file; never a directory.
                    Remove-Item -LiteralPath $change.Target
                }
            } catch { $rollbackErrors.Add($_.Exception.Message) }
        }
        if ($rollbackErrors.Count) { throw "Update failed: $($failure.Exception.Message). Restore the affected controller/config files from $backup. Rollback: $($rollbackErrors -join '; ')" }
        if ($journal.Count -or $configChanged) { Write-Warning 'Update failed; previous files restored and newly copied update files removed. Backup retained.' }
        throw $failure
    } finally {
        if ($deploymentLock) { $deploymentLock.Dispose() }
        if ($updateLock) { $updateLock.Dispose() }
    }
}

Export-ModuleMember -Function Get-ManualIisPayloadNames, Get-VerifiedManualIisPayload, ConvertTo-ManualIisConfig, Install-ManualIisControllerUpdate

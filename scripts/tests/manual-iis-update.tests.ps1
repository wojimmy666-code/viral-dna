# Offline installer tests against generated temporary files; no IIS/SCM/network.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$deploy = Join-Path $repo 'scripts\deploy'
Import-Module (Join-Path $deploy 'Server.Prepare.psm1') -Force -DisableNameChecking
Import-Module (Join-Path $deploy 'Deploy.Core.psm1') -Force -DisableNameChecking
Import-Module (Join-Path $deploy 'ManualIis.Update.psm1') -Force -DisableNameChecking
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('viraldna-manual-update-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $testRoot
$package = Join-Path $testRoot 'package'
$script:passed = 0
$script:fixtureCount = 0
function Assert-True($Value) { if (-not $Value) { throw 'Assertion failed.' } }
function Assert-Throws([scriptblock]$Body, [string]$Pattern = '.') {
    try { & $Body } catch { if ($_.Exception.Message -notmatch $Pattern) { throw }; return }
    throw 'Expected failure.'
}
function Case([string]$Name, [scriptblock]$Body) {
    Import-Module (Join-Path $deploy 'ManualIis.Update.psm1') -Force -DisableNameChecking
    & (Get-Module ManualIis.Update) { function script:Assert-Administrator { } }
    & $Body; $script:passed++; Write-Host "PASS $Name"
}
function New-Fixture {
    $script:fixtureCount++
    $root = Join-Path $testRoot ('server-' + $script:fixtureCount)
    $c = New-ServerConfig $root (Join-Path $root '.server') '.\Administrator'
    $c | Add-Member NoteProperty UserExtension ([pscustomobject]@{ Keep = @('first', 'second'); Nested = @{ Value = 42 } })
    foreach ($path in @('setup', 'config', 'data', 'iis\site')) { $null = New-Item -ItemType Directory -Path (Join-Path $c.PrivateRuntimeRoot $path) -Force }
    Write-AtomicJson (Join-Path $c.PrivateRuntimeRoot 'config\deploy.json') $c
    Write-AtomicText $c.EnvFile ((New-ServerEnv $c.PrivateRuntimeRoot).Replace('http://127.0.0.1:8081', 'http://127.0.0.1:8081,https://viraldnastudio.com') + "`r`nTEST_PROVIDER_SECRET=fixture-only-not-a-real-secret`r`n")
    Write-AtomicText (Join-Path $c.PrivateRuntimeRoot 'iis\site\web.config') '<user-managed-IIS />'
    Write-AtomicText (Join-Path $c.PrivateRuntimeRoot 'data\sentinel.txt') 'existing account and asset sentinel'
    Write-AtomicText (Join-Path $c.PrivateRuntimeRoot 'setup\03-update-git.bat') 'existing untouched git entry'
    foreach ($name in (Get-ManualIisPayloadNames | Where-Object { $_ -ne '06-check-https.bat' })) {
        $file = Join-Path (Join-Path $c.PrivateRuntimeRoot 'setup') $name
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $file) -Force
        Write-AtomicText $file ('old controller fixture: ' + $name)
    }
    return $c
}
function Protected-Snapshot($Config, [switch]$IncludeController) {
    $names = @('config\api.env', 'iis\site\web.config', 'data\sentinel.txt', 'setup\03-update-git.bat')
    if ($IncludeController) {
        $names += 'config\deploy.json'
        $names += @(Get-ManualIisPayloadNames | Where-Object { $_ -ne '06-check-https.bat' } | ForEach-Object { 'setup\' + $_ })
    }
    return (($names | ForEach-Object { $_ + ':' + (Get-FileHash -LiteralPath (Join-Path $Config.PrivateRuntimeRoot $_) -Algorithm SHA256).Hash }) -join '|')
}
try {
    $built = & (Join-Path $deploy 'build-manual-iis-update.ps1') -OutputRoot $package
    Assert-True (Test-Path -LiteralPath $built.Archive -PathType Leaf)
    Case 'package has exactly the approved controller payload and a valid zip' {
        Assert-True (@(Get-VerifiedManualIisPayload $package).Count -eq 12)
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [IO.Compression.ZipFile]::OpenRead($built.Archive)
        try {
            $entries = @($zip.Entries | Where-Object { $_.Name })
            Assert-True ($entries.Count -eq 19)
            Assert-True (@($entries | Where-Object FullName -Match '/(data|config)/|/api\.env$|\.pfx$|\.key$').Count -eq 0)
        } finally { $zip.Dispose() }
    }
    Case 'preview is read-only and does not need administrator privileges' {
        $c = New-Fixture; $before = Protected-Snapshot $c -IncludeController
        & (Get-Module ManualIis.Update) { function script:Assert-Administrator { throw 'Preview must not request elevation' } }
        $result = Install-ManualIisControllerUpdate -UpdateRoot $package -RepositoryRoot $c.RepositoryRoot -Preview
        Assert-True $result.Preview
        Assert-True ((Protected-Snapshot $c -IncludeController) -ceq $before)
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $c.PrivateRuntimeRoot 'backups')))
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $c.PrivateRuntimeRoot 'config\controller-update.lock')))
    }
    Case 'the distributed installer runs a real standalone preview' {
        $c = New-Fixture; $before = Protected-Snapshot $c -IncludeController
        $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $package 'install-manual-iis-update.ps1') -RepositoryRoot $c.RepositoryRoot -Preview
        Assert-True ($LASTEXITCODE -eq 0 -and ($output -join "`n") -match 'Preview\s*:\s*True')
        Assert-True ((Protected-Snapshot $c -IncludeController) -ceq $before)
    }
    Case 'installation preserves IIS env data identity and custom settings with exact backups' {
        $c = New-Fixture; $before = Protected-Snapshot $c
        $configPath = Join-Path $c.PrivateRuntimeRoot 'config\deploy.json'
        $oldConfigHash = (Get-FileHash -LiteralPath $configPath).Hash
        $result = Install-ManualIisControllerUpdate -UpdateRoot $package -RepositoryRoot $c.RepositoryRoot
        Assert-True ((Protected-Snapshot $c) -ceq $before)
        Assert-True ((Get-FileHash -LiteralPath (Join-Path $result.BackupRoot 'deploy.json')).Hash -ceq $oldConfigHash)
        $updated = Read-DeployConfig $configPath
        Assert-True ((Test-ManualIis $updated) -and $updated.Iis.Enabled -and $updated.Iis.SiteUrl -ceq 'https://viraldnastudio.com')
        Assert-True ($updated.ServiceAccount -ceq $c.ServiceAccount -and $updated.SiteUrl -ceq $c.SiteUrl -and -not $updated.AllowPublicAccess)
        Assert-True ($updated.Iis.CertificateThumbprint -ceq $c.Iis.CertificateThumbprint -and $updated.UserExtension.Nested.Value -eq 42)
        foreach ($file in (Get-VerifiedManualIisPayload $package)) { Assert-True ((Get-FileHash -LiteralPath (Join-Path (Join-Path $c.PrivateRuntimeRoot 'setup') $file.Path)).Hash -ieq $file.Sha256) }
        $installed = Protected-Snapshot $c -IncludeController
        $null = Install-ManualIisControllerUpdate -UpdateRoot $package -RepositoryRoot $c.RepositoryRoot
        Assert-True ((Protected-Snapshot $c -IncludeController) -ceq $installed)
    }
    Case 'missing required CORS aborts before any controller change' {
        $c = New-Fixture
        Write-AtomicText $c.EnvFile (New-ServerEnv $c.PrivateRuntimeRoot)
        $before = Protected-Snapshot $c -IncludeController
        Assert-Throws { Install-ManualIisControllerUpdate -UpdateRoot $package -RepositoryRoot $c.RepositoryRoot } 'CORS'
        Assert-True ((Protected-Snapshot $c -IncludeController) -ceq $before)
    }
    Case 'payload tampering and duplicate paths abort before any target write' {
        $c = New-Fixture; $before = Protected-Snapshot $c -IncludeController
        $bad = Join-Path $testRoot 'bad-package'; Copy-Item -LiteralPath $package -Destination $bad -Recurse
        $manifestPath = Join-Path $bad 'update-manifest.json'
        $manifest = Read-JsonFile $manifestPath; $manifest.Files += $manifest.Files[0]; Write-AtomicJson $manifestPath $manifest
        Assert-Throws { Install-ManualIisControllerUpdate -UpdateRoot $bad -RepositoryRoot $c.RepositoryRoot } 'duplicate'
        Copy-Item -LiteralPath (Join-Path $package 'update-manifest.json') -Destination $manifestPath -Force
        Write-AtomicText (Join-Path $bad 'payload\Deploy.Core.psm1') 'tampered fixture'
        Assert-Throws { Install-ManualIisControllerUpdate -UpdateRoot $bad -RepositoryRoot $c.RepositoryRoot } 'integrity'
        Assert-True ((Protected-Snapshot $c -IncludeController) -ceq $before)
    }
    Case 'invalid URL or a different repository is refused without copying' {
        $c = New-Fixture; $before = Protected-Snapshot $c -IncludeController
        Assert-Throws { Install-ManualIisControllerUpdate -UpdateRoot $package -RepositoryRoot $c.RepositoryRoot -PublicSiteUrl 'http://viraldnastudio.com' } 'HTTPS'
        $other = Join-Path $testRoot 'different-server'
        Assert-Throws { Install-ManualIisControllerUpdate -UpdateRoot $package -RepositoryRoot $other } 'missing'
        Assert-True ((Protected-Snapshot $c -IncludeController) -ceq $before)
    }
    Case 'a running deployment lock prevents an update without stopping anything' {
        $c = New-Fixture; $before = Protected-Snapshot $c -IncludeController
        $null = New-Item -ItemType Directory -Path $c.DeploymentRoot -Force
        Write-AtomicText (Join-Path $c.DeploymentRoot 'owner.json') 'fixture-owned-runtime'
        $held = Open-DeployLock $c
        try { Assert-Throws { Install-ManualIisControllerUpdate -UpdateRoot $package -RepositoryRoot $c.RepositoryRoot } 'Another deployment' } finally { $held.Dispose() }
        Assert-True ((Protected-Snapshot $c -IncludeController) -ceq $before)
    }
    foreach ($failurePoint in @('copy', 'config')) {
        Case "failure rollback restores originals and removes only new update files: $failurePoint" {
            $c = New-Fixture; $before = Protected-Snapshot $c -IncludeController
            $module = Get-Module ManualIis.Update
            if ($failurePoint -eq 'copy') {
                & $module {
                    function script:Copy-Item {
                        param($LiteralPath, $Destination, [switch]$Force)
                        if ($LiteralPath -like '*\payload\templates\iis-web.config.template') { throw 'Injected copy failure' }
                        Microsoft.PowerShell.Management\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Force:$Force
                    }
                }
            } else {
                & $module { function script:Write-AtomicText { throw 'Injected config failure' } }
            }
            Assert-Throws { Install-ManualIisControllerUpdate -UpdateRoot $package -RepositoryRoot $c.RepositoryRoot } 'Injected'
            Assert-True ((Protected-Snapshot $c -IncludeController) -ceq $before)
            Assert-True (-not (Test-Path -LiteralPath (Join-Path $c.PrivateRuntimeRoot 'setup\06-check-https.bat')))
            Assert-True (@(Get-ChildItem -LiteralPath (Join-Path $c.PrivateRuntimeRoot 'backups') -Directory).Count -eq 1)
        }
    }
    Write-Host "$script:passed manual IIS update tests passed. Only isolated temporary fixtures were changed."
} finally {
    $resolved = [IO.Path]::GetFullPath($testRoot)
    if ((Split-Path -Parent $resolved) -eq ([IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')) -and (Split-Path -Leaf $resolved) -match '^viraldna-manual-update-[a-f0-9]{32}$') {
        Assert-NoReparsePoint $resolved
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

# All functions are inert until explicitly called. Tests mock the one policy write.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Deploy.Core.psm1') -DisableNameChecking

function New-ServerConfig {
    param([string]$RepositoryRoot, [string]$RuntimeRoot, [string]$AccountName)
    $repository = Get-FullPath $RepositoryRoot
    $runtime = Get-FullPath $RuntimeRoot
    $singleRoot = $runtime -eq (Join-Path $repository '.server')
    if (-not $singleRoot -and ($runtime.Length -le 3 -or (Test-PathWithin $runtime $repository) -or
        (Test-PathWithin $repository $runtime))) {
        throw 'Use RepositoryRoot\.server, or separate non-nested legacy directories.'
    }
    if ($AccountName -notmatch '^[^\s\\]+\\[^\s\\]+$' -or
        $AccountName -match '(?i)^(NT AUTHORITY|NT SERVICE)\\|LocalSystem') {
        throw 'Use the current local/domain Windows user, not a built-in system account.'
    }
    $config = Read-JsonFile (Join-Path $PSScriptRoot 'config.example.json')
    $config.RepositoryRoot = $repository
    $config.DeploymentRoot = Join-Path $runtime 'deployment'
    $config.EnvFile = Join-Path $runtime 'config\api.env'
    $config.ServiceAccount = $AccountName
    if ($singleRoot) {
        $config | Add-Member NoteProperty PrivateRuntimeRoot $runtime
        $config | Add-Member NoteProperty Iis ([pscustomobject]@{
            Enabled = $true; SiteName = 'ViralDNA'; AppPoolName = 'ViralDNA'
            SiteRoot = (Join-Path $runtime 'iis\site'); SiteUrl = 'http://127.0.0.1:8081'
            AllowPublicAccess = $false; CertificateThumbprint = ''
        })
        $config.Tools.Git = Join-Path $runtime 'tools\git\cmd\git.exe'
    }
    $config.Tools.Node = Join-Path $runtime 'tools\node\node.exe'
    $config.Tools.Npm = Join-Path $runtime 'tools\node\node_modules\npm\bin\npm-cli.js'
    $config.Tools.Python = Join-Path $runtime 'tools\python\python.exe'
    $config.Tools.FFmpeg = Join-Path $runtime 'tools\ffmpeg\bin\ffmpeg.exe'
    $config.Tools.FFprobe = Join-Path $runtime 'tools\ffmpeg\bin\ffprobe.exe'
    $config.Tools.Caddy = Join-Path $runtime 'tools\caddy.exe'
    $config.Tools.WinSW = Join-Path $runtime 'tools\WinSW-x64.exe'
    return $config
}

function New-ServerEnv([string]$RuntimeRoot) {
    $data = Join-Path (Get-FullPath $RuntimeRoot) 'data'
    $content = ([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'templates\api.env.example'),
        [Text.Encoding]::UTF8)).Replace('D:\ViralDNA\data', $data)
    if ((Split-Path -Leaf $RuntimeRoot) -eq '.server') {
        $content = $content.Replace('http://127.0.0.1:18080', 'http://127.0.0.1:18080,http://127.0.0.1:8081')
    }
    return $content
}

function Grant-CurrentUserServiceLogon {
    if (-not ('ViralDNA.Deployment.ServiceAccountRights' -as [type])) {
        Add-Type -Path (Join-Path $PSScriptRoot 'ServiceAccountRights.cs')
    }
    [ViralDNA.Deployment.ServiceAccountRights]::GrantToCurrentUser()
}

function Assert-ServerTools($Config) {
    foreach ($key in @('Git', 'Node', 'Npm', 'Python', 'FFmpeg', 'FFprobe', 'Caddy', 'WinSW')) {
        Assert-NoReparsePoint $Config.Tools.$key
        if (-not (Test-Path -LiteralPath $Config.Tools.$key -PathType Leaf)) {
            throw "Missing $key at $($Config.Tools.$key). Copy the complete tools directory / install the included prerequisites first."
        }
    }
    if ((Get-Item -LiteralPath $Config.Tools.WinSW).VersionInfo.FileMajorPart -ne 2) {
        throw 'WinSW 2.x is required.'
    }
}

function Initialize-CurrentUserServer {
    param([string]$RepositoryRoot, [string]$RuntimeRoot, [string]$ConfigPath)
    Assert-Administrator
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $config = New-ServerConfig $RepositoryRoot $RuntimeRoot $identity.Name
    $outputPath = Get-FullPath $ConfigPath
    foreach ($path in @($RepositoryRoot, $RuntimeRoot, $outputPath, $config.EnvFile)) {
        Assert-NoReparsePoint $path
    }
    $private = Get-PrivateRuntimeRoot $config
    if (($private -and $outputPath -ne (Join-Path $private 'config\deploy.json')) -or
        (-not $private -and (Test-PathWithin $outputPath $config.RepositoryRoot)) -or
        (Test-PathWithin $outputPath $config.DeploymentRoot)) {
        throw 'Keep the deployment config outside source and generated deployment directories.'
    }

    $existingConfig = Test-Path -LiteralPath $outputPath -PathType Leaf
    if ($existingConfig) {
        $previous = Read-DeployConfig $outputPath
        if ($previous.RepositoryRoot -ne $config.RepositoryRoot -or
            $previous.DeploymentRoot -ne $config.DeploymentRoot -or
            $previous.EnvFile -ne $config.EnvFile -or
            (Get-ServiceAccountSid $previous) -ne $identity.User.Value) {
            throw 'Existing deployment belongs to different paths/user; it has not been changed.'
        }
        # Preserve a configured domain, model settings and all operator edits.
        $config = $previous
    } elseif (Test-Path -LiteralPath (Join-Path $config.DeploymentRoot 'owner.json')) {
        throw 'An existing deployment has no matching config. Restore its original config instead of reinitializing.'
    }
    foreach ($role in @('api', 'web')) {
        $service = Get-DeployService $config $role
        if ($null -ne $service) { Assert-ManagedService $config $role $service }
    }
    if (Test-Path -LiteralPath $config.EnvFile -PathType Leaf) {
        $null = Read-ProductionEnv $config
    }
    # Check tools before making any configuration or Windows-policy changes.
    Assert-ServerTools $config

    foreach ($directory in @((Split-Path -Parent $outputPath), (Split-Path -Parent $config.EnvFile),
        (Join-Path $RuntimeRoot 'data'))) {
        if (-not (Test-Path -LiteralPath $directory)) {
            $null = New-Item -ItemType Directory -Path $directory -Force
            Set-PrivateDirectoryAcl $directory $identity.User.Value -Writable
        } elseif ($private) {
            # Copied package folders already exist and may inherit Users:Read.
            # Protect configuration/data before the application stores secrets.
            Set-PrivateDirectoryAcl $directory $identity.User.Value -Writable
        }
    }
    if (-not (Test-Path -LiteralPath $config.EnvFile)) {
        Write-AtomicText $config.EnvFile (New-ServerEnv $RuntimeRoot)
    }
    if (-not $existingConfig) { Write-AtomicJson $outputPath $config }
    $verified = Read-DeployConfig $outputPath
    $null = Read-ProductionEnv $verified
    if ($private -and (Test-Path -LiteralPath (Join-Path $RepositoryRoot '.git'))) {
        Add-PrivateGitExclude $verified
    }
    Grant-CurrentUserServiceLogon
    Write-Host "Prepared for current Windows account: $($config.ServiceAccount)"
    Write-Host "Deployment config: $outputPath"
    Write-Host "API config: $($config.EnvFile)"
    Write-Host 'No user was created; no services were registered, stopped or started.'
    Write-Host 'First service registration still needs this Windows account password (not a PIN).'
    return $verified
}

Export-ModuleMember -Function New-ServerConfig, New-ServerEnv, Initialize-CurrentUserServer

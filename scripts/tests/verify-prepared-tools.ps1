[CmdletBinding()]
param([string]$ToolsRoot = 'D:\ViralDNA\tools')
# Read-only executable/configuration smoke tests; no service or IIS installation.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Import-Module (Join-Path $repo 'scripts\deploy\Server.Prepare.psm1') -Force -DisableNameChecking
Import-Module (Join-Path $repo 'scripts\deploy\Deploy.Core.psm1') -DisableNameChecking
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('viraldna-tools-check-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $testRoot
try {
    foreach ($tool in @(@('git\cmd\git.exe', '--version'), @('node\node.exe', '--version'),
        @('ffmpeg\bin\ffmpeg.exe', '-version'), @('ffmpeg\bin\ffprobe.exe', '-version'), @('caddy.exe', 'version'))) {
        $result = Invoke-DeployProcess (Join-Path $ToolsRoot $tool[0]) @($tool[1]) $testRoot -Quiet
        Write-Host (($result.Output -split "`r?`n")[0])
    }
    Assert-NoReparsePoint (Join-Path $ToolsRoot 'git\usr\bin\ssh-keygen.exe')
    $c = New-ServerConfig (Join-Path $testRoot 'source') (Join-Path $testRoot 'source\.server') '.\Administrator'
    $release = [pscustomobject]@{ Id = 'fixture'; Path = (Join-Path $testRoot 'release') }
    # WinSW 2 loads its sidecar XML even for the 'version' command.
    $wrapper = Join-Path $testRoot 'winsw-test.exe'
    Copy-Item -LiteralPath (Join-Path $ToolsRoot 'WinSW-x64.exe') -Destination $wrapper
    Write-AtomicText (Join-Path $testRoot 'winsw-test.xml') (Get-DeployServiceXml $c $release 'api')
    $winSwResult = Invoke-DeployProcess $wrapper @('version') $testRoot -Quiet
    Write-Host ('WinSW: ' + $winSwResult.Output.Trim())
    $caddyFile = Join-Path $testRoot 'Caddyfile'
    Write-AtomicText $caddyFile (Get-CaddyConfig $c $release)
    $null = Invoke-DeployProcess (Join-Path $ToolsRoot 'caddy.exe') @('validate', '--config', $caddyFile, '--adapter', 'caddyfile') $testRoot -Quiet
    Write-Host 'PASS real Caddy validates the IIS forwarding template without starting listeners.'
    $c.Iis | Add-Member -MemberType NoteProperty -Name ManagementMode -Value 'Manual'
    $c.Iis.SiteUrl = 'https://viraldnastudio.com'
    $c.Iis.AllowPublicAccess = $true
    Assert-IisConfig $c
    $manualCaddyFile = Join-Path $testRoot 'Caddyfile.manual'
    Write-AtomicText $manualCaddyFile (Get-CaddyConfig $c $release)
    $null = Invoke-DeployProcess (Join-Path $ToolsRoot 'caddy.exe') @('validate', '--config', $manualCaddyFile, '--adapter', 'caddyfile') $testRoot -Quiet
    Write-Host 'PASS real Caddy validates manual IIS mode without public listeners or certificate changes.'

    # Prove Git fast-forward can populate an unborn main in a nonempty copy-first
    # directory. The source is a local fixture, not GitHub; no network involved.
    $git = Join-Path $ToolsRoot 'git\cmd\git.exe'
    $originFixture = Join-Path $testRoot 'origin'
    $working = Join-Path $testRoot 'working'
    foreach ($directory in @($originFixture, $working)) {
        $null = New-Item -ItemType Directory -Path $directory
        $null = Invoke-DeployProcess $git @('init', '--initial-branch=main') $directory -Quiet
    }
    Write-AtomicText (Join-Path $originFixture 'fixture.txt') 'tracked fixture'
    $null = Invoke-DeployProcess $git @('add', 'fixture.txt') $originFixture -Quiet
    $null = Invoke-DeployProcess $git @('-c', 'user.name=Offline Test', '-c', 'user.email=offline@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-m', 'offline fixture') $originFixture -Quiet
    $private = Join-Path $working '.server'
    $null = New-Item -ItemType Directory -Path $private
    Write-AtomicText (Join-Path $private 'private.txt') 'must survive'
    $null = Invoke-DeployProcess $git @('-c', 'protocol.file.allow=always', 'fetch', '--no-tags', $originFixture, 'main') $working -Quiet
    $null = Invoke-DeployProcess $git @('merge', '--ff-only', 'FETCH_HEAD') $working -Quiet
    if ([IO.File]::ReadAllText((Join-Path $private 'private.txt')) -ne 'must survive' -or
        [IO.File]::ReadAllText((Join-Path $working 'fixture.txt')) -ne 'tracked fixture') { throw 'Copy-first Git fixture failed.' }
    Write-Host 'PASS real portable Git populates unborn main and preserves .server files.'
} finally {
    $resolved = Get-FullPath $testRoot
    if ((Split-Path -Parent $resolved) -eq ([IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')) -and
        (Split-Path -Leaf $resolved) -match '^viraldna-tools-check-[a-f0-9]{32}$') {
        Assert-NoReparsePoint $resolved
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

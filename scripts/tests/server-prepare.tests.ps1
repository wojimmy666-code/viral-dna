$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Import-Module (Join-Path $repo 'scripts\deploy\Server.Prepare.psm1') -Force -DisableNameChecking
Import-Module (Join-Path $repo 'scripts\deploy\Deploy.Core.psm1') -DisableNameChecking
$prepareModule = Get-Module Server.Prepare
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('viraldna-prepare-tests-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $testRoot
$script:passed = 0
function Assert-True($Value) { if (-not $Value) { throw 'Assertion failed.' } }
function Assert-Throws([scriptblock]$Body, [string]$Pattern) {
    try { & $Body } catch { if ($_.Exception.Message -notmatch $Pattern) { throw }; return }
    throw 'Expected a failure.'
}
function Case([string]$Name, [scriptblock]$Body) { & $Body; $script:passed++; Write-Host "PASS $Name" }
try {
    Case 'prepared C drive paths and current-user profile require no new account' {
        $c = New-ServerConfig 'C:\Projects\ViralDNA' 'C:\Projects\ViralDNA-runtime' '.\Administrator'
        Assert-True ($c.RepositoryRoot -eq 'C:\Projects\ViralDNA')
        Assert-True ($c.ServiceAccount -eq '.\Administrator')
        Assert-True ($c.Tools.Npm -eq 'C:\Projects\ViralDNA-runtime\tools\node\node_modules\npm\bin\npm-cli.js')
        Assert-True (-not $c.AllowPublicAccess)
        $file = Join-Path $testRoot 'profile.json'
        Write-AtomicJson $file $c
        $null = Read-DeployConfig $file
    }
    Case 'source/runtime nesting and SYSTEM identities are rejected' {
        Assert-Throws { New-ServerConfig 'C:\Projects\ViralDNA' 'C:\Projects\ViralDNA\data' '.\Administrator' } 'separate'
        Assert-Throws { New-ServerConfig 'C:\code' 'C:\runtime' 'NT AUTHORITY\SYSTEM' } 'current'
    }
    Case 'API env preserves exact local origins and uses only the selected runtime' {
        $envText = New-ServerEnv 'C:\Projects\ViralDNA-runtime'
        Assert-True ($envText.Contains('VIRAL_DNA_AUTH_MODE=password'))
        Assert-True ($envText.Contains('C:\Projects\ViralDNA-runtime\data\accounts.sqlite3'))
        Assert-True (-not $envText.Contains('D:\ViralDNA'))
        Assert-True ($envText.Contains('http://127.0.0.1:8080,http://127.0.0.1:18080'))
    }
    # Compile, but never invoke the native Windows policy mutation in tests.
    Case 'Windows policy helper compiles without invoking native policy APIs' {
        if (-not ('ViralDNA.Deployment.ServiceAccountRights' -as [type])) {
            Add-Type -Path (Join-Path $repo 'scripts\deploy\ServiceAccountRights.cs')
        }
        Assert-True ($null -ne ('ViralDNA.Deployment.ServiceAccountRights' -as [type]))
    }
    & $prepareModule {
        $script:grants = 0
        function script:Assert-Administrator { }
        function script:Assert-ServerTools { }
        function script:Get-DeployService { return $null }
        function script:Set-PrivateDirectoryAcl { }
        function script:Grant-CurrentUserServiceLogon { $script:grants++ }
    }
    $source = Join-Path $testRoot 'source'
    $runtime = Join-Path $testRoot 'runtime'
    $configPath = Join-Path $testRoot 'private\deployment.json'
    Case 'preparation binds this machine identity and leaves deployment/services absent' {
        $c = Initialize-CurrentUserServer $source $runtime $configPath
        Assert-True ($c.ServiceAccount -eq [Security.Principal.WindowsIdentity]::GetCurrent().Name)
        Assert-True (Test-Path -LiteralPath $c.EnvFile)
        Assert-True (-not (Test-Path -LiteralPath $c.DeploymentRoot))
        Assert-True ((& $prepareModule { $script:grants }) -eq 1)
    }
    Case 'repeat preparation preserves public domain and private API settings byte-for-byte' {
        $c = Read-DeployConfig $configPath
        $c.SiteUrl = 'https://video.example.com'; $c.AllowPublicAccess = $true
        Write-AtomicJson $configPath $c
        $envText = (New-ServerEnv $runtime).Replace('http://127.0.0.1:8080', 'https://video.example.com') + "`r`nSAMPLE_PRIVATE_SETTING=preserve-me`r`n"
        Write-AtomicText $c.EnvFile $envText
        $oldConfig = [IO.File]::ReadAllText($configPath)
        $oldEnv = [IO.File]::ReadAllText($c.EnvFile)
        $null = Initialize-CurrentUserServer $source $runtime $configPath
        Assert-True ([IO.File]::ReadAllText($configPath) -ceq $oldConfig)
        Assert-True ([IO.File]::ReadAllText($c.EnvFile) -ceq $oldEnv)
    }
    Case 'existing configuration with different ownership paths is not overwritten' {
        $before = [IO.File]::ReadAllText($configPath)
        Assert-Throws { Initialize-CurrentUserServer (Join-Path $testRoot 'another-source') $runtime $configPath } 'different paths/user'
        Assert-True ([IO.File]::ReadAllText($configPath) -ceq $before)
    }
    Case 'owned runtime cannot be reinitialized after its original config disappears' {
        $otherRuntime = Join-Path $testRoot 'owned-runtime'
        $null = New-Item -ItemType Directory -Path (Join-Path $otherRuntime 'deployment') -Force
        Write-AtomicJson (Join-Path $otherRuntime 'deployment\owner.json') @{ existing = $true }
        Assert-Throws { Initialize-CurrentUserServer $source $otherRuntime (Join-Path $testRoot 'missing.json') } 'Restore its original'
    }
    Case 'missing tools fail before creating private configuration or changing rights' {
        & $prepareModule { function script:Assert-ServerTools { throw 'Missing tools fixture' } }
        $missingConfig = Join-Path $testRoot 'not-created\config.json'
        $grants = & $prepareModule { $script:grants }
        Assert-Throws { Initialize-CurrentUserServer $source (Join-Path $testRoot 'missing-tools') $missingConfig } 'Missing tools'
        Assert-True (-not (Test-Path -LiteralPath $missingConfig))
        Assert-True ((& $prepareModule { $script:grants }) -eq $grants)
    }
    $verifyRoot = Join-Path $testRoot 'verify'
    $null = New-Item -ItemType Directory -Path (Join-Path $verifyRoot 'setup') -Force
    $verifyEntry = Join-Path $verifyRoot 'setup\verify-bundle.ps1'
    Copy-Item -LiteralPath (Join-Path $repo 'scripts\deploy\verify-bundle.ps1') -Destination $verifyEntry
    $fixture = Join-Path $verifyRoot 'fixture.txt'
    Write-AtomicText $fixture 'original fixture'
    $manifest = @{ SchemaVersion = 1; GeneratedBy = 'ViralDNA server bundle'; Complete = $true; Missing = @();
        Files = @(@{ Path = 'fixture.txt'; Sha256 = (Get-FileHash -LiteralPath $fixture).Hash }) }
    Write-AtomicJson (Join-Path $verifyRoot 'bundle-manifest.generated.json') $manifest
    Case 'bundle verifier locates its default root without parameter binding failures' {
        & $verifyEntry
    }
    Case 'bundle verifier reports incomplete downloads even when existing hashes match' {
        $manifest.Complete = $false; $manifest.Missing = @('tools\WinSW-x64.exe')
        Write-AtomicJson (Join-Path $verifyRoot 'bundle-manifest.generated.json') $manifest
        Assert-Throws { & $verifyEntry } 'Downloads are incomplete'
    }
    Case 'bundle verifier rejects changed files before accepting a manifest' {
        Write-AtomicText $fixture 'changed fixture'
        Assert-Throws { & $verifyEntry } 'Missing or changed'
    }
    Write-Host "$script:passed server-preparation tests passed. No accounts, privileges or services changed."
} finally {
    $resolved = [IO.Path]::GetFullPath($testRoot)
    $tempParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    if ((Split-Path -Parent $resolved) -eq $tempParent -and
        (Split-Path -Leaf $resolved) -match '^viraldna-prepare-tests-[a-f0-9]{32}$') {
        Assert-NoReparsePoint $resolved
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

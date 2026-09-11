# Offline regression tests. No IIS, services, accounts or network mutations.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$corePath = Join-Path $repo 'scripts\deploy\Deploy.Core.psm1'
Import-Module (Join-Path $repo 'scripts\deploy\Server.Prepare.psm1') -Force -DisableNameChecking
Import-Module $corePath -DisableNameChecking
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('viraldna-single-tests-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $testRoot
$script:passed = 0
function Assert-True($Value) { if (-not $Value) { throw 'Assertion failed.' } }
function Assert-Throws([scriptblock]$Body, [string]$Pattern) {
    try { & $Body } catch { if ($_.Exception.Message -notmatch $Pattern) { throw }; return }
    throw 'Expected a failure.'
}
function Case([string]$Name, [scriptblock]$Body) { & $Body; $script:passed++; Write-Host "PASS $Name" }
function Config {
    $source = Join-Path $testRoot 'source'
    return New-ServerConfig $source (Join-Path $source '.server') '.\Administrator'
}
function Validate($Value) {
    $file = Join-Path $testRoot 'config.json'; Write-AtomicJson $file $Value
    return Read-DeployConfig $file
}
function Reset-Core { Import-Module $corePath -Force -DisableNameChecking }
try {
    Case 'all project paths stay in the single root; default IIS is loopback' {
        $c = Validate (Config)
        Assert-True ($c.DeploymentRoot -eq (Join-Path $c.RepositoryRoot '.server\deployment'))
        Assert-True ($c.Tools.Git -eq (Join-Path $c.RepositoryRoot '.server\tools\git\cmd\git.exe'))
        Assert-True ((Get-DeployEntryUrl $c) -eq 'http://127.0.0.1:8081')
        Assert-True ((Get-IisBinding $c) -eq '127.0.0.1:8081:')
    }
    Case 'reserved path mode does not allow arbitrary source/runtime overlap' {
        $c = Config; $c.PrivateRuntimeRoot = Join-Path $c.RepositoryRoot 'anything'
        Assert-Throws { Validate $c } 'exactly'
        $c = Config; $c.EnvFile = Join-Path $c.RepositoryRoot '.env'
        Assert-Throws { Validate $c } 'reserved'
        $c = Config; $c.Tools.Python = 'C:\Python313\python.exe'
        Assert-Throws { Validate $c } 'tools'
    }
    Case 'private data paths and IIS CORS are mandatory' {
        $c = Config; $null = New-Item -ItemType Directory -Path (Split-Path -Parent $c.EnvFile) -Force
        $envText = New-ServerEnv $c.PrivateRuntimeRoot
        Write-AtomicText $c.EnvFile $envText
        $null = Read-ProductionEnv $c
        Write-AtomicText $c.EnvFile ($envText.Replace(',http://127.0.0.1:8081', ''))
        Assert-Throws { Read-ProductionEnv $c } 'IIS SiteUrl'
        Write-AtomicText $c.EnvFile ($envText.Replace((Join-Path $c.PrivateRuntimeRoot 'data\accounts.sqlite3'), (Join-Path $c.RepositoryRoot 'accounts.sqlite3')))
        Assert-Throws { Read-ProductionEnv $c } 'persistent'
        Write-AtomicText $c.EnvFile $envText
    }
    Case 'IIS cannot serve the repository or collide with internal ports' {
        $c = Config; $c.Iis.SiteRoot = $c.RepositoryRoot
        Assert-Throws { Validate $c } 'physical root'
        $c = Config; $c.Iis.SiteUrl = 'http://127.0.0.1:8080'
        Assert-Throws { Validate $c } 'distinct'
        $c = Config; $c.SiteUrl = 'https://example.com'; $c.AllowPublicAccess = $true
        Assert-Throws { Validate $c } 'internal SiteUrl'
    }
    Case 'public IIS requires explicit HTTPS and certificate' {
        $c = Config; $c.Iis.SiteUrl = 'http://video.example.com'
        Assert-Throws { Validate $c } 'HTTPS'
        $c.Iis.SiteUrl = 'https://video.example.com'; $c.Iis.AllowPublicAccess = $true
        Assert-Throws { Validate $c } 'thumbprint'
        $c.Iis.CertificateThumbprint = 'a' * 40
        $null = Validate $c
        Assert-True ((Get-IisBinding $c) -eq '*:443:video.example.com')
    }
    Case 'IIS proxy preserves query and overwrites forwarded scheme host and client' {
        $xml = [xml](Get-IisWebConfig (Config))
        $rules = @($xml.configuration.'system.webServer'.rewrite.rules.rule)
        Assert-True ($rules.Count -eq 2)
        foreach ($rule in $rules) {
            Assert-True ($rule.action.url -eq 'http://127.0.0.1:8080/{R:1}')
            Assert-True ($rule.action.appendQueryString -eq 'true')
            Assert-True (@($rule.serverVariables.set).Count -eq 3)
        }
        Assert-True ($rules[0].serverVariables.set[0].value -eq 'https')
        Assert-True ($rules[1].serverVariables.set[0].value -eq 'http')
    }
    Case 'IIS internal Caddy trusts only loopback, flushes SSE and blocks private paths' {
        $c = Config; $release = [pscustomobject]@{ Id = 'fixture'; Path = (Join-Path $c.DeploymentRoot 'releases\fixture') }
        $text = Get-CaddyConfig $c $release
        Assert-True ($text.Contains('trusted_proxies static 127.0.0.1/32'))
        Assert-True ($text.Contains('header_up Host {original_host}'))
        Assert-True ($text.Contains('flush_interval -1'))
        Assert-True ($text.Contains('/.server*'))
        Assert-True ($text.Contains('http://:8080 {'))
        Assert-True ($text -notmatch '@@[A-Z_]+@@')
    }
    Case 'copy-first initialization permits only the reserved .server folder' {
        $c = Config
        Assert-Repository $c -AllowMissing
        Write-AtomicText (Join-Path $c.RepositoryRoot 'unrelated.txt') 'do not overwrite'
        Assert-Throws { Assert-Repository $c -AllowMissing } 'missing|empty'
        # Remove only this exact test-created file, not a directory or user data.
        Remove-Item -LiteralPath (Join-Path $c.RepositoryRoot 'unrelated.txt')
    }
    Case 'private Git exclusion preserves existing local exclusions and is idempotent' {
        $c = Config; $null = New-Item -ItemType Directory -Path (Join-Path $c.RepositoryRoot '.git\info') -Force
        $file = Join-Path $c.RepositoryRoot '.git\info\exclude'
        Write-AtomicText $file '/existing-local/'
        Add-PrivateGitExclude $c; Add-PrivateGitExclude $c
        $text = [IO.File]::ReadAllText($file)
        Assert-True ($text.Contains('/existing-local/'))
        Assert-True ([regex]::Matches($text, '/\.server/').Count -eq 1)
    }
    Case 'unborn main fetch checks remote private files before checkout and never resets' {
        $module = Get-Module Deploy.Core
        & $module {
            $script:trace = New-Object 'Collections.Generic.List[string]'
            function script:Assert-Repository { }
            function script:Invoke-DeployGit {
                param($Config, $Arguments, [switch]$AllowFailure)
                $script:trace.Add(($Arguments -join ' '))
                return [pscustomobject]@{ Code = $(if ($Arguments[0] -eq 'rev-parse') { 128 } else { 0 }); Output = ''; Error = '' }
            }
        }
        Update-DeployRepository (Config)
        $trace = & $module { $script:trace.ToArray() }
        Assert-True ($trace[0] -eq 'fetch --no-tags origin main')
        Assert-True ($trace[1] -eq 'ls-tree -r --name-only FETCH_HEAD -- .server')
        Assert-True ($trace -contains 'merge --ff-only FETCH_HEAD')
        Assert-True (($trace -join ' ') -notmatch 'merge-base|reset|push|checkout')
        Reset-Core
    }
    Case 'remote private files abort before merge' {
        $module = Get-Module Deploy.Core
        & $module {
            function script:Assert-Repository { }
            function script:Invoke-DeployGit {
                param($Config, $Arguments, [switch]$AllowFailure)
                if ($Arguments[0] -eq 'merge') { throw 'Must not merge' }
                return [pscustomobject]@{ Code = 0; Output = $(if ($Arguments[0] -eq 'ls-tree') { '.server/config/api.env' } else { '' }); Error = '' }
            }
        }
        Assert-Throws { Update-DeployRepository (Config) } 'Remote main contains'
        Reset-Core
    }
    Case 'IIS missing ownership cannot take over a same-name site' {
        $c = Config
        Assert-Throws { Assert-IisOwner $c ([pscustomobject]@{ Id = 1 }) } 'collision|ownership'
    }
    Case 'uninitialized application cannot start public IIS even with loopback Caddy' {
        $c = Config; $c.Iis.SiteUrl = 'https://video.example.com'
        $module = Get-Module Deploy.Core
        & $module {
            function script:Assert-DeployPorts { }
            function script:Assert-RunningDeployInstance { }
            function script:Start-Service { param($Name) if ($Name -match '-web$') { throw 'Web must not start' } }
            function script:Start-ManagedIis { throw 'IIS must not start' }
            function script:Wait-DeployHttp { }
            function script:Invoke-RestMethod { return [pscustomobject]@{ auth_mode = 'password'; initialized = $false } }
            function script:Stop-DeployServices { }
        }
        Assert-Throws { Start-DeployServices $c ([pscustomobject]@{ Id = 'fixture' }) } 'Public startup refused'
        Reset-Core
    }
    Case 'stop closes owned IIS before stopping the application services' {
        $module = Get-Module Deploy.Core
        & $module {
            $script:trace = New-Object 'Collections.Generic.List[string]'
            function script:Stop-ManagedIis { $script:trace.Add('iis') }
            function script:Get-DeployService { param($Config, $Role) $script:trace.Add($Role); return $null }
            function script:Assert-DeployPorts { }
        }
        Stop-DeployServices (Config)
        Assert-True (((& $module { $script:trace.ToArray() }) -join ',') -eq 'iis,web,api')
        Reset-Core
    }
    Write-Host "$script:passed single-root/IIS tests passed. No services, IIS or accounts changed."
} finally {
    $resolved = [IO.Path]::GetFullPath($testRoot)
    if ((Split-Path -Parent $resolved) -eq ([IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')) -and
        (Split-Path -Leaf $resolved) -match '^viraldna-single-tests-[a-f0-9]{32}$') {
        Assert-NoReparsePoint $resolved
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

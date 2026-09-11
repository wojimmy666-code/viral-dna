# Offline regression tests: Windows/IIS/SCM/network operations are mocked.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$corePath = Join-Path $repo 'scripts\deploy\Deploy.Core.psm1'
Import-Module (Join-Path $repo 'scripts\deploy\Server.Prepare.psm1') -Force -DisableNameChecking
Import-Module $corePath -Force -DisableNameChecking
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('viraldna-manual-controller-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $testRoot
$script:passed = 0
function Assert-True($Value) { if (-not $Value) { throw 'Assertion failed.' } }
function Assert-Throws([scriptblock]$Body, [string]$Pattern) {
    try { & $Body } catch { if ($_.Exception.Message -notmatch $Pattern) { throw }; return }
    throw 'Expected failure.'
}
function Reset-Core { Import-Module $corePath -Force -DisableNameChecking }
function Case([string]$Name, [scriptblock]$Body) { Reset-Core; & $Body; $script:passed++; Write-Host "PASS $Name" }
function Config {
    $source = Join-Path $testRoot 'source'
    $c = New-ServerConfig $source (Join-Path $source '.server') '.\Administrator'
    $c.Iis | Add-Member NoteProperty ManagementMode 'Manual'
    $c.Iis.SiteUrl = 'https://viraldnastudio.com'; $c.Iis.AllowPublicAccess = $true
    $null = New-Item -ItemType Directory -Path (Split-Path -Parent $c.EnvFile),$c.DeploymentRoot -Force
    Write-AtomicText $c.EnvFile ((New-ServerEnv $c.PrivateRuntimeRoot).Replace('http://127.0.0.1:8081', 'http://127.0.0.1:8081,https://viraldnastudio.com'))
    return $c
}
function Set-RuntimeMocks([bool]$Initialized) {
    & (Get-Module Deploy.Core) {
        param($Initialized)
        $script:initialized = $Initialized
        $script:events = New-Object 'Collections.Generic.List[string]'
        function script:Assert-DeployPorts { }
        function script:Assert-RunningDeployInstance { }
        function script:Start-Service { param($Name) $script:events.Add("start:$Name") }
        function script:Set-Service { param($Name, $StartupType) $script:events.Add("autostart:${Name}:$StartupType") }
        function script:Wait-DeployHttp { }
        function script:Invoke-RestMethod { return [pscustomobject]@{ auth_mode = 'password'; initialized = $script:initialized } }
        function script:Assert-ManualIisBootstrapStopped { $script:events.Add('bootstrap-read-only') }
        function script:Stop-DeployServices { $script:events.Add('cleanup-internal') }
        function script:Start-ManagedIis { throw 'FORBIDDEN IIS START' }
        function script:Enable-ManagedIisAutostart { throw 'FORBIDDEN IIS AUTOSTART' }
        function script:New-IisManager { throw 'FORBIDDEN IIS ACCESS' }
    } $Initialized
}
try {
    Case 'manual mode preserves IIS-aware Caddy and validates public URL without a pinned thumbprint' {
        $c = Resolve-DeployConfig (Config)
        Assert-True (Test-ManualIis $c)
        Assert-True (-not (Test-AutomaticIis $c))
        $text = Get-CaddyConfig $c ([pscustomobject]@{ Id = 'fixture'; Path = $testRoot })
        foreach ($expected in @('trusted_proxies static 127.0.0.1/32', 'header_up Host {original_host}', 'flush_interval -1', 'bind 127.0.0.1', 'http://:8080 {')) { Assert-True $text.Contains($expected) }
        Assert-True ($text -notmatch '@@[A-Z_]+@@')
        Assert-True (@(Get-DeployPorts $c) -notcontains 443 -and @(Get-DeployPorts $c) -notcontains 80)
    }
    Case 'unknown modes and invalid manual public URLs are rejected' {
        $c = Config; $c.Iis.ManagementMode = 'Manul'; Assert-Throws { Resolve-DeployConfig $c } 'ManagementMode'
        $c = Config; $c.Iis.SiteUrl = 'http://viraldnastudio.com'; Assert-Throws { Resolve-DeployConfig $c } 'HTTPS'
        $c = Config; $c.Iis.AllowPublicAccess = $false; Assert-Throws { Resolve-DeployConfig $c } 'AllowPublicAccess'
        $c = Config; $c.Iis.SiteUrl = 'http://127.0.0.1:8081'; Assert-Throws { Resolve-DeployConfig $c } 'Manual IIS requires'
    }
    Case 'legacy default remains automatic and all automatic entry points refuse manual mode' {
        $c = Config; $c.Iis.PSObject.Properties.Remove('ManagementMode'); Assert-True (Test-AutomaticIis $c)
        $c = Config
        & (Get-Module Deploy.Core) { function script:New-IisManager { throw 'FORBIDDEN IIS ACCESS' } }
        foreach ($name in @('Assert-ManagedIis', 'Start-ManagedIis', 'Stop-ManagedIis', 'Enable-ManagedIisAutostart', 'Initialize-ManagedIis')) {
            Assert-Throws { & $name $c } 'Automatic IIS management is disabled'
        }
        $configure = [IO.File]::ReadAllText((Join-Path $repo 'scripts\deploy\configure-iis.ps1'))
        Assert-True ($configure.IndexOf('Assert-AutomaticIis $settings') -lt $configure.IndexOf('if ($InstallComponents)'))
    }
    Case 'manual stop never inspects or stops IIS' {
        $c = Config
        $module = Get-Module Deploy.Core
        & $module {
            $script:events = New-Object 'Collections.Generic.List[string]'
            function script:Stop-ManagedIis { throw 'FORBIDDEN IIS STOP' }
            function script:Get-DeployService { param($Config, $Role) $script:events.Add($Role); return $null }
            function script:Assert-DeployPorts { }
        }
        Stop-DeployServices $c
        Assert-True (((& $module { $script:events.ToArray() }) -join ',') -eq 'web,api')
    }
    Case 'manual preflight never requires IIS ownership or automatic binding checks' {
        $c = Config
        & (Get-Module Deploy.Core) {
            function script:Assert-Administrator { }
            function script:Get-ServiceAccountSid { return 'fixture-sid' }
            function script:Get-DeployService { return $null }
            function script:Assert-ManagedIis { throw 'FORBIDDEN AUTOMATIC IIS CHECK' }
            function script:New-IisManager { throw 'FORBIDDEN IIS ACCESS' }
        }
        Test-DeployPrerequisites $c 'stop'
    }
    Case 'uninitialized manual startup stays local and does not enable reboot starts' {
        $c = Config; Set-RuntimeMocks $false
        Start-DeployServices $c ([pscustomobject]@{ Id = 'fixture' })
        $events = (& (Get-Module Deploy.Core) { $script:events.ToArray() }) -join ','
        Assert-True ($events -match 'bootstrap-read-only' -and $events -match 'start:.*-web' -and $events -match ':Manual' -and $events -notmatch ':Automatic|cleanup')
    }
    Case 'initialized manual startup never touches IIS and enables internal service autostart' {
        $c = Config; Set-RuntimeMocks $true
        Start-DeployServices $c ([pscustomobject]@{ Id = 'fixture' })
        $events = (& (Get-Module Deploy.Core) { $script:events.ToArray() }) -join ','
        Assert-True ($events -match ':Automatic' -and $events -notmatch 'bootstrap-read-only|:Manual|cleanup')
    }
    Case 'bootstrap safety failure does not start web and cleans up only internal services' {
        $c = Config; Set-RuntimeMocks $false
        & (Get-Module Deploy.Core) { function script:Assert-ManualIisBootstrapStopped { throw 'Stop ONLY the ViralDNA site' } }
        Assert-Throws { Start-DeployServices $c ([pscustomobject]@{ Id = 'fixture' }) } 'Stop ONLY'
        $events = (& (Get-Module Deploy.Core) { $script:events.ToArray() }) -join ','
        Assert-True ($events -notmatch 'start:.*-web|autostart' -and $events -match 'cleanup-internal')
    }
    Case 'ambiguous initialization values fail closed before web startup' {
        $c = Config; Set-RuntimeMocks $false
        & (Get-Module Deploy.Core) { function script:Invoke-RestMethod { return [pscustomobject]@{ auth_mode = 'password'; initialized = 'false' } } }
        Assert-Throws { Start-DeployServices $c ([pscustomobject]@{ Id = 'fixture' }) } 'boolean initialization'
        $events = (& (Get-Module Deploy.Core) { $script:events.ToArray() }) -join ','
        Assert-True ($events -notmatch 'start:.*-web|autostart')
    }
    Case 'real bootstrap guard only reads state and always disposes its manager' {
        $c = Config; $module = Get-Module Deploy.Core
        & $module {
            $script:fake = [pscustomobject]@{ Sites = @{ ViralDNA = [pscustomobject]@{ State = 'Stopped' } }; Disposed = $false }
            $script:fake | Add-Member ScriptMethod Dispose { $this.Disposed = $true }
            function script:New-IisManager { return $script:fake }
        }
        Assert-ManualIisBootstrapStopped $c
        Assert-True (& $module { $script:fake.Disposed })
        & $module { $script:fake.Disposed = $false; $script:fake.Sites.ViralDNA.State = 'Started' }
        Assert-Throws { Assert-ManualIisBootstrapStopped $c } 'Stop ONLY'
        Assert-True (& $module { $script:fake.Disposed })
        & $module { $script:fake.Sites.Clear() }
        Assert-Throws { Assert-ManualIisBootstrapStopped $c } 'not found'
    }
    foreach ($scenario in @('ok', 'uninitialized', 'wrong-release', 'tls-failure', 'redirect')) {
        Case "read-only public check: $scenario" {
            $c = Config
            $id = '20260910-123456-0123456789-abcdef01'
            Write-AtomicJson (Join-Path $c.DeploymentRoot 'active.json') @{ SchemaVersion = 1; Id = $id; Path = (Join-Path $c.DeploymentRoot ('releases\' + $id)) }
            $module = Get-Module Deploy.Core
            & $module {
                param($Scenario, $Id)
                $script:scenario = $Scenario; $script:release = $Id
                function script:Invoke-WebRequest {
                    param($Uri, $MaximumRedirection, $TimeoutSec, [switch]$UseBasicParsing)
                    if ($MaximumRedirection -ne 0 -or $TimeoutSec -ne 10 -or $Uri -notlike 'https://viraldnastudio.com/*') { throw 'Invalid request options' }
                    if ($script:scenario -eq 'tls-failure') { throw 'TLS certificate failure' }
                    $auth = @{ auth_mode = 'password'; initialized = ($script:scenario -ne 'uninitialized') } | ConvertTo-Json
                    return [pscustomobject]@{ StatusCode = $(if ($script:scenario -eq 'redirect') { 302 } else { 200 });
                        Headers = @{ 'X-ViralDNA-Release' = $(if ($script:scenario -eq 'wrong-release') { 'other' } else { $script:release }) };
                        Content = $(if ($Uri.EndsWith('/login')) { '<html>ViralDNA</html>' } else { $auth }) }
                }
                function script:New-IisManager { throw 'FORBIDDEN IIS ACCESS' }
                function script:Start-Service { throw 'FORBIDDEN SERVICE START' }
                function script:Stop-DeployServices { throw 'FORBIDDEN SERVICE STOP' }
            } $scenario $id
            if ($scenario -eq 'ok') { Assert-True ((Test-DeployPublicEntry $c) -ceq 'https://viraldnastudio.com') }
            else { Assert-Throws { Test-DeployPublicEntry $c } 'TLS|expected release|completed local account setup' }
        }
    }
    Write-Host "$script:passed manual IIS controller tests passed. No real IIS, services or network calls."
} finally {
    Reset-Core
    $resolved = [IO.Path]::GetFullPath($testRoot)
    if ((Split-Path -Parent $resolved) -eq ([IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')) -and (Split-Path -Leaf $resolved) -match '^viraldna-manual-controller-[a-f0-9]{32}$') {
        Assert-NoReparsePoint $resolved
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

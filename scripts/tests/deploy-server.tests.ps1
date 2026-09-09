# Self-contained offline tests. No Pester, SCM mutations or network needed.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$modulePath = Join-Path $repositoryRoot 'scripts\deploy\Deploy.Core.psm1'
Import-Module $modulePath -Force -DisableNameChecking
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('viraldna-deploy-tests-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $testRoot
$script:passed = 0

function Assert-True($Value, [string]$Message = 'Assertion failed') {
    if (-not $Value) { throw $Message }
}
function Assert-Equal($Actual, $Expected) {
    if (($Actual | ConvertTo-Json -Compress -Depth 8) -cne ($Expected | ConvertTo-Json -Compress -Depth 8)) {
        throw "Expected: $Expected; actual: $Actual"
    }
}
function Assert-Throws([scriptblock]$Block, [string]$Pattern = '.') {
    try { & $Block } catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw "Unexpected error: $($_.Exception.Message)" }
        return
    }
    throw 'Expected an error, but the operation succeeded.'
}
function Test-Case([string]$Name, [scriptblock]$Body) {
    & $Body
    $script:passed++
    Write-Host "PASS $Name"
}
function New-TestConfig {
    $value = Read-JsonFile (Join-Path $repositoryRoot 'scripts\deploy\config.example.json')
    $value.RepositoryRoot = Join-Path $testRoot 'source with spaces'
    $value.DeploymentRoot = Join-Path $testRoot 'runtime with spaces'
    $value.EnvFile = Join-Path $testRoot 'private\api.env'
    return $value
}
function Validate-TestConfig($Value) {
    $file = Join-Path $testRoot 'config.json'
    Write-AtomicJson $file $Value
    return Read-DeployConfig $file
}
function Reset-Module { Import-Module $modulePath -Force -DisableNameChecking }

try {
    foreach ($selected in @('update', 'build', 'start', 'stop')) {
        Test-Case "workflow order: $selected" {
            $trace = New-Object 'Collections.Generic.List[string]'
            $steps = @{}
            foreach ($step in @('Preflight', 'Stop', 'Update', 'Build', 'Configure', 'Start')) {
                $steps[$step] = { $trace.Add($step) }.GetNewClosure()
            }
            Invoke-DeployWorkflow $selected $steps
            $expected = switch ($selected) {
                'update' { @('Preflight', 'Stop', 'Update', 'Build', 'Configure', 'Start') }
                'build' { @('Preflight', 'Stop', 'Build', 'Configure', 'Start') }
                'start' { @('Preflight', 'Stop', 'Configure', 'Start') }
                'stop' { @('Preflight', 'Stop') }
            }
            Assert-Equal @($trace.ToArray()) $expected
        }
    }
    foreach ($failedStep in @('Preflight', 'Stop', 'Update', 'Build', 'Configure', 'Start')) {
        Test-Case "failure short-circuits after $failedStep" {
            $trace = New-Object 'Collections.Generic.List[string]'
            $steps = @{}
            foreach ($step in @('Preflight', 'Stop', 'Update', 'Build', 'Configure', 'Start')) {
                $steps[$step] = { $trace.Add($step); if ($step -eq $failedStep) { throw "failed $step" } }.GetNewClosure()
            }
            Assert-Throws { Invoke-DeployWorkflow 'update' $steps } 'failed'
            Assert-Equal $trace[$trace.Count - 1] $failedStep
        }
    }
    Test-Case 'relative paths and broad roots are rejected' {
        Assert-Throws { Get-FullPath '..\outside' } 'absolute'
        $c = New-TestConfig; $c.DeploymentRoot = 'D:\'
        Assert-Throws { Validate-TestConfig $c } 'dedicated'
    }
    Test-Case 'path boundaries distinguish sibling prefixes' {
        Assert-True (Test-PathWithin 'D:\release\a' 'D:\release')
        Assert-True (-not (Test-PathWithin 'D:\release-other\a' 'D:\release'))
        Assert-True (-not (Test-PathWithin 'D:\release\..\other' 'D:\release'))
    }
    Test-Case 'source and runtime must not overlap' {
        $c = New-TestConfig; $c.DeploymentRoot = Join-Path $c.RepositoryRoot 'runtime'
        Assert-Throws { Validate-TestConfig $c } 'non-nested'
    }
    Test-Case 'private env cannot live in a release or source tree' {
        $c = New-TestConfig; $c.EnvFile = Join-Path $c.RepositoryRoot '.env.local'
        Assert-Throws { Validate-TestConfig $c } 'EnvFile'
    }
    Test-Case 'public HTTP and implicit HTTPS are refused' {
        $c = New-TestConfig; $c.SiteUrl = 'http://video.example.com'
        Assert-Throws { Validate-TestConfig $c } 'HTTPS'
        $c.SiteUrl = 'https://video.example.com'
        Assert-Throws { Validate-TestConfig $c } 'AllowPublicAccess'
        $c.AllowPublicAccess = $true
        $null = Validate-TestConfig $c
    }
    Test-Case 'URL injection and port conflicts are rejected' {
        $c = New-TestConfig; $c.SiteUrl = 'http://127.0.0.1:8080/path'
        Assert-Throws { Validate-TestConfig $c } 'SiteUrl'
        $c = New-TestConfig; $c.ProbePort = $c.ApiPort
        Assert-Throws { Validate-TestConfig $c } 'distinct'
    }
    Test-Case 'default system service identities are refused' {
        $c = New-TestConfig; $c.ServiceAccount = 'NT AUTHORITY\SYSTEM'
        Assert-Throws { Validate-TestConfig $c } 'service account'
    }
    Test-Case 'env validation protects authentication and persistent data' {
        $c = New-TestConfig
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $c.EnvFile) -Force
        $contents = [IO.File]::ReadAllText((Join-Path $repositoryRoot 'scripts\deploy\templates\api.env.example'))
        Write-AtomicText $c.EnvFile $contents
        $null = Read-ProductionEnv $c
        Write-AtomicText $c.EnvFile ($contents.Replace('VIRAL_DNA_AUTH_MODE=password', 'VIRAL_DNA_AUTH_MODE=local_bootstrap'))
        Assert-Throws { Read-ProductionEnv $c } 'password'
        Write-AtomicText $c.EnvFile ($contents.Replace('D:\ViralDNA\data\accounts.sqlite3', (Join-Path $c.RepositoryRoot 'accounts.sqlite3')))
        Assert-Throws { Read-ProductionEnv $c } 'persistent'
        Write-AtomicText $c.EnvFile $contents
    }
    Test-Case 'exclusive lock is released without deleting state' {
        $c = New-TestConfig
        $null = New-Item -ItemType Directory -Path $c.DeploymentRoot -Force
        $lock = Open-DeployLock $c
        try { Assert-Throws { Open-DeployLock $c } 'Another deployment' } finally { $lock.Dispose() }
        $again = Open-DeployLock $c; $again.Dispose()
        Assert-True (Test-Path -LiteralPath (Join-Path $c.DeploymentRoot 'deploy.lock'))
    }
    Test-Case 'atomic JSON replacement keeps valid content' {
        $file = Join-Path $testRoot 'state.json'
        Write-AtomicJson $file @{ value = 1 }
        Write-AtomicJson $file @{ value = 2 }
        Assert-Equal (Read-JsonFile $file).value 2
    }
    Test-Case 'missing or escaped release cannot start' {
        $c = New-TestConfig
        Assert-Throws { Get-LastDeployRelease $c } 'No successful build'
        Write-AtomicJson (Join-Path $c.DeploymentRoot 'last-build.json') @{ SchemaVersion = 1; Id = '../outside'; Path = 'D:\outside' }
        Assert-Throws { Get-LastDeployRelease $c } 'Invalid release'
    }
    Test-Case 'templates escape XML and keep loopback control ports' {
        $c = New-TestConfig
        $release = [pscustomobject]@{ Id = '20260909-120000-0123456789-01234567'; Path = (Join-Path $c.DeploymentRoot 'releases\test & release') }
        $xml = [xml](Get-DeployServiceXml $c $release 'api')
        Assert-True ($xml.service.executable -like '*test & release*')
        Assert-True ($xml.service.arguments -match 'api-host.py')
        Assert-True (-not ($xml.OuterXml -match 'password|--reload'))
        $caddy = Get-CaddyConfig $c $release
        Assert-True ($caddy -match 'admin 127.0.0.1:12019')
        Assert-True ($caddy -match 'bind 127.0.0.1')
        Assert-True ($caddy -match 'handle /api/\*' -and $caddy -notmatch 'handle_path')
        Assert-True ($caddy -match 'handle @static' -and $caddy -match 'flush_interval -1')
    }
    Test-Case 'native argv survives spaces quotes backslashes and shell characters' {
        $exe = (Get-Command python.exe -ErrorAction Stop).Source
        $arguments = @('', 'space value', 'a"b', 'D:\trailing\', 'x&y', '$(not-executed)', '%NO_EXPANSION%')
        $result = Invoke-DeployProcess $exe (@('-c', 'import json,sys; print(json.dumps(sys.argv[1:]))') + $arguments) $testRoot -Quiet
        Assert-Equal ($result.Output | ConvertFrom-Json) $arguments
        Assert-Throws { Invoke-DeployProcess $exe @('-c', 'raise SystemExit(7)') $testRoot -Quiet } 'exit 7'
    }
    Test-Case 'port collision never terminates the other process' {
        $module = Get-Module Deploy.Core
        & $module {
            function script:Get-DeployService { return $null }
            function script:Get-NetTCPConnection { return [pscustomobject]@{ LocalPort = 8000; OwningProcess = 1234 } }
        }
        Assert-Throws { Assert-DeployPorts (New-TestConfig) } 'unmanaged'
        Reset-Module
    }
    Test-Case 'PID parent reuse is not treated as service ownership' {
        $module = Get-Module Deploy.Core
        & $module {
            function script:Get-CimInstance {
                param($ClassName, $Filter)
                if ($Filter -eq 'ProcessId=22') { return [pscustomobject]@{ ProcessId = 22; ParentProcessId = 11; CreationDate = [DateTime]'2026-01-01' } }
                if ($Filter -eq 'ProcessId=11') { return [pscustomobject]@{ ProcessId = 11; ParentProcessId = 1; CreationDate = [DateTime]'2026-01-02' } }
            }
        }
        Assert-True (-not (Test-DescendantProcess 22 11))
        Reset-Module
    }
    Test-Case 'already-stopped services are idempotent and disabled for reboot' {
        $module = Get-Module Deploy.Core
        & $module {
            $script:stopped = New-Object 'Collections.Generic.List[string]'
            function script:Get-DeployService { param($Config, $Role) return [pscustomobject]@{ Name = $Role; State = 'Stopped' } }
            function script:Assert-ManagedService { }
            function script:Assert-DeployPorts { }
            function script:Set-Service { param($Name, $StartupType) $script:stopped.Add("${Name}:$StartupType") }
        }
        Stop-DeployServices (New-TestConfig)
        $values = & $module { $script:stopped.ToArray() }
        Assert-Equal $values @('web:Manual', 'api:Manual')
        Reset-Module
    }
    Test-Case 'Git uses main SSH and fast-forward without push or reset' {
        $c = New-TestConfig
        $null = New-Item -ItemType Directory -Path (Join-Path $c.RepositoryRoot '.git') -Force
        $module = Get-Module Deploy.Core
        & $module {
            $script:gitCalls = New-Object 'Collections.Generic.List[string]'
            function script:Assert-Repository { }
            function script:Invoke-DeployGit {
                param($Config, $Arguments, [switch]$AllowFailure)
                $script:gitCalls.Add(($Arguments -join ' '))
                return [pscustomobject]@{ Code = 0; Output = ''; Error = '' }
            }
        }
        Update-DeployRepository $c
        $calls = & $module { $script:gitCalls.ToArray() }
        Assert-Equal $calls @('fetch --no-tags origin main', 'merge-base --is-ancestor HEAD FETCH_HEAD', 'merge --ff-only FETCH_HEAD')
        Reset-Module
    }
    Test-Case 'diverged main is not merged or reset' {
        $module = Get-Module Deploy.Core
        & $module {
            function script:Assert-Repository { }
            function script:Invoke-DeployGit {
                param($Config, $Arguments, [switch]$AllowFailure)
                if ($Arguments[0] -eq 'merge') { throw 'Merge must not run' }
                return [pscustomobject]@{ Code = $(if ($Arguments[0] -eq 'merge-base') { 1 } else { 0 }); Output = ''; Error = '' }
            }
        }
        Assert-Throws { Update-DeployRepository (New-TestConfig) } 'diverged'
        Reset-Module
    }
    Test-Case 'release snapshot isolates local changes and excludes private configuration' {
        $c = New-TestConfig
        foreach ($file in @('package-lock.json', 'services\api\pyproject.toml', 'scripts\deploy\api-host.py', 'untracked.txt', '.env.local')) {
            $selected = Join-Path $c.RepositoryRoot $file
            $null = New-Item -ItemType Directory -Path (Split-Path -Parent $selected) -Force
            Write-AtomicText $selected 'fixture'
        }
        $module = Get-Module Deploy.Core
        & $module {
            function script:Assert-Repository { }
            function script:Invoke-DeployGit {
                param($Config, $Arguments)
                $output = switch ($Arguments[0]) {
                    'rev-parse' { '0123456789012345678901234567890123456789' }
                    'status' { ' M untracked.txt' }
                    'ls-files' { (@('package-lock.json', 'services/api/pyproject.toml', 'scripts/deploy/api-host.py', 'untracked.txt', '.env.local', 'deleted.txt') -join [char]0) + [char]0 }
                }
                return [pscustomobject]@{ Code = 0; Output = $output; Error = '' }
            }
            function script:Invoke-DeployProcess {
                param($Executable, $Arguments, $WorkingDirectory, $Environment, [switch]$AllowFailure, [switch]$Quiet)
                if ($Arguments -contains 'build:web') {
                    $web = Join-Path $WorkingDirectory 'apps\web\dist\client'
                    $null = New-Item -ItemType Directory -Path $web -Force
                    Write-AtomicText (Join-Path $web 'index.html') 'ViralDNA'
                }
                if ($Arguments -contains 'venv') {
                    $venv = Join-Path $WorkingDirectory '.venv\Scripts'
                    $null = New-Item -ItemType Directory -Path $venv -Force
                    Write-AtomicText (Join-Path $venv 'python.exe') 'fixture, never executed'
                }
                return [pscustomobject]@{ Code = 0; Output = 'fixture==1'; Error = '' }
            }
        }
        $release = New-DeployRelease $c
        Assert-True (Test-Path -LiteralPath (Join-Path $release.Path 'untracked.txt'))
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $release.Path '.env.local')))
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $release.Path 'deleted.txt')))
        Assert-True $release.Dirty
        Assert-Equal (Get-LastDeployRelease $c).Id $release.Id
        Write-AtomicText (Join-Path $c.RepositoryRoot 'untracked.txt') 'modified after build'
        Assert-Equal ([IO.File]::ReadAllText((Join-Path $release.Path 'untracked.txt'))) 'fixture'
        # Keep these mocks for the next failure test; no actual build tools run.
    }
    Test-Case 'failed build preserves the previous successful release and its files' {
        $c = New-TestConfig
        $previous = Get-LastDeployRelease $c
        $module = Get-Module Deploy.Core
        & $module {
            function script:Invoke-DeployProcess { throw 'simulated npm failure' }
        }
        Assert-Throws { New-DeployRelease $c } 'simulated npm failure'
        Assert-Equal (Get-LastDeployRelease $c).Id $previous.Id
        Assert-True (Test-Path -LiteralPath (Join-Path $previous.Path 'apps\web\dist\client\index.html'))
        Reset-Module
    }
    Test-Case 'web health failure triggers scoped cleanup and never marks a release active' {
        $c = New-TestConfig
        $release = Get-LastDeployRelease $c
        $module = Get-Module Deploy.Core
        & $module {
            $script:startupCalls = New-Object 'Collections.Generic.List[string]'
            function script:Assert-DeployPorts { }
            function script:Assert-RunningDeployInstance { }
            function script:Start-Service { param($Name) $script:startupCalls.Add($Name) }
            function script:Wait-DeployHttp {
                param($Url, $Timeout, $Validate)
                if ($Url -match '/login$') { throw 'simulated web health failure' }
            }
            function script:Invoke-RestMethod { return [pscustomobject]@{ auth_mode = 'password'; initialized = $true } }
            function script:Stop-DeployServices { $script:startupCalls.Add('cleanup') }
            function script:Set-Service { throw 'Automatic startup must not be enabled on failure' }
        }
        Assert-Throws { Start-DeployServices $c $release } 'simulated web health failure'
        Assert-Equal (& $module { $script:startupCalls.ToArray() }) @('ViralDNA-Production-api', 'ViralDNA-Production-web', 'cleanup')
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $c.DeploymentRoot 'active.json')))
        Reset-Module
    }
    Test-Case 'uninitialized accounts cannot be exposed on a public site' {
        $c = New-TestConfig; $c.SiteUrl = 'https://video.example.com'; $c.AllowPublicAccess = $true
        $release = Get-LastDeployRelease $c
        $module = Get-Module Deploy.Core
        & $module {
            function script:Assert-DeployPorts { }
            function script:Assert-RunningDeployInstance { }
            function script:Start-Service { param($Name) if ($Name -match '-web$') { throw 'Web must not start' } }
            function script:Wait-DeployHttp { }
            function script:Invoke-RestMethod { return [pscustomobject]@{ auth_mode = 'password'; initialized = $false } }
            function script:Stop-DeployServices { }
        }
        Assert-Throws { Start-DeployServices $c $release } 'Public startup refused'
        Reset-Module
    }
    Test-Case 'API state refuses PID reuse even when the parent chain looks valid' {
        $c = New-TestConfig
        $null = New-Item -ItemType Directory -Path (Join-Path $c.DeploymentRoot 'control') -Force
        $release = Get-LastDeployRelease $c
        Write-AtomicJson (Join-Path $c.DeploymentRoot 'control\api-state.json') @{
            pid = 22; startedAt = '2026-01-01T00:00:00Z'; token = ('a' * 32); releaseId = $release.Id
        }
        $module = Get-Module Deploy.Core
        & $module {
            function script:Test-DescendantProcess { return $true }
            function script:Get-CimInstance { return [pscustomobject]@{ CreationDate = [DateTime]'2026-01-02T00:00:00Z'; CommandLine = 'unused' } }
        }
        Assert-Throws { Get-VerifiedApiState $c ([pscustomobject]@{ ProcessId = 11 }) $release.Id } 'start-time'
        Reset-Module
    }
    Test-Case 'healthy-looking endpoint from a sibling process is not accepted as the API' {
        $module = Get-Module Deploy.Core
        & $module {
            function script:Get-DeployService { return [pscustomobject]@{ State = 'Running'; ProcessId = 11 } }
            function script:Assert-ManagedService { }
            function script:Get-VerifiedApiState { return [pscustomobject]@{ pid = 22 } }
            function script:Get-NetTCPConnection { return [pscustomobject]@{ OwningProcess = 33 } }
            function script:Test-DescendantProcess { return $true }
        }
        $c = New-TestConfig
        Assert-Throws { Assert-RunningDeployInstance $c (Get-LastDeployRelease $c) 'api' } 'another process'
        Reset-Module
    }
    Test-Case 'a colliding Windows service name does not authorize stopping it' {
        $module = Get-Module Deploy.Core
        & $module { function script:Assert-DeployOwner { } }
        Assert-Throws {
            Assert-ManagedService (New-TestConfig) 'api' ([pscustomobject]@{ Name = 'ViralDNA-Production-api'; PathName = '"D:\another-service.exe"' })
        } 'collision'
        Reset-Module
    }
    Write-Host "$script:passed deployment tests passed. No services were registered, stopped or started; no network calls were made."
} finally {
    # Delete only the unique test-owned temporary directory after absolute-path,
    # name and reparse-point checks. Never operate on the repository or data roots.
    $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
    $temporaryParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    if ((Split-Path -Parent $resolvedTestRoot) -eq $temporaryParent -and
        (Split-Path -Leaf $resolvedTestRoot) -match '^viraldna-deploy-tests-[a-f0-9]{32}$') {
        Assert-NoReparsePoint $resolvedTestRoot
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}

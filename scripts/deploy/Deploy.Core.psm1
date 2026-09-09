# Requires Windows PowerShell 5.1. Importing this module never starts services.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Remote = 'git@github.com:wojimmy666-code/viral-dna.git'
$script:LogPath = $null
$script:Templates = Join-Path $PSScriptRoot 'templates'

function Write-DeployLog([string]$Message) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    if ($script:LogPath) { [IO.File]::AppendAllText($script:LogPath, $line + "`r`n", [Text.Encoding]::UTF8) }
}

function Set-DeployLog([string]$Path) { $script:LogPath = $Path }

function Get-FullPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path) -or $Path -notmatch '^[A-Za-z]:[\\/]') {
        throw "A local absolute drive path is required: $Path"
    }
    if ($Path -match '[\x00-\x1f"%]' -or $Path.Substring(2).Contains(':')) {
        throw "Unsupported characters in path: $Path"
    }
    $full = [IO.Path]::GetFullPath($Path)
    if ($full.Length -le 3) { return $full }
    return $full.TrimEnd('\', '/')
}

function Test-PathWithin([string]$Path, [string]$Root) {
    $selected = Get-FullPath $Path
    $parent = Get-FullPath $Root
    return $selected.Equals($parent, [StringComparison]::OrdinalIgnoreCase) -or
        $selected.StartsWith($parent + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoReparsePoint([string]$Path) {
    $selected = Get-FullPath $Path
    while ($selected) {
        if (Test-Path -LiteralPath $selected) {
            $item = Get-Item -LiteralPath $selected -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Junctions/symlinks are not allowed in deployment paths: $selected"
            }
        }
        $selected = Split-Path -Parent $selected
    }
}

function Read-JsonFile([string]$Path) {
    return ([IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json)
}

function Write-AtomicText([string]$Path, [string]$Content) {
    $temporary = $Path + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::WriteAllText($temporary, $Content, (New-Object Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $Path) {
        [IO.File]::Replace($temporary, $Path, [NullString]::Value)
    } else {
        [IO.File]::Move($temporary, $Path)
    }
}

function Write-AtomicJson([string]$Path, $Value) {
    Write-AtomicText $Path ($Value | ConvertTo-Json -Depth 12)
}

function Read-DeployConfig([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Deployment config not found: $Path. Copy scripts/deploy/config.example.json and configure it first."
    }
    $c = Read-JsonFile $Path
    if ($c.SchemaVersion -ne 1) { throw 'Unsupported deployment config schema.' }
    foreach ($key in @('RepositoryRoot', 'DeploymentRoot', 'EnvFile')) {
        $c.$key = Get-FullPath $c.$key
        Assert-NoReparsePoint $c.$key
    }
    foreach ($root in @($c.RepositoryRoot, $c.DeploymentRoot)) {
        if ($root.Length -lt 4 -or $root -eq $env:USERPROFILE -or $root -eq $env:WINDIR -or $root -eq $env:ProgramData) {
            throw 'Use a dedicated deployment directory, not a drive, user, or system root.'
        }
    }
    if ((Test-PathWithin $c.DeploymentRoot $c.RepositoryRoot) -or
        (Test-PathWithin $c.RepositoryRoot $c.DeploymentRoot)) {
        throw 'RepositoryRoot and DeploymentRoot must be separate, non-nested directories.'
    }
    if ((Test-PathWithin $c.EnvFile $c.RepositoryRoot) -or
        (Test-PathWithin $c.EnvFile (Join-Path $c.DeploymentRoot 'releases'))) {
        throw 'EnvFile must stay outside source code and release directories.'
    }
    if ($c.ServicePrefix -notmatch '^[A-Za-z][A-Za-z0-9-]{2,48}$') { throw 'Invalid ServicePrefix.' }
    if ($c.ServiceAccount -notmatch '^[^\s\\]+\\[^\s\\]+$' -or
        $c.ServiceAccount -match '(?i)^(NT AUTHORITY|NT SERVICE)\\|LocalSystem') {
        throw 'Configure a dedicated local/domain service account, not a built-in system account.'
    }
    $site = [Uri]$c.SiteUrl
    if (-not $site.IsAbsoluteUri -or $site.UserInfo -or $site.Query -or $site.Fragment -or
        $site.AbsolutePath -ne '/' -or $site.Host -notmatch '^[a-zA-Z0-9.-]+$') { throw 'Invalid SiteUrl.' }
    if ($c.AllowPublicAccess -isnot [bool] -or $c.LocalAI -isnot [bool]) { throw 'Use JSON booleans for AllowPublicAccess/LocalAI.' }
    if ($site.IsLoopback) {
        if ($site.Scheme -ne 'http' -or $site.Host -notin @('127.0.0.1', 'localhost')) { throw 'Local setup uses http://127.0.0.1:<port>.' }
    } elseif ($site.Scheme -ne 'https' -or -not $c.AllowPublicAccess -or $site.Port -ne 443) {
        throw 'Public access requires HTTPS on port 443 and AllowPublicAccess=true after local account setup.'
    }
    $ports = @($c.ApiPort, $c.ProbePort, $c.CaddyAdminPort, $site.Port)
    foreach ($port in $ports) {
        if ($port -isnot [int] -or $port -lt 1 -or $port -gt 65535) { throw 'Invalid TCP port.' }
    }
    if (@($ports | Select-Object -Unique).Count -ne $ports.Count -or
        (@($c.ApiPort, $c.ProbePort, $c.CaddyAdminPort) -contains 80)) { throw 'Deployment ports must be distinct; port 80 is reserved for HTTPS.' }
    foreach ($key in @('StopTimeoutSeconds', 'HealthTimeoutSeconds')) {
        if ($c.$key -isnot [int] -or $c.$key -lt 10 -or $c.$key -gt 1800) { throw "Invalid $key (10-1800 seconds)." }
    }
    foreach ($key in @('Git', 'Node', 'Npm', 'Python', 'FFmpeg', 'FFprobe', 'Caddy', 'WinSW')) {
        $c.Tools.$key = Get-FullPath $c.Tools.$key
    }
    return $c
}

function Read-ProductionEnv($Config) {
    if (-not (Test-Path -LiteralPath $Config.EnvFile -PathType Leaf)) { throw 'Create the private API env file from templates/api.env.example first.' }
    $values = @{}
    foreach ($line in [IO.File]::ReadAllLines($Config.EnvFile, [Text.Encoding]::UTF8)) {
        if ($line.TrimStart().StartsWith('#') -or $line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') { continue }
        $key = $Matches[1]; $value = $Matches[2].Trim()
        if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'")))) { $value = $value.Substring(1, $value.Length - 2) }
        $values[$key] = $value
    }
    if ($values['VIRAL_DNA_AUTH_MODE'] -cne 'password') { throw 'Production requires VIRAL_DNA_AUTH_MODE=password.' }
    foreach ($key in @('VIRAL_DNA_ACCOUNT_CATALOG_PATH', 'VIRAL_DNA_AUTH_DB_PATH', 'VIRAL_DNA_ACCOUNTS_ROOT',
        'VIRAL_DNA_WORKSPACE_ROOT', 'VIRAL_DNA_PLATFORM_SECRET_ROOT')) {
        $path = Get-FullPath $values[$key]
        Assert-NoReparsePoint $path
        if ((Test-PathWithin $path $Config.RepositoryRoot) -or (Test-PathWithin $path $Config.DeploymentRoot)) {
            throw "$key must point to persistent business data outside source/deployment directories."
        }
        if ($path.Length -lt 4) { throw "$key cannot use a drive root." }
    }
    $origins = @(([string]$values['VIRAL_DNA_CORS_ORIGINS']).Split(',') | ForEach-Object { $_.Trim().TrimEnd('/') })
    if ($origins -contains '*' -or $origins -notcontains $Config.SiteUrl.TrimEnd('/') -or
        $origins -notcontains "http://127.0.0.1:$($Config.ProbePort)") {
        throw 'CORS_ORIGINS must include the exact SiteUrl and local probe origin, never a wildcard.'
    }
    return $values
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run deploy-server.bat as Administrator to manage these Windows services.'
    }
}

function Get-ServiceAccountSid($Config) {
    $name = $Config.ServiceAccount -replace '^\.\\', ($env:COMPUTERNAME + '\')
    return (New-Object Security.Principal.NTAccount($name)).Translate([Security.Principal.SecurityIdentifier]).Value
}

function Quote-NativeArgument([string]$Value) {
    return '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}

function Invoke-DeployProcess {
    param([string]$Executable, [string[]]$Arguments = @(), [string]$WorkingDirectory,
        [hashtable]$Environment = @{}, [switch]$AllowFailure, [switch]$Quiet)
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.Arguments = ($Arguments | ForEach-Object { Quote-NativeArgument $_ }) -join ' '
    $info.WorkingDirectory = $WorkingDirectory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = [Text.Encoding]::UTF8
    $info.StandardErrorEncoding = [Text.Encoding]::UTF8
    foreach ($key in $Environment.Keys) {
        if ($null -eq $Environment[$key]) { $info.EnvironmentVariables.Remove($key) }
        else { $info.EnvironmentVariables[$key] = [string]$Environment[$key] }
    }
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    try {
        if (-not $process.Start()) { throw "Failed to start $Executable" }
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $elapsedSeconds = 0
        while (-not $process.WaitForExit(1000)) {
            $elapsedSeconds++
            if (-not $Quiet -and $elapsedSeconds % 15 -eq 0) {
                Write-DeployLog "$([IO.Path]::GetFileName($Executable)) is still running ($elapsedSeconds seconds)..."
            }
        }
        $output = $stdout.GetAwaiter().GetResult()
        $errorText = $stderr.GetAwaiter().GetResult()
        $result = [pscustomobject]@{ Code = $process.ExitCode; Output = $output; Error = $errorText }
        if (-not $Quiet -and ($output -or $errorText)) {
            Write-DeployLog (($output + $errorText).Trim())
        }
        if (-not $AllowFailure -and $result.Code -ne 0) {
            throw "Command failed: $([IO.Path]::GetFileName($Executable)) (exit $($result.Code)). $errorText"
        }
        return $result
    } finally { $process.Dispose() }
}

function Invoke-DeployGit($Config, [string[]]$Arguments, [switch]$AllowFailure) {
    $gitArgs = @('-c', 'core.quotepath=false', '-c', 'protocol.allow=never', '-c', 'protocol.ssh.allow=always',
        '-c', 'core.sshCommand=ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=15') + $Arguments
    $cwd = if (Test-Path -LiteralPath $Config.RepositoryRoot) { $Config.RepositoryRoot } else { Split-Path -Parent $Config.EnvFile }
    return Invoke-DeployProcess $Config.Tools.Git $gitArgs $cwd -Environment @{
        GIT_TERMINAL_PROMPT = '0'; GIT_SSH_COMMAND = $null; GIT_SSH = $null
        GIT_DIR = $null; GIT_WORK_TREE = $null; GIT_INDEX_FILE = $null
    } -AllowFailure:$AllowFailure -Quiet
}

function Assert-Repository($Config, [switch]$Clean, [switch]$AllowMissing) {
    if (-not (Test-Path -LiteralPath (Join-Path $Config.RepositoryRoot '.git'))) {
        if ($AllowMissing -and (-not (Test-Path -LiteralPath $Config.RepositoryRoot) -or
            @(Get-ChildItem -LiteralPath $Config.RepositoryRoot -Force).Count -eq 0)) { return }
        throw 'Repository is missing or target is not an empty clone directory.'
    }
    $top = (Invoke-DeployGit $Config @('rev-parse', '--show-toplevel')).Output.Trim()
    if ((Get-FullPath $top) -ne $Config.RepositoryRoot) { throw 'RepositoryRoot must be the Git repository root.' }
    $branch = (Invoke-DeployGit $Config @('symbolic-ref', '--short', 'HEAD')).Output.Trim()
    if ($branch -ne 'main') { throw 'Deployment uses main only; no branch switching is performed.' }
    foreach ($remoteArguments in @(@('remote', 'get-url', '--all', 'origin'), @('remote', 'get-url', '--push', '--all', 'origin'))) {
        if ((Invoke-DeployGit $Config $remoteArguments).Output.Trim() -cne $script:Remote) { throw 'origin must use the approved SSH URL for fetch and push.' }
    }
    if ($Clean -and (Invoke-DeployGit $Config @('status', '--porcelain')).Output.Trim()) {
        throw 'Uncommitted/untracked changes found. Update refused; nothing will be overwritten or stashed.'
    }
    if ((Invoke-DeployGit $Config @('ls-files', '--unmerged')).Output.Trim()) { throw 'Resolve merge conflicts before building.' }
}

function Update-DeployRepository($Config) {
    Assert-Repository $Config -Clean -AllowMissing
    if (-not (Test-Path -LiteralPath (Join-Path $Config.RepositoryRoot '.git'))) {
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $Config.RepositoryRoot) -Force
        $null = Invoke-DeployGit $Config @('clone', '--branch', 'main', '--single-branch', $script:Remote, $Config.RepositoryRoot)
    } else {
        $null = Invoke-DeployGit $Config @('fetch', '--no-tags', 'origin', 'main')
        $ancestor = Invoke-DeployGit $Config @('merge-base', '--is-ancestor', 'HEAD', 'FETCH_HEAD') -AllowFailure
        if ($ancestor.Code -ne 0) { throw 'Local main is ahead/diverged from GitHub main; fast-forward update refused.' }
        $null = Invoke-DeployGit $Config @('merge', '--ff-only', 'FETCH_HEAD')
    }
    Assert-Repository $Config -Clean
}

function Expand-DeployTemplate([string]$Name, [hashtable]$Values, [switch]$Xml) {
    $content = [IO.File]::ReadAllText((Join-Path $script:Templates $Name), [Text.Encoding]::UTF8)
    foreach ($key in $Values.Keys) {
        $value = [string]$Values[$key]
        if ($Xml) { $value = [Security.SecurityElement]::Escape($value) }
        $content = $content.Replace('@@' + $key + '@@', $value)
    }
    if ($content -match '@@[A-Z_]+@@') { throw "Unresolved template field in $Name" }
    if ($Xml) { $null = [xml]$content }
    return $content
}

function Get-CaddyConfig($Config, $Release) {
    $root = $Config.DeploymentRoot
    $site = [Uri]$Config.SiteUrl
    return Expand-DeployTemplate 'Caddyfile.template' @{
        ADMIN_PORT = $Config.CaddyAdminPort; API_PORT = $Config.ApiPort; PROBE_PORT = $Config.ProbePort
        CADDY_DATA = (Join-Path $root 'caddy\data').Replace('\', '/')
        WEB_ROOT = (Join-Path $Release.Path 'apps\web\dist\client').Replace('\', '/')
        RELEASE_ID = $Release.Id; SITE_URL = $Config.SiteUrl.TrimEnd('/')
        SITE_BIND = $(if ($site.IsLoopback) { 'bind 127.0.0.1' } else { '# Public HTTPS explicitly enabled.' })
    }
}

function New-DeployRelease($Config) {
    Assert-Repository $Config
    $commit = (Invoke-DeployGit $Config @('rev-parse', 'HEAD')).Output.Trim()
    $dirty = [bool](Invoke-DeployGit $Config @('status', '--porcelain')).Output.Trim()
    $id = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $commit.Substring(0, 10) + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
    $releaseRoot = Join-Path $Config.DeploymentRoot ('releases\' + $id)
    $null = New-Item -ItemType Directory -Path $releaseRoot
    $files = (Invoke-DeployGit $Config @('ls-files', '--cached', '--others', '--exclude-standard', '-z')).Output.Split([char]0)
    foreach ($relative in ($files | Where-Object { $_ } | Select-Object -Unique)) {
        if ($relative -match '(^|/)(\.git|node_modules|\.venv[^/]*|__pycache__|storage|uploads|tmp|\.tmp|tools)(/|$)' -or
            $relative -match '(^|/)\.env(?!\.example$)' -or $relative -match '\.local\.(json|ya?ml)$') { continue }
        $source = Get-FullPath (Join-Path $Config.RepositoryRoot $relative)
        $target = Get-FullPath (Join-Path $releaseRoot $relative)
        if (-not (Test-PathWithin $source $Config.RepositoryRoot) -or -not (Test-PathWithin $target $releaseRoot)) { throw 'Source entry escaped snapshot roots.' }
        # A deliberately deleted tracked file stays deleted in a local build.
        if (-not (Test-Path -LiteralPath $source)) { continue }
        Assert-NoReparsePoint $source
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Submodules/directories require explicit deployment support: $relative" }
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force
        Copy-Item -LiteralPath $source -Destination $target
    }
    foreach ($required in @('package-lock.json', 'services\api\pyproject.toml', 'scripts\deploy\api-host.py')) {
        if (-not (Test-Path -LiteralPath (Join-Path $releaseRoot $required))) { throw "Incomplete source snapshot: $required" }
    }
    Write-DeployLog "Building isolated release $id (local changes: $dirty)."
    $buildEnv = @{ VITE_API_BASE_URL = '/api/v1'; NODE_ENV = 'production'; PYTHONUTF8 = '1';
        PATH = (Split-Path -Parent $Config.Tools.Node) + ';' + $env:PATH }
    $null = Invoke-DeployProcess $Config.Tools.Node @($Config.Tools.Npm, 'ci', '--include=dev', '--no-audit', '--no-fund') $releaseRoot -Environment $buildEnv
    $null = Invoke-DeployProcess $Config.Tools.Node @($Config.Tools.Npm, 'run', 'build:web') $releaseRoot -Environment $buildEnv
    $null = Invoke-DeployProcess $Config.Tools.Python @('-m', 'venv', (Join-Path $releaseRoot '.venv')) $releaseRoot
    $python = Join-Path $releaseRoot '.venv\Scripts\python.exe'
    $api = Join-Path $releaseRoot 'services\api'
    if ($Config.LocalAI) { $api += '[local-ai]' }
    $null = Invoke-DeployProcess $python @('-m', 'pip', 'install', '-e', $api) $releaseRoot
    $null = Invoke-DeployProcess $python @('-m', 'pip', 'check') $releaseRoot
    $freeze = Invoke-DeployProcess $python @('-m', 'pip', 'freeze') $releaseRoot -Quiet
    Write-AtomicText (Join-Path $releaseRoot 'python-packages.txt') $freeze.Output
    if (-not (Test-Path -LiteralPath (Join-Path $releaseRoot 'apps\web\dist\client\index.html'))) { throw 'Frontend build output is missing.' }
    $release = [pscustomobject]@{ SchemaVersion = 1; Id = $id; Path = $releaseRoot; Commit = $commit; Dirty = $dirty; BuiltAt = [DateTime]::UtcNow.ToString('o') }
    Write-AtomicJson (Join-Path $releaseRoot 'release.json') $release
    Write-AtomicJson (Join-Path $Config.DeploymentRoot 'last-build.json') $release
    return $release
}

function Get-LastDeployRelease($Config) {
    $marker = Join-Path $Config.DeploymentRoot 'last-build.json'
    if (-not (Test-Path -LiteralPath $marker)) { throw 'No successful build found. Choose option 1 or 2 first.' }
    $release = Read-JsonFile $marker
    if ($release.SchemaVersion -ne 1 -or $release.Id -notmatch '^[0-9]{8}-[0-9]{6}-[0-9a-f]{10}-[0-9a-f]{8}$' -or
        (Get-FullPath $release.Path) -ne (Join-Path $Config.DeploymentRoot ('releases\' + $release.Id))) { throw 'Invalid release manifest.' }
    Assert-NoReparsePoint $release.Path
    foreach ($required in @('release.json', '.venv\Scripts\python.exe', 'scripts\deploy\api-host.py', 'apps\web\dist\client\index.html')) {
        if (-not (Test-Path -LiteralPath (Join-Path $release.Path $required) -PathType Leaf)) { throw "Incomplete release: $required. Choose option 1 or 2." }
    }
    $stored = Read-JsonFile (Join-Path $release.Path 'release.json')
    if ($stored.Id -ne $release.Id -or $stored.Commit -ne $release.Commit) { throw 'Release metadata does not match.' }
    return $release
}

function Get-DeployServiceName($Config, [string]$Role) { return $Config.ServicePrefix + '-' + $Role }

function Get-DeployWrapperPath($Config, [string]$Role) {
    return Join-Path $Config.DeploymentRoot ('services\' + $Role + '\' + (Get-DeployServiceName $Config $Role) + '.exe')
}

function Get-DeployService($Config, [string]$Role) {
    $name = Get-DeployServiceName $Config $Role
    return Get-CimInstance Win32_Service -Filter "Name='$name'"
}

function Assert-DeployOwner($Config) {
    $path = Join-Path $Config.DeploymentRoot 'owner.json'
    if (-not (Test-Path -LiteralPath $path)) { throw 'Deployment ownership record missing; refusing to manage existing services.' }
    $owner = Read-JsonFile $path
    if ($owner.RepositoryRoot -ne $Config.RepositoryRoot -or $owner.ServicePrefix -ne $Config.ServicePrefix -or
        $owner.ServiceSid -ne (Get-ServiceAccountSid $Config)) {
        throw 'Deployment directory belongs to a different repository/service account. Do not switch DPAPI identities.'
    }
    return $owner
}

function Assert-ManagedService($Config, [string]$Role, $Service) {
    if ($null -eq $Service) { return }
    $null = Assert-DeployOwner $Config
    $expected = Get-DeployWrapperPath $Config $Role
    if ($Service.PathName -cne ('"' + $expected + '"')) { throw "Service name collision: $($Service.Name). Its executable is not this deployment's wrapper." }
    $accountName = $Service.StartName -replace '^\.\\', ($env:COMPUTERNAME + '\')
    $account = New-Object Security.Principal.NTAccount($accountName)
    if ($account.Translate([Security.Principal.SecurityIdentifier]).Value -ne (Get-ServiceAccountSid $Config)) {
        throw "Service account mismatch for $($Service.Name); refusing an implicit identity change."
    }
    if ([int]$Service.ProcessId -gt 0) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($Service.ProcessId)"
        if ($null -eq $process -or $process.ExecutablePath -ne $expected) { throw 'Running wrapper identity changed.' }
    }
}

function Test-DescendantProcess([int]$ChildId, [int]$ParentId) {
    if ($ChildId -le 0 -or $ParentId -le 0) { return $false }
    $child = Get-CimInstance Win32_Process -Filter "ProcessId=$ChildId"
    for ($depth = 0; $null -ne $child -and $depth -lt 32; $depth++) {
        $ancestorId = [int]$child.ParentProcessId
        if ($ancestorId -le 0 -or $ancestorId -eq [int]$child.ProcessId) { return $false }
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$ancestorId"
        if ($null -eq $parent -or $parent.CreationDate -gt $child.CreationDate) { return $false }
        if ($ancestorId -eq $ParentId) { return $true }
        $child = $parent
    }
    return $false
}

function Get-DeployPorts($Config) {
    $site = [Uri]$Config.SiteUrl
    $ports = @($Config.ApiPort, $Config.ProbePort, $Config.CaddyAdminPort, $site.Port)
    if (-not $site.IsLoopback) { $ports += 80 }
    return @($ports | Select-Object -Unique)
}

function Assert-DeployPorts($Config, [switch]$RequireFree) {
    $services = @{}
    foreach ($role in @('api', 'web')) {
        $services[$role] = Get-DeployService $Config $role
        Assert-ManagedService $Config $role $services[$role]
    }
    $connections = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue)
    foreach ($port in (Get-DeployPorts $Config)) {
        foreach ($connection in @($connections | Where-Object { $_.LocalPort -eq $port })) {
            $role = if ($port -eq $Config.ApiPort) { 'api' } else { 'web' }
            $service = $services[$role]
            if ($RequireFree -or $null -eq $service -or
                -not (Test-DescendantProcess ([int]$connection.OwningProcess) ([int]$service.ProcessId))) {
                throw "Port $port is occupied by an unmanaged/still-running process. No process was killed."
            }
        }
    }
}

function Set-PrivateDirectoryAcl([string]$Path, [string]$ServiceSid, [switch]$Writable) {
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @('S-1-5-18', 'S-1-5-32-544', $ServiceSid)) {
        $rights = if ($sid -eq $ServiceSid) { if ($Writable) { 'Modify' } else { 'ReadAndExecute' } } else { 'FullControl' }
        $identity = New-Object Security.Principal.SecurityIdentifier($sid)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($identity, $rights, 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Initialize-DeployRuntime($Config) {
    $root = $Config.DeploymentRoot
    Assert-NoReparsePoint $root
    $sid = Get-ServiceAccountSid $Config
    if (Test-Path -LiteralPath (Join-Path $root 'owner.json')) {
        $null = Assert-DeployOwner $Config
    } else {
        if (Test-Path -LiteralPath $root) {
            $unexpected = @(Get-ChildItem -LiteralPath $root -Force | Where-Object { $_.Name -ne 'config.json' })
            if ($unexpected.Count) { throw 'Unowned deployment directory is not empty. Use a new dedicated directory.' }
        } else { $null = New-Item -ItemType Directory -Path $root }
        Set-PrivateDirectoryAcl $root $sid
        Write-AtomicJson (Join-Path $root 'owner.json') @{
            RepositoryRoot = $Config.RepositoryRoot; ServicePrefix = $Config.ServicePrefix; ServiceSid = $sid
        }
    }
    foreach ($directory in @('controllers', 'releases', 'bin', 'services\api', 'services\web', 'logs', 'control', 'caddy')) {
        $path = Join-Path $root $directory
        Assert-NoReparsePoint $path
        if (-not (Test-Path -LiteralPath $path)) {
            $null = New-Item -ItemType Directory -Path $path -Force
            if ($directory -in @('logs', 'control', 'caddy')) { Set-PrivateDirectoryAcl $path $sid -Writable }
        }
    }
}

function Open-DeployLock($Config) {
    try {
        return [IO.File]::Open((Join-Path $Config.DeploymentRoot 'deploy.lock'), [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch { throw 'Another deployment menu/action is running. Close it before starting a second one.' }
}

function Install-DeployTools($Config, [switch]$CheckOnly) {
    $copies = @{
        (Join-Path $Config.DeploymentRoot 'bin\caddy.exe') = $Config.Tools.Caddy
        (Get-DeployWrapperPath $Config 'api') = $Config.Tools.WinSW
        (Get-DeployWrapperPath $Config 'web') = $Config.Tools.WinSW
    }
    foreach ($target in $copies.Keys) {
        $source = $copies[$target]
        if (Test-Path -LiteralPath $target) {
            if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne
                (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash) {
                throw 'Installed service binary differs from configured tool. Upgrade service tools explicitly; automatic replacement is disabled.'
            }
        } elseif (-not $CheckOnly) { Copy-Item -LiteralPath $source -Destination $target }
    }
}

function Test-DeployPrerequisites($Config, [string]$Action) {
    Assert-Administrator
    $null = Get-ServiceAccountSid $Config
    foreach ($role in @('api', 'web')) { Assert-ManagedService $Config $role (Get-DeployService $Config $role) }
    if ($Action -eq 'stop') { return }
    $null = Read-ProductionEnv $Config
    $tools = @('Caddy', 'WinSW', 'FFmpeg', 'FFprobe')
    if ($Action -in @('update', 'build', 'check')) { $tools += @('Git', 'Node', 'Npm', 'Python') }
    foreach ($key in $tools) {
        Assert-NoReparsePoint $Config.Tools.$key
        if (-not (Test-Path -LiteralPath $Config.Tools.$key -PathType Leaf)) { throw "Tool missing: $key. Configure its absolute path first." }
    }
    if ((Get-Item -LiteralPath $Config.Tools.WinSW).VersionInfo.FileMajorPart -ne 2) { throw 'These service templates require WinSW 2.x (x64).' }
    Install-DeployTools $Config -CheckOnly
    if ($Action -in @('update', 'build', 'check')) {
        $cwd = Split-Path -Parent $Config.EnvFile
        $nodeVersion = (Invoke-DeployProcess $Config.Tools.Node @('--version') $cwd -Quiet).Output.Trim().TrimStart('v')
        if ([version]$nodeVersion -lt [version]'20.19') { throw 'Node.js 20.19+ is required.' }
        $null = Invoke-DeployProcess $Config.Tools.Python @('-c', 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)') $cwd -Quiet
        Assert-Repository $Config -Clean:($Action -eq 'update') -AllowMissing:($Action -in @('update', 'check'))
        if ($Action -eq 'update') {
            # Read-only connectivity test before downtime. No host-key bypass or prompts.
            $null = Invoke-DeployGit $Config @('ls-remote', '--exit-code', $script:Remote, 'refs/heads/main')
        }
    }
    if ($Action -eq 'start') { $null = Get-LastDeployRelease $Config }
    Assert-DeployPorts $Config
}

function Wait-DeployServiceStopped($Config, [string]$Role) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Config.StopTimeoutSeconds)
    do {
        $service = Get-DeployService $Config $Role
        if ($null -eq $service -or $service.State -eq 'Stopped') { return }
        Assert-ManagedService $Config $Role $service
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "$Role did not stop in time. No forced kill was performed; the operation is aborted."
}

function Get-VerifiedApiState($Config, $Service, [string]$ReleaseId = '') {
    $stateFile = Join-Path $Config.DeploymentRoot 'control\api-state.json'
    if (-not (Test-Path -LiteralPath $stateFile)) { throw 'API process state is missing; no forced termination was attempted.' }
    $state = Read-JsonFile $stateFile
    if ($state.token -notmatch '^[a-f0-9]{32}$' -or
        $state.releaseId -notmatch '^[0-9]{8}-[0-9]{6}-[0-9a-f]{10}-[0-9a-f]{8}$' -or
        ($ReleaseId -and $state.releaseId -ne $ReleaseId)) { throw 'API instance/release identity is invalid.' }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$state.pid)"
    if ($null -eq $process -or -not (Test-DescendantProcess ([int]$state.pid) ([int]$Service.ProcessId)) -or
        [Math]::Abs(($process.CreationDate.ToUniversalTime() - [DateTimeOffset]::Parse($state.startedAt).UtcDateTime).TotalSeconds) -gt 1) {
        throw 'API PID/start-time validation failed; refusing to manage it.'
    }
    $releaseHost = Join-Path $Config.DeploymentRoot ('releases\' + $state.releaseId + '\scripts\deploy\api-host.py')
    if (([string]$process.CommandLine).IndexOf($releaseHost, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw 'API command does not belong to this release.'
    }
    return $state
}

function Assert-RunningDeployInstance($Config, $Release, [string]$Role) {
    $service = Get-DeployService $Config $Role
    Assert-ManagedService $Config $Role $service
    if ($null -eq $service -or $service.State -ne 'Running') { throw "$Role service is not running after startup." }
    $state = if ($Role -eq 'api') { Get-VerifiedApiState $Config $service $Release.Id } else { $null }
    $ports = if ($Role -eq 'api') { @($Config.ApiPort) } else { @($Config.ProbePort, $Config.CaddyAdminPort) }
    foreach ($port in $ports) {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
        if ($listeners.Count -eq 0) { throw "Started service has no listener on port $port." }
        foreach ($listener in $listeners) {
            if (-not (Test-DescendantProcess ([int]$listener.OwningProcess) ([int]$service.ProcessId)) -or
                ($null -ne $state -and [int]$listener.OwningProcess -ne [int]$state.pid)) {
                throw "Health endpoint on port $port belongs to another process, not the started release."
            }
        }
    }
}

function Stop-DeployServices($Config) {
    foreach ($role in @('web', 'api')) {
        $service = Get-DeployService $Config $role
        Assert-ManagedService $Config $role $service
        if ($null -eq $service) { continue }
        # Disable reboot starts BEFORE asking the child to exit. Failed builds and
        # explicit Stop must not resurrect the old service at the next reboot.
        Set-Service -Name $service.Name -StartupType Manual
        if ($service.State -eq 'Stopped') { continue }
        if ($service.State -ne 'Running') { throw "$role is in $($service.State); wait for a stable state before deploying." }
        Write-DeployLog "Gracefully stopping $role..."
        if ($role -eq 'web') {
            $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Config.CaddyAdminPort -ErrorAction SilentlyContinue)
            if ($listeners.Count -eq 0) { throw 'Caddy admin listener is missing; refusing to stop an unidentified process.' }
            foreach ($listener in $listeners) {
                if (-not (Test-DescendantProcess ([int]$listener.OwningProcess) ([int]$service.ProcessId))) { throw 'Caddy admin port belongs to another process.' }
            }
            $null = Invoke-DeployProcess (Join-Path $Config.DeploymentRoot 'bin\caddy.exe') @(
                'stop', '--address', "127.0.0.1:$($Config.CaddyAdminPort)"
            ) $Config.DeploymentRoot
        } else {
            $state = Get-VerifiedApiState $Config $service
            Write-AtomicJson (Join-Path $Config.DeploymentRoot 'control\api-stop.json') @{ token = $state.token }
        }
        Wait-DeployServiceStopped $Config $role
    }
    Assert-DeployPorts $Config -RequireFree
}

function Get-DeployServiceXml($Config, $Release, [string]$Role) {
    $root = $Config.DeploymentRoot
    $values = @{
        SERVICE_ID = Get-DeployServiceName $Config $Role
        WORKING_DIRECTORY = $Release.Path
        LOG_DIRECTORY = Join-Path $root ('logs\' + $Role)
    }
    if ($Role -eq 'api') {
        $values.EXECUTABLE = Join-Path $Release.Path '.venv\Scripts\python.exe'
        $arguments = @((Join-Path $Release.Path 'scripts\deploy\api-host.py'), '--env-file', $Config.EnvFile,
            '--state-file', (Join-Path $root 'control\api-state.json'), '--stop-file', (Join-Path $root 'control\api-stop.json'),
            '--release-id', $Release.Id, '--port', [string]$Config.ApiPort, '--stop-timeout', [string]$Config.StopTimeoutSeconds)
        $values.ARGUMENTS = ($arguments | ForEach-Object { Quote-NativeArgument $_ }) -join ' '
        $values.ENV_FILE = $Config.EnvFile
        $values.TOOL_PATH = ((@($Config.Tools.FFmpeg, $Config.Tools.FFprobe, $Config.Tools.Node) | ForEach-Object { Split-Path -Parent $_ } | Select-Object -Unique) -join ';')
    } else {
        $values.EXECUTABLE = Join-Path $root 'bin\caddy.exe'
        $values.ARGUMENTS = 'run --config ' + (Quote-NativeArgument (Join-Path $root 'services\web\Caddyfile')) + ' --adapter caddyfile'
        $values.CADDY_DATA = Join-Path $root 'caddy\data'
        $values.CADDY_CONFIG = Join-Path $root 'caddy\config'
    }
    return Expand-DeployTemplate "$Role-service.xml.template" $values -Xml
}

function Configure-DeployServices($Config, $Release, [Management.Automation.PSCredential]$Credential) {
    Assert-DeployPorts $Config -RequireFree
    foreach ($role in @('api', 'web')) {
        $service = Get-DeployService $Config $role
        Assert-ManagedService $Config $role $service
        if ($null -ne $service -and $service.State -ne 'Stopped') { throw 'All services must be stopped before configuring a release.' }
    }
    Install-DeployTools $Config
    $caddyPath = Join-Path $Config.DeploymentRoot 'services\web\Caddyfile'
    Write-AtomicText $caddyPath (Get-CaddyConfig $Config $Release)
    $null = Invoke-DeployProcess (Join-Path $Config.DeploymentRoot 'bin\caddy.exe') @(
        'validate', '--config', $caddyPath, '--adapter', 'caddyfile'
    ) $Config.DeploymentRoot -Environment @{ XDG_DATA_HOME = (Join-Path $Config.DeploymentRoot 'caddy\data'); XDG_CONFIG_HOME = (Join-Path $Config.DeploymentRoot 'caddy\config') }
    foreach ($role in @('api', 'web')) {
        $name = Get-DeployServiceName $Config $role
        $wrapper = Get-DeployWrapperPath $Config $role
        Write-AtomicText ([IO.Path]::ChangeExtension($wrapper, '.xml')) (Get-DeployServiceXml $Config $Release $role)
        $null = New-Item -ItemType Directory -Path (Join-Path $Config.DeploymentRoot ('logs\' + $role)) -Force
        if ($null -eq (Get-DeployService $Config $role)) {
            if ($null -eq $Credential) { throw 'First service registration needs the configured service account credential.' }
            # New-Service passes credentials to SCM, not to a process command line
            # or the WinSW XML. No plaintext password is persisted by this script.
            $null = New-Service -Name $name -BinaryPathName ('"' + $wrapper + '"') -DisplayName $name -StartupType Manual -Credential $Credential
        }
    }
    Write-AtomicJson (Join-Path $Config.DeploymentRoot 'configured.json') $Release
}

function Wait-DeployHttp([string]$Url, [int]$Timeout, [scriptblock]$Validate) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Timeout)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($response.StatusCode -eq 200 -and (& $Validate $response)) { return $response }
        } catch { }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Health check timed out: $Url"
}

function Start-DeployServices($Config, $Release) {
    Assert-DeployPorts $Config -RequireFree
    $apiName = Get-DeployServiceName $Config 'api'
    $webName = Get-DeployServiceName $Config 'web'
    try {
        Start-Service -Name $apiName
        $null = Wait-DeployHttp "http://127.0.0.1:$($Config.ApiPort)/health" $Config.HealthTimeoutSeconds {
            param($r) $health = $r.Content | ConvertFrom-Json
            return $health.service -eq 'viral-dna-api'
        }
        Assert-RunningDeployInstance $Config $Release 'api'
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:$($Config.ApiPort)/api/v1/auth/status" -TimeoutSec 5
        if ($status.auth_mode -ne 'password') { throw 'API is not in password authentication mode.' }
        if (-not ([Uri]$Config.SiteUrl).IsLoopback -and -not $status.initialized) {
            throw 'Public startup refused: complete account setup using the local SiteUrl first.'
        }
        Start-Service -Name $webName
        $probe = "http://127.0.0.1:$($Config.ProbePort)"
        $expectedRelease = $Release.Id
        $null = Wait-DeployHttp "$probe/login" $Config.HealthTimeoutSeconds {
            param($r) return $r.Headers['X-ViralDNA-Release'] -eq $expectedRelease -and $r.Content -match 'ViralDNA'
        }
        $null = Wait-DeployHttp "$probe/api/v1/auth/status" $Config.HealthTimeoutSeconds {
            param($r) return ($r.Content | ConvertFrom-Json).auth_mode -eq 'password'
        }
        $null = Wait-DeployHttp ($Config.SiteUrl.TrimEnd('/') + '/login') $Config.HealthTimeoutSeconds {
            param($r) return $r.Headers['X-ViralDNA-Release'] -eq $expectedRelease -and $r.Content -match 'ViralDNA'
        }
        Assert-RunningDeployInstance $Config $Release 'api'
        Assert-RunningDeployInstance $Config $Release 'web'
        # Enable reboot startup only after the complete stack has passed checks.
        Set-Service -Name $apiName -StartupType Automatic
        Set-Service -Name $webName -StartupType Automatic
        Write-AtomicJson (Join-Path $Config.DeploymentRoot 'active.json') $Release
        Write-DeployLog "Ready: $($Config.SiteUrl) | release $($Release.Id)"
    } catch {
        $failure = $_
        Write-DeployLog 'Startup failed; attempting scoped graceful cleanup (no database rollback).'
        try { Stop-DeployServices $Config } catch { Write-DeployLog "Cleanup needs operator attention: $($_.Exception.Message)" }
        throw $failure
    }
}

function Invoke-DeployWorkflow([string]$Action, [hashtable]$Steps) {
    # Kept independent of Windows/SCM for deterministic ordering/failure tests.
    if ($Action -notin @('update', 'build', 'start', 'stop')) { throw 'Unknown deployment action.' }
    & $Steps.Preflight
    & $Steps.Stop
    if ($Action -eq 'stop') { return }
    if ($Action -eq 'update') { & $Steps.Update }
    if ($Action -in @('update', 'build')) { & $Steps.Build }
    & $Steps.Configure
    & $Steps.Start
}

Export-ModuleMember -Function *-*

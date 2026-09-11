[CmdletBinding()]
param(
    [string]$BundleRoot = 'D:\ViralDNA\server-package',
    [string]$ToolsSource = 'D:\ViralDNA\tools',
    [string]$RepositoryRoot = 'C:\Projects\ViralDNA'
)
# Generator only: public setup/tools, never accounts, keys, databases or IIS state.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Server.Prepare.psm1') -Force -DisableNameChecking
Import-Module (Join-Path $PSScriptRoot 'Deploy.Core.psm1') -DisableNameChecking
$output = Get-FullPath $BundleRoot
$tools = Get-FullPath $ToolsSource
$sourceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if ($output.Length -le 3 -or (Test-PathWithin $output $sourceRoot) -or (Test-PathWithin $sourceRoot $output) -or
    (Test-PathWithin $output $tools) -or (Test-PathWithin $tools $output)) { throw 'Use a separate dedicated package output directory.' }
Assert-NoReparsePoint $output
Assert-NoReparsePoint $tools
$runtimeTarget = Join-Path (Get-FullPath $RepositoryRoot) '.server'
$bundle = Join-Path $output '.server'
$manifestPath = Join-Path $bundle 'bundle-manifest.generated.json'
$oldHashes = @{}
if (Test-Path -LiteralPath $output) {
    if (Test-Path -LiteralPath $manifestPath) {
        $previous = Read-JsonFile $manifestPath
        if ($previous.GeneratedBy -ne 'ViralDNA server bundle' -or $previous.RepositoryRoot -ne $RepositoryRoot -or
            $previous.RuntimeRoot -ne $runtimeTarget) { throw 'Existing output has a different owner/target.' }
        foreach ($record in $previous.Files) { $oldHashes[$record.Path] = $record.Sha256 }
        foreach ($item in Get-ChildItem -LiteralPath $output -Recurse -Force) {
            Assert-NoReparsePoint $item.FullName
            if ($item.PSIsContainer -or $item.FullName -eq $manifestPath) { continue }
            if (-not (Test-PathWithin $item.FullName $bundle)) { throw 'Unexpected file outside generated .server directory.' }
            $relative = $item.FullName.Substring($bundle.Length + 1)
            if (-not $oldHashes.ContainsKey($relative) -or (Get-FileHash -LiteralPath $item.FullName).Hash -ne $oldHashes[$relative]) {
                throw "Output has private/operator changes; it has not been overwritten: $relative"
            }
        }
    } elseif (@(Get-ChildItem -LiteralPath $output -Force).Count) { throw 'Use an empty output directory or a verified previously generated package.' }
}
$null = New-Item -ItemType Directory -Path $bundle -Force
$records = New-Object 'Collections.Generic.List[object]'
function Add-PackageFile([string]$Relative, [string]$Source, [string]$Content) {
    $destination = Get-FullPath (Join-Path $bundle $Relative)
    if (-not (Test-PathWithin $destination $bundle)) { throw 'Package path escaped output.' }
    Assert-NoReparsePoint $destination
    $null = New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force
    if ($Source) {
        Assert-NoReparsePoint $Source
        if (-not (Test-Path -LiteralPath $destination) -or
            (Get-FileHash -LiteralPath $Source).Hash -ne (Get-FileHash -LiteralPath $destination).Hash) {
            Copy-Item -LiteralPath $Source -Destination $destination -Force
        }
    } else { Write-AtomicText $destination $Content }
    $item = Get-Item -LiteralPath $destination
    $records.Add([pscustomobject]@{ Path = $Relative; Bytes = $item.Length;
        Sha256 = (Get-FileHash -LiteralPath $destination).Hash.ToLowerInvariant() })
}
$required = @('caddy.exe', 'WinSW-x64.exe', 'git\cmd\git.exe', 'git\usr\bin\ssh.exe', 'git\usr\bin\ssh-keygen.exe',
    'node\node.exe', 'node\node_modules\npm\bin\npm-cli.js', 'ffmpeg\bin\ffmpeg.exe', 'ffmpeg\bin\ffprobe.exe',
    'installers\python-3.13.15-amd64.exe', 'installers\rewrite_amd64_en-US.msi', 'installers\requestRouter_amd64.msi')
foreach ($relative in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $tools $relative) -PathType Leaf)) { throw "Missing required download/extraction: $relative" }
}
foreach ($installer in @(@('python-3.13.15-amd64.exe', 'Python Software Foundation'),
    @('rewrite_amd64_en-US.msi', 'Microsoft Corporation'), @('requestRouter_amd64.msi', 'Microsoft Corporation'))) {
    $signature = Get-AuthenticodeSignature -LiteralPath (Join-Path $tools ('installers\' + $installer[0]))
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or
        $signature.SignerCertificate.Subject -notmatch ('CN=' + [regex]::Escape($installer[1]) + ',')) { throw "Invalid installer signature: $($installer[0])" }
}
if ((Get-Item -LiteralPath (Join-Path $tools 'WinSW-x64.exe')).VersionInfo.FileMajorPart -ne 2) { throw 'WinSW 2.x is required.' }
# Fixed allowlist: no developer settings or download cache in the package.
foreach ($directory in @('git', 'node', 'ffmpeg')) {
    foreach ($item in Get-ChildItem -LiteralPath (Join-Path $tools $directory) -File -Recurse -Force) {
        Add-PackageFile ('tools\' + $item.FullName.Substring($tools.Length + 1)) $item.FullName
    }
}
foreach ($relative in @('caddy.exe', 'WinSW-x64.exe', 'installers\python-3.13.15-amd64.exe',
    'installers\rewrite_amd64_en-US.msi', 'installers\requestRouter_amd64.msi')) {
    Add-PackageFile ('tools\' + $relative) (Join-Path $tools $relative)
}
$setupFiles = @('prepare-server.ps1', 'install-prerequisites.ps1', 'sync-code.ps1', 'configure-iis.ps1',
    'verify-bundle.ps1', 'Server.Prepare.psm1', 'ServiceAccountRights.cs', 'Iis.Proxy.ps1', 'Deploy.Core.psm1',
    'deploy-server.ps1', 'api-host.py', 'config.example.json', 'templates\api.env.example',
    'templates\Caddyfile.template', 'templates\Caddyfile.iis.template', 'templates\iis-web.config.template',
    'templates\api-service.xml.template', 'templates\web-service.xml.template')
foreach ($relative in $setupFiles) { Add-PackageFile ('setup\' + $relative) (Join-Path $PSScriptRoot $relative) }
$preview = New-ServerConfig $RepositoryRoot $runtimeTarget '.\Administrator'
Add-PackageFile 'config\deployment.preview.json' '' ($preview | ConvertTo-Json -Depth 8)
Add-PackageFile 'config\api.env' '' (New-ServerEnv $runtimeTarget)
$readme = [IO.File]::ReadAllText((Join-Path $sourceRoot 'docs\deployment\当前账户服务器工具包.md'))
foreach ($document in @('Windows服务器一键部署.md', '升级备份与恢复.md')) {
    $readme = $readme.Replace('](' + $document + ')', '](' + $RepositoryRoot.Replace('\', '/') + '/docs/deployment/' + $document + ')')
}
Add-PackageFile 'README-部署步骤.md' '' $readme
$batCommands = @{
    '02-prepare.bat' = @('powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify-bundle.ps1"',
        'if errorlevel 1 goto failed',
        ('powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-prerequisites.ps1" -RepositoryRoot "' + $RepositoryRoot + '"'))
    '03-update-git.bat' = @('powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync-code.ps1" -Config "%~dp0..\config\deploy.json"')
    '04-configure-iis.bat' = @('powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0configure-iis.ps1" -Config "%~dp0..\config\deploy.json" -InstallComponents')
    '05-run.bat' = @('powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy-server.ps1" -Config "%~dp0..\config\deploy.json"')
}
foreach ($name in $batCommands.Keys) {
    $lines = @('@echo off', 'setlocal DisableDelayedExpansion') + $batCommands[$name] + @(
        'if errorlevel 1 goto failed', 'echo Completed.', 'pause', 'exit /b 0', ':failed', 'echo FAILED. Read the error above before continuing.', 'pause', 'exit /b 1', '')
    Add-PackageFile ('setup\' + $name) '' ($lines -join "`r`n")
}
Write-AtomicJson $manifestPath @{
    SchemaVersion = 1; GeneratedBy = 'ViralDNA server bundle'; PreparedAtUtc = [DateTime]::UtcNow.ToString('o')
    RepositoryRoot = $RepositoryRoot; RuntimeRoot = $runtimeTarget; Complete = $true; Missing = @(); Files = @($records.ToArray())
    Sources = @(
        @{ Tool = 'Caddy 2.11.4'; Url = 'https://caddyserver.com/api/download?os=windows&arch=amd64'; Verification = 'Official HTTPS; local hash is not a publisher signature.' }
        @{ Tool = 'WinSW 2.12.0'; Url = 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe'; Verification = 'Official release HTTPS; local hash recorded, no publisher digest supplied.' }
        @{ Tool = 'Git 2.55.0.5'; Url = 'https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.5/PortableGit-2.55.0.5-64-bit.7z.exe'; ArchiveSha256 = '5aa8a20f6e9abb2c755f0e73c91c687701a46b309ad84a0ca6509380fa4ae290' }
        @{ Tool = 'FFmpeg 9.0.1'; Url = 'https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.1-essentials_build.zip'; ArchiveSha256 = 'fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9' }
        @{ Tool = 'Node 24.20.0'; Url = 'https://nodejs.org/dist/v24.20.0/node-v24.20.0-win-x64.zip'; ArchiveSha256 = '6cac9ffbca8f6a47091e4b5c772e0606049c3871cb67d900c0cedde630e545ba' }
        @{ Tool = 'Python 3.13.15'; Url = 'https://www.python.org/ftp/python/3.13.15/python-3.13.15-amd64.exe'; Verification = 'Valid Python Software Foundation Authenticode signature.' }
        @{ Tool = 'IIS URL Rewrite 2.1'; Url = 'https://download.microsoft.com/download/1/2/8/128E2E22-C1B9-44A4-BE2A-5859ED1D4592/rewrite_amd64_en-US.msi'; Verification = 'Valid Microsoft Authenticode signature.' }
        @{ Tool = 'IIS ARR 3.0'; Url = 'https://download.microsoft.com/download/E/9/8/E9849D6A-020E-47E4-9FD0-A023E99B54EB/requestRouter_amd64.msi'; Verification = 'Valid Microsoft Authenticode signature.' }
    )
    Notes = @('Copy CONTENTS of server-package into the repository root; .server stays private.',
        'No credentials/business data. Python/IIS installers are not run on the preparation computer.',
        'Build still requires npm/PyPI network. Windows roles may need installation media.',
        'This is a tool/setup package, not a fully offline app image. Existing business data needs separate migration.')
}
Write-Host "Complete single-root package: $output ($($records.Count) files)."

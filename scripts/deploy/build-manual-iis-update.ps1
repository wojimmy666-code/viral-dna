[CmdletBinding()]
param([string]$OutputRoot = 'D:\ViralDNA\ViralDNA-manual-iis-update')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Deploy.Core.psm1') -DisableNameChecking
Import-Module (Join-Path $PSScriptRoot 'ManualIis.Update.psm1') -DisableNameChecking
$output = Get-FullPath $OutputRoot
$archive = $output + '.zip'
Assert-NoReparsePoint $output
Assert-NoReparsePoint $archive
if ((Test-Path -LiteralPath $output) -or (Test-Path -LiteralPath $archive)) { throw 'Output already exists; choose a new update package path. Nothing was overwritten.' }
if ($output.Length -le 3 -or (Test-PathWithin $PSScriptRoot $output)) { throw 'Use a dedicated new output directory, not a drive or source root.' }

function Copy-UpdateText([string]$Source, [string]$Destination) {
    $text = [IO.File]::ReadAllText($Source, [Text.Encoding]::UTF8) -replace '\r?\n', "`r`n"
    $null = New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force
    $bom = [IO.Path]::GetExtension($Destination) -in @('.ps1', '.psm1', '.md')
    [IO.File]::WriteAllText($Destination, $text, (New-Object Text.UTF8Encoding($bom)))
}

$null = New-Item -ItemType Directory -Path $output
$manifestFiles = @()
foreach ($name in (Get-ManualIisPayloadNames)) {
    $source = if ($name.EndsWith('.bat')) { Join-Path $PSScriptRoot ('templates\manual-iis-update\' + $name) } else { Join-Path $PSScriptRoot $name }
    $target = Join-Path (Join-Path $output 'payload') $name
    Copy-UpdateText $source $target
    $manifestFiles += [pscustomobject]@{ Path = $name; Bytes = (Get-Item -LiteralPath $target).Length; Sha256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() }
}
foreach ($name in @('ManualIis.Update.psm1', 'Deploy.Core.psm1', 'Iis.Proxy.ps1')) {
    Copy-UpdateText (Join-Path $PSScriptRoot $name) (Join-Path (Join-Path $output 'updater') $name)
}
Copy-UpdateText (Join-Path $PSScriptRoot 'install-manual-iis-update.ps1') (Join-Path $output 'install-manual-iis-update.ps1')
Copy-UpdateText (Join-Path $PSScriptRoot 'templates\manual-iis-update\01-install-update.bat') (Join-Path $output '01-install-update.bat')
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Copy-UpdateText (Join-Path $repo 'docs\deployment\手动IIS启动更新包.md') (Join-Path $output 'README.md')
Write-AtomicJson (Join-Path $output 'update-manifest.json') @{
    SchemaVersion = 1; Kind = 'ViralDNA manual IIS controller update'
    BuiltAtUtc = [DateTime]::UtcNow.ToString('o'); Files = $manifestFiles
}
$null = Get-VerifiedManualIisPayload $output
Compress-Archive -LiteralPath $output -DestinationPath $archive -CompressionLevel Optimal
Write-Output ([pscustomobject]@{ Folder = $output; Archive = $archive; Bytes = (Get-Item -LiteralPath $archive).Length; Sha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() })

param([string]$BundleRoot = 'D:\ViralDNA\server-package')
# Refresh only source-controlled setup files in an untouched PREPARATION package.
# Never use this on an installed server: its new files/config changes are refused.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Deploy.Core.psm1') -DisableNameChecking
$output = Get-FullPath $BundleRoot
$root = Join-Path $output '.server'
Assert-NoReparsePoint $root
$manifestPath = Join-Path $root 'bundle-manifest.generated.json'
$manifest = Read-JsonFile $manifestPath
if ($manifest.GeneratedBy -ne 'ViralDNA server bundle' -or $manifest.RuntimeRoot -ne 'C:\Projects\ViralDNA\.server') {
    throw 'Not the expected preparation package.'
}
& (Join-Path $root 'setup\verify-bundle.ps1')
$expected = @{}
foreach ($entry in $manifest.Files) { $expected[$entry.Path] = $true }
foreach ($file in Get-ChildItem -LiteralPath $root -File -Recurse -Force) {
    $relative = $file.FullName.Substring($root.Length + 1)
    if ($relative -ne 'bundle-manifest.generated.json' -and -not $expected.ContainsKey($relative)) {
        throw 'Unexpected files: this package may have been installed. Refresh refused.'
    }
}
foreach ($entry in $manifest.Files | Where-Object Path -Like 'setup\*') {
    $source = Get-FullPath (Join-Path $PSScriptRoot $entry.Path.Substring(6))
    $target = Get-FullPath (Join-Path $root $entry.Path)
    if (-not (Test-PathWithin $source $PSScriptRoot) -or -not (Test-PathWithin $target (Join-Path $root 'setup'))) { throw 'Invalid setup path.' }
    Assert-NoReparsePoint $source
    Assert-NoReparsePoint $target
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { continue } # Generated batch entries.
    $hash = (Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant()
    if ($hash -ne $entry.Sha256) {
        Copy-Item -LiteralPath $source -Destination $target -Force
        $entry.Sha256 = $hash
        $entry.Bytes = (Get-Item -LiteralPath $target).Length
        Write-Host "Refreshed $($entry.Path)"
    }
}
$manifest.PreparedAtUtc = [DateTime]::UtcNow.ToString('o')
Write-AtomicJson $manifestPath $manifest

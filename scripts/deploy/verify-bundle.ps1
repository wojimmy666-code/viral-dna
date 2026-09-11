[CmdletBinding()]
param([string]$BundleRoot)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($BundleRoot)) { $BundleRoot = Split-Path -Parent $PSScriptRoot }
$root = [IO.Path]::GetFullPath($BundleRoot).TrimEnd('\')
$manifestPath = Join-Path $root 'bundle-manifest.generated.json'
$manifest = [IO.File]::ReadAllText($manifestPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
if ($manifest.SchemaVersion -ne 1 -or $manifest.GeneratedBy -ne 'ViralDNA server bundle') {
    throw 'Unrecognized bundle manifest.'
}
foreach ($file in $manifest.Files) {
    $path = [IO.Path]::GetFullPath((Join-Path $root $file.Path))
    if (-not $path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Manifest path escaped the bundle.'
    }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $file.Sha256) {
        throw "Missing or changed bundle file: $($file.Path)"
    }
}
if (-not $manifest.Complete) { throw ('Downloads are incomplete: ' + ($manifest.Missing -join ', ')) }
Write-Host "Verified $($manifest.Files.Count) files. No software was installed and no services/accounts were changed."

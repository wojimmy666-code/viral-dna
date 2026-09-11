param(
    [string]$BundleRoot = 'D:\ViralDNA\server-package',
    [string]$ArchivePath = 'D:\ViralDNA\ViralDNA-server-package.zip',
    [switch]$VerifyExisting
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Deploy.Core.psm1') -DisableNameChecking
$root = Get-FullPath $BundleRoot
$archive = Get-FullPath $ArchivePath
Assert-NoReparsePoint $root
Assert-NoReparsePoint $archive
if ((Test-PathWithin $archive $root) -or ((Test-Path -LiteralPath $archive) -and -not $VerifyExisting) -or
    (Test-Path -LiteralPath ($archive + '.sha256'))) { throw 'Use a new archive path outside the package. Existing output is never overwritten.' }
& (Join-Path $root '.server\setup\verify-bundle.ps1')
$null = New-Item -ItemType Directory -Path (Split-Path -Parent $archive) -Force
Add-Type -AssemblyName System.IO.Compression.FileSystem
if ($VerifyExisting) {
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) { throw 'Archive to verify is missing.' }
} else { [IO.Compression.ZipFile]::CreateFromDirectory($root, $archive, [IO.Compression.CompressionLevel]::Optimal, $false) }
$zip = [IO.Compression.ZipFile]::OpenRead($archive)
try {
    $manifest = Read-JsonFile (Join-Path $root '.server\bundle-manifest.generated.json')
    # Windows PowerShell/.NET Framework writes ZIP names with backslashes;
    # newer runtimes use forward slashes. Validate both against exact file names.
    $expected = @{}
    foreach ($file in $manifest.Files) { $expected['.server/' + $file.Path.Replace('\', '/')] = $file.Sha256 }
    $expected['.server/bundle-manifest.generated.json'] = (Get-FileHash -LiteralPath (Join-Path $root '.server\bundle-manifest.generated.json')).Hash
    $seen = @{}
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName.Replace('\', '/')
            if ($name.EndsWith('/')) { continue }
            if (-not $expected.ContainsKey($name) -or $seen.ContainsKey($name)) { throw 'Unexpected/duplicate archive entry; do not distribute it.' }
            $stream = $entry.Open()
            try { $digest = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') } finally { $stream.Dispose() }
            if ($digest -ne $expected[$name]) { throw "Archive content failed SHA-256: $name" }
            $seen[$name] = $true
        }
        if ($seen.Count -ne $expected.Count) { throw 'Archive is incomplete; do not distribute it.' }
    } finally { $sha.Dispose() }
} finally { $zip.Dispose() }
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Write-AtomicText ($archive + '.sha256') ($hash + '  ' + (Split-Path -Leaf $archive) + "`r`n")
Write-Host "Archive ready: $archive"
Write-Host "SHA-256: $hash"

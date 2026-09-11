[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][uri]$Url,
    [Parameter(Mandatory = $true)][string]$Destination,
    [ValidatePattern('^$|^[a-fA-F0-9]{64}$')][string]$Sha256 = '',
    [switch]$AllowGitHubRelease
)

# Download only. Never install software, start services or modify Git settings.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $Url.IsAbsoluteUri -or $Url.Scheme -ne 'https' -or $Url.UserInfo) {
    throw 'An HTTPS download URL without credentials is required.'
}
if ($Destination -notmatch '^[A-Za-z]:[\\/]') { throw 'Use an absolute destination path.' }
$target = [IO.Path]::GetFullPath($Destination)
$parent = Split-Path -Parent $target
$ancestor = $parent
while ($ancestor) {
    if ((Test-Path -LiteralPath $ancestor) -and
        ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing a linked destination: $ancestor"
    }
    $ancestor = Split-Path -Parent $ancestor
}
if (Test-Path -LiteralPath $target) {
    if ($Sha256 -and (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -eq $Sha256) {
        Write-Host "Already verified: $target"
        return
    }
    throw "Destination already exists; it has not been overwritten: $target"
}
$null = New-Item -ItemType Directory -Path $parent -Force
$partial = $target + '.' + [Guid]::NewGuid().ToString('N') + '.partial'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$currentUrl = $Url
for ($redirect = 0; $redirect -lt 8; $redirect++) {
    $hostName = $currentUrl.DnsSafeHost
    $githubHost = $hostName -match '(^|\.)(github\.com|githubusercontent\.com|githubassets\.com)$'
    if ($githubHost -and -not $AllowGitHubRelease) {
        throw 'A GitHub release download requires explicit AllowGitHubRelease authorization. Git transport remains SSH.'
    }
    if ($currentUrl.Scheme -ne 'https' -or $currentUrl.UserInfo) { throw 'Unsafe download redirect.' }
    $request = [Net.HttpWebRequest]::Create($currentUrl)
    $request.AllowAutoRedirect = $false
    $request.UserAgent = 'ViralDNA-server-tool-preparation/1.0'
    $request.Timeout = 60000
    $request.ReadWriteTimeout = 60000
    $response = $request.GetResponse()
    try {
        $status = [int]$response.StatusCode
        if ($status -ge 300 -and $status -lt 400) {
            $currentUrl = [uri]::new($currentUrl, $response.Headers['Location'])
            continue
        }
        if ($status -ne 200) { throw "Unexpected download status: $status" }
        Write-Host "Downloading $($currentUrl.DnsSafeHost) -> $target"
        $inputStream = $response.GetResponseStream()
        $outputStream = [IO.File]::Open($partial, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
        try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose(); $inputStream.Dispose() }
        $length = (Get-Item -LiteralPath $partial).Length
        if ($length -eq 0 -or ($response.ContentLength -gt 0 -and $length -ne $response.ContentLength)) {
            throw 'Incomplete download; the partial file has not been promoted.'
        }
        $actual = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($Sha256 -and $actual -ne $Sha256.ToLowerInvariant()) { throw "SHA-256 mismatch; retained partial file: $partial" }
        [IO.File]::Move($partial, $target)
        [pscustomobject]@{ File = $target; Bytes = $length; Sha256 = $actual; Source = $Url.AbsoluteUri;
            PublisherHashVerified = [bool]$Sha256 } | Format-List
        return
    } finally { $response.Dispose() }
}
throw 'Too many download redirects.'

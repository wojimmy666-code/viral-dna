[CmdletBinding()]
param([string]$RepositoryRoot = 'C:\Projects\ViralDNA',
    [string]$PublicSiteUrl = 'https://viraldnastudio.com', [switch]$Preview)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
try {
    Import-Module (Join-Path $PSScriptRoot 'updater\ManualIis.Update.psm1') -Force -DisableNameChecking
    $result = Install-ManualIisControllerUpdate -UpdateRoot $PSScriptRoot -RepositoryRoot $RepositoryRoot -PublicSiteUrl $PublicSiteUrl -Preview:$Preview
    if ($Preview) { $result | Format-List; return }
    Write-Host 'Next: keep ONLY the ViralDNA IIS site stopped; run .server\setup\05-run.bat and choose 2.'
    Write-Host 'Complete local account setup, choose 3 once, then start IIS manually and run 06-check-https.bat.'
} catch {
    Write-Host ('Update failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}

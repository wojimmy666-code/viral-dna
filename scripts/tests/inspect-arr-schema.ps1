param([string]$Installer = 'D:\ViralDNA\tools\installers\requestRouter_amd64.msi')
# Extract the publisher's schema for inspection; NEVER run msiexec or install ARR.
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
public static class ViralDnaMsiReadOnly {
    [DllImport("msi.dll", CharSet=CharSet.Unicode)] static extern uint MsiOpenDatabaseW(string path, IntPtr mode, out uint db);
    [DllImport("msi.dll", CharSet=CharSet.Unicode)] static extern uint MsiDatabaseOpenViewW(uint db, string sql, out uint view);
    [DllImport("msi.dll")] static extern uint MsiViewExecute(uint view, uint record);
    [DllImport("msi.dll")] static extern uint MsiViewFetch(uint view, out uint record);
    [DllImport("msi.dll")] static extern uint MsiRecordReadStream(uint record, uint field, byte[] bytes, ref uint length);
    [DllImport("msi.dll")] static extern uint MsiCloseHandle(uint handle);
    static void Check(uint result) { if(result != 0) throw new Exception("MSI read failed: " + result); }
    public static void ExtractCab(string path, string target) {
        uint db=0, view=0, record=0;
        try {
            Check(MsiOpenDatabaseW(path, IntPtr.Zero, out db));
            Check(MsiDatabaseOpenViewW(db, "SELECT `Data` FROM `_Streams` WHERE `Name`='requestRouter.cab'", out view));
            Check(MsiViewExecute(view, 0)); Check(MsiViewFetch(view, out record));
            using(var file = new FileStream(target, FileMode.CreateNew)) {
                var bytes = new byte[65536];
                while(true) {
                    uint length = (uint)bytes.Length;
                    Check(MsiRecordReadStream(record, 1, bytes, ref length));
                    if(length == 0) break;
                    file.Write(bytes, 0, (int)length);
                }
            }
        } finally { if(record != 0) MsiCloseHandle(record); if(view != 0) MsiCloseHandle(view); if(db != 0) MsiCloseHandle(db); }
    }
}
'@
$root = Join-Path ([IO.Path]::GetTempPath()) ('viraldna-arr-schema-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $root
try {
    $cab = Join-Path $root 'arr.cab'
    [ViralDnaMsiReadOnly]::ExtractCab($Installer, $cab)
    $null = & (Join-Path $env:WINDIR 'System32\expand.exe') '-F:RequestRoutingSchemaFile' $cab $root
    if ($LASTEXITCODE -ne 0) { throw 'Cabinet extraction failed.' }
    $schema = [xml][IO.File]::ReadAllText((Join-Path $root 'RequestRoutingSchemaFile'))
    $proxy = $schema.configSchema.sectionSchema | Where-Object name -eq 'system.webServer/proxy'
    if (-not $proxy) { throw 'ARR proxy schema missing.' }
    foreach ($name in @('enabled', 'timeout', 'responseBufferLimit')) {
        $attribute = $proxy.attribute | Where-Object name -eq $name
        if (-not $attribute) { throw "Unknown ARR attribute: $name" }
        Write-Host $attribute.OuterXml
    }
} finally {
    $resolved = [IO.Path]::GetFullPath($root)
    if ((Split-Path -Parent $resolved) -eq ([IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')) -and
        (Split-Path -Leaf $resolved) -match '^viraldna-arr-schema-[a-f0-9]{32}$') {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

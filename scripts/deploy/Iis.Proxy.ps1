# Loaded by Deploy.Core. Importing this file never loads IIS or changes Windows.
function Test-IisEnabled($Config) {
    return $Config.PSObject.Properties.Name -contains 'Iis' -and $Config.Iis.Enabled -eq $true
}

function Get-IisManagementMode($Config) {
    if (-not (Test-IisEnabled $Config)) { return 'Disabled' }
    if ($Config.Iis.PSObject.Properties.Name -notcontains 'ManagementMode') { return 'Automatic' }
    if ($Config.Iis.ManagementMode -notin @('Automatic', 'Manual')) {
        throw 'Iis.ManagementMode must be Automatic or Manual.'
    }
    return [string]$Config.Iis.ManagementMode
}

function Test-ManualIis($Config) { return (Get-IisManagementMode $Config) -eq 'Manual' }
function Test-AutomaticIis($Config) { return (Get-IisManagementMode $Config) -eq 'Automatic' }

function Assert-AutomaticIis($Config) {
    if (-not (Test-AutomaticIis $Config)) {
        throw 'Automatic IIS management is disabled. Use IIS Manager; no IIS settings were changed.'
    }
}

function Get-DeployEntryUrl($Config) {
    if (Test-IisEnabled $Config) { return $Config.Iis.SiteUrl }
    return $Config.SiteUrl
}

function Assert-IisConfig($Config) {
    if ($Config.PSObject.Properties.Name -notcontains 'Iis') { return }
    if ($Config.Iis.Enabled -isnot [bool]) { throw 'Iis.Enabled must be a JSON boolean.' }
    if (-not (Test-IisEnabled $Config)) { return }
    $manual = Test-ManualIis $Config
    $private = Get-PrivateRuntimeRoot $Config
    if (-not $private -or (Get-FullPath $Config.Iis.SiteRoot) -ne (Join-Path $private 'iis\site')) {
        throw 'IIS physical root must be the dedicated .server\iis\site proxy directory, never the repository.'
    }
    Assert-NoReparsePoint $Config.Iis.SiteRoot
    foreach ($name in @($Config.Iis.SiteName, $Config.Iis.AppPoolName)) {
        if ($name -notmatch '^[A-Za-z][A-Za-z0-9-]{2,48}$') { throw 'Invalid IIS site/application pool name.' }
    }
    $internal = [Uri]$Config.SiteUrl
    if (-not $internal.IsLoopback -or $internal.Scheme -ne 'http' -or $Config.AllowPublicAccess) {
        throw 'With IIS, the internal SiteUrl must remain loopback HTTP and AllowPublicAccess=false.'
    }
    $uri = [Uri]$Config.Iis.SiteUrl
    if (-not $uri.IsAbsoluteUri -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or
        $uri.AbsolutePath -ne '/' -or $uri.Host -notmatch '^[a-zA-Z0-9.-]+$' -or
        $Config.Iis.AllowPublicAccess -isnot [bool]) { throw 'Invalid IIS SiteUrl.' }
    if ($uri.IsLoopback) {
        if ($uri.Scheme -ne 'http' -or $uri.Host -ne '127.0.0.1') { throw 'Initial IIS SiteUrl uses http://127.0.0.1:<port>.' }
    } else {
        if ($uri.Scheme -ne 'https' -or $uri.Port -ne 443 -or -not $Config.Iis.AllowPublicAccess) {
            throw 'Public IIS requires HTTPS:443 and AllowPublicAccess=true.'
        }
        if (-not $manual -and $Config.Iis.CertificateThumbprint -notmatch '^[a-fA-F0-9]{40}$') {
            throw 'Automatic public IIS requires a certificate thumbprint.'
        }
    }
    if ($manual -and $uri.IsLoopback) {
        throw 'Manual IIS requires its public HTTPS SiteUrl; local setup uses the internal SiteUrl directly.'
    }
    if (@($Config.ApiPort, $Config.ProbePort, $Config.CaddyAdminPort, $internal.Port) -contains $uri.Port) {
        throw 'IIS and internal service ports must be distinct.'
    }
}

function Get-IisBinding($Config) {
    $uri = [Uri]$Config.Iis.SiteUrl
    if ($uri.IsLoopback) { return "127.0.0.1:$($uri.Port):" }
    return "*:443:$($uri.DnsSafeHost)"
}

function New-IisManager {
    $assembly = Join-Path $env:WINDIR 'System32\inetsrv\Microsoft.Web.Administration.dll'
    if (-not (Test-Path -LiteralPath $assembly)) { throw 'IIS is not installed. Run configure-iis.ps1 -InstallComponents first.' }
    if (-not ('Microsoft.Web.Administration.ServerManager' -as [type])) { Add-Type -Path $assembly }
    return New-Object Microsoft.Web.Administration.ServerManager
}

function Get-IisOwnerPath($Config) { return Join-Path (Get-PrivateRuntimeRoot $Config) 'config\iis-owner.json' }

function Assert-IisOwner($Config, $Site) {
    $ownerPath = Get-IisOwnerPath $Config
    Assert-NoReparsePoint $ownerPath
    if (-not (Test-Path -LiteralPath $ownerPath)) { throw 'IIS site name collision or missing ownership record; no existing site will be taken over.' }
    $owner = Read-JsonFile $ownerPath
    if ($owner.RepositoryRoot -ne $Config.RepositoryRoot -or $owner.SiteName -ne $Config.Iis.SiteName -or
        $owner.AppPoolName -ne $Config.Iis.AppPoolName -or $owner.SiteRoot -ne $Config.Iis.SiteRoot -or
        $owner.SiteId -ne $Site.Id -or $Site.Applications.Count -ne 1 -or
        $Site.Applications['/'].ApplicationPoolName -ne $Config.Iis.AppPoolName -or
        $Site.Applications['/'].VirtualDirectories.Count -ne 1 -or
        $Site.Applications['/'].VirtualDirectories['/'].PhysicalPath -ne $Config.Iis.SiteRoot) {
        throw 'IIS ownership/path changed; refusing to manage this site.'
    }
}

function Assert-ManagedIis($Config) {
    Assert-AutomaticIis $Config
    Assert-IisConfig $Config
    $manager = New-IisManager
    try {
        $site = $manager.Sites[$Config.Iis.SiteName]
        if ($null -eq $site) { throw 'Managed IIS site is missing. Run configure-iis.ps1 before building/starting.' }
        Assert-IisOwner $Config $site
        $uri = [Uri]$Config.Iis.SiteUrl
        if ($site.Bindings.Count -ne 1 -or $site.Bindings[0].BindingInformation -ne (Get-IisBinding $Config) -or
            $site.Bindings[0].Protocol -ne $uri.Scheme) { throw 'IIS bindings differ from config; run configure-iis.ps1 while stopped.' }
        if (-not $uri.IsLoopback) {
            $actualHash = [BitConverter]::ToString($site.Bindings[0].CertificateHash).Replace('-', '')
            if ($actualHash -ne $Config.Iis.CertificateThumbprint -or [int]$site.Bindings[0].SslFlags -ne 1) {
                throw 'IIS certificate/SNI differs from the configured HTTPS binding.'
            }
        }
        $proxyFile = Join-Path $Config.Iis.SiteRoot 'web.config'
        Assert-NoReparsePoint $proxyFile
        if (-not (Test-Path -LiteralPath $proxyFile) -or
            [IO.File]::ReadAllText($proxyFile) -cne (Get-IisWebConfig $Config)) {
            throw 'IIS proxy configuration differs; run configure-iis.ps1 while stopped.'
        }
    } finally { $manager.Dispose() }
}

function Stop-ManagedIis($Config) {
    Assert-AutomaticIis $Config
    Assert-ManagedIis $Config
    $manager = New-IisManager
    try {
        $site = $manager.Sites[$Config.Iis.SiteName]
        $site.ServerAutoStart = $false
        $manager.CommitChanges()
        if ($site.State.ToString() -eq 'Started') { $null = $site.Stop() }
        if ($site.State.ToString() -ne 'Stopped') { throw 'Managed IIS site has not stopped; wait and retry.' }
    } finally { $manager.Dispose() }
}

function Start-ManagedIis($Config) {
    Assert-AutomaticIis $Config
    Assert-ManagedIis $Config
    $manager = New-IisManager
    try {
        $pool = $manager.ApplicationPools[$Config.Iis.AppPoolName]
        if ($pool.State.ToString() -eq 'Stopped') { $null = $pool.Start() }
        $null = $manager.Sites[$Config.Iis.SiteName].Start()
    } finally { $manager.Dispose() }
}

function Enable-ManagedIisAutostart($Config) {
    Assert-AutomaticIis $Config
    Assert-ManagedIis $Config
    $manager = New-IisManager
    try {
        $manager.Sites[$Config.Iis.SiteName].ServerAutoStart = $true
        $manager.CommitChanges()
    } finally { $manager.Dispose() }
}

function Get-IisWebConfig($Config) {
    return Expand-DeployTemplate 'iis-web.config.template' @{ UPSTREAM = $Config.SiteUrl.TrimEnd('/') } -Xml
}

function Assert-ManualIisBootstrapStopped($Config) {
    if (-not (Test-ManualIis $Config)) { throw 'Expected manual IIS mode.' }
    # Read-only: never CommitChanges, Start, Stop or change bindings here.
    # Keep an uninitialized application off the public proxy. The API also
    # independently requires a loopback client AND Host for account setup.
    $manager = New-IisManager
    try {
        $site = $manager.Sites[$Config.Iis.SiteName]
        if ($null -eq $site) { throw 'Manual IIS site was not found. Check Iis.SiteName; no site was created.' }
        if ($site.State.ToString() -ne 'Stopped') {
            throw 'Account setup is incomplete. Stop ONLY the ViralDNA site in IIS Manager, then retry. IIS was not changed.'
        }
    } finally { $manager.Dispose() }
}

function Initialize-ManagedIis($Config) {
    Assert-AutomaticIis $Config
    Assert-Administrator
    Assert-IisConfig $Config
    if (-not (Test-IisEnabled $Config)) { throw 'Enable IIS in the deployment configuration first.' }
    $null = Read-ProductionEnv $Config
    $manager = New-IisManager
    try {
        $site = $manager.Sites[$Config.Iis.SiteName]
        $pool = $manager.ApplicationPools[$Config.Iis.AppPoolName]
        if ($null -ne $site) {
            Assert-IisOwner $Config $site
            if ($site.State.ToString() -ne 'Stopped') { throw 'Stop ViralDNA using menu option 4 before changing IIS configuration.' }
        } elseif ($null -ne $pool) { throw 'IIS application pool name collision; no existing pool will be taken over.' }
        foreach ($other in $manager.Sites) {
            if ($other.Name -eq $Config.Iis.SiteName) { continue }
            if (@($other.Bindings | Where-Object BindingInformation -eq (Get-IisBinding $Config)).Count) {
                throw 'An existing IIS site has this binding; it has not been changed.'
            }
        }
        if ($null -ne $pool) {
            foreach ($other in $manager.Sites) {
                if ($other.Name -ne $Config.Iis.SiteName -and
                    @($other.Applications | Where-Object ApplicationPoolName -eq $Config.Iis.AppPoolName).Count) {
                    throw 'The ViralDNA pool is shared with another IIS site; separate it manually first.'
                }
            }
        }
        $uri = [Uri]$Config.Iis.SiteUrl
        $certificate = $null
        if (-not $uri.IsLoopback) {
            $certPath = 'Cert:\LocalMachine\My\' + $Config.Iis.CertificateThumbprint
            $certificate = Get-Item -LiteralPath $certPath -ErrorAction Stop
            if (-not $certificate.HasPrivateKey -or $certificate.NotAfter -le (Get-Date) -or $certificate.NotBefore -gt (Get-Date)) {
                throw 'The IIS certificate must be valid and have its private key in LocalMachine\My.'
            }
        }
        $appHost = $manager.GetApplicationHostConfiguration()
        # ARR proxy is a server-level setting. Component/configuration entry warns
        # about its scope; unrelated IIS sites and application pools are not stopped.
        $proxy = $appHost.GetSection('system.webServer/proxy')
        $proxy['enabled'] = $true
        $proxy['timeout'] = [TimeSpan]::FromMinutes(30)
        $proxy['responseBufferLimit'] = [uint32]0
        $root = $Config.Iis.SiteRoot
        Assert-NoReparsePoint $root
        $proxyFile = Join-Path $root 'web.config'
        if ($null -eq $site -and (Test-Path -LiteralPath $root) -and @(Get-ChildItem -LiteralPath $root -Force).Count) {
            throw 'Unowned IIS proxy directory is not empty; no files were overwritten.'
        }
        $null = New-Item -ItemType Directory -Path $root -Force
        if ($null -eq $pool) {
            $pool = $manager.ApplicationPools.Add($Config.Iis.AppPoolName)
            $pool.ManagedRuntimeVersion = ''
            $pool.ProcessModel.IdentityType = 4 # Built-in ApplicationPoolIdentity; no Windows login account is created.
        }
        if ($null -eq $site) {
            $site = $manager.Sites.Add($Config.Iis.SiteName, $uri.Scheme, (Get-IisBinding $Config), $root)
        }
        $site.ServerAutoStart = $false
        $site.Applications['/'].ApplicationPoolName = $Config.Iis.AppPoolName
        $site.Bindings.Clear()
        $binding = $site.Bindings.Add((Get-IisBinding $Config), $uri.Scheme)
        if ($certificate) {
            $binding.CertificateHash = $certificate.GetCertHash()
            $binding.CertificateStoreName = 'My'
            $binding.SslFlags = 1 # SNI, scoped by hostname; do not take over all :443 sites.
        }
        $allowed = $appHost.GetSection('system.webServer/rewrite/allowedServerVariables', $Config.Iis.SiteName).GetCollection()
        foreach ($name in @('HTTP_X_FORWARDED_PROTO', 'HTTP_X_FORWARDED_HOST', 'HTTP_X_FORWARDED_FOR')) {
            if (@($allowed | Where-Object { $_['name'] -eq $name }).Count -eq 0) {
                $entry = $allowed.CreateElement('add'); $entry['name'] = $name; $allowed.Add($entry)
            }
        }
        # Put locked IIS sections in site-scoped applicationHost.config locations.
        $filter = $appHost.GetSection('system.webServer/security/requestFiltering', $Config.Iis.SiteName)
        $filter.GetChildElement('requestLimits')['maxAllowedContentLength'] = [uint32]2147483648
        $appHost.GetSection('system.webServer/httpErrors', $Config.Iis.SiteName)['existingResponse'] = 'PassThrough'
        $compression = $appHost.GetSection('system.webServer/urlCompression', $Config.Iis.SiteName)
        $compression['doStaticCompression'] = $false
        $compression['doDynamicCompression'] = $false
        $cache = $appHost.GetSection('system.webServer/caching', $Config.Iis.SiteName)
        $cache['enabled'] = $false; $cache['enableKernelCache'] = $false
        Write-AtomicText $proxyFile (Get-IisWebConfig $Config)
        $manager.CommitChanges()
        Write-AtomicJson (Get-IisOwnerPath $Config) @{
            RepositoryRoot = $Config.RepositoryRoot; SiteName = $site.Name; SiteId = $site.Id
            AppPoolName = $Config.Iis.AppPoolName; SiteRoot = $root
        }
        # Only the proxy directory is readable by the built-in IIS worker group.
        Set-PrivateDirectoryAcl $root 'S-1-5-32-568'
        Write-Host 'IIS configured and left STOPPED. Build/start from the ViralDNA deployment menu next.'
    } finally { $manager.Dispose() }
}

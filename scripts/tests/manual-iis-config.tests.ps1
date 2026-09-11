# Offline, read-only checks. This is not an IIS runtime/integration test.
param([string]$PackageRoot = (Join-Path $PSScriptRoot '..\..\docs\deployment\examples\manual-iis-viraldnastudio'))

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:assertions = 0

function Assert-Config([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:assertions++
}

function Read-ConfigXml([string]$Name) {
    $document = New-Object System.Xml.XmlDocument
    $document.XmlResolver = $null
    $document.LoadXml([IO.File]::ReadAllText((Join-Path $PackageRoot $Name), [Text.Encoding]::UTF8))
    return $document
}

$web = Read-ConfigXml 'web.config'
$site = Read-ConfigXml 'applicationHost.ViralDNA.location.xml'
$rules = @($web.SelectNodes('/configuration/system.webServer/rewrite/rules/rule'))
Assert-Config ($rules.Count -eq 3) 'Expected redirect, HTTPS proxy and reject rules.'
Assert-Config ($web.SelectNodes('/configuration/system.webServer/rewrite/rules/clear').Count -eq 1) 'Clear inherited distributed rules only at this site.'
Assert-Config ($web.SelectNodes('//globalRules | //allowedServerVariables | //proxy | //sites | //bindings').Count -eq 0) 'web.config must not contain server-level settings or bindings.'
Assert-Config ($site.DocumentElement.Name -eq 'location' -and $site.DocumentElement.GetAttribute('path') -ceq 'ViralDNA') 'Reference fragment must target only ViralDNA.'
Assert-Config ($site.SelectNodes('//proxy | //sites | //bindings | //applicationPools').Count -eq 0) 'Reference fragment must not mutate shared ARR, bindings or pools.'

$requiredHeaders = @('HTTP_X_FORWARDED_PROTO', 'HTTP_X_FORWARDED_HOST', 'HTTP_X_FORWARDED_FOR')
$allowedHeaders = @($site.SelectNodes('//allowedServerVariables/add') | ForEach-Object { $_.GetAttribute('name') })
Assert-Config ((($allowedHeaders | Sort-Object) -join ',') -ceq (($requiredHeaders | Sort-Object) -join ',')) 'Allowed headers differ from the required headers.'
Assert-Config ($site.SelectSingleNode('//requestLimits').GetAttribute('maxAllowedContentLength') -eq '2147483648') 'Unexpected per-request upload limit.'
Assert-Config ($site.SelectSingleNode('//httpErrors').GetAttribute('existingResponse') -eq 'PassThrough') 'Preserve API error responses.'
foreach ($setting in @(@('urlCompression', 'doStaticCompression'), @('urlCompression', 'doDynamicCompression'), @('caching', 'enabled'), @('caching', 'enableKernelCache'))) {
    Assert-Config ($site.SelectSingleNode('//' + $setting[0]).GetAttribute($setting[1]) -eq 'false') ('Disable site setting: ' + ($setting -join '.'))
}

# Evaluate only the subset of URL Rewrite used by this configuration.
# Actual IIS decoding, ARR streaming, TLS, ACLs and binding behavior require
# server-side acceptance tests and are deliberately not simulated here.
function Resolve-TestRule([string]$RequestHost, [string]$Https, [string]$RequestPath = '', [string]$Query = '', [string]$RemoteAddress = '203.0.113.24') {
    $serverValues = @{
        '{HTTP_HOST}' = $RequestHost
        '{HTTPS}' = $Https
        '{REMOTE_ADDR}' = $RemoteAddress
    }
    foreach ($rule in $rules) {
        $ruleMatch = [regex]::Match($RequestPath, $rule.SelectSingleNode('match').GetAttribute('url'), [Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if (-not $ruleMatch.Success) { continue }
        $matched = $true
        $conditionMatch = $null
        foreach ($condition in $rule.SelectNodes('conditions/add')) {
            $inputName = $condition.GetAttribute('input')
            if (-not $serverValues.ContainsKey($inputName)) { throw "Unsupported test condition: $inputName" }
            $conditionMatch = [regex]::Match($serverValues[$inputName], $condition.GetAttribute('pattern'), [Text.RegularExpressions.RegexOptions]::IgnoreCase)
            if (-not $conditionMatch.Success) { $matched = $false; break }
        }
        if (-not $matched) { continue }
        $action = $rule.SelectSingleNode('action')
        $target = $action.GetAttribute('url').Replace('{R:1}', $ruleMatch.Groups[1].Value)
        if ($null -ne $conditionMatch) { $target = $target.Replace('{C:1}', $conditionMatch.Groups[1].Value) }
        if ($Query -and $action.GetAttribute('appendQueryString') -eq 'true') { $target += '?' + $Query }
        $headers = @{}
        foreach ($header in $rule.SelectNodes('serverVariables/set')) {
            $value = $header.GetAttribute('value')
            if ($serverValues.ContainsKey($value)) { $value = $serverValues[$value] }
            $headers[$header.GetAttribute('name')] = $value
        }
        return @{
            Type = $action.GetAttribute('type'); Target = $target
            RedirectType = $action.GetAttribute('redirectType')
            StatusCode = $action.GetAttribute('statusCode'); Headers = $headers
        }
    }
    throw 'No rule matched.'
}

foreach ($requestName in @('viraldnastudio.com', 'www.viraldnastudio.com', 'viraldnastudio.com:80', 'www.viraldnastudio.com:80', 'VIRALDNASTUDIO.COM')) {
    $result = Resolve-TestRule $requestName 'OFF' 'api/v1/assets' 'page=1&name=a%20b'
    Assert-Config ($result.Type -eq 'Redirect' -and $result.RedirectType -eq 'Temporary') 'HTTP must use a method-preserving temporary redirect.'
    Assert-Config ($result.Target -ceq ('https://' + ($requestName -replace ':80$', '') + '/api/v1/assets?page=1&name=a%20b')) 'HTTP redirect must preserve the validated hostname, path and query.'
    Assert-Config ($result.Headers.Count -eq 0) 'HTTP must not proxy a request to the API.'
}

foreach ($requestName in @('viraldnastudio.com', 'www.viraldnastudio.com', 'viraldnastudio.com:443', 'www.viraldnastudio.com:443', 'VIRALDNASTUDIO.COM')) {
    foreach ($requestPath in @('', 'login', 'projects/123/storyboards', 'api/v1/assets/123/content')) {
        $result = Resolve-TestRule $requestName 'ON' $requestPath 'download=1&label=a%20b'
        Assert-Config ($result.Type -eq 'Rewrite' -and $result.Target -ceq ('http://127.0.0.1:8080/' + $requestPath + '?download=1&label=a%20b')) 'HTTPS proxy target/path/query mismatch.'
        Assert-Config ($result.Headers.Count -eq 3 -and $result.Headers.HTTP_X_FORWARDED_PROTO -ceq 'https' -and
            $result.Headers.HTTP_X_FORWARDED_HOST -ceq $requestName -and $result.Headers.HTTP_X_FORWARDED_FOR -ceq '203.0.113.24') 'Forwarded headers must use the IIS connection and validated Host.'
    }
}

foreach ($requestName in @('old.example.com', 'evil.example', 'viraldnastudio.com.evil.example', 'evilviraldnastudio.com', 'viraldnastudio.com@evil.example', 'api.viraldnastudio.com', '127.0.0.1:8081', 'localhost:8081', 'viraldnastudio.com:8080', '')) {
    foreach ($httpsValue in @('ON', 'OFF')) {
        $result = Resolve-TestRule $requestName $httpsValue 'login'
        Assert-Config ($result.Type -eq 'CustomResponse' -and $result.StatusCode -eq '400' -and $result.Headers.Count -eq 0) 'Unexpected hostname/port must not be proxied or reflected in a redirect.'
    }
}
foreach ($invalidProtocol in @(@('viraldnastudio.com:80', 'ON'), @('viraldnastudio.com:443', 'OFF'), @('viraldnastudio.com', ''))) {
    $result = Resolve-TestRule $invalidProtocol[0] $invalidProtocol[1]
    Assert-Config ($result.StatusCode -eq '400') 'Reject mismatched port/protocol.'
}

foreach ($rule in $rules) {
    Assert-Config ($rule.GetAttribute('stopProcessing') -ceq 'true') 'Every rule must stop subsequent processing.'
    foreach ($condition in $rule.SelectNodes('conditions/add')) {
        Assert-Config ($condition.GetAttribute('input') -notmatch 'FORWARDED') 'Routing must not trust a client-supplied forwarded protocol.'
    }
}

$envLines = @([IO.File]::ReadAllLines((Join-Path $PackageRoot 'api.env.merge.txt'), [Text.Encoding]::UTF8) | Where-Object { $_ -match '^[A-Z][A-Z0-9_]*=' })
Assert-Config ($envLines.Count -eq 1 -and $envLines[0].StartsWith('VIRAL_DNA_CORS_ORIGINS=')) 'The env fragment may change only the CORS setting.'
$origins = @($envLines[0].Substring('VIRAL_DNA_CORS_ORIGINS='.Length).Split(','))
foreach ($origin in @('http://127.0.0.1:8080', 'http://127.0.0.1:18080', 'http://127.0.0.1:8081', 'https://viraldnastudio.com', 'https://www.viraldnastudio.com')) {
    Assert-Config ($origins -ccontains $origin) ('Missing required origin: ' + $origin)
}
Assert-Config ($origins.Count -eq 5 -and $origins -notcontains '*') 'Unexpected or wildcard CORS origin.'
$readme = [IO.File]::ReadAllText((Join-Path $PackageRoot 'README.md'), [Text.Encoding]::UTF8)
foreach ($notice in @('04-configure-iis.bat', '05-run.bat', 'Iis.Enabled=false', 'http://127.0.0.1:8080/login', 'initialized', 'applicationHost.config')) {
    Assert-Config ($readme.Contains($notice)) ('Missing manual handoff prerequisite: ' + $notice)
}
Write-Output "Manual IIS configuration checks passed: $script:assertions assertions. No IIS, services or external state changed."

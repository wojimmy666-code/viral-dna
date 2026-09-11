[CmdletBinding()]
param(
    [ValidateSet('menu', 'update', 'build', 'start', 'stop', 'status', 'check', 'verify-public')]
    [string]$Action = 'menu',
    [string]$Config = $env:VIRAL_DNA_DEPLOY_CONFIG,
    [switch]$Yes,
    [switch]$Snapshot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Deploy.Core.psm1') -Force -DisableNameChecking

function Show-DeployStatus($Settings) {
    Write-Host ''
    Write-Host 'ViralDNA 正式服务器部署' -ForegroundColor Cyan
    Write-Host "代码目录：$($Settings.RepositoryRoot)"
    Write-Host "访问地址：$(Get-DeployEntryUrl $Settings)"
    if (Test-ManualIis $Settings) {
        Write-Host 'IIS：手动管理，菜单不会修改或启停 IIS。'
        Write-Host "本机初始化／检查：$($Settings.SiteUrl.TrimEnd('/'))/login"
        Write-Host '首次初始化完成后按 3，随后手动启动 IIS 并运行 06-check-https.bat。'
    }
    foreach ($role in @('api', 'web')) {
        $service = Get-DeployService $Settings $role
        $state = if ($null -eq $service) { '未注册' } else { $service.State }
        Write-Host "${role}: $state"
    }
    $active = Join-Path $Settings.DeploymentRoot 'active.json'
    if (Test-Path -LiteralPath $active) { Write-Host "最近通过启动检查的版本：$((Read-JsonFile $active).Id)" }
}

function Invoke-SelectedAction($Settings, [string]$Selected, [bool]$NonInteractive) {
    $context = @{ Release = $null; Credential = $null }
    $steps = @{
        Preflight = {
            Write-DeployLog 'Checking configuration, service ownership and prerequisites...'
            Test-DeployPrerequisites $Settings $Selected
            if ($Selected -ne 'stop') {
                $missing = @('api', 'web') | Where-Object { $null -eq (Get-DeployService $Settings $_) }
                if ($missing) {
                    if ($NonInteractive) { throw 'First installation requires an interactive menu to enter the service account password.' }
                    Write-Host "首次注册服务，运行账户：$($Settings.ServiceAccount)（密码只交给 Windows 服务管理器，不写入文件）"
                    $password = Read-Host '请输入该 Windows 运行账户的密码' -AsSecureString
                    $context.Credential = New-Object Management.Automation.PSCredential($Settings.ServiceAccount, $password)
                }
            }
        }.GetNewClosure()
        Stop = { Write-DeployLog 'Stopping this deployment before proceeding...'; Stop-DeployServices $Settings }.GetNewClosure()
        Update = { Write-DeployLog 'Updating main from GitHub over SSH...'; Update-DeployRepository $Settings }.GetNewClosure()
        Build = { $context.Release = New-DeployRelease $Settings }.GetNewClosure()
        Configure = {
            if ($null -eq $context.Release) { $context.Release = Get-LastDeployRelease $Settings }
            Configure-DeployServices $Settings $context.Release $context.Credential
        }.GetNewClosure()
        Start = { Start-DeployServices $Settings $context.Release }.GetNewClosure()
    }
    try {
        Invoke-DeployWorkflow $Selected $steps
        if ($Selected -eq 'stop') { Write-DeployLog 'API 与 Web 均已关闭；项目、账号和媒体数据未删除。' }
    } finally {
        if ($context.Credential) { $context.Credential.Password.Dispose(); $context.Credential = $null }
    }
}

try {
    if ($env:OS -ne 'Windows_NT') { throw 'This entry is for Windows Server with Windows PowerShell 5.1.' }
    if ([string]::IsNullOrWhiteSpace($Config)) {
        $singleRootConfig = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) '.server\config\deploy.json'
        $Config = if (Test-Path -LiteralPath $singleRootConfig) { $singleRootConfig } else { Join-Path $env:ProgramData 'ViralDNA\deployment\config.json' }
    }
    $settings = Read-DeployConfig $Config
    if ($Action -eq 'status') { Show-DeployStatus $settings; return }
    if ($Action -eq 'verify-public') {
        $entry = Test-DeployPublicEntry $settings
        Write-Host "HTTPS 入口检查通过：$entry"
        Write-Host '已核对 TLS、当前版本和账号初始化状态；未修改或启停任何服务。登录、上传和实时进度仍需人工验收。'
        return
    }
    if ($Action -eq 'check') {
        Test-DeployPrerequisites $settings 'check'
        Write-Host '配置和基础检查通过。此操作未停止、启动或注册服务，也未访问 GitHub。'
        return
    }
    if ($Action -ne 'menu' -and -not $Yes) { throw 'Options update/build/start/stop stop current services. Pass -Yes to acknowledge downtime, or use the interactive menu.' }
    Assert-Administrator
    foreach ($role in @('api', 'web')) { Assert-ManagedService $settings $role (Get-DeployService $settings $role) }
    Initialize-DeployRuntime $settings
    if (-not $Snapshot) {
        # Run a complete private copy so git fast-forward cannot replace the
        # active controller, module or templates halfway through a menu action.
        $copyRoot = Join-Path $settings.DeploymentRoot ('controllers\' + [Guid]::NewGuid().ToString('N'))
        $null = New-Item -ItemType Directory -Path $copyRoot
        foreach ($item in Get-ChildItem -LiteralPath $PSScriptRoot) {
            Copy-Item -LiteralPath $item.FullName -Destination $copyRoot -Recurse
        }
        & (Join-Path $copyRoot 'deploy-server.ps1') -Action $Action -Config $Config -Yes:$Yes -Snapshot
        return
    }
    $deploymentLock = Open-DeployLock $settings
    try {
        $log = Join-Path $settings.DeploymentRoot ('logs\deploy-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8) + '.log')
        Set-DeployLog $log
        Write-Host "本次部署日志：$log"
        if ($Action -ne 'menu') { Invoke-SelectedAction $settings $Action ([bool]$Yes); return }
        while ($true) {
            Show-DeployStatus $settings
            Write-Host ''
            Write-Host '1. 从 GitHub 下载 + 编译 + 启动'
            Write-Host '2. 编译 + 启动'
            Write-Host '3. 启动（最近一次成功构建）'
            Write-Host '4. 关闭'
            Write-Host '0. 退出菜单（不关闭服务）'
            Write-Host '注意：1、2、3 会先关闭本项目服务；正在生成的任务可能中断，上游任务不保证自动取消。' -ForegroundColor Yellow
            Write-Host '按数字选择：' -NoNewline
            $key = [Console]::ReadKey($true).KeyChar.ToString()
            Write-Host $key
            if ($key -eq '0') { break }
            $choices = @{ '1' = 'update'; '2' = 'build'; '3' = 'start'; '4' = 'stop' }
            if (-not $choices.ContainsKey($key)) { continue }
            try {
                Invoke-SelectedAction $settings $choices[$key] $false
            } catch {
                Write-DeployLog "操作失败：$($_.Exception.Message)"
                Write-Host '没有强制杀进程、覆盖本地 Git 修改或回滚业务数据。请检查日志后再操作。' -ForegroundColor Yellow
            }
            Write-Host '按任意键返回菜单（退出后重新打开可加载新版本部署控制器）…'
            $null = [Console]::ReadKey($true)
        }
    } finally { $deploymentLock.Dispose() }
} catch {
    Write-Host "[ViralDNA] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host '首次配置说明：docs/deployment/Windows服务器一键部署.md'
    exit 1
}

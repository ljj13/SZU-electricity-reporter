<#
.SYNOPSIS
  把 szu-electricity-reporter 部署到 EAIDK-310 板（Windows 侧一键脚本）。

.DESCRIPTION
  1) 将仓库文件（不含 .venv / 日志 / config.json）打包到板上 staging 目录
  2) 在板上执行 deploy/board-install.sh：备份 -> 部署 -> 启动专用出口 -> 装 cron -> 自测
  说明：不传输、不覆盖 config.json（含 SendKey）；订阅地址由板端安装脚本从 ShellCrash
        运行配置中读取，不经过本仓库。

.EXAMPLE
  pwsh -File deploy/deploy.ps1 -Board 172.31.180.4
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Board,
    [string]$User = 'Fog',
    [string]$KeyPath = "$HOME\.ssh\id_ed25519_eaidk310_codex",
    [string]$RemoteStage = '/home/Fog/.local/share/szu-stage'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$sshArgs = @('-i', $KeyPath, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new')
$target = "$User@$Board"

Write-Host "== 1/3 上传文件到 $target : $RemoteStage =="
& ssh @sshArgs $target "rm -rf '$RemoteStage' && mkdir -p '$RemoteStage/deploy' '$RemoteStage/tests'"
if ($LASTEXITCODE -ne 0) { throw 'ssh 连接失败' }

$files = @()
$files += Get-ChildItem -Path "$repo\*" -File -Force |
    Where-Object { $_.Extension -in '.py', '.md', '.json', '.txt', '.sh' -or $_.Name -eq '.gitignore' }
$files += Get-ChildItem -Path (Join-Path $repo 'tests') -File -Filter '*.py'
$files += Get-ChildItem -Path (Join-Path $repo 'deploy') -File

foreach ($f in $files) {
    $rel = $f.FullName.Substring($repo.Length + 1).Replace('\', '/')
    $remote = "$RemoteStage/$rel"
    & scp -i $KeyPath -o BatchMode=yes $f.FullName "${target}:$remote"
    if ($LASTEXITCODE -ne 0) { throw "scp 失败: $rel" }
}
Write-Host "   已传输 $($files.Count) 个文件"

Write-Host '== 2/3 板端安装 =='
& ssh @sshArgs $target "bash '$RemoteStage/deploy/board-install.sh' '$RemoteStage'"
if ($LASTEXITCODE -ne 0) { throw 'board-install.sh 失败' }

Write-Host '== 3/3 出口状态 =='
& ssh @sshArgs $target 'bash $HOME/.local/lib/szu-egress/status.sh'
Write-Host '完成。建议接着执行:  ssh <board> "cd /home/Fog/szu-electricity-reporter && .venv/bin/python main.py --dry-run --once"'

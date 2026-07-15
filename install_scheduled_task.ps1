param(
    [string]$PythonwPath = "G:\Environments\Python12\pythonw.exe",
    [ValidateRange(0, 23)]
    [int]$DailyHour = 9
)

$ErrorActionPreference = 'Stop'
$taskName = 'SZU Electricity Reporter'
$projectDir = $PSScriptRoot
$mainScript = Join-Path $projectDir 'main.py'

if (-not (Test-Path -LiteralPath $PythonwPath)) {
    $pythonw = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if (-not $pythonw) {
        throw 'pythonw.exe was not found. Pass its path with -PythonwPath.'
    }
    $PythonwPath = $pythonw.Source
}
if (-not (Test-Path -LiteralPath $mainScript)) {
    throw "main.py was not found: $mainScript"
}

$arguments = '"{0}" --once' -f $mainScript
$action = New-ScheduledTaskAction `
    -Execute $PythonwPath `
    -Argument $arguments `
    -WorkingDirectory $projectDir

$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$triggers = @(
    New-ScheduledTaskTrigger -AtLogOn -User $currentUser
    New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours($DailyHour))
)
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description 'Queries dorm electricity at logon and once per day.' `
    -Force | Out-Null

$startup = [Environment]::GetFolderPath('Startup')
$legacyShortcut = Join-Path $startup 'szu-electricity-reporter.lnk'
if (Test-Path -LiteralPath $legacyShortcut) {
    Remove-Item -LiteralPath $legacyShortcut -Force
}

Write-Host "Scheduled task installed: $taskName"
Write-Host "Triggers: at logon and daily at $($DailyHour.ToString('00')):00"
Write-Host 'The legacy Startup shortcut has been removed.'

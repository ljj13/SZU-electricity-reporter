$ErrorActionPreference = 'Stop'
$taskName = 'SZU Electricity Reporter'

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Scheduled task removed: $taskName"
} else {
    Write-Host "Scheduled task not found: $taskName"
}

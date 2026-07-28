# remove_autostart.ps1
# Unregister the VoiceJournal scheduled task.
# Run as Administrator.

$TaskName = "VoiceJournal"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Task '$TaskName' removed."
} else {
    Write-Host "Task '$TaskName' not found (already removed or never registered)."
}

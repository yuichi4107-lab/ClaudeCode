# remove_autostart_startupfolder.ps1
# Removes the Startup-folder autostart shortcut for voice-journal.
# Windows PowerShell 5.1 compatible. No administrator rights required.

$Startup = [Environment]::GetFolderPath('Startup')
$LnkPath = Join-Path $Startup "VoiceJournal.lnk"
if (Test-Path $LnkPath) {
    Remove-Item $LnkPath -Force
    Write-Host "Removed startup shortcut: $LnkPath"
} else {
    Write-Host "Startup shortcut not found (already removed or never created): $LnkPath"
}

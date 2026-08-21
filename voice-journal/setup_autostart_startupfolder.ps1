# setup_autostart_startupfolder.ps1
# No-admin autostart: places a shortcut in the user's Startup folder so
# voice-journal launches (hidden, via pythonw) at every logon.
# Windows PowerShell 5.1 compatible. No administrator rights required.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ServicePy = Join-Path $ScriptDir "service.py"

# --- Resolve pythonw.exe ---
$PythonW = $null
$cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if ($cmd) { $PythonW = $cmd.Source }
if (-not $PythonW) {
    $pyCmd = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyCmd) {
        $candidate = Join-Path (Split-Path $pyCmd.Source) "pythonw.exe"
        if (Test-Path $candidate) { $PythonW = $candidate }
    }
}
if (-not $PythonW) {
    $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $candidate = Join-Path (Split-Path $pythonCmd.Source) "pythonw.exe"
        if (Test-Path $candidate) { $PythonW = $candidate }
    }
}
if (-not $PythonW -or -not (Test-Path $PythonW)) {
    Write-Error "pythonw.exe not found. Install Python and ensure it is on PATH."
    exit 1
}

$Startup = [Environment]::GetFolderPath('Startup')
$LnkPath = Join-Path $Startup "VoiceJournal.lnk"

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($LnkPath)
$sc.TargetPath       = $PythonW
$sc.Arguments        = ('"{0}"' -f $ServicePy)
$sc.WorkingDirectory = $ScriptDir
$sc.WindowStyle      = 7   # minimized (pythonw shows no window anyway)
$sc.Description       = "voice-journal continuous audio transcription"
$sc.Save()

Write-Host "Startup shortcut created: $LnkPath"
Write-Host "voice-journal will start automatically at the next logon."
Write-Host "Python : $PythonW"
Write-Host "Script : $ServicePy"

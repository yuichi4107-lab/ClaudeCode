# setup_autostart.ps1
# Register VoiceJournal as a Windows Task Scheduler task (logon trigger).
# Windows PowerShell 5.1 compatible. Runs as the current user, no elevation needed.
# If registration fails with access denied, run this script as Administrator.

$ErrorActionPreference = "Stop"
$TaskName  = "VoiceJournal"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ServicePy = Join-Path $ScriptDir "service.py"

# --- Resolve pythonw.exe (PS 5.1 compatible: no null-conditional operator) ---
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

$Action = New-ScheduledTaskAction `
    -Execute $PythonW `
    -Argument ('"{0}"' -f $ServicePy) `
    -WorkingDirectory $ScriptDir

$Trigger = New-ScheduledTaskTrigger -AtLogOn

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$Principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "voice-journal: continuous audio transcription service" `
        -Force | Out-Null
    Write-Host "Task '$TaskName' registered. It will start at next logon."
    Write-Host "Python: $PythonW"
    Write-Host "Script: $ServicePy"
} catch {
    Write-Error ("Failed to register task: {0}" -f $_.Exception.Message)
    Write-Host "If this is an access-denied error, right-click the script and choose 'Run as administrator'."
    exit 1
}

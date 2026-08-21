# Launch Chrome with CDP enabled in a dedicated profile.
# Sign in to Google normally in this Chrome (no automation flags = no Google bot detection).
# After signing in, run: python scripts/setup_auth.py  (in another terminal).

$ProfileDir = Join-Path $env:LOCALAPPDATA "notebooklm-sync-chrome-profile"
$Port = 9222

$candidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
)

$chrome = $null
foreach ($c in $candidates) {
    if (Test-Path $c) { $chrome = $c; break }
}

if (-not $chrome) {
    Write-Host "[ERROR] Chrome not found." -ForegroundColor Red
    foreach ($c in $candidates) { Write-Host "  searched: $c" }
    exit 1
}

$alreadyRunning = $false
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/json/version" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    $alreadyRunning = $true
} catch {
    $alreadyRunning = $false
}

if ($alreadyRunning) {
    Write-Host "[WARN] CDP Chrome already running on port $Port. Skipping launch." -ForegroundColor Yellow
    Write-Host "       Next: python scripts/setup_auth.py" -ForegroundColor Yellow
    exit 0
}

if (-not (Test-Path $ProfileDir)) {
    New-Item -ItemType Directory -Path $ProfileDir -Force | Out-Null
}

Write-Host "[INFO] exe: $chrome"
Write-Host "[INFO] profile: $ProfileDir"
Write-Host "[INFO] CDP port: $Port"
Write-Host ""
Write-Host "[NEXT STEPS]" -ForegroundColor Green
Write-Host "  1. In the Chrome that opens, sign in to your Google account"
Write-Host "  2. Create 2 notebooks on NotebookLM: 'AI sennin' and 'AX'"
Write-Host "  3. Copy each notebook URL and send it to the assistant"
Write-Host "  4. Keep Chrome OPEN. In another terminal, run:"
Write-Host "     python scripts/setup_auth.py"
Write-Host ""

Start-Process -FilePath $chrome -ArgumentList @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=$ProfileDir",
    "--no-first-run",
    "--no-default-browser-check",
    "https://notebooklm.google.com"
)

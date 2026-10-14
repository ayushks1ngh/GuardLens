# Attach a USB / laptop webcam to WSL so GuardLens can use it.  Run in an ADMINISTRATOR PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\attach-webcam.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\windows\attach-webcam.ps1 -BusId 2-7
# Needs usbipd-win:  winget install --interactive --exact dorssel.usbipd-win
param([string]$BusId = "")

if (-not (Get-Command usbipd -ErrorAction SilentlyContinue)) {
    Write-Host "usbipd is not installed. Run:  winget install --interactive --exact dorssel.usbipd-win  (then reopen PowerShell)" -ForegroundColor Yellow
    exit 1
}
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Open PowerShell as Administrator and run this again." -ForegroundColor Yellow
    exit 1
}

if (-not $BusId) {
    $lines = usbipd list | Select-String -Pattern "cam|video|uvc|imaging" -CaseSensitive:$false
    if (-not $lines) { Write-Host "No webcam found. Here is what usbipd sees:"; usbipd list; exit 1 }
    $BusId = ($lines | Select-Object -First 1).ToString().Trim().Split(" ")[0]
    Write-Host "Using the first camera found: $BusId  ($($lines | Select-Object -First 1))"
}

usbipd bind --busid $BusId
Write-Host "Attaching $BusId to WSL (keeps re-attaching while this window stays open; Ctrl+C to stop)..."
Write-Host "While attached, Windows apps cannot use the camera.  To give it back:  usbipd detach --busid $BusId"
Write-Host "Then, inside WSL, once:  sudo modprobe uvcvideo   and check:  ls /dev/video*"
usbipd attach --wsl --busid $BusId --auto-attach

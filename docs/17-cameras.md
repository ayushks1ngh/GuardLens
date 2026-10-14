# 17 — Connecting cameras

Open **Settings → Cameras → Add a camera**. After adding one, press **Test** next to it: GuardLens checks the
camera and tells you what is wrong and what to do.

## A phone as a camera (two ways)
1. **Browser camera (recommended, works on any phone).** Add a camera → *phone or browser* → scan the QR code (or press
   *Open the camera page* on the same computer) → allow the camera → *Start*. The link works for 5 minutes. The page
   needs https (or `localhost`); for LAN phones generate a development certificate with
   `scripts/setup_dev_tls.sh <LAN-IP>` and trust it on the phone, then set `GUARDLENS_PUBLIC_URL`.
2. **IP-camera app** (e.g. "IP Webcam" on Android). Start its server, note the address it shows
   (`http://192.168.x.x:8080/video`), and add it as *network camera*. Phones get a new address when they reconnect —
   if the camera stops, look the address up again and edit the camera.
   On WSL2 the phone's Wi-Fi is a different network: use WSL *mirrored networking* (`networkingMode=mirrored` in
   `%UserProfile%\.wslconfig`, then `wsl --shutdown`) or run GuardLens on Windows/Docker.

## A laptop or USB webcam in WSL2
WSL2 cannot see USB cameras by itself. In an **administrator PowerShell** on Windows:
```powershell
winget install --interactive --exact dorssel.usbipd-win     # once; reopen PowerShell afterwards
powershell -ExecutionPolicy Bypass -File scripts\windows\attach-webcam.ps1
```
Inside WSL (once per WSL restart): `sudo modprobe uvcvideo && ls /dev/video*`. Then add *camera attached to this
computer*, device 0. While attached, Windows apps can't use the camera (`usbipd detach --busid <id>` returns it).
Alternative without usbipd: use the Windows browser as the camera (*Browser camera* above, opened at
`https://localhost:<port>`).

## RTSP / ONVIF cameras
Add as *network camera* with the full address, e.g. `rtsp://user:password@192.168.1.30:554/stream1`. Passwords are never
shown again in the UI or in test results. Typical paths: Hikvision `/Streaming/Channels/101`, Dahua
`/cam/realmonitor?channel=1&subtype=0`, generic `/stream1`.

## When something is wrong
Press **Test** on the camera. It checks: switched on? video arriving? (device present / address reachable /
browser connected / file readable) and lists the next steps. Deeper detail: **Settings → Health**.

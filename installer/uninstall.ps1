# Gỡ cài đặt YouTube Channel Downloader. Video đã tải KHÔNG bị xoá.
param(
    [string]$ShortcutDir = '',  # chỉ dùng khi kiểm thử (khớp với install.ps1 -ShortcutDir)
    [switch]$Yes
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

$AppName = 'YouTube Channel Downloader'
$RegKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\YouTubeChannelDownloader'
$InstallDir = $PSScriptRoot

Write-Host ''
Write-Host "  Gỡ cài đặt $AppName" -ForegroundColor White
Write-Host "  Thư mục chương trình: $InstallDir"
Write-Host '  Video đã tải về sẽ được GIỮ NGUYÊN.' -ForegroundColor Green
Write-Host ''
if (-not $Yes -and (Read-Host 'Tiếp tục gỡ cài đặt? (Y/N)') -notmatch '^\s*[yYcC]') { exit 0 }

# An toàn: chỉ xoá thư mục thật sự là nơi cài chương trình
if (-not (Test-Path (Join-Path $InstallDir 'channel_downloader.py'))) {
    Write-Host 'Thư mục này không phải nơi cài chương trình — dừng.' -ForegroundColor Red
    exit 1
}

if ($ShortcutDir) {
    $desktopDir = $ShortcutDir; $menuDir = Join-Path $ShortcutDir 'StartMenu'
} else {
    $desktopDir = [Environment]::GetFolderPath('Desktop')
    $menuDir = Join-Path ([Environment]::GetFolderPath('Programs')) $AppName
}
# Python riêng do bộ cài tự tải: gỡ bằng chính bộ cài của nó để xoá cả mục trong Settings > Apps
$pySetup = Join-Path $InstallDir 'runtime\python-setup.exe'
if (Test-Path $pySetup) {
    Write-Host 'Đang gỡ Python riêng của chương trình...'
    Start-Process $pySetup -ArgumentList '/uninstall', '/quiet' -Wait
}

Remove-Item (Join-Path $desktopDir "$AppName.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item $menuDir -Recurse -Force -ErrorAction SilentlyContinue
if (-not $ShortcutDir) { Remove-Item $RegKey -Recurse -Force -ErrorAction SilentlyContinue }

# Script đang chạy từ chính thư mục cần xoá → nhờ 1 tiến trình khác xoá sau khi script này thoát
Start-Process cmd.exe -ArgumentList "/c timeout /t 2 /nobreak >nul & rmdir /s /q `"$InstallDir`"" -WindowStyle Hidden

Write-Host ''
Write-Host '✅ Đã gỡ cài đặt.' -ForegroundColor Green
if (-not $Yes) { Start-Sleep -Seconds 2 }

# Đóng gói chương trình thành 1 file zip cài đặt: dist\YouTubeChannelDownloader-Setup.zip
# Chạy:  powershell -NoProfile -ExecutionPolicy Bypass -File build_installer.ps1
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$name = 'YouTubeChannelDownloader-Setup'
$dist = Join-Path $root 'dist'
$stage = Join-Path $dist $name
$zip = Join-Path $dist "$name.zip"

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force (Join-Path $stage 'app') | Out-Null

# Windows PowerShell 5.1 chỉ đọc đúng tiếng Việt trong .ps1 khi file là UTF-8 có BOM
$utf8Bom = New-Object System.Text.UTF8Encoding $true
function Copy-Utf8Bom($from, $to) {
    $text = [IO.File]::ReadAllText($from, [Text.Encoding]::UTF8)
    [IO.File]::WriteAllText($to, $text, $utf8Bom)
}

Copy-Item (Join-Path $root 'installer\CaiDat.bat') $stage
Copy-Utf8Bom (Join-Path $root 'installer\install.ps1') (Join-Path $stage 'install.ps1')
Copy-Utf8Bom (Join-Path $root 'installer\uninstall.ps1') (Join-Path $stage 'uninstall.ps1')
Copy-Utf8Bom (Join-Path $root 'installer\HUONG-DAN-CAI-DAT.txt') (Join-Path $stage 'HUONG-DAN-CAI-DAT.txt')
# Chỉ chép đúng các file này. license_tool.py và license_private_key.pem KHÔNG BAO GIỜ được đưa vào.
if ((Get-Content (Join-Path $root 'trial.py') -Raw) -match 'PUBLIC_KEY_HEX = "0{64}"') {
    throw 'Chưa tạo khoá kích hoạt. Chạy trước: python license_tool.py init'
}
foreach ($f in 'channel_downloader.py', 'trial.py', 'requirements.txt', 'run.bat', 'README.md') {
    Copy-Item (Join-Path $root $f) (Join-Path $stage 'app')
}
if (Get-ChildItem $stage -Recurse -Include 'license_tool.py', '*.pem') { throw 'Lộ file khoá bí mật trong gói cài đặt!' }

if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $stage -DestinationPath $zip
Remove-Item $stage -Recurse -Force

$size = (Get-Item $zip).Length / 1KB
Write-Host ("Đã tạo: {0}  ({1:N0} KB)" -f $zip, $size)

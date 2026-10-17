# Cài đặt Download Tool cho người dùng hiện tại (không cần quyền admin).
#   - Máy chưa có Python 3.10+ / Node.js thì TỰ TẢI bản chính thức (python.org, nodejs.org) về
#     cài riêng vào thư mục chương trình — không hỏi, không cần admin, không đụng bản có sẵn trên máy
#   - Mọi file tải về đều được kiểm tra mã SHA-256 trước khi dùng
#   - Chép chương trình vào %LOCALAPPDATA%\DownloadTool, tạo môi trường Python riêng
#   - Tạo shortcut ở Desktop + Start Menu, đăng ký trong "Apps & features" để gỡ cài đặt
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'DownloadTool'),
    [string]$ShortcutDir = '',   # chỉ dùng khi kiểm thử: tạo shortcut vào thư mục này thay cho Desktop/Start Menu
    [switch]$NoRegister,         # chỉ dùng khi kiểm thử: không ghi vào "Apps & features"
    [switch]$ForceDownload,      # chỉ dùng khi kiểm thử: luôn tải Python/Node riêng dù máy đã có
    [switch]$Yes                 # tự trả lời "có" cho mọi câu hỏi
)

# Bản Python / Node.js tải về khi máy chưa có (ghim phiên bản + mã SHA-256 để chắc chắn tải đúng file)
$PythonVersion = '3.13.16'
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
$PythonSha256 = 'fb4f9f5d438b2396da0086dc70b935c530cb578e37adc6d354f7ad2037fee83b'
$NodeVersion = '22.23.3'
$NodeUrl = "https://nodejs.org/dist/v$NodeVersion/node-v$NodeVersion-win-x64.zip"
$NodeSha256 = '2b0ff57b049cda1bbcea2240eec20467018713c1efe1f7360c2681859b90ed71'  # từ SHASUMS256.txt của nodejs.org

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

$AppName = 'Download Tool'
$AppVersion = '1.6.0'
$RegKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DownloadTool'
$Src = Join-Path $PSScriptRoot 'app'
$RuntimeDir = Join-Path $InstallDir 'runtime'       # Python / Node.js riêng của chương trình
$PyDir = Join-Path $RuntimeDir 'python'
$PySetup = Join-Path $RuntimeDir 'python-setup.exe' # giữ lại để gỡ cài đặt Python riêng
$NodeExe = Join-Path $RuntimeDir 'node\node.exe'

function Say($msg, $color = 'Gray') { Write-Host $msg -ForegroundColor $color }
function Step($msg) { Write-Host ''; Write-Host "▶ $msg" -ForegroundColor Cyan }
function Fail($msg) {
    Write-Host ''; Write-Host "✖ $msg" -ForegroundColor Red
    exit 1  # CaiDat.bat sẽ dừng lại cho người dùng đọc lỗi
}
function Ask($question) {
    if ($Yes) { return $true }
    return (Read-Host "$question (Y/N)") -match '^\s*[yYcC]'
}

# ---------- tải file ----------

function Get-Download($url, $dest, $sha256, $label) {
    # Tải có hiện %, thử lại 3 lần khi lỗi mạng, kiểm tra SHA-256. Đã tải đúng từ lần trước thì bỏ qua.
    if ((Test-Path $dest) -and (Get-FileHash $dest -Algorithm SHA256).Hash -eq $sha256) { return }
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $tmp = "$dest.part"
    for ($try = 1; $try -le 3; $try++) {
        $out = $null; $res = $null
        try {
            $req = [Net.HttpWebRequest]::Create($url)
            $req.UserAgent = 'DownloadTool-Setup'
            $req.Timeout = 30000; $req.ReadWriteTimeout = 30000
            $res = $req.GetResponse()
            $total = $res.ContentLength
            $in = $res.GetResponseStream()
            $out = [IO.File]::Create($tmp)
            $buf = New-Object byte[] 262144
            $done = 0; $shown = -5
            while (($n = $in.Read($buf, 0, $buf.Length)) -gt 0) {
                $out.Write($buf, 0, $n); $done += $n
                if ($total -gt 0) {
                    $pct = [int]($done * 100 / $total)
                    if ($pct -ge $shown + 5) {
                        Write-Host -NoNewline ("`r   Đang tải {0}: {1,3}%  ({2:N1} / {3:N1} MB)  " -f $label, $pct, ($done / 1MB), ($total / 1MB))
                        $shown = $pct
                    }
                }
            }
            $out.Close(); $res.Close(); Write-Host ''
            break
        } catch {
            if ($out) { $out.Close() }
            if ($res) { $res.Close() }
            Write-Host ''
            if ($try -eq 3) { Fail "Không tải được $label ($($_.Exception.Message)). Hãy kiểm tra kết nối Internet rồi chạy lại CaiDat.bat." }
            Say "   Lỗi mạng, đang thử lại ($try/3)..." Yellow
            Start-Sleep -Seconds 3
        }
    }
    if ((Get-FileHash $tmp -Algorithm SHA256).Hash -ne $sha256) {
        Remove-Item $tmp -Force
        Fail "File $label tải về bị lỗi (sai mã kiểm tra SHA-256). Hãy chạy lại CaiDat.bat."
    }
    Move-Item $tmp $dest -Force
}

# ---------- Python ----------

function Test-PythonExe($exe, [string[]]$prefix = @()) {
    # Trả về đường dẫn python.exe thật nếu là Python 3.10+ có tkinter, ngược lại $null
    try {
        $out = & $exe @prefix -c "import sys, tkinter; print(sys.executable if sys.version_info >= (3, 10) else '')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out -and (Test-Path $out)) { return [string]$out }
    } catch {}
    return $null
}

function Find-Python {
    $launchers = @("$env:WINDIR\py.exe", "$env:LOCALAPPDATA\Programs\Python\Launcher\py.exe")
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { $launchers = @($cmd.Source) + $launchers }
    foreach ($l in $launchers | Select-Object -Unique) {
        if (Test-Path $l) { $p = Test-PythonExe $l @('-3'); if ($p) { return $p } }
    }
    $candidates = @()
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike '*\WindowsApps\*') { $candidates += $cmd.Source }  # bỏ qua lối tắt Microsoft Store
    $candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object FullName
    foreach ($c in $candidates) { $p = Test-PythonExe $c; if ($p) { return $p } }
    return $null
}

# ---------- JavaScript runtime (yt-dlp cần để giải mã link video YouTube) ----------

function Find-JsRuntime {
    if (Test-Path $NodeExe) { return $NodeExe }  # bản riêng đã tải ở lần cài trước
    foreach ($n in 'deno', 'node', 'bun') {
        $cmd = Get-Command $n -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    foreach ($p in "$env:ProgramFiles\nodejs\node.exe", "$env:USERPROFILE\.deno\bin\deno.exe", "$env:LOCALAPPDATA\Programs\nodejs\node.exe") {
        if (Test-Path $p) { return $p }
    }
    return $null
}

# ---------- tự tải bản riêng khi máy chưa có ----------

function Install-PrivatePython {
    New-Item -ItemType Directory -Force $RuntimeDir | Out-Null
    Get-Download $PythonUrl $PySetup $PythonSha256 "Python $PythonVersion"
    Say '   Đang cài Python (chạy ngầm, khoảng 1–2 phút)...'
    # Chỉ cho tài khoản này, vào thư mục riêng; không thêm PATH, không gắn file .py, không cài py launcher
    $setupArgs = @('/quiet', 'InstallAllUsers=0', "TargetDir=`"$PyDir`"", 'PrependPath=0', 'Include_launcher=0',
                   'InstallLauncherAllUsers=0', 'Shortcuts=0', 'AssociateFiles=0', 'Include_doc=0',
                   'Include_test=0', 'Include_dev=0', 'Include_tcltk=1', 'Include_pip=1', 'CompileAll=0')
    $p = Start-Process $PySetup -ArgumentList $setupArgs -Wait -PassThru
    if ($p.ExitCode -ne 0) { Fail "Cài Python thất bại (mã lỗi $($p.ExitCode)). Hãy chạy lại CaiDat.bat." }
    return Test-PythonExe (Join-Path $PyDir 'python.exe')
}

function Install-PrivateNode {
    New-Item -ItemType Directory -Force (Split-Path $NodeExe) | Out-Null
    $zip = Join-Path $RuntimeDir 'node.zip'
    Get-Download $NodeUrl $zip $NodeSha256 "Node.js $NodeVersion"
    # yt-dlp chỉ cần node.exe → lấy riêng file đó (nhanh hơn nhiều so với giải nén cả gói)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zip)
    try {
        $entry = $archive.Entries | Where-Object { $_.FullName -match '^[^/]+/node\.exe$' } | Select-Object -First 1
        if (-not $entry) { Fail 'File Node.js tải về không có node.exe.' }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $NodeExe, $true)
    } finally { $archive.Dispose() }
    Remove-Item $zip -Force
    return $NodeExe
}

# ====================================================================== bắt đầu

Write-Host ''
Write-Host "  $AppName $AppVersion — Cài đặt" -ForegroundColor White
Write-Host "  Thư mục cài đặt: $InstallDir"
Write-Host ''
Say 'Lưu ý: chỉ dùng để tải nội dung bạn có quyền sử dụng (kênh của bạn, video Creative Commons,' Yellow
Say 'hoặc được chủ kênh cho phép). Tải video YouTube có thể vi phạm Điều khoản dịch vụ của YouTube.' Yellow

if (-not (Test-Path (Join-Path $Src 'channel_downloader.py'))) {
    Fail "Không thấy thư mục 'app' cạnh file cài đặt. Hãy giải nén TOÀN BỘ file zip rồi chạy lại CaiDat.bat."
}

Step 'Kiểm tra Python 3.10+'
$Python = $null
if (Test-Path (Join-Path $PyDir 'python.exe')) { $Python = Test-PythonExe (Join-Path $PyDir 'python.exe') }  # bản riêng từ lần cài trước
if (-not $Python -and -not $ForceDownload) { $Python = Find-Python }
if (-not $Python) {
    Say "Máy chưa có Python phù hợp → tự tải Python $PythonVersion chính thức từ python.org." Yellow
    $Python = Install-PrivatePython
    if (-not $Python) { Fail 'Cài Python xong nhưng không chạy được. Hãy chạy lại CaiDat.bat.' }
}
Say "OK: $Python" Green

Step 'Kiểm tra Node.js (yt-dlp cần để giải mã link video YouTube)'
$Js = if ($ForceDownload -and -not (Test-Path $NodeExe)) { $null } else { Find-JsRuntime }
if (-not $Js) {
    Say "Máy chưa có Node.js → tự tải Node.js $NodeVersion chính thức từ nodejs.org." Yellow
    $Js = Install-PrivateNode
}
Say "OK: $Js" Green

# Bản cũ tên "YouTube Channel Downloader" (trước 1.6.0) → gỡ trước để máy không có 2 phần mềm trùng nhau.
# Video đã tải và dữ liệu dùng thử / kích hoạt không bị ảnh hưởng. (Bỏ qua khi kiểm thử với -ShortcutDir.)
$OldDir = Join-Path $env:LOCALAPPDATA 'YouTubeChannelDownloader'
$OldUninstall = Join-Path $OldDir 'uninstall.ps1'
if ((Test-Path $OldUninstall) -and ($OldDir -ne $InstallDir) -and -not $ShortcutDir) {
    Step 'Gỡ bản cũ "YouTube Channel Downloader"'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $OldUninstall -Yes | Out-Null
    Say 'OK' Green
}

Step 'Chép chương trình'
New-Item -ItemType Directory -Force $InstallDir | Out-Null
Copy-Item (Join-Path $Src '*') $InstallDir -Recurse -Force
Copy-Item (Join-Path $PSScriptRoot 'uninstall.ps1') $InstallDir -Force
Get-ChildItem $InstallDir -Recurse -File | Unblock-File -ErrorAction SilentlyContinue  # bỏ cảnh báo "file tải từ Internet"
Say 'OK' Green

Step 'Cài thư viện (yt-dlp, ffmpeg) — lần đầu mất khoảng 1–3 phút'
$Venv = Join-Path $InstallDir '.venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $VenvPy)) {
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail 'Không tạo được môi trường Python.' }
}
& $VenvPy -m pip install --disable-pip-version-check -q --upgrade pip
& $VenvPy -m pip install --disable-pip-version-check -q --upgrade -r (Join-Path $InstallDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail 'Cài thư viện thất bại. Kiểm tra kết nối Internet rồi chạy lại CaiDat.bat.' }
# Thư viện phụ của yt-dlp (curl-cffi, yt-dlp-ejs…) — cài theo đúng phiên bản yt-dlp yêu cầu, bỏ mutagen (GPL)
& $VenvPy (Join-Path $InstallDir 'channel_downloader.py') --sync-deps
if ($LASTEXITCODE -ne 0) { Fail 'Cài thư viện phụ thất bại. Kiểm tra kết nối Internet rồi chạy lại CaiDat.bat.' }
& $VenvPy -c "import yt_dlp, imageio_ffmpeg, cryptography, curl_cffi, yt_dlp_ejs; print('yt-dlp', yt_dlp.version.__version__); print('ffmpeg', imageio_ffmpeg.get_ffmpeg_exe())"
if ($LASTEXITCODE -ne 0) { Fail 'Kiểm tra thư viện thất bại.' }
Say 'OK' Green

Step 'Tạo shortcut'
$shell = New-Object -ComObject WScript.Shell
if ($ShortcutDir) {
    $desktopDir = $ShortcutDir; $menuDir = Join-Path $ShortcutDir 'StartMenu'
} else {
    $desktopDir = [Environment]::GetFolderPath('Desktop')
    $menuDir = Join-Path ([Environment]::GetFolderPath('Programs')) $AppName
}
New-Item -ItemType Directory -Force $menuDir | Out-Null
$icon = Join-Path $Venv 'Scripts\pythonw.exe'
function New-Shortcut($path, $target, $arguments, $description) {
    # WScript.Shell chỉ lưu được đường dẫn ANSI → lưu với tên tạm ASCII rồi đổi sang tên tiếng Việt
    $tmp = Join-Path (Split-Path $path) ("shortcut-{0}.lnk" -f [guid]::NewGuid().ToString('N'))
    $s = $shell.CreateShortcut($tmp)
    $s.TargetPath = $target
    $s.Arguments = $arguments
    $s.WorkingDirectory = $InstallDir
    $s.Description = $description
    $s.IconLocation = "$icon,0"
    $s.WindowStyle = 7  # thu nhỏ cửa sổ dòng lệnh (chỉ hiện vài giây khi cập nhật yt-dlp)
    $s.Save()
    Move-Item -LiteralPath $tmp -Destination $path -Force
}
$runBat = Join-Path $InstallDir 'run.bat'
$uninstallCmd = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $InstallDir 'uninstall.ps1')`""
# Mô tả viết không dấu vì WScript.Shell không lưu được tiếng Việt; đích phải là đường dẫn đầy đủ
$powershellExe = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$notepadExe = Join-Path $env:WINDIR 'System32\notepad.exe'
New-Shortcut (Join-Path $desktopDir "$AppName.lnk") $runBat '' 'Tai toan bo video cua 1 kenh YouTube'
New-Shortcut (Join-Path $menuDir "$AppName.lnk") $runBat '' 'Tai toan bo video cua 1 kenh YouTube'
New-Shortcut (Join-Path $menuDir "Gỡ cài đặt $AppName.lnk") $powershellExe $uninstallCmd "Go cai dat $AppName"
New-Shortcut (Join-Path $menuDir 'Hướng dẫn sử dụng.lnk') $notepadExe "`"$(Join-Path $InstallDir 'README.md')`"" 'Huong dan su dung'
Say "OK: Desktop + Start Menu" Green

if (-not $NoRegister) {
    # Hiện trong Settings > Apps > Installed apps để gỡ cài đặt như phần mềm bình thường
    New-Item -Path $RegKey -Force | Out-Null
    $props = @{
        DisplayName = $AppName; DisplayVersion = $AppVersion; Publisher = 'Download Tool'
        InstallLocation = $InstallDir; DisplayIcon = $icon
        UninstallString = "`"$powershellExe`" $uninstallCmd"
    }
    foreach ($k in $props.Keys) { Set-ItemProperty -Path $RegKey -Name $k -Value $props[$k] }
    Set-ItemProperty -Path $RegKey -Name NoModify -Value 1 -Type DWord
    Set-ItemProperty -Path $RegKey -Name NoRepair -Value 1 -Type DWord
}

Write-Host ''
Write-Host '✅ Cài đặt xong!' -ForegroundColor Green
Write-Host "   Mở chương trình bằng shortcut '$AppName' trên Desktop hoặc trong Start Menu."
Write-Host "   Gỡ cài đặt: Start Menu > $AppName > Gỡ cài đặt, hoặc Settings > Apps."
Write-Host ''
if (-not $Yes) {
    if (Ask 'Mở chương trình ngay bây giờ?') { Start-Process $runBat -WorkingDirectory $InstallDir -WindowStyle Minimized }
}

# Buka dashboard ke internet lewat ngrok.
#
# Pakai: .\scripts\share.ps1            -> lihat-saja (disarankan)
#        .\scripts\share.ps1 -Bisatulis -> penonton boleh menekan "Ambil data baru"
#
# App ini tidak punya sistem login sendiri, jadi gerbangnya HTTP Basic dari .env.
# Tanpa itu, siapa pun yang tahu URL-nya bisa menekan /refresh dan menjalankan
# Chrome memakai sesi TikTok di mesin ini. Karena itu skrip berhenti kalau
# AUTH_USER/AUTH_PASS masih kosong - bukan cuma memperingatkan.

param(
    [int]$Port = 8000,
    [switch]$Bisatulis
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# --- prasyarat --------------------------------------------------------------
# winget menambah ngrok ke PATH, tapi PATH sesi yang SEDANG jalan tidak ikut
# berubah - jadi tepat setelah install, `Get-Command ngrok` masih kosong padahal
# programnya sudah ada. Segarkan PATH dari registry dulu, lalu cari langsung ke
# folder pasangan winget, baru menyerah.
# Paket winget "Ngrok.Ngrok" mentok di 3.3.1 (rilis lama) dan cuma paham file
# konfigurasi versi 1-2. Konfigurasi ngrok modern versi "3", jadi 3.3.1 menolak
# jalan dengan "unknown version '3'". Menjalankan `add-authtoken` dengan 3.3.1
# malah akan menimpa konfigurasi yang sudah benar. Karena itu: butuh >= 3.5,
# dan kalau tidak ada, ambil biner resmi ke tools\ (tidak menyentuh sistem).
$MIN_NGROK = [version]"3.5.0"
$LOKAL = Join-Path $root "tools\ngrok\ngrok.exe"

function Versi-Ngrok($exe) {
    try {
        $t = (& $exe version 2>&1) -join " "
        if ($t -match '(\d+)\.(\d+)\.(\d+)') {
            return [version]("{0}.{1}.{2}" -f $Matches[1], $Matches[2], $Matches[3])
        }
    } catch {}
    return $null
}

function Kandidat-Ngrok {
    if (Test-Path $LOKAL) { $LOKAL }
    $c = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($c) { $c.Source }
    # PATH sesi yang sedang jalan tidak ikut berubah setelah winget install,
    # jadi segarkan dari registry sebelum menyerah.
    $env:Path = ([Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                 [Environment]::GetEnvironmentVariable("Path", "User"))
    $c = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($c) { $c.Source }
    $wg = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet"
    if (Test-Path $wg) {
        Get-ChildItem $wg -Filter "ngrok.exe" -Recurse -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName
    }
}

function Ambil-Ngrok {
    Write-Host "Mengunduh ngrok v3 terbaru ke tools\ngrok ..." -ForegroundColor Cyan
    $dir = Join-Path $root "tools"
    New-Item -ItemType Directory -Force $dir | Out-Null
    $zip = Join-Path $dir "ngrok.zip"
    $url = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest $url -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath (Join-Path $dir "ngrok") -Force
    Remove-Item $zip -Force
    return $LOKAL
}

$ngrok = $null
foreach ($k in (Kandidat-Ngrok | Select-Object -Unique)) {
    $v = Versi-Ngrok $k
    if ($v -and $v -ge $MIN_NGROK) { $ngrok = $k; break }
    if ($v) { Write-Host "  lewati $k (versi $v, terlalu lama)" -ForegroundColor DarkGray }
}

if (-not $ngrok) {
    $ngrok = Ambil-Ngrok
    $v = Versi-Ngrok $ngrok
    if (-not $v -or $v -lt $MIN_NGROK) {
        Write-Host "Gagal menyiapkan ngrok. Unduh manual dari https://ngrok.com/download" -ForegroundColor Red
        exit 1
    }
}
Write-Host "ngrok: $ngrok (versi $(Versi-Ngrok $ngrok))" -ForegroundColor DarkGray

# Tanpa authtoken, ngrok mati dengan galat panjang SETELAH server terlanjur
# hidup. Lebih baik ketahuan sekarang.
$cfg_path = Join-Path $env:LOCALAPPDATA "ngrok\ngrok.yml"
if (-not (Test-Path $cfg_path) -or
    -not (Select-String -Path $cfg_path -Pattern 'authtoken' -Quiet)) {
    Write-Host "ngrok belum diberi authtoken. Jalankan dulu:" -ForegroundColor Yellow
    Write-Host "  $ngrok config add-authtoken <TOKEN_KAMU>"
    Write-Host "(ambil di https://dashboard.ngrok.com/get-started/your-authtoken)"
    exit 1
}

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
$env_isi = Get-Content ".env" -Raw

# Ambil nilai TERAKHIR, bukan pertama. python-dotenv memproses berkas dari atas
# ke bawah sehingga kunci yang muncul belakangan menimpa yang awal. Kalau skrip
# ini mengambil yang pertama, sandi yang dicetak untuk dibagikan bisa berbeda
# dari sandi yang benar-benar dipakai aplikasi - dan itu baru ketahuan setelah
# penonton gagal login.
function Nilai-Env($kunci) {
    # pola dirakit lewat penggabungan: menaruh "$" tepat sebelum kutip penutup
    # membuat PowerShell mengira itu awal variabel dan merusak string
    $pola = '(?m)^' + $kunci + '=(.*)' + '$'
    $m = [regex]::Matches($env_isi, $pola)
    if ($m.Count -eq 0) { return "" }
    if ($m.Count -gt 1) {
        Write-Host "PERINGATAN: $kunci ada $($m.Count)x di .env; yang dipakai baris terakhir." -ForegroundColor Yellow
        Write-Host "            Hapus duplikatnya supaya tidak membingungkan." -ForegroundColor Yellow
    }
    return $m[$m.Count - 1].Groups[1].Value.Trim()
}

$user  = Nilai-Env "AUTH_USER"
$pass  = Nilai-Env "AUTH_PASS"
$auser = Nilai-Env "ADMIN_USER"
$apass = Nilai-Env "ADMIN_PASS"

if (-not $user -or -not $pass) {
    Write-Host "AUTH_USER / AUTH_PASS di .env masih kosong." -ForegroundColor Red
    Write-Host "Tanpa itu link ngrok-mu terbuka untuk siapa saja. Contoh sandi acak:"
    $acak = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 20 |
                   ForEach-Object { [char]$_ })
    Write-Host ""
    Write-Host "  AUTH_USER=sas"
    Write-Host "  AUTH_PASS=$acak"
    Write-Host ""
    Write-Host "Tambahkan dua baris itu ke .env lalu jalankan skrip ini lagi."
    exit 1
}

# --- mode -------------------------------------------------------------------
# Default lihat-saja UNTUK PENONTON. Kredensial admin (kalau ada di .env) tetap
# bisa menekan tombol aksi - jadi kamu bisa update dari jauh tanpa memberi
# kuasa itu ke semua orang yang kamu kirimi link.
$env:READ_ONLY = if ($Bisatulis) { "false" } else { "true" }
$env:PYTHONPATH = $root

if ($Bisatulis) {
    Write-Host "MODE TULIS TERBUKA: SEMUA penonton bisa menjalankan scraping" -ForegroundColor Red
    Write-Host "di mesin ini pakai akun TikTok-mu. Biasanya bukan ini yang kamu mau -" -ForegroundColor Red
    Write-Host "cukup pakai kredensial admin di bawah tanpa flag -Bisatulis." -ForegroundColor Red
} elseif ($apass) {
    Write-Host "Penonton: lihat-saja. Admin: bisa update dari jauh." -ForegroundColor Green
} else {
    Write-Host "Mode lihat-saja: semua tombol aksi dimatikan." -ForegroundColor Green
    Write-Host "(isi ADMIN_USER/ADMIN_PASS di .env kalau mau bisa update dari jauh)" -ForegroundColor DarkGray
}

# --- jalan ------------------------------------------------------------------
# uvicorn tetap mendengarkan 127.0.0.1 saja; yang menghadap internet cuma ngrok,
# jadi app-nya tidak ikut terbuka ke jaringan Wi-Fi lokal.
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$app = Start-Process -FilePath $py `
    -ArgumentList "-m", "uvicorn", "app.api:app", "--host", "127.0.0.1", "--port", "$Port" `
    -PassThru -NoNewWindow

try {
    Start-Sleep -Seconds 5
    Write-Host ""
    Write-Host "BAGIKAN yang ini ke penonton (lihat-saja):" -ForegroundColor Cyan
    Write-Host "  user: $user"
    Write-Host "  pass: $pass"
    if ($apass) {
        Write-Host ""
        Write-Host "JANGAN dibagikan - ini punyamu, bisa menekan tombol update:" -ForegroundColor Yellow
        Write-Host "  user: $auser"
        Write-Host "  pass: $apass"
    }
    Write-Host ""
    Write-Host "URL publik muncul di bawah ini (Ctrl+C untuk berhenti):"
    & $ngrok http $Port
}
finally {
    if ($app -and -not $app.HasExited) { Stop-Process -Id $app.Id -Force }
    Write-Host "`nTunnel & server dimatikan." -ForegroundColor Green
}

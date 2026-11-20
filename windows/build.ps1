# ============================================================
#  EC-Tube — genera el instalador de Windows
#  Lo corre GitHub Actions (ver .github/workflows/windows-installer.yml).
#  A mano: Python 3.12 + PyInstaller + Inno Setup 6, y:
#    powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
#  Resultado: windows\out\EC-Tube-Setup-<versión>.exe
# ============================================================
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir '..')).Path
$srcRoot     = Join-Path $projectRoot 'src'
$ffmpegUrl   = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
$ytdlpUrl    = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe'
$denoUrl     = 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip'

function Invoke-Checked([string]$FilePath, [string[]]$ArgumentList = @()) {
  & $FilePath @ArgumentList
  if ($LASTEXITCODE -ne 0) { throw "$FilePath terminó con código $LASTEXITCODE" }
}

$version = (Select-String -Path (Join-Path $srcRoot 'ectube_server.py') -Pattern '^APP_VERSION = "(.+)"').Matches[0].Groups[1].Value
Write-Host "EC-Tube $version" -ForegroundColor Cyan

# El Python que está en el PATH (en GitHub Actions, el de setup-python con PyInstaller).
$python = 'python'
$pythonArgs = @()

$distDir = Join-Path $scriptDir 'dist'
$outDir  = Join-Path $scriptDir 'out'
$appDir  = Join-Path $distDir 'ectube'
$binDir  = Join-Path $appDir 'bin'
$cache   = Join-Path $scriptDir 'cache'
New-Item -ItemType Directory -Force -Path $distDir, $outDir, $cache | Out-Null

# --- Herramientas: FFmpeg + ffprobe, yt-dlp y Deno ---
function Get-Zip([string]$url, [string]$name) {
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ("ectube-" + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  Write-Host "Descargando $name..."
  Invoke-WebRequest -Uri $url -OutFile (Join-Path $tmp 'a.zip')
  Expand-Archive -Path (Join-Path $tmp 'a.zip') -DestinationPath (Join-Path $tmp 'x') -Force
  return (Join-Path $tmp 'x')
}
if (-not (Test-Path (Join-Path $cache 'ffmpeg.exe'))) {
  $x = Get-Zip $ffmpegUrl 'FFmpeg'
  foreach ($exe in 'ffmpeg.exe', 'ffprobe.exe') {
    $bin = Get-ChildItem -Path $x -Filter $exe -Recurse | Select-Object -First 1
    if (-not $bin) { throw "No se encontró $exe en el zip de FFmpeg." }
    Copy-Item $bin.FullName (Join-Path $cache $exe) -Force
  }
}
if (-not (Test-Path (Join-Path $cache 'deno.exe'))) {
  $x = Get-Zip $denoUrl 'Deno'
  Copy-Item (Join-Path $x 'deno.exe') (Join-Path $cache 'deno.exe') -Force
}
Write-Host 'Descargando yt-dlp (siempre la última)...'
Invoke-WebRequest -Uri $ytdlpUrl -OutFile (Join-Path $cache 'yt-dlp.exe')

# --- Fecha de publicación (hora de Ciudad de México) ---
try { $tz = [TimeZoneInfo]::FindSystemTimeZoneById('Central Standard Time (Mexico)') } catch { $tz = [TimeZoneInfo]::Local }
$buildDate = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $tz).ToString('yyyy-MM-dd HH:mm')
Set-Content -Path (Join-Path $srcRoot 'ectube_build.py') -Value "BUILD_DATE = `"$buildDate`"" -Encoding ascii

# --- Programa (PyInstaller, carpeta, sin consola) ---
Write-Host 'Compilando EC-Tube...'
Invoke-Checked $python ($pythonArgs + @(
  '-m', 'PyInstaller', '--clean', '--noconfirm', '--onedir', '--noconsole',
  '--name', 'ectube',
  '--icon', (Join-Path $srcRoot 'web\img\ectube.ico'),
  '--add-data', "$(Join-Path $srcRoot 'web');web",
  '--paths', $srcRoot,
  '--hidden-import', 'ectube_build',
  '--hidden-import', 'ectube_update',
  '--hidden-import', 'ectube_separate',
  '--hidden-import', 'ectube_karaoke',
  '--hidden-import', 'ectube_overlay',
  '--hidden-import', 'ectube_subs',
  '--hidden-import', 'ectube_asr',
  '--collect-all', 'onnxruntime',
  '--collect-all', 'faster_whisper',
  '--collect-all', 'ctranslate2',
  '--collect-all', 'tokenizers',
  '--collect-all', 'av',
  '--exclude-module', 'tkinter',
  '--distpath', $distDir,
  '--workpath', (Join-Path $scriptDir '.build'),
  '--specpath', (Join-Path $scriptDir '.build'),
  (Join-Path $srcRoot 'ectube_server.py')
))
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
foreach ($exe in 'yt-dlp.exe', 'deno.exe', 'ffmpeg.exe', 'ffprobe.exe') { Copy-Item (Join-Path $cache $exe) (Join-Path $binDir $exe) -Force }

# FFmpeg debe traer zscale (para pasar los videos HDR del iPhone a colores normales).
$filters = & (Join-Path $binDir 'ffmpeg.exe') -hide_banner -filters 2>&1 | Out-String
if ($filters -notmatch 'zscale') { throw 'Este FFmpeg no trae zscale (videos HDR).' }

# Prueba rápida: que yt-dlp corra.
$ytv = & (Join-Path $binDir 'yt-dlp.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'yt-dlp.exe no corrió.' }
Write-Host "yt-dlp $ytv · Deno $(& (Join-Path $binDir 'deno.exe') --version | Select-Object -First 1)"

# Prueba del «oído» (subtítulos automáticos) en el programa YA compilado: baja el modelo y escucha una muestra.
if ($env:GITHUB_ACTIONS) {
  $tmp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
  $wav = Join-Path $tmp 'muestra-voz.wav'
  Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/ggerganov/whisper.cpp/master/samples/jfk.wav' -OutFile $wav
  $env:ECTUBE_HOME = Join-Path $tmp 'ectube-prueba'
  $env:ECTUBE_SELFTEST_ASR = $wav
  $env:ECTUBE_SELFTEST_OUT = Join-Path $tmp 'oido.json'
  $proc = Start-Process -FilePath (Join-Path $appDir 'ectube.exe') -Wait -PassThru
  $result = Get-Content $env:ECTUBE_SELFTEST_OUT -Raw -Encoding UTF8
  Write-Host "Prueba del oído (código $($proc.ExitCode)): $result"
  Remove-Item env:ECTUBE_SELFTEST_ASR, env:ECTUBE_SELFTEST_OUT, env:ECTUBE_HOME
  $data = $result | ConvertFrom-Json
  if (-not $data.ok -or $data.blocks.Count -lt 1 -or ($result -notmatch 'country')) { throw 'El oído (reconocimiento de voz) no funcionó en el programa compilado.' }
}

# --- Instalador ---
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Falta Inno Setup 6.' }
Invoke-Checked $iscc @("/DAppVersion=$version", "/DSourceDir=$appDir", "/O$outDir", (Join-Path $scriptDir 'ectube.iss'))
Write-Host "Listo: $outDir\EC-Tube-Setup-$version.exe" -ForegroundColor Green

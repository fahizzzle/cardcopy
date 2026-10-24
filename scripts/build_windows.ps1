<#
.SYNOPSIS
  Build CardCopy for Windows into dist\:

    CardCopy-Setup\          the installer folder: Install.cmd, install.ps1, READ ME.txt and CardCopy\
                             (the embedded Python 3.11.9 from python.org, PySide6, the app's .py files)
    CardCopy-Setup.zip       that folder zipped: the download antivirus leaves alone, and what installed
                             copies fetch to update themselves (selfupdate.py)
    CardCopy-Setup.exe       the same files as a regular setup program (Inno Setup), unless -NoExe

  Nothing of ours is an executable inside the app: python\pythonw.exe -m cardcopy runs it.
  Run from anywhere:  powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 [-NoExe]
#>
param([switch]$NoExe, [string]$Python = "python")

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$pyVersion = "3.11.9"
$version = ([regex]'__version__ = "([^"]+)"').Match((Get-Content -Raw (Join-Path $root "cardcopy\__init__.py"))).Groups[1].Value
$dist = Join-Path $root "dist"
$stage = Join-Path $dist "CardCopy-Setup"
$app = Join-Path $stage "CardCopy"
$cache = Join-Path $root "build\cache"
Write-Host "CardCopy $version for Windows"

# Our own build output only: dist\CardCopy-Setup is made fresh each time.
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $app, $cache | Out-Null

Write-Host "== embedded Python $pyVersion"
$embed = Join-Path $cache "python-$pyVersion-embed-amd64.zip"
if (-not (Test-Path $embed)) {
    Invoke-WebRequest "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-embed-amd64.zip" -OutFile $embed
}
Expand-Archive $embed -DestinationPath (Join-Path $app "python")
# where the embedded Python looks for modules: its stdlib zip, itself, the packages, and the app folder (..)
[IO.File]::WriteAllText((Join-Path $app "python\python311._pth"), "python311.zip`r`n.`r`nLib\site-packages`r`n..`r`n")
$site = Join-Path $app "python\Lib\site-packages"
New-Item -ItemType Directory -Force $site | Out-Null

Write-Host "== PySide6 (requirements.txt)"
$requirements = Join-Path $root "requirements.txt"
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $env:UV_NATIVE_TLS = "1"
    & uv pip install --quiet --target $site --python-platform x86_64-pc-windows-msvc --python-version 3.11 --no-compile -r $requirements
} else {
    & $Python -m pip install --quiet --target $site --only-binary=:all: --platform win_amd64 --python-version 3.11 `
        --implementation cp --no-compile -r $requirements
}
if ($LASTEXITCODE -ne 0) { throw "installing the requirements failed" }
foreach ($junk in @("bin", "Scripts", ".lock")) {         # pyside6-uic and friends: not needed to run
    $path = Join-Path $site $junk
    if (Test-Path $path) { Remove-Item $path -Recurse -Force }
}
# CardCopy is QtWidgets only. Leave out what PySide6 brings for QML/Quick, its developer tools (Designer,
# Linguist, uic ...), headers and translations: about 50 MB and 2,000 files, as the 1.19.0 build did.
$pyside = Join-Path $site "PySide6"
foreach ($folder in @("qml", "translations", "include", "glue", "scripts", "support", "typesystems")) {
    $path = Join-Path $pyside $folder
    if (Test-Path $path) { Remove-Item $path -Recurse -Force }
}
Get-ChildItem $pyside -File | Where-Object {
    $_.Name -like "*.exe" -or $_.Name -like "Qt6Qml*.dll" -or $_.Name -like "Qt6Quick*.dll" -or
    $_.Name -like "QtQml*.pyd" -or $_.Name -like "QtQuick*.pyd"
} | Remove-Item -Force

Write-Host "== the app"
& robocopy (Join-Path $root "cardcopy") (Join-Path $app "cardcopy") /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ /XF "*.pyc" "build.json" | Out-Null
if ($LASTEXITCODE -ge 8) { throw "copying the app failed (robocopy $LASTEXITCODE)" }
Copy-Item (Join-Path $root "windows\app\*") $app
Copy-Item (Join-Path $root "windows\installer\*") $stage
[IO.File]::WriteAllText((Join-Path $app "build.txt"), "CardCopy $version built $(Get-Date -Format 'yyyy-MM-dd HH:mm') python $pyVersion`r`n")

Write-Host "== CardCopy-Setup.zip"
$zip = Join-Path $dist "CardCopy-Setup.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $stage -DestinationPath $zip -CompressionLevel Optimal

if (-not $NoExe) {
    Write-Host "== CardCopy-Setup.exe"
    $iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
    if (-not $iscc) {
        $iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $iscc) { throw "Inno Setup 6 (ISCC.exe) is not installed; use -NoExe for the zip alone" }
    & $iscc /Q "/DAppVersion=$version" (Join-Path $root "windows\CardCopy.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed ($LASTEXITCODE)" }
}

Get-ChildItem $dist -File | Where-Object { $_.Name -like "CardCopy-Setup.*" } | ForEach-Object {
    "{0,-24} {1,8:N1} MB  sha256 {2}" -f $_.Name, ($_.Length / 1MB), (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
}

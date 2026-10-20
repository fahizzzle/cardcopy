<#
.SYNOPSIS
  Installs CardCopy for the current user from the CardCopy folder next to this script.
  No admin rights, nothing of ours is an executable: the folder (an embedded, signed Python
  plus the app's .py files) is copied to %LOCALAPPDATA%\Programs\CardCopy, Desktop and Start
  Menu shortcuts run  python\pythonw.exe -m cardcopy,  and an entry is added to
  Settings > Apps so it can be uninstalled normally.

  Double-click Install.cmd, or:  powershell -ExecutionPolicy Bypass -File install.ps1 [-Silent]
#>
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\CardCopy"),
    [switch]$Silent,
    [switch]$NoDesktopShortcut
)

$ErrorActionPreference = "Stop"
$src = Join-Path $PSScriptRoot "CardCopy"
if (-not (Test-Path (Join-Path $src "python\pythonw.exe"))) {
    throw "The CardCopy folder is missing next to this script. Unzip the whole download first, then run Install.cmd."
}
$version = ((Get-Content (Join-Path $src "build.txt") -TotalCount 1) -split " ")[1]

Write-Host ""
Write-Host "CardCopy $version setup" -ForegroundColor Cyan
Write-Host "  Installs to: $InstallDir   (this Windows user only, no admin rights needed)"
Write-Host ""
if (-not $Silent) { $null = Read-Host "Press Enter to install (Ctrl+C to cancel)" }

# Close a running CardCopy so its files can be replaced.
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "-m cardcopy" -and $_.ExecutablePath -like "$InstallDir*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 400

Write-Host "[1/3] Copying the app..."
New-Item -ItemType Directory -Force $InstallDir | Out-Null
# /XF: an install made by Setup.exe keeps its own uninstaller (unins000.*), which the mirror must not remove
& robocopy $src $InstallDir /MIR /MT:8 /NFL /NDL /NJH /NJS /NP /R:3 /W:2 /XF "unins*.exe" "unins*.dat" "unins*.msg" | Out-Null
if ($LASTEXITCODE -ge 8) { throw "copying the app failed (robocopy $LASTEXITCODE)" }
# Files from a downloaded zip carry a "came from the internet" mark; clear it on our copy.
Get-ChildItem $InstallDir -Recurse -File | Unblock-File -ErrorAction SilentlyContinue
$pyw = Join-Path $InstallDir "python\pythonw.exe"
$icon = Join-Path $InstallDir "cardcopy\assets\cardcopy.ico"

Write-Host "[2/3] Creating shortcuts..."
$shell = New-Object -ComObject WScript.Shell
$places = @((Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))
if (-not $NoDesktopShortcut) { $places += [Environment]::GetFolderPath("Desktop") }
foreach ($dir in $places) {
    try {
        New-Item -ItemType Directory -Force $dir | Out-Null
        $s = $shell.CreateShortcut((Join-Path $dir "CardCopy.lnk"))
        $s.TargetPath = $pyw
        $s.Arguments = "-m cardcopy"
        $s.WorkingDirectory = $InstallDir
        $s.IconLocation = "$icon,0"
        $s.Description = "Copy camera SD cards into project folders"
        $s.Save()
    } catch { Write-Warning "shortcut in $dir failed: $($_.Exception.Message)" }
}

$innoKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{6E0B5C0E-6B5B-4F6B-9C55-CA2DC0971A10}_is1"
if ((Test-Path $innoKey) -and (Test-Path (Join-Path $InstallDir "unins000.exe"))) {
    # Installed earlier by Setup.exe: keep that Apps entry and its uninstaller, just show the new version.
    Write-Host "[3/3] Updating the existing Settings > Apps entry..."
    Set-ItemProperty -Path $innoKey -Name DisplayVersion -Value $version
    Write-Host ""
    Write-Host "Updated to $version." -ForegroundColor Green
    if (-not $Silent) { $null = Read-Host "Press Enter to close" }
    exit 0
}
Write-Host "[3/3] Registering with Windows (Settings > Apps)..."
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CardCopy"
New-Item -Path $key -Force | Out-Null
$uninstall = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$InstallDir\uninstall.ps1`""
$sizeKb = [int]((Get-ChildItem $InstallDir -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
@{ DisplayName = "CardCopy"; DisplayVersion = $version; Publisher = "Framed Horizon LLC"; DisplayIcon = $icon;
   InstallLocation = $InstallDir; UninstallString = $uninstall; QuietUninstallString = "$uninstall -Silent" }.GetEnumerator() |
    ForEach-Object { Set-ItemProperty -Path $key -Name $_.Key -Value $_.Value }
Set-ItemProperty -Path $key -Name EstimatedSize -Value $sizeKb -Type DWord
Set-ItemProperty -Path $key -Name NoModify -Value 1 -Type DWord
Set-ItemProperty -Path $key -Name NoRepair -Value 1 -Type DWord

Write-Host ""
Write-Host "Installed. Open CardCopy from the Start Menu or the Desktop." -ForegroundColor Green
if (-not $Silent) { $null = Read-Host "Press Enter to close" }
exit 0   # robocopy's status codes (1-7 = success) must not leak as the script's exit code

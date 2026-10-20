<#
.SYNOPSIS
  Removes CardCopy: the program folder this script sits in, its shortcuts and its Settings > Apps entry.
  It touches nothing else: no photos, no videos, no project folders, and your CardCopy settings
  (%APPDATA%\CardCopy) are kept in case you install it again.
#>
param([switch]$Silent)

$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
# Only ever remove a folder that really is a CardCopy install.
if (-not ((Test-Path (Join-Path $dir "cardcopy\__main__.py")) -and (Test-Path (Join-Path $dir "python\pythonw.exe")))) {
    throw "$dir does not look like a CardCopy install; nothing was removed."
}
if (-not $Silent) {
    Write-Host "This removes the CardCopy program from $dir."
    Write-Host "Your photos, videos, project folders and CardCopy settings are not touched."
    $null = Read-Host "Press Enter to uninstall (Ctrl+C to cancel)"
}

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -like "$dir*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

foreach ($place in @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
    $lnk = Join-Path $place "CardCopy.lnk"
    if (Test-Path $lnk) { Remove-Item $lnk -Force }
}
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CardCopy" -Recurse -Force -ErrorAction SilentlyContinue

# A script cannot delete the folder it is running from, so hand that to a detached command.
$cmd = "ping -n 3 127.0.0.1 >nul & rmdir /s /q `"$dir`""
Start-Process cmd.exe -ArgumentList "/c", $cmd -WindowStyle Hidden -WorkingDirectory $env:TEMP
Write-Host "CardCopy was removed."
if (-not $Silent) { Start-Sleep -Seconds 2 }
